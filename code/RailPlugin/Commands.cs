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
    // 2차선 레일 지오메트리 (test_big 블록 A$C31676947 측정값)
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

    // 3차선 레일 지오메트리 (test_big 블록 A$Ca08771bd 측정값, native 길이 46750에서 1:1 복제 검증됨).
    //  원본프레임: 좌 edge x=500·우 x=2920(폭2420)·부분 중앙 edge x=2000, 하단 y=500.
    //  플러그인 프레임으로 (DX,DY)=(-1710,-500) 평행이동 → 외곽 corridor 중심 x=0, 하단 y=0, 상단 y=length.
    //  구조 골격(외곽 edge·캡·throat·부분 중앙 edge·끝 ramp)은 끝(0/length)에 고정 → 길이 따라 직선만 신축.
    //  내부 station(좌 bowtie 2개·측면 개구부·r600 turnout 2개)은 rigid 유닛, 중앙(length/2)에 native 오프셋(-1175) 유지.
    //  실사용 inserts 32개 전부 native 길이(46750)라 resize는 보조 기능. MINLEN으로 station/끝그룹 겹침 방지.
    public static class RailGeom3
    {
        public const double R = 500.0, R6 = 600.0;
        public const double XL = 500.0, XR = 2920.0, XM = 2000.0;   // 원본프레임 edge x (좌/우/중앙)
        public const double Y_BOT = 500.0;                          // 원본프레임 하단 y
        const double DX = -1710.0, DY = -500.0;                     // 원본→플러그인 프레임 평행이동
        const double STATION_OFFSET = -1175.0;                      // 레일중심 대비 station 중심 오프셋(native)
        public const double MINLEN = 38000.0;                       // station(±~10735)+끝 그룹 겹침 방지

        static Line Ln(double x0, double y0, double x1, double y1)
            => new Line(new Point3d(x0 + DX, y0 + DY, 0), new Point3d(x1 + DX, y1 + DY, 0));
        static Arc Ar(double cx, double cy, double r, double a0, double a1)
            => new Arc(new Point3d(cx + DX, cy + DY, 0), r, a0 * Math.PI / 180.0, a1 * Math.PI / 180.0);

        public static List<Entity> Build(double length)
        {
            if (length < MINLEN) length = MINLEN;
            double yt = Y_BOT + length;                          // 상단 y (원본프레임)
            double ys = Y_BOT + length / 2.0 + STATION_OFFSET;   // station 중심 y (중앙 배치, native 오프셋)
            var e = new List<Entity>();
            // ── 외곽 edge 2개 (full length) ──
            e.Add(Ln(XL, yt, XL, Y_BOT));
            e.Add(Ln(XR, yt, XR, Y_BOT));
            // ── 양 끝 캡(flare): 외곽 edge가 바깥 90°호(r=R)로 벌어짐 ──
            e.Add(Ar(XR + R, Y_BOT, R, 180, 270)); e.Add(Ar(XL - R, Y_BOT, R, 270, 360));   // 하단 우/좌
            e.Add(Ar(XR + R, yt,    R,  90, 180)); e.Add(Ar(XL - R, yt,    R,   0,  90));   // 상단 우/좌
            // ── throat (하단: 바 y=1180·모서리 center y=1680 / 상단: yt-680·yt-1180) ──
            e.Add(Ln(1000, 1180, 2420, 1180)); e.Add(Ar(1000, 1680, R, 180, 270)); e.Add(Ar(2420, 1680, R, 270, 360));
            e.Add(Ln(1000, yt - 680, 2420, yt - 680)); e.Add(Ar(1000, yt - 1180, R, 90, 180)); e.Add(Ar(2420, yt - 1180, R, 0, 90));
            // ── 부분 중앙 edge + 끝 ramp (중앙 lane이 우측 edge로 합류) ──
            double ymb = 6005.2677;            // 중앙 edge 하단 (하단 고정)
            double ymt = yt - 5504.7269;       // 중앙 edge 상단 (상단 고정)
            e.Add(Ln(XM, ymt, XM, ymb));
            // 하단 ramp: 우 edge(2920,4940) S→ 중앙(2000,6005)
            e.Add(Ar(2420, 4940.0054, R, 0, 65.112)); e.Add(Ln(2289.5754, 5551.7024, 2630.4246, 5393.5707)); e.Add(Ar(2500, 6005.2677, R, 180, 245.112));
            // 상단 ramp: 중앙(2000,ymt) S→ 우 edge (하단 ramp의 레일중심 대칭)
            e.Add(Ar(2500, ymt, R, 114.888, 180)); e.Add(Ln(2289.5754, yt - 5051.1616, 2630.4246, yt - 4893.0299)); e.Add(Ar(2420, yt - 4439.4646, R, 294.888, 360));
            // ── 내부 station (중심 ys, native 오프셋 테이블) ──
            AddStation(e, ys);
            return e;
        }

        // 내부 station: y=ys 중심의 rigid 유닛. 오프셋은 native(중심 22700) 기준 측정값.
        static void AddStation(List<Entity> e, double ys)
        {
            // 좌 lane bowtie 조인트 #1 (하단)
            e.Add(Ar(1000, ys - 10735.2529, R, 90, 180)); e.Add(Ar(1500, ys - 10735.2529, R, 0, 90));
            e.Add(Ln(1500, ys - 10235.2529, 1000, ys - 10235.2529));
            e.Add(Ln(1000, ys - 9085.2529, 1500, ys - 9085.2529));
            e.Add(Ar(1000, ys - 8585.2529, R, 180, 270)); e.Add(Ar(1500, ys - 8585.2529, R, 270, 360));
            // 좌 lane bowtie 조인트 #2 (상단)
            e.Add(Ar(1000, ys + 8585.2717, R, 90, 180)); e.Add(Ar(1500, ys + 8585.2717, R, 0, 90));
            e.Add(Ln(1500, ys + 9085.2717, 1000, ys + 9085.2717));
            e.Add(Ln(1000, ys + 10235.2717, 1500, ys + 10235.2717));
            e.Add(Ar(1000, ys + 10735.2717, R, 180, 270)); e.Add(Ar(1500, ys + 10735.2717, R, 270, 360));
            // r600 turnout 하단: 중앙(2000,17216) S→ 우(2920,18440)
            e.Add(Ar(2600, ys - 5483.9786, R6, 120, 180)); e.Add(Ln(2300, ys - 4964.3633, 2620, ys - 4779.6112)); e.Add(Ar(2320, ys - 4259.996, R6, 300, 360));
            // r600 turnout 상단: 우(2920,26960) S→ 중앙(2000,28184)
            e.Add(Ar(2320, ys + 4260.004, R6, 0, 60)); e.Add(Ln(2300, ys + 4964.3713, 2620, ys + 4779.6192)); e.Add(Ar(2600, ys + 5483.9866, R6, 180, 240));
            // 측면 개구부 (좌·우 외곽 edge가 바깥으로 벌어짐, y=21700/23700)
            e.Add(Ar(XL - R, ys - 999.996, R, 0, 90)); e.Add(Ar(XL - R, ys + 1000.004, R, 270, 360));
            e.Add(Ar(XR + R, ys - 999.996, R, 90, 180)); e.Add(Ar(XR + R, ys + 1000.004, R, 180, 270));
        }
    }

    // 레일 = 고유 블록 + XData(길이, 조인트수, kind). kind: 2=2차선, 3=3차선. 리사이즈 = 블록 재정의.
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

        static void FillBlock(BlockTableRecord btr, Transaction tr, double length, int count, int kind)
        {
            var ents = kind == 3 ? RailGeom3.Build(length) : RailGeom.Build(length, count);
            foreach (Entity e in ents)
            { btr.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true); }
        }

        // XData: [APP, Real(length), Int16(count), Int16(kind)]. 구버전(2차선)은 kind 없음 → GetKind 기본 2.
        static ResultBuffer XData(double length, int count, int kind) => new ResultBuffer(
            new TypedValue((int)DxfCode.ExtendedDataRegAppName, APP),
            new TypedValue((int)DxfCode.ExtendedDataReal, length),
            new TypedValue((int)DxfCode.ExtendedDataInteger16, (short)count),
            new TypedValue((int)DxfCode.ExtendedDataInteger16, (short)kind));

        public static ObjectId CreateRail(Database db, Transaction tr, Point3d pos, double length, int count, int kind = 2)
        {
            EnsureRegApp(db, tr);
            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForWrite);
            string name = "RAIL_" + Guid.NewGuid().ToString("N").Substring(0, 8);
            var btr = new BlockTableRecord { Name = name, Origin = Point3d.Origin };
            ObjectId btrId = bt.Add(btr); tr.AddNewlyCreatedDBObject(btr, true);
            FillBlock(btr, tr, length, count, kind);

            var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);
            var br = new BlockReference(pos, btrId);
            ms.AppendEntity(br); tr.AddNewlyCreatedDBObject(br, true);
            br.XData = XData(length, count, kind);
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

        // kind = 2번째 Int16. 구버전(2차선) XData엔 Int16이 1개뿐 → 기본 2.
        public static int GetKind(BlockReference br)
        {
            ResultBuffer rb = br.GetXDataForApplication(APP);
            if (rb != null)
            {
                int n = 0;
                foreach (TypedValue tv in rb)
                    if (tv.TypeCode == (int)DxfCode.ExtendedDataInteger16)
                    { n++; if (n == 2) return (short)tv.Value; }
            }
            return 2;
        }

        public static double MinLen(int kind) => kind == 3 ? RailGeom3.MINLEN : RailGeom.MINLEN;

        // 길이 변경: kind/개수 유지, 블록 재정의 → 모든 참조 갱신
        public static void SetLength(Transaction tr, BlockReference br, double length)
        {
            int kind = GetKind(br);
            double minlen = MinLen(kind);
            if (length < minlen) length = minlen;
            int count = GetCount(br);
            var btr = (BlockTableRecord)tr.GetObject(br.BlockTableRecord, OpenMode.ForWrite);
            foreach (ObjectId id in btr)
            { var e = (Entity)tr.GetObject(id, OpenMode.ForWrite); e.Erase(); }
            FillBlock(btr, tr, length, count, kind);
            if (!br.IsWriteEnabled) br.UpgradeOpen();
            br.XData = XData(length, count, kind);
        }
    }

    public class Commands
    {
        public const double DEFAULT_LEN = 30000.0;
        public const int DEFAULT_LANES = 2;       // 2차선
        public const double DEFAULT_LEN3 = 46750.0;  // 3차선 native 길이

        // 2차선 생성: 위치 한 번 클릭 → 기본 길이로 생성 (이후 RAILLEN/그립으로 비율 조절)
        [CommandMethod("DRAWRAIL2")]
        public void DrawRail2()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            PromptPointResult p0 = ed.GetPoint("\n레일 위치: ");
            if (p0.Status != PromptStatus.OK) return;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { RailFactory.CreateRail(db, tr, p0.Value, DEFAULT_LEN, DEFAULT_LANES, 2); tr.Commit(); }
            ed.WriteMessage($"\nDRAWRAIL2: {DEFAULT_LANES}차선 레일 len={DEFAULT_LEN:0} 생성. (조인트 {DEFAULT_LANES}개, 비율 이동)");
        }

        // 3차선 생성: 위치 한 번 클릭 → native 길이(46750)로 생성 (이후 RAILLEN/그립으로 길이 조절)
        [CommandMethod("DRAWRAIL3")]
        public void DrawRail3()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            PromptPointResult p0 = ed.GetPoint("\n레일 위치: ");
            if (p0.Status != PromptStatus.OK) return;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { RailFactory.CreateRail(db, tr, p0.Value, DEFAULT_LEN3, 3, 3); tr.Commit(); }
            ed.WriteMessage($"\nDRAWRAIL3: 3차선 레일 len={DEFAULT_LEN3:0} 생성. (내부 station 중앙 고정, 직선만 신축)");
        }

        // 길이 변경: 레일 선택 → 새 길이 → 재정의(2차선=조인트 비율 이동, 3차선=station 중앙 고정·직선 신축)
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
            ed.WriteMessage($"\nRAILLEN: 길이={pdr.Value:0}.");
        }

        // 헤드리스 검증용(2차선): 생성(20000) 후 리사이즈(50000) — 개수 유지·비율 이동 확인
        [CommandMethod("RAILTEST")]
        public void RailTest()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Database db = doc.Database;
            ObjectId id;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { id = RailFactory.CreateRail(db, tr, Point3d.Origin, 20000, DEFAULT_LANES, 2); tr.Commit(); }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { var br = (BlockReference)tr.GetObject(id, OpenMode.ForWrite); RailFactory.SetLength(tr, br, 50000); tr.Commit(); }
            doc.Editor.WriteMessage("\nRAILTEST: 20000 생성 후 50000 리사이즈.");
        }

        // 헤드리스 검증용(3차선): native(46750) 생성 후 60000 리사이즈 — station 중앙 고정·직선 신축 확인
        [CommandMethod("RAILTEST3")]
        public void RailTest3()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Database db = doc.Database;
            ObjectId id;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { id = RailFactory.CreateRail(db, tr, Point3d.Origin, DEFAULT_LEN3, 3, 3); tr.Commit(); }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { var br = (BlockReference)tr.GetObject(id, OpenMode.ForWrite); RailFactory.SetLength(tr, br, 60000); tr.Commit(); }
            doc.Editor.WriteMessage("\nRAILTEST3: 46750 생성 후 60000 리사이즈.");
        }
    }

    // 커스텀 그립: 끝(상단) 그립 드래그 → 길이 변경 (크래시 방지 try/catch)
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
                double minlen = RailFactory.MinLen(RailFactory.GetKind(br));
                double newLen = Math.Max(minlen, rgFound.Length + offset.DotProduct(axis));
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
