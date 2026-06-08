using System;
using System.Collections.Generic;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.GraphicsInterface;

[assembly: CommandClass(typeof(RailPlugin.Commands))]
[assembly: ExtensionApplication(typeof(RailPlugin.PluginApp))]

namespace RailPlugin
{
    // 레일 지오메트리 (test_big 블록 A$C31676947 측정값)
    //  로컬: 축=+Y, 시작(0,0). edge x=±960(폭1920). 조인트(bowtie) 호 r500·바920(±460)·바간격650(±325)·호center±825.
    //  양 끝 입구(flare): edge가 바깥으로 90°호(r=R)로 벌어짐 — 끝(y=0/length)에 고정(비율X).
    //  입구 throat: 입구 안쪽 둥근 닫힘(바+모서리 호 2개) — 끝에서 680/1180 오프셋 고정.
    //  조인트 개수 = 차선수(고정). 위치는 길이에 비례(균등) — 길이 변하면 비율대로 이동(추가 아님).
    public static class RailGeom
    {
        public const double HALF_W = 960.0, R = 500.0, NECK = 460.0;
        public const double BAR_DY = 325.0, ARC_DY = 825.0;
        public const double THROAT_BAR_DY = 680.0, THROAT_ARC_DY = 1180.0;  // 입구 throat: 끝에서 바/호center 거리
        public const double MINLEN = 2000.0;

        public static List<Entity> Build(double length, int jointCount)
        {
            if (length < MINLEN) length = MINLEN;
            if (jointCount < 1) jointCount = 1;
            var ents = new List<Entity>();
            // 세로 edge 2개 (x=±960, y 0→length)
            ents.Add(new Line(new Point3d(-HALF_W, 0, 0), new Point3d(-HALF_W, length, 0)));
            ents.Add(new Line(new Point3d(HALF_W, 0, 0), new Point3d(HALF_W, length, 0)));
            AddEndCaps(ents, length);                                  // 양 끝 입구(flare) — 끝에 고정
            AddEndThroats(ents, length);                               // 입구 안쪽 throat(반쪽 조인트) — 끝에 고정
            for (int i = 0; i < jointCount; i++)
                AddJoint(ents, length * (i + 1) / (jointCount + 1));   // 내부 조인트 — 비율 위치(균등)
            return ents;
        }

        // 양 끝 입구(flare): 각 edge 끝이 바깥으로 90° 호(r=R)로 벌어짐. y=0/length에 고정(비율X).
        // tip은 edge 바깥 R·끝선 바깥 R (하단 y=-R, 상단 y=length+R). 원본 블록 측정 그대로.
        static void AddEndCaps(List<Entity> ents, double length)
        {
            double cxo = HALF_W + R;               // 입구 호 center x (edge 바깥으로 R)
            // 하단(y=0): edge가 바깥·아래로 벌어짐 (tip y=-R)
            ents.Add(Arc(-cxo, 0, 270, 360));      // 좌: tip(-cxo,-R) → edge(-HALF_W,0)
            ents.Add(Arc(cxo, 0, 180, 270));       // 우: edge(HALF_W,0) → tip(cxo,-R)
            // 상단(y=length): edge가 바깥·위로 벌어짐 (tip y=length+R)
            ents.Add(Arc(-cxo, length, 0, 90));    // 좌: edge(-HALF_W,length) → tip(-cxo,length+R)
            ents.Add(Arc(cxo, length, 90, 180));   // 우: tip(cxo,length+R) → edge(HALF_W,length)
        }

        // 입구 안쪽 throat(반쪽 bowtie): 바(920) + 모서리 호 2개로 둥근 닫힘. 끝에서 고정 오프셋.
        // 하단=위로 열림, 상단=아래로 열림. 원본 블록 측정(바 끝에서 680, 호center 1180).
        static void AddEndThroats(List<Entity> ents, double length)
        {
            // 하단(y=0 쪽)
            ents.Add(new Line(new Point3d(-NECK, THROAT_BAR_DY, 0), new Point3d(NECK, THROAT_BAR_DY, 0)));
            ents.Add(Arc(-NECK, THROAT_ARC_DY, 180, 270));   // 좌: edge → 바 좌끝
            ents.Add(Arc(NECK, THROAT_ARC_DY, 270, 360));    // 우: 바 우끝 → edge
            // 상단(y=length 쪽)
            ents.Add(new Line(new Point3d(-NECK, length - THROAT_BAR_DY, 0), new Point3d(NECK, length - THROAT_BAR_DY, 0)));
            ents.Add(Arc(-NECK, length - THROAT_ARC_DY, 90, 180));  // 좌: 바 좌끝 → edge
            ents.Add(Arc(NECK, length - THROAT_ARC_DY, 0, 90));     // 우: edge → 바 우끝
        }

        static void AddJoint(List<Entity> ents, double yc)
        {
            ents.Add(new Line(new Point3d(-NECK, yc - BAR_DY, 0), new Point3d(NECK, yc - BAR_DY, 0)));
            ents.Add(new Line(new Point3d(-NECK, yc + BAR_DY, 0), new Point3d(NECK, yc + BAR_DY, 0)));
            ents.Add(Arc(-NECK, yc - ARC_DY, 90, 180));
            ents.Add(Arc(NECK, yc - ARC_DY, 0, 90));
            ents.Add(Arc(-NECK, yc + ARC_DY, 180, 270));
            ents.Add(Arc(NECK, yc + ARC_DY, 270, 360));
        }

        static Arc Arc(double cx, double cy, double a0, double a1)
            => new Arc(new Point3d(cx, cy, 0), R, a0 * Math.PI / 180.0, a1 * Math.PI / 180.0);
    }

    // 레일 = 고유 블록 + XData(길이, 차선/조인트수). 리사이즈 = 블록 재정의(비율 이동).
    public static class RailFactory
    {
        public const string APP = "RAILPLUGIN";

        static void EnsureRegApp(Database db, Transaction tr)
        {
            var rat = (RegAppTable)tr.GetObject(db.RegAppTableId, OpenMode.ForRead);
            if (!rat.Has(APP))
            {
                rat.UpgradeOpen();
                var r = new RegAppTableRecord { Name = APP };
                rat.Add(r); tr.AddNewlyCreatedDBObject(r, true);
            }
        }

        static void FillBlock(BlockTableRecord btr, Transaction tr, double length, int count)
        {
            foreach (Entity e in RailGeom.Build(length, count))
            { btr.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true); }
        }

        static ResultBuffer XData(double length, int count) => new ResultBuffer(
            new TypedValue((int)DxfCode.ExtendedDataRegAppName, APP),
            new TypedValue((int)DxfCode.ExtendedDataReal, length),
            new TypedValue((int)DxfCode.ExtendedDataInteger16, (short)count));

        public static ObjectId CreateRail(Database db, Transaction tr, Point3d pos, double length, int count)
        {
            EnsureRegApp(db, tr);
            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForWrite);
            string name = "RAIL_" + Guid.NewGuid().ToString("N").Substring(0, 8);
            var btr = new BlockTableRecord { Name = name, Origin = Point3d.Origin };
            ObjectId btrId = bt.Add(btr); tr.AddNewlyCreatedDBObject(btr, true);
            FillBlock(btr, tr, length, count);

            var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);
            var br = new BlockReference(pos, btrId);
            ms.AppendEntity(br); tr.AddNewlyCreatedDBObject(br, true);
            br.XData = XData(length, count);
            return br.ObjectId;
        }

        public static double GetLength(BlockReference br)
        {
            ResultBuffer rb = br.GetXDataForApplication(APP);
            if (rb != null) foreach (TypedValue tv in rb)
                if (tv.TypeCode == (int)DxfCode.ExtendedDataReal) return (double)tv.Value;
            return -1;
        }

        public static int GetCount(BlockReference br)
        {
            ResultBuffer rb = br.GetXDataForApplication(APP);
            if (rb != null) foreach (TypedValue tv in rb)
                if (tv.TypeCode == (int)DxfCode.ExtendedDataInteger16) return (short)tv.Value;
            return 2;
        }

        // 길이 변경: 개수는 유지, 조인트를 비율대로 재배치(블록 재정의 → 모든 참조 갱신)
        public static void SetLength(Transaction tr, BlockReference br, double length)
        {
            if (length < RailGeom.MINLEN) length = RailGeom.MINLEN;
            int count = GetCount(br);
            var btr = (BlockTableRecord)tr.GetObject(br.BlockTableRecord, OpenMode.ForWrite);
            foreach (ObjectId id in btr)
            { var e = (Entity)tr.GetObject(id, OpenMode.ForWrite); e.Erase(); }
            FillBlock(btr, tr, length, count);
            if (!br.IsWriteEnabled) br.UpgradeOpen();
            br.XData = XData(length, count);
        }
    }

    public class Commands
    {
        public const double DEFAULT_LEN = 30000.0;
        public const int DEFAULT_LANES = 2;   // 2차선

        // 생성: 위치 한 번 클릭 → 기본 길이로 생성 (이후 RAILLEN/그립으로 비율 조절)
        [CommandMethod("DRAWRAIL2")]
        public void DrawRail2()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            PromptPointResult p0 = ed.GetPoint("\n레일 위치: ");
            if (p0.Status != PromptStatus.OK) return;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { RailFactory.CreateRail(db, tr, p0.Value, DEFAULT_LEN, DEFAULT_LANES); tr.Commit(); }
            ed.WriteMessage($"\nDRAWRAIL2: {DEFAULT_LANES}차선 레일 len={DEFAULT_LEN:0} 생성. (조인트 {DEFAULT_LANES}개, 비율 이동)");
        }

        // 길이 변경: 레일 선택 → 새 길이 → 조인트 비율대로 이동(개수 유지)
        [CommandMethod("RAILLEN")]
        public void RailLen()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            var peo = new PromptEntityOptions("\n레일 선택: ");
            peo.SetRejectMessage("\n레일(블록)만."); peo.AddAllowedClass(typeof(BlockReference), false);
            PromptEntityResult per = ed.GetEntity(peo);
            if (per.Status != PromptStatus.OK) return;
            PromptDoubleResult pdr = ed.GetDouble("\n새 길이: ");
            if (pdr.Status != PromptStatus.OK) return;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var br = (BlockReference)tr.GetObject(per.ObjectId, OpenMode.ForWrite);
                RailFactory.SetLength(tr, br, pdr.Value);
                tr.Commit();
            }
            ed.WriteMessage($"\nRAILLEN: 길이={pdr.Value:0} (조인트 비율 이동).");
        }

        // 헤드리스 검증용: 생성(20000) 후 리사이즈(50000) — 개수 유지·비율 이동 확인
        [CommandMethod("RAILTEST")]
        public void RailTest()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Database db = doc.Database;
            ObjectId id;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { id = RailFactory.CreateRail(db, tr, Point3d.Origin, 20000, DEFAULT_LANES); tr.Commit(); }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { var br = (BlockReference)tr.GetObject(id, OpenMode.ForWrite); RailFactory.SetLength(tr, br, 50000); tr.Commit(); }
            doc.Editor.WriteMessage("\nRAILTEST: 20000 생성 후 50000 리사이즈.");
        }
    }

    // 커스텀 그립: 끝(상단) 그립 드래그 → 길이 변경 + 조인트 비율 이동 (크래시 방지 try/catch)
    public class RailGrip : GripData { public double Length; public RailGrip(double len) { Length = len; } }

    public class RailGripOverrule : GripOverrule
    {
        public override void GetGripPoints(Entity e, GripDataCollection grips, double curViewUnitSize,
            int gripSize, Vector3d curViewDir, GetGripPointsFlags bitFlags)
        {
            try
            {
                var br = e as BlockReference;
                double len = br != null ? RailFactory.GetLength(br) : -1;
                if (len > 0)
                {
                    // 레일엔 끝점 리사이즈 그립 1개만 (기본 이동 그립 미추가 → base 호출 안 함)
                    Point3d top = new Point3d(0, len, 0).TransformBy(br.BlockTransform);
                    grips.Add(new RailGrip(len) { GripPoint = top });
                    return;
                }
            }
            catch { }
            base.GetGripPoints(e, grips, curViewUnitSize, gripSize, curViewDir, bitFlags);
        }

        public override void MoveGripPointsAt(Entity e, GripDataCollection grips, Vector3d offset,
            MoveGripPointsFlags bitFlags)
        {
            var br = e as BlockReference;
            RailGrip rgFound = null;
            foreach (GripData g in grips) if (g is RailGrip rg) { rgFound = rg; break; }
            if (rgFound == null || br == null) { base.MoveGripPointsAt(e, grips, offset, bitFlags); return; }
            try
            {
                Vector3d axis = Vector3d.YAxis.TransformBy(br.BlockTransform).GetNormal();
                double newLen = Math.Max(RailGeom.MINLEN, rgFound.Length + offset.DotProduct(axis));
                Transaction top = e.Database.TransactionManager.TopTransaction;
                if (top != null)
                {
                    RailFactory.SetLength(top, br, newLen);   // br(e)는 이미 쓰기 열림
                }
                else
                {
                    using (Transaction my = e.Database.TransactionManager.StartTransaction())
                    {
                        var brw = (BlockReference)my.GetObject(e.ObjectId, OpenMode.ForWrite);
                        RailFactory.SetLength(my, brw, newLen);
                        my.Commit();
                    }
                }
            }
            catch { /* 크래시 방지 */ }
            // 리사이즈 그립은 우리가 처리 — base(이동) 호출 안 함
        }
    }

    public class PluginApp : IExtensionApplication
    {
        static RailGripOverrule _ov;
        public void Initialize()
        {
            try
            {
                _ov = new RailGripOverrule();
                Overrule.AddOverrule(RXObject.GetClass(typeof(BlockReference)), _ov, true);
                _ov.SetXDataFilter(RailFactory.APP);
            }
            catch { }
        }
        public void Terminate()
        {
            try { if (_ov != null) Overrule.RemoveOverrule(RXObject.GetClass(typeof(BlockReference)), _ov); }
            catch { }
        }
    }
}
