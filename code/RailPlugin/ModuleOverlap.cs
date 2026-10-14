using System;
using System.Collections.Generic;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.EditorInput;

[assembly: CommandClass(typeof(RailPlugin.ModuleOverlapCommands))]

namespace RailPlugin
{
    // 모듈 겹침 표시 — 모듈(kind 7) 모양끼리 겹쳐 그려지면 그 모듈들만 빨간 레이어로 옮기고,
    //  겹침이 풀리면 원래 레이어로 되돌린다.
    //  겹침 = 두 모듈의 선·호가 서로 가로지르거나(교차점이 양쪽 모두의 끝점이면 = 접속구끼리 맞닿음 → 정상),
    //         한쪽 선·호 위의 점이 다른 쪽 선·호 위에 놓임(포개짐).
    //  블록 안 선·호는 0 레이어·색 BYLAYER 라 블록 참조의 레이어 색을 따른다 → 레이어만 바꾸면 모듈 전체 색이 바뀐다.
    //  변환기는 모듈을 레이어와 상관없이 읽으므로(XData) 빨간 레이어여도 CAD→MAP 에는 영향이 없다.
    public static class ModuleOverlap
    {
        public const string OVERLAP_LAYER = "RAIL_MODULE_OVERLAP";
        public const short OVERLAP_COLOR = 1;       // 빨강
        const string SAVE_APP = "RAILPLUGIN_OVL";   // 빨간 레이어로 옮기기 전 원래 레이어 이름
        const double TOL = 1.0;                     // mm — 맞닿음/포개짐 판정 거리

        sealed class Mod
        {
            public ObjectId Id;
            public List<Curve> Curves = new List<Curve>();
            public Extents3d Ext;
        }

        /// <summary>도면의 모든 모듈을 검사해 겹친 모듈을 빨간 레이어로, 풀린 모듈을 원래 레이어로 옮긴다.
        /// 반환: (모듈 수, 겹친 모듈 수).</summary>
        public static (int modules, int overlapped) Check(Database db)
        {
            var mods = new List<Mod>();
            var hit = new HashSet<ObjectId>();
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                foreach (ObjectId id in ms)
                {
                    var br = tr.GetObject(id, OpenMode.ForRead) as BlockReference;
                    if (br == null || !IsModule(br)) continue;
                    var m = Load(tr, br);
                    if (m != null) mods.Add(m);
                }

                // 범위가 겹치는 쌍만 자세히 본다 (x 최소값 순 스윕)
                mods.Sort((a, b) => a.Ext.MinPoint.X.CompareTo(b.Ext.MinPoint.X));
                for (int i = 0; i < mods.Count; i++)
                {
                    var a = mods[i];
                    for (int j = i + 1; j < mods.Count; j++)
                    {
                        var b = mods[j];
                        if (b.Ext.MinPoint.X > a.Ext.MaxPoint.X + TOL) break;
                        if (!ExtOverlap(a.Ext, b.Ext)) continue;
                        if (Overlaps(a, b)) { hit.Add(a.Id); hit.Add(b.Id); }
                    }
                }

                foreach (var m in mods)
                {
                    var br = (BlockReference)tr.GetObject(m.Id, OpenMode.ForRead);
                    bool red = br.Layer.Equals(OVERLAP_LAYER, StringComparison.OrdinalIgnoreCase);
                    if (hit.Contains(m.Id) && !red) MarkRed(db, tr, br);
                    else if (!hit.Contains(m.Id) && red) Restore(db, tr, br);
                    foreach (var c in m.Curves) c.Dispose();
                }
                tr.Commit();
            }
            return (mods.Count, hit.Count);
        }

        public static bool IsModule(BlockReference br)
            => br.GetXDataForApplication(RailFactory.APP) != null && RailFactory.GetKind(br) == 7;

        static Mod Load(Transaction tr, BlockReference br)
        {
            var bdef = tr.GetObject(br.BlockTableRecord, OpenMode.ForRead) as BlockTableRecord;
            if (bdef == null) return null;
            var m = new Mod { Id = br.ObjectId };
            Matrix3d xf = br.BlockTransform;
            bool first = true;
            foreach (ObjectId eid in bdef)
            {
                var ent = tr.GetObject(eid, OpenMode.ForRead) as Entity;
                if (!(ent is Line) && !(ent is Arc)) continue;
                var c = ent.GetTransformedCopy(xf) as Curve;
                if (c == null) continue;
                m.Curves.Add(c);
                try
                {
                    var e = c.GeometricExtents;
                    if (first) { m.Ext = e; first = false; } else m.Ext.AddExtents(e);
                }
                catch { }
            }
            return first ? null : m;
        }

        static bool ExtOverlap(Extents3d a, Extents3d b)
            => a.MinPoint.X <= b.MaxPoint.X + TOL && b.MinPoint.X <= a.MaxPoint.X + TOL
            && a.MinPoint.Y <= b.MaxPoint.Y + TOL && b.MinPoint.Y <= a.MaxPoint.Y + TOL;

        static bool Overlaps(Mod a, Mod b)
        {
            foreach (var ca in a.Curves)
                foreach (var cb in b.Curves)
                {
                    if (Crosses(ca, cb)) return true;
                }
            // 포개짐: 한쪽 선·호의 안쪽 점이 다른 쪽 선·호 위에 있으면 (양방향 — 짧은 쪽이 긴 쪽 안에 들어간 경우)
            return OnOther(a, b) || OnOther(b, a);
        }

        // 가로지름: 교차점이 두 곡선 모두의 끝점(접속구끼리 맞닿음)이 아니면 겹침
        static bool Crosses(Curve ca, Curve cb)
        {
            var pts = new Point3dCollection();
            try { ca.IntersectWith(cb, Intersect.OnBothOperands, pts, IntPtr.Zero, IntPtr.Zero); }
            catch { return false; }
            foreach (Point3d p in pts)
                if (!(IsEnd(ca, p) && IsEnd(cb, p))) return true;
            return false;
        }

        static bool IsEnd(Curve c, Point3d p)
            => c.StartPoint.DistanceTo(p) <= TOL || c.EndPoint.DistanceTo(p) <= TOL;

        static bool OnOther(Mod a, Mod b)
        {
            foreach (var ca in a.Curves)
            {
                double len;
                try { len = ca.GetDistanceAtParameter(ca.EndParam); } catch { continue; }
                double margin = 2 * TOL;
                if (len <= 2 * margin) continue;
                int n = Math.Max(4, Math.Min(200, (int)(len / 25.0)));
                for (int k = 0; k <= n; k++)
                {
                    double s = margin + (len - 2 * margin) * k / n;
                    Point3d p;
                    try { p = ca.GetPointAtDist(s); } catch { continue; }
                    foreach (var cb in b.Curves)
                    {
                        try
                        {
                            if (p.DistanceTo(cb.GetClosestPointTo(p, false)) <= TOL) return true;
                        }
                        catch { }
                    }
                }
            }
            return false;
        }

        static void MarkRed(Database db, Transaction tr, BlockReference br)
        {
            RailFactory.EnsureRegApp(db, tr, SAVE_APP);
            br.UpgradeOpen();
            string orig = br.Layer;
            br.XData = new ResultBuffer(
                new TypedValue((int)DxfCode.ExtendedDataRegAppName, SAVE_APP),
                new TypedValue((int)DxfCode.ExtendedDataAsciiString, orig));
            br.LayerId = EnsureOverlapLayer(db, tr);
        }

        static void Restore(Database db, Transaction tr, BlockReference br)
        {
            string orig = null;
            ResultBuffer rb = br.GetXDataForApplication(SAVE_APP);
            if (rb != null)
                foreach (TypedValue tv in rb)
                    if (tv.TypeCode == (int)DxfCode.ExtendedDataAsciiString) { orig = (string)tv.Value; break; }
            var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
            br.UpgradeOpen();
            br.LayerId = !string.IsNullOrEmpty(orig) && lt.Has(orig) ? lt[orig] : RailFactory.EnsureModuleLayer(db, tr);
            if (rb != null)   // 앱 이름만 남기면 그 앱의 XData 가 지워진다
                br.XData = new ResultBuffer(new TypedValue((int)DxfCode.ExtendedDataRegAppName, SAVE_APP));
        }

        public static ObjectId EnsureOverlapLayer(Database db, Transaction tr)
        {
            var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
            if (lt.Has(OVERLAP_LAYER)) return lt[OVERLAP_LAYER];
            lt.UpgradeOpen();
            var ltr = new LayerTableRecord
            {
                Name = OVERLAP_LAYER,
                Color = Autodesk.AutoCAD.Colors.Color.FromColorIndex(Autodesk.AutoCAD.Colors.ColorMethod.ByAci, OVERLAP_COLOR),
            };
            ObjectId id = lt.Add(ltr);
            tr.AddNewlyCreatedDBObject(ltr, true);
            return id;
        }

        // ── 자동 검사: 명령 중에 모듈이 추가·변경·삭제되면 그 명령이 끝날 때 한 번 검사 ──
        static readonly HashSet<Database> _dirty = new HashSet<Database>();
        static readonly HashSet<Document> _hookedDocs = new HashSet<Document>();
        static bool _busy, _hooked;

        public static void Hook()
        {
            if (_hooked) return;
            try
            {
                foreach (Document d in Application.DocumentManager) HookDoc(d);
                Application.DocumentManager.DocumentCreated += (s, e) => HookDoc(e.Document);
                Application.DocumentManager.DocumentToBeDestroyed += (s, e) => UnhookDoc(e.Document);
                _hooked = true;
            }
            catch { }
        }

        static void HookDoc(Document doc)
        {
            if (doc == null || _hookedDocs.Contains(doc)) return;
            try
            {
                Database db = doc.Database;
                db.ObjectAppended += OnObject;
                db.ObjectModified += OnObject;
                db.ObjectErased += OnErased;
                doc.CommandEnded += OnCommandEnded;
                _hookedDocs.Add(doc);
            }
            catch { }
        }

        static void UnhookDoc(Document doc)
        {
            if (doc == null || !_hookedDocs.Contains(doc)) return;
            try
            {
                Database db = doc.Database;
                db.ObjectAppended -= OnObject;
                db.ObjectModified -= OnObject;
                db.ObjectErased -= OnErased;
                doc.CommandEnded -= OnCommandEnded;
                _dirty.Remove(db);
            }
            catch { }
            _hookedDocs.Remove(doc);
        }

        static void OnObject(object sender, ObjectEventArgs e) => Flag(sender as Database, e.DBObject);
        static void OnErased(object sender, ObjectErasedEventArgs e) => Flag(sender as Database, e.DBObject);

        static void Flag(Database db, DBObject o)
        {
            if (_busy || db == null) return;
            try
            {
                var br = o as BlockReference;
                if (br != null && br.GetXDataForApplication(RailFactory.APP) != null) _dirty.Add(db);
            }
            catch { }
        }

        static void OnCommandEnded(object sender, CommandEventArgs e)
        {
            var doc = sender as Document;
            if (doc == null || _busy || !_dirty.Contains(doc.Database)) return;
            string cmd = (e.GlobalCommandName ?? "").ToUpperInvariant();
            // 되돌리기 뒤에 다시 고치면 그 변경이 다음 되돌리기에 걸려 되돌리기가 반복된다 → 다음 명령 때 검사
            if (cmd == "U" || cmd == "UNDO" || cmd == "REDO" || cmd == "MREDO") return;
            _dirty.Remove(doc.Database);
            _busy = true;
            try
            {
                using (doc.LockDocument())
                {
                    var r = Check(doc.Database);
                    if (r.overlapped > 0)
                        doc.Editor.WriteMessage($"\n[모듈 겹침] {r.overlapped}개 모듈이 겹쳐 있어 빨간색({OVERLAP_LAYER})으로 표시했습니다.");
                }
            }
            catch { }
            finally { _busy = false; }
        }

        /// <summary>명령에서 직접 검사할 때 (자동 검사 이벤트가 다시 걸리지 않게).</summary>
        public static (int modules, int overlapped) CheckNow(Database db)
        {
            _busy = true;
            try { return Check(db); }
            finally { _busy = false; _dirty.Remove(db); }
        }
    }

    public class ModuleOverlapCommands
    {
        // 리본 [겹침 검사]: 도면 전체 모듈의 겹침을 다시 검사해 색을 맞춘다.
        [CommandMethod("RAILMODOVERLAP")]
        public void RailModOverlap()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            var r = ModuleOverlap.CheckNow(doc.Database);
            doc.Editor.WriteMessage(r.overlapped > 0
                ? $"\nRAILMODOVERLAP: 모듈 {r.modules}개 중 {r.overlapped}개가 겹쳐 있어 빨간색({ModuleOverlap.OVERLAP_LAYER})으로 표시했습니다."
                : $"\nRAILMODOVERLAP: 모듈 {r.modules}개 — 겹친 모듈이 없습니다.");
        }

        // ── 헤드리스 검증 ──
        //  RAILMODOVLTEST1: 쌍 4종 배치(같은 자리 2개 / 90° 돌려 십자로 겹침 / 접속구끼리 맞닿음 / 혼자) — 검사는 자동(명령 끝)
        //  RAILMODOVLREPORT: 모듈별 위치·레이어 출력
        //  RAILMODOVLTEST2: 같은 자리 쌍 중 하나 삭제 → 남은 하나는 원래 색으로 돌아와야 함
        [CommandMethod("RAILMODOVLTEST1")]
        public void Test1()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Database db = doc.Database;
            double r = 450, l = 200, w = 900, a = 45;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                // A: CURVE LEFT 두 개를 같은 자리에 (포개짐)
                RailFactory.PlaceModule(db, tr, new Point3d(0, 0, 0), 0, r, l, w, a);
                RailFactory.PlaceModule(db, tr, new Point3d(0, 0, 0), 0, r, l, w, a);
                // B: BRANCH LEFT 와 90° 돌린 BRANCH LEFT (가로지름)
                RailFactory.PlaceModule(db, tr, new Point3d(10000, 0, 0), 2, r, l, w, a);
                var idB = RailFactory.PlaceModule(db, tr, new Point3d(10000, 0, 0), 2, r, l, w, a);
                var bB = (BlockReference)tr.GetObject(idB, OpenMode.ForWrite);
                Point3d cB = Center(tr, bB);
                bB.TransformBy(Matrix3d.Rotation(Math.PI / 2, Vector3d.ZAxis, cB));
                // C: CURVE LEFT 와, 그 끝점을 중심으로 180° 돌린 복사본 (끝점끼리만 맞닿음 = 정상)
                var idC = RailFactory.PlaceModule(db, tr, new Point3d(20000, 0, 0), 0, r, l, w, a);
                var bC = (BlockReference)tr.GetObject(idC, OpenMode.ForRead);
                Point3d endC = FreeEnd(tr, bC);
                var idC2 = RailFactory.PlaceModule(db, tr, new Point3d(20000, 0, 0), 0, r, l, w, a);
                var bC2 = (BlockReference)tr.GetObject(idC2, OpenMode.ForWrite);
                bC2.TransformBy(Matrix3d.Rotation(Math.PI, Vector3d.ZAxis, endC));
                // D: 혼자
                RailFactory.PlaceModule(db, tr, new Point3d(30000, 0, 0), 5, r, l, w, a);
                tr.Commit();
            }
            doc.Editor.WriteMessage("\nRAILMODOVLTEST1: 7개 배치(겹침 기대 = x 0 두 개, x 10000 두 개).");
        }

        [CommandMethod("RAILMODOVLTEST2")]
        public void Test2()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Database db = doc.Database;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                foreach (ObjectId id in ms)
                {
                    var br = tr.GetObject(id, OpenMode.ForRead) as BlockReference;
                    if (br != null && ModuleOverlap.IsModule(br) && br.Position.DistanceTo(Point3d.Origin) < 1)
                    { br.UpgradeOpen(); br.Erase(); break; }
                }
                tr.Commit();
            }
            doc.Editor.WriteMessage("\nRAILMODOVLTEST2: x 0 의 모듈 하나 삭제(남은 하나는 원래 색이어야 함).");
        }

        [CommandMethod("RAILMODOVLREPORT")]
        public void Report()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Database db = doc.Database;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                foreach (ObjectId id in ms)
                {
                    var br = tr.GetObject(id, OpenMode.ForRead) as BlockReference;
                    if (br == null || !ModuleOverlap.IsModule(br)) continue;
                    doc.Editor.WriteMessage($"\n  OVL module @({br.Position.X:0},{br.Position.Y:0}) rot {br.Rotation * 180 / Math.PI:0} layer={br.Layer}");
                }
                tr.Commit();
            }
        }

        static Point3d Center(Transaction tr, BlockReference br)
        {
            var e = br.GeometricExtents;
            return new Point3d((e.MinPoint.X + e.MaxPoint.X) / 2, (e.MinPoint.Y + e.MaxPoint.Y) / 2, 0);
        }

        // 모듈의 끝점 중 다른 선·호와 공유되지 않는 점(= 접속구) 하나
        static Point3d FreeEnd(Transaction tr, BlockReference br)
        {
            var bdef = (BlockTableRecord)tr.GetObject(br.BlockTableRecord, OpenMode.ForRead);
            var ends = new List<Point3d>();
            foreach (ObjectId eid in bdef)
            {
                var c = tr.GetObject(eid, OpenMode.ForRead) as Curve;
                if (c == null) continue;
                ends.Add(c.StartPoint.TransformBy(br.BlockTransform));
                ends.Add(c.EndPoint.TransformBy(br.BlockTransform));
            }
            foreach (var p in ends)
            {
                int n = 0;
                foreach (var q in ends) if (q.DistanceTo(p) < 1e-3) n++;
                if (n == 1) return p;
            }
            return br.Position;
        }
    }
}
