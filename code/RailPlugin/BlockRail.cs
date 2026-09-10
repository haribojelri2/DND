using System;
using System.Collections.Generic;
using System.IO;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.EditorInput;

[assembly: CommandClass(typeof(RailPlugin.BlockRailCommands))]

namespace RailPlugin
{
    // 부품 블록 임포트: 번들 DXF(BlockCatalog.SourceDxfName, DLL 옆)에서 블록 정의를 현재 도면으로 복제.
    public static class BlockImport
    {
        public static string BundlePath()
        {
            string dir = Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location);
            return Path.Combine(dir, BlockCatalog.SourceDxfName);
        }

        // 필요 블록들이 도면에 없으면 번들 DXF에서 한꺼번에 복제. 반환: 이름→BlockTableRecord ObjectId.
        public static Dictionary<string, ObjectId> Ensure(Database db, Transaction tr, params string[] names)
        {
            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
            var result = new Dictionary<string, ObjectId>();
            var missing = new List<string>();
            foreach (string n in names)
            {
                if (bt.Has(n)) result[n] = bt[n];
                else missing.Add(n);
            }
            if (missing.Count > 0)
            {
                string path = BundlePath();
                if (!File.Exists(path))
                    throw new InvalidOperationException("부품 DXF 없음: " + path);
                using (var src = new Database(false, true))
                {
                    src.DxfIn(path, null);
                    var ids = new ObjectIdCollection();
                    using (var str = src.TransactionManager.StartTransaction())
                    {
                        var sbt = (BlockTable)str.GetObject(src.BlockTableId, OpenMode.ForRead);
                        foreach (string n in missing)
                        {
                            if (!sbt.Has(n))
                                throw new InvalidOperationException("부품 블록 없음: " + n);
                            ids.Add(sbt[n]);
                        }
                        str.Commit();
                    }
                    var map = new IdMapping();
                    db.WblockCloneObjects(ids, db.BlockTableId, map, DuplicateRecordCloning.Ignore, false);
                }
                bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                foreach (string n in missing) result[n] = bt[n];
            }
            return result;
        }
    }

    // 블록 조립 베이 레일 (kind=4) — BAY 1 레이아웃, B안(BRANCH 블록 코너).
    //  로컬: 좌레일 x=0, 우레일 x=W, y=0..L.
    //  U아치(상/하) = BRANCH RIGHT/LEFT 블록 코너 + 가변 바(W-1300).  ★U분기 직선(바)만 신축 규칙★
    //  보타이 스테이션 = BRANCH 블록 코너 4개 + 바 2개(간격 700). 등간격(클리어 균등) 배치.
    //  레일 = 블록의 레일조각(1035) 사이를 필러 LINE으로 연결.
    public static class BlockRailGeom
    {
        public const double MINLEN = 10000.0;
        public const double MINW = 1500.0;        // 바 = W-1300 > 0 여유
        public const double RAILPC = 1035.0;      // BRANCH 블록 레일조각 길이
        public const double BARIN = 650.0;        // 바 끝 x = 레일 ± 650
        public const double BAROFF = 385.0;       // 아치 바 y = 레일끝에서 385 안쪽
        public const double HALF = 1000.0;        // 보타이 반높이 (코너 레일조각 포함)
        public const double BAR_HGAP = 350.0;     // 보타이 바 = 중심 ± 350

        // 스텁 끝(바 접점)의 블록 내 좌표 — rot0: P = 바끝 − 스텁, rot180: P = 바끝 + 스텁
        static readonly Point3d STUB_L = new Point3d(51330.7, 36027.1, 0);   // BRANCH LEFT
        static readonly Point3d STUB_R = new Point3d(52630.7, 33905.2, 0);   // BRANCH RIGHT

        public const double XGAP = 900.0;      // 크로스오버(BRANCH N) 레일 간격 (고정)
        public const double XOVER_H = 1670.0;  // 크로스오버 블록 레일조각 높이
        public const double BGAP = 1350.0;     // U턴 브릿지(2CH) 레일 간격 (고정)
        public const double BRIDGE_H = 1035.0; // 브릿지 블록 레일조각 높이

        // BRANCH N / 2CH 기준 포트(좌측 레일 하단)의 블록 내 좌표
        //  (2026-07-28: N 레일조각 1502→1670 수정으로 하단이 84 내려감)
        static readonly Point3d REF_NL = new Point3d(42092.6, 49566.9, 0);   // BRANCH N LEFT
        static readonly Point3d REF_NR = new Point3d(44168.9, 49816.9, 0);   // BRANCH N RIGHT
        static readonly Point3d REF_2CH = new Point3d(27592.0, 60273.1, 0);  // DOUBLE BRANCH 2CH

        // lanes: 2=레일2+아치/보타이(폭 W 가변), 3=페어(900,크로스오버)+아치/보타이(W 가변),
        //        4=페어(900)+브릿지(1350)+페어(900), 바깥 아치 (전 간격 고정)
        public static void Fill(BlockTableRecord btr, Transaction tr, double L, int count, double W, int lanes)
        {
            if (L < MINLEN) L = MINLEN;
            if (W < MINW) W = MINW;
            if (count < 0) count = 0;
            Database db = btr.Database;
            var defs = BlockImport.Ensure(db, tr, "BRANCH LEFT", "BRANCH RIGHT",
                                          "BRANCH N LEFT", "BRANCH N RIGHT", "DOUBLE BRANCH 2CH");
            ObjectId BL = defs["BRANCH LEFT"], BR = defs["BRANCH RIGHT"];
            ObjectId NL = defs["BRANCH N LEFT"], NR = defs["BRANCH N RIGHT"];
            ObjectId CH2 = defs["DOUBLE BRANCH 2CH"];

            void Add(Entity e) { btr.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true); }
            void Put(ObjectId bid, double px, double py, double rotDeg)
            {
                var b = new BlockReference(new Point3d(px, py, 0), bid) { Rotation = rotDeg * Math.PI / 180.0 };
                Add(b);
            }
            var occ = new Dictionary<double, List<(double lo, double hi)>>();   // 레일x → 점유 구간
            void Occ(double x, double lo, double hi)
            { if (!occ.ContainsKey(x)) occ[x] = new List<(double, double)>(); occ[x].Add((lo, hi)); }

            // ── 아치/보타이 (x1~x2 사이, 바만 가변) ──
            void Bar(double x1, double x2, double y) => Rail34Geom.AddLinePart(btr, tr, new Point3d(x1 + BARIN, y, 0), new Point3d(x2 - BARIN, y, 0));
            void CornerUpL(double x1, double barY) => Put(BR, x1 + BARIN - STUB_R.X, barY - STUB_R.Y, 0);
            void CornerUpR(double x2, double barY) => Put(BL, x2 - BARIN - STUB_L.X, barY - STUB_L.Y, 0);
            void CornerDnL(double x1, double barY) => Put(BL, x1 + BARIN + STUB_L.X, barY + STUB_L.Y, 180);
            void CornerDnR(double x2, double barY) => Put(BR, x2 - BARIN + STUB_R.X, barY + STUB_R.Y, 180);
            void Arches(double x1, double x2, int nBowtie)
            {
                Bar(x1, x2, BAROFF); CornerDnL(x1, BAROFF); CornerDnR(x2, BAROFF);
                Occ(x1, 0, RAILPC); Occ(x2, 0, RAILPC);
                Bar(x1, x2, L - BAROFF); CornerUpL(x1, L - BAROFF); CornerUpR(x2, L - BAROFF);
                Occ(x1, L - RAILPC, L); Occ(x2, L - RAILPC, L);
                double g = (L - 2 * RAILPC - nBowtie * 2 * HALF) / (nBowtie + 1);
                for (int i = 0; i < nBowtie; i++)
                {
                    double yc = RAILPC + (i + 1) * g + (2 * i + 1) * HALF;
                    // 보타이 = DOUBLE BRANCH_700 세로(90°) − 직 2개 − 세로(−90°) [DB−직−DB = 4CH 규칙]
                    Rail34Geom.Funnel4At(btr, tr, x1, yc - BAR_HGAP, x2 - x1);
                    Occ(x1, yc - HALF, yc + HALF); Occ(x2, yc - HALF, yc + HALF);
                }
            }
            // ── 크로스오버 페어 (x1, x1+900): count개 등간격, L/R 교대 ──
            void Xovers(double x1, int n, double yLo, double yHi)
            {
                double g = (yHi - yLo - n * XOVER_H) / (n + 1);
                for (int i = 0; i < n; i++)
                {
                    double y = yLo + (i + 1) * g + i * XOVER_H;
                    if (i % 2 == 0) Put(NL, x1 - REF_NL.X, y - REF_NL.Y, 0);
                    else Put(NR, x1 - REF_NR.X, y - REF_NR.Y, 0);
                    Occ(x1, y, y + XOVER_H); Occ(x1 + XGAP, y, y + XOVER_H);
                }
            }
            // ── U턴 브릿지 (x1, x1+1350): count개 등간격, 상/하향 교대 ──
            void Bridges(double x1, int n, double yLo, double yHi)
            {
                double g = (yHi - yLo - n * BRIDGE_H) / (n + 1);
                for (int i = 0; i < n; i++)
                {
                    double y = yLo + (i + 1) * g + i * BRIDGE_H;
                    if (i % 2 == 0) Put(CH2, x1 - REF_2CH.X, y - REF_2CH.Y, 0);
                    else Put(CH2, x1 + BGAP + REF_2CH.X, y + BRIDGE_H + REF_2CH.Y, 180);
                    Occ(x1, y, y + BRIDGE_H); Occ(x1 + BGAP, y, y + BRIDGE_H);
                }
            }

            var railSpan = new Dictionary<double, (double lo, double hi)>();   // 레일x → 전체 스팬

            if (lanes <= 2)
            {
                railSpan[0] = (0, L); railSpan[W] = (0, L);
                Arches(0, W, count);
            }
            else if (lanes == 3)
            {
                // 좌 페어(0,900) 크로스오버 + (900, 900+W) 아치/보타이
                railSpan[0] = (0, L); railSpan[XGAP] = (0, L); railSpan[XGAP + W] = (0, L);
                Arches(XGAP, XGAP + W, count);
                Xovers(0, count, RAILPC, L - RAILPC);
            }
            else
            {
                // 4차선: 페어(0,900) + 브릿지(900~2250) + 페어(2250,3150), 바깥 아치(0~3150)
                double xB = XGAP, xC = XGAP + BGAP, xD = XGAP + BGAP + XGAP;
                railSpan[0] = (0, L); railSpan[xD] = (0, L);
                railSpan[xB] = (RAILPC, L - RAILPC); railSpan[xC] = (RAILPC, L - RAILPC);
                Arches(0, xD, 0);                       // 바깥 아치 (보타이 없음)
                Xovers(0, count, RAILPC, L - RAILPC);   // 좌 페어
                Xovers(xC, count, RAILPC, L - RAILPC);  // 우 페어
                Bridges(xB, count, RAILPC, L - RAILPC); // 중앙 브릿지
            }

            // ── 레일 필러: 스팬 내 점유 구간 사이/양끝 채움 ──
            foreach (var kv in railSpan)
            {
                double x = kv.Key; double lo = kv.Value.lo, hi = kv.Value.hi;
                List<(double lo, double hi)> iv = occ.ContainsKey(x) ? occ[x] : new List<(double lo, double hi)>();
                iv.Sort((a, b) => a.lo.CompareTo(b.lo));
                double cur = lo;
                foreach (var (a, b2) in iv)
                {
                    if (a - cur > 0.001) Rail34Geom.AddLinePart(btr, tr, new Point3d(x, cur, 0), new Point3d(x, a, 0));
                    cur = Math.Max(cur, b2);
                }
                if (hi - cur > 0.001) Rail34Geom.AddLinePart(btr, tr, new Point3d(x, cur, 0), new Point3d(x, hi, 0));
            }
        }
    }

    public class BlockRailCommands
    {
        // 구형 2차선(베이, DRAWRAILB)은 완전 삭제됨 — 2차선 = 2rail 변형(리본 드롭다운)

        // 리본 드롭다운 → 명령 브릿지 (버튼이 Pending 설정 후 명령 실행)
        public static int PendingVariant = -1;
        public static string PendingPart = null;

        // 0716 매니페스트 변형 생성 (리본 드롭다운: PendingVariant / 명령: 목록에서 번호)
        [CommandMethod("DRAWRAILV")]
        public void DrawRailV()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            int vi = PendingVariant; PendingVariant = -1;
            if (vi < 0 || vi >= Rail34Manifest.Variants.Count)
            {
                for (int i = 0; i < Rail34Manifest.Variants.Count; i++)
                    ed.WriteMessage($"\n {i + 1}. {Rail34Manifest.Variants[i].Name}");
                var pio = new PromptIntegerOptions("\n변형 번호: ") { LowerLimit = 1, UpperLimit = Rail34Manifest.Variants.Count };
                PromptIntegerResult pir = ed.GetInteger(pio);
                if (pir.Status != PromptStatus.OK) return;
                vi = pir.Value - 1;
            }
            var v = Rail34Manifest.Variants[vi];
            PromptPointResult p0 = ed.GetPoint($"\n{v.Name} 위치: ");
            if (p0.Status != PromptStatus.OK) return;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { RailFactory.CreateRail(db, tr, p0.Value, Rail34Manifest.L0, vi, 5, v.Wn, v.Lanes); tr.Commit(); }
            ed.WriteMessage($"\nDRAWRAILV: {v.Name} 생성 (native 59100). RAILLEN/그립=길이{(v.Wn > 0 ? ", RAILW=우측 폭(바만 신축)" : "")}.");
        }

        // 3차선 변형 목록 (명령용)
        [CommandMethod("DRAWRAILB3")]
        public void DrawRailB3() { PendingVariant = -1; DrawRailVRange(0, 8, "3차선"); }

        // 4차선 변형 목록 (명령용)
        [CommandMethod("DRAWRAILB4")]
        public void DrawRailB4() { PendingVariant = -1; DrawRailVRange(8, 24, "4차선"); }

        void DrawRailVRange(int lo, int hi, string label)
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            for (int i = lo; i < hi; i++)
                ed.WriteMessage($"\n {i - lo + 1}. {Rail34Manifest.Variants[i].Name}");
            var pio = new PromptIntegerOptions($"\n{label} 변형 번호: ") { LowerLimit = 1, UpperLimit = hi - lo };
            PromptIntegerResult pir = ed.GetInteger(pio);
            if (pir.Status != PromptStatus.OK) return;
            PendingVariant = lo + pir.Value - 1;
            DrawRailV();
        }

        // 폭 변경: U분기(아치/보타이) 바만 늘어나고 블록 코너는 통째 이동 — ★규칙 구현★
        [CommandMethod("RAILW")]
        public void RailW()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            var peo = new PromptEntityOptions("\n베이 레일 선택: ");
            peo.SetRejectMessage("\n레일(블록)만."); peo.AddAllowedClass(typeof(BlockReference), false);
            PromptEntityResult per = ed.GetEntity(peo);
            if (per.Status != PromptStatus.OK) return;
            PromptDoubleResult pdr = ed.GetDouble("\n새 폭(레일 간격): ");
            if (pdr.Status != PromptStatus.OK) return;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var br = (BlockReference)tr.GetObject(per.ObjectId, OpenMode.ForWrite);
                if (RailFactory.GetKind(br) < 4) { ed.WriteMessage("\n블록 레일(2차선/3·4차선 변형/신축 파츠)만 가능."); return; }
                RailFactory.SetWidth(tr, br, pdr.Value);
                tr.Commit();
            }
            ed.WriteMessage($"\nRAILW: 폭={pdr.Value:0} (U분기 직선만 신축).");
        }

        // 부품 블록 개별 삽입: 리본 드롭다운(PendingPart) 또는 번호 선택 → 위치 클릭 (클릭점 = 레일 접점)
        [CommandMethod("RAILPART")]
        public void RailPart()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            string name = PendingPart; PendingPart = null;
            if (name == null || !BlockCatalog.Parts.ContainsKey(name))
            {
                var names = new List<string>(BlockCatalog.Parts.Keys);
                for (int i = 0; i < names.Count; i++)
                    ed.WriteMessage($"\n {i + 1}. {names[i]}");
                var pio = new PromptIntegerOptions("\n부품 번호: ") { LowerLimit = 1, UpperLimit = names.Count };
                PromptIntegerResult pir = ed.GetInteger(pio);
                if (pir.Status != PromptStatus.OK) return;
                name = names[pir.Value - 1];
            }
            PromptPointResult p0 = ed.GetPoint($"\n{name} 위치(레일 접점): ");
            if (p0.Status != PromptStatus.OK) return;
            // U분기형(가로 직선 보유) 파츠 = kind6 신축 레일로 생성 → 좌/우 그립으로 바만 신축
            int fam = System.Array.IndexOf(Rail34Geom.PartFam, name);
            if (fam >= 0)
            {
                using (Transaction tr = db.TransactionManager.StartTransaction())
                { RailFactory.CreateRail(db, tr, p0.Value, 0, fam, 6, Rail34Geom.PartFamG[fam], 2); tr.Commit(); }
                ed.WriteMessage($"\nRAILPART: {name} 삽입 (신축 파츠 — 좌/우 그립·RAILW로 폭 변경, U분기 직선만 신축).");
                return;
            }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var defs = BlockImport.Ensure(db, tr, name);
                var part = BlockCatalog.Parts[name];
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);
                // base=(0,0)·지오는 절대좌표에 있으므로: 삽입점 = 클릭점 − RefOffset
                var pos = new Point3d(p0.Value.X - part.RefOffset.X, p0.Value.Y - part.RefOffset.Y, 0);
                var b = new BlockReference(pos, defs[name]);
                ms.AppendEntity(b); tr.AddNewlyCreatedDBObject(b, true);
                tr.Commit();
            }
            ed.WriteMessage($"\nRAILPART: {name} 삽입.");
        }

        // 레일 재생성(복구): 현재 길이/폭/변형 그대로 파츠로 다시 그림 — 깨진 레일 수리
        [CommandMethod("RAILFIX")]
        public void RailFix()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            var peo = new PromptEntityOptions("\n복구할 레일 선택: ");
            peo.SetRejectMessage("\n레일(블록)만."); peo.AddAllowedClass(typeof(BlockReference), false);
            PromptEntityResult per = ed.GetEntity(peo);
            if (per.Status != PromptStatus.OK) return;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var br = (BlockReference)tr.GetObject(per.ObjectId, OpenMode.ForWrite);
                double len = RailFactory.GetLength(br);
                if (len <= 0) { ed.WriteMessage("\n레일 블록이 아닙니다."); return; }
                RailFactory.SetLength(tr, br, len);   // 동일 파라미터로 완전 재생성
                tr.Commit();
            }
            ed.WriteMessage("\nRAILFIX: 재생성 완료.");
        }

        // 헤드리스 검증(매니페스트): 24종 전부 native 생성(그리드) + rail3_02 리사이즈(70000/2000)
        [CommandMethod("RAILTESTM")]
        public void RailTestM()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Database db = doc.Database;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                for (int i = 0; i < Rail34Manifest.Variants.Count; i++)
                {
                    var v = Rail34Manifest.Variants[i];
                    RailFactory.CreateRail(db, tr, new Point3d(i * 8000.0, 0, 0), Rail34Manifest.L0, i, 5, v.Wn, v.Lanes);
                }
                tr.Commit();
            }
            ObjectId id;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { id = RailFactory.CreateRail(db, tr, new Point3d(1 * 8000.0, 70000, 0), Rail34Manifest.L0, 1, 5, Rail34Manifest.Variants[1].Wn, 3); tr.Commit(); }
            ObjectId id4;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { id4 = RailFactory.CreateRail(db, tr, new Point3d(10 * 8000.0, 70000, 0), Rail34Manifest.L0, 14, 5, Rail34Manifest.Variants[14].Wn, 4); tr.Commit(); }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { var br4 = (BlockReference)tr.GetObject(id4, OpenMode.ForWrite); RailFactory.SetWidth(tr, br4, 2000); tr.Commit(); }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { var br = (BlockReference)tr.GetObject(id, OpenMode.ForWrite); RailFactory.SetLength(tr, br, 70000); tr.Commit(); }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { var br = (BlockReference)tr.GetObject(id, OpenMode.ForWrite); RailFactory.SetWidth(tr, br, 2000); tr.Commit(); }
            // 아치 파츠 폭 교체: rail4_top_03(1350) → W900 (_900 반원 파츠) / rail4_top_01(900) → W1350 (1350 파츠)
            ObjectId id9, id13;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                id9 = RailFactory.CreateRail(db, tr, new Point3d(12 * 8000.0, 70000, 0), Rail34Manifest.L0, 14, 5, Rail34Manifest.Variants[14].Wn, 4);
                id13 = RailFactory.CreateRail(db, tr, new Point3d(14 * 8000.0, 70000, 0), Rail34Manifest.L0, 12, 5, Rail34Manifest.Variants[12].Wn, 4);
                tr.Commit();
            }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { var br = (BlockReference)tr.GetObject(id9, OpenMode.ForWrite); RailFactory.SetWidth(tr, br, 900); tr.Commit(); }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { var br = (BlockReference)tr.GetObject(id13, OpenMode.ForWrite); RailFactory.SetWidth(tr, br, 1350); tr.Commit(); }
            // 신축 파츠(kind6): 2CH → W2000 (3피스), 깔때기 DOUBLE BRANCH → W1200 (바만 신축)
            ObjectId ip1, ip2;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                ip1 = RailFactory.CreateRail(db, tr, new Point3d(16 * 8000.0, 70000, 0), 0, 0, 6, 1350, 2);
                ip2 = RailFactory.CreateRail(db, tr, new Point3d(17 * 8000.0, 70000, 0), 0, 4, 6, 650, 2);
                tr.Commit();
            }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { var br = (BlockReference)tr.GetObject(ip1, OpenMode.ForWrite); RailFactory.SetWidth(tr, br, 2000); tr.Commit(); }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { var br = (BlockReference)tr.GetObject(ip2, OpenMode.ForWrite); RailFactory.SetWidth(tr, br, 1200); tr.Commit(); }
            // 원형 보타이(#BOWTIE, rail3_01 1020) 스트레치 → DB_700 세로 조립
            ObjectId ib;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { ib = RailFactory.CreateRail(db, tr, new Point3d(18 * 8000.0, 70000, 0), Rail34Manifest.L0, 0, 5, Rail34Manifest.Variants[0].Wn, 3); tr.Commit(); }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { var br = (BlockReference)tr.GetObject(ib, OpenMode.ForWrite); RailFactory.SetWidth(tr, br, 1500); tr.Commit(); }
            // 2차선(2rail_1, idx 30) W2000 → 보타이 DB_700 세로 조립
            ObjectId i2r;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { i2r = RailFactory.CreateRail(db, tr, new Point3d(19 * 8000.0, 70000, 0), Rail34Manifest.L0, 30, 5, Rail34Manifest.Variants[30].Wn, 2); tr.Commit(); }
            using (Transaction tr = db.TransactionManager.StartTransaction())
            { var br = (BlockReference)tr.GetObject(i2r, OpenMode.ForWrite); RailFactory.SetWidth(tr, br, 2000); tr.Commit(); }
            // 세로 스트레치 검증: 신형 3차선(8)·기존 4차선(12)·2차선(30) → L=70000
            foreach (var (vi2, px2) in new[] { (8, 20), (12, 21), (30, 22) })
            {
                ObjectId sid;
                using (Transaction tr = db.TransactionManager.StartTransaction())
                { sid = RailFactory.CreateRail(db, tr, new Point3d(px2 * 8000.0, 70000, 0), Rail34Manifest.L0, vi2, 5, Rail34Manifest.Variants[vi2].Wn, Rail34Manifest.Variants[vi2].Lanes); tr.Commit(); }
                using (Transaction tr = db.TransactionManager.StartTransaction())
                { var br = (BlockReference)tr.GetObject(sid, OpenMode.ForWrite); RailFactory.SetLength(tr, br, 70000); tr.Commit(); }
            }
            doc.Editor.WriteMessage("\nRAILTESTM: 38종 native + 리사이즈/신축 케이스 완료.");
        }

        // 도면의 정형화 부품 수량 집계 — 변환기(part_counter.py)와 같은 규칙으로 명령창에 표시.
        //  조립체(폭이 900·1350 이 아닌 U턴 브릿지)는 대표 엔티티의 RAILPART 태그로 1개로 센다.
        [CommandMethod("RAILCOUNT")]
        public void RailCount()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            var tally = new SortedDictionary<string, int>(StringComparer.Ordinal);
            int taggedTotal = 0;

            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);

                // 엔티티의 조립체 태그 읽기 → (논리명, 폭, 역할)
                bool ReadTag(Entity e, out string nm, out double w, out int role)
                {
                    nm = null; w = 0; role = 0;
                    ResultBuffer rb = e.GetXDataForApplication(Rail34Geom.PARTAPP);
                    if (rb == null) return false;
                    foreach (TypedValue tv in rb)
                    {
                        if (tv.TypeCode == (int)DxfCode.ExtendedDataAsciiString && nm == null) nm = (string)tv.Value;
                        else if (tv.TypeCode == (int)DxfCode.ExtendedDataReal) w = (double)tv.Value;
                        else if (tv.TypeCode == (int)DxfCode.ExtendedDataInteger16) role = (short)tv.Value;
                    }
                    return nm != null;
                }
                void Bump(string key, int n)
                { tally.TryGetValue(key, out int c); tally[key] = c + n; }

                void Walk(BlockTableRecord owner, int depth, int mult)
                {
                    if (depth > 8) return;
                    foreach (ObjectId id in owner)
                    {
                        var ent = tr.GetObject(id, OpenMode.ForRead) as Entity;
                        if (ent == null) continue;
                        // 비-INSERT(호 등)에 붙은 대표 태그 = 조립체 1개
                        if (!(ent is BlockReference) && ReadTag(ent, out string tn, out double tw, out int trole))
                        {
                            if (trole == 0) { Bump($"{tn}|{tw:0}", mult); taggedTotal += mult; }
                            continue;
                        }
                        var br2 = ent as BlockReference;
                        if (br2 == null) continue;
                        // 조립체 구성원 블록(BRANCH 코너 등)은 개별 부품으로 세지 않는다
                        if (ReadTag(br2, out string bn, out double bw, out int brole))
                        {
                            if (brole == 0) { Bump($"{bn}|{bw:0}", mult); taggedTotal += mult; }
                            continue;
                        }
                        var def = (BlockTableRecord)tr.GetObject(br2.BlockTableRecord, OpenMode.ForRead);
                        string name = def.Name ?? "";
                        string up = name.ToUpperInvariant();
                        if (up.StartsWith("BRANCH") || up.StartsWith("DOUBLE BRANCH"))
                        { Bump(BlockCatalog.CountKey(name), mult); continue; }
                        if (up.StartsWith("RP_") || def.IsLayout) continue;
                        Walk(def, depth + 1, mult);
                    }
                }
                Walk(ms, 0, 1);
                tr.Commit();
            }

            int total = 0;
            ed.WriteMessage("\n\n── 부품 수량 ──────────────────────────────");
            ed.WriteMessage("\n{0,-26} {1,6} {2,5}", "부품명", "폭", "수량");
            foreach (var kv in tally)
            {
                int bar = kv.Key.IndexOf('|');
                string nm = bar < 0 ? kv.Key : kv.Key.Substring(0, bar);
                string w = bar < 0 ? "" : kv.Key.Substring(bar + 1);
                if (w == "0") w = "";
                ed.WriteMessage("\n{0,-26} {1,6} {2,5}", nm, w, kv.Value);
                total += kv.Value;
            }
            ed.WriteMessage("\n───────────────────────────────────────────");
            ed.WriteMessage($"\n{tally.Count}종 {total}개 (조립체 태그로 잡은 것 {taggedTotal}개)");
            ed.WriteMessage("\n※ 변환기(map 생성)도 같은 규칙으로 <도면이름>_parts.csv 를 만듭니다.\n");
        }

        // 헤드리스 검증(임의 폭): 고정폭 4종(900·1020·1270·1350) + 그 사이/이상 폭까지
        //  U턴 브릿지는 1300 미만이 호-직-호(ArcBridgeAt), 이상이 3피스/_700 조립 — 두 경로 모두 확인.
        [CommandMethod("RAILTESTW")]
        public void RailTestW()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Database db = doc.Database;
            double[] ws = { 900, 1020, 1150, 1270, 1300, 1350, 2000 };

            // 1) 단독 파츠(kind6): 2CH(f=0) / 4CH(f=1)
            for (int f = 0; f <= 1; f++)
                for (int k = 0; k < ws.Length; k++)
                {
                    ObjectId id;
                    using (Transaction tr = db.TransactionManager.StartTransaction())
                    { id = RailFactory.CreateRail(db, tr, new Point3d(k * 6000.0, f * 6000.0, 0), 0, f, 6, Rail34Geom.PartFamG[f], 2); tr.Commit(); }
                    using (Transaction tr = db.TransactionManager.StartTransaction())
                    { var br = (BlockReference)tr.GetObject(id, OpenMode.ForWrite); RailFactory.SetWidth(tr, br, ws[k]); tr.Commit(); }
                }

            // 2) 레일 변형(kind5): 아치 보유 4차선(14) / 보타이 3차선(0) / 2차선(30)
            int[] vis = { 14, 0, 30 };
            for (int j = 0; j < vis.Length; j++)
                for (int k = 0; k < ws.Length; k++)
                {
                    var v = Rail34Manifest.Variants[vis[j]];
                    ObjectId id;
                    using (Transaction tr = db.TransactionManager.StartTransaction())
                    { id = RailFactory.CreateRail(db, tr, new Point3d(k * 6000.0, (j + 2) * 70000.0, 0), Rail34Manifest.L0, vis[j], 5, v.Wn, v.Lanes); tr.Commit(); }
                    using (Transaction tr = db.TransactionManager.StartTransaction())
                    { var br = (BlockReference)tr.GetObject(id, OpenMode.ForWrite); RailFactory.SetWidth(tr, br, ws[k]); tr.Commit(); }
                }
            doc.Editor.WriteMessage("\nRAILTESTW: 파츠 2종 + 변형 3종 × 폭 7종 생성 완료.");
        }
    }
}
