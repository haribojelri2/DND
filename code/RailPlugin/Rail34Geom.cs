using System;
using System.Collections.Generic;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace RailPlugin
{
    // 0716 매니페스트 기반 3/4차선 조립 (kind=5).
    //  네이티브(L=59100, W=Wn)에서 원본 도면과 동일(파츠 오버행 제외). 부품=I타깃 앵커(강체) 배치.
    //  세로(L): 타깃만 비율/고정 이동, 파츠는 강체 — 레일은 전장에서 부품 점유(PartRails)를 현재 치수로 빼고 분할.
    //  가로(W): 우측/가운데 레일존 이동, 캡/보타이 바만 신축. ★U분기 직선만 신축 규칙★
    public static class Rail34Geom
    {
        public const double MINLEN = 15000.0;

        // ── 조립체 태그 (수량 집계용) ──────────────────────────────────────
        //  표준 폭(900·1350)은 파츠 블록 그대로라 블록명으로 세면 되지만,
        //  그 외 폭은 호-직-호나 BRANCH 3피스로 "조립"되므로 블록명으로는 셀 수 없다.
        //  → 조립 결과에 논리 부품명을 XData 로 새겨 변환기가 1개로 집계하게 한다.
        //    role 0 = 대표(이것만 셈) / role 1 = 종속(집계에서 제외 — 이중 계산 방지)
        //  [사용자 규칙: 고정폭 집합을 DOUBLE BRANCH 4CH 하나의 단위로 인식]
        public const string PARTAPP = "RAILPART";

        public static void Tag(Entity e, Transaction tr, string logicalName, double width, int role)
        {
            try
            {
                RailFactory.EnsureRegApp(e.Database, tr, PARTAPP);
                e.XData = new ResultBuffer(
                    new TypedValue((int)DxfCode.ExtendedDataRegAppName, PARTAPP),
                    new TypedValue((int)DxfCode.ExtendedDataAsciiString, logicalName),
                    new TypedValue((int)DxfCode.ExtendedDataReal, width),
                    new TypedValue((int)DxfCode.ExtendedDataInteger16, (short)role));
            }
            catch { /* 태그 실패는 형상에 영향 없음 */ }
        }

        // 조립체의 논리 부품명 (2CH / 4CH)
        public static string LogicalName(bool four) =>
            four ? "DOUBLE BRANCH 4CH" : "DOUBLE BRANCH 2CH";

        // ── 고정폭 규격 표시 ────────────────────────────────────────────────
        //  [사용자/상무 규격] DOUBLE BRANCH 4CH 는 900·1020·1270·1350 에만 적용.
        //  고정폭으로 조립된 것만 부품 표준색(초록)을 입혀 파츠 원형과 색이 맞게 한다.
        //  ※ 부품 블록 내부는 색 3 고정 → 900·1350(파츠 원형)은 원래 초록이므로
        //    1020·1270(조립)에도 같은 초록을 주면 고정폭끼리 색이 통일된다.
        //    규격 외 폭은 색을 건드리지 않는다(경고 표시 없음 — 사용자 지시).
        public static readonly double[] FixedWidths = { 900.0, 1020.0, 1270.0, 1350.0 };
        public const short COLOR_FIXED = 3;      // 초록 = 규격 폭 (부품 표준색)
        public const short COLOR_FREE = 0;       // 0 = 색 지정 안 함(기존 그대로)

        public static bool IsFixedWidth(double w)
        {
            foreach (double f in FixedWidths) if (Math.Abs(w - f) < 0.5) return true;
            return false;
        }

        public static short WidthColor(double w) => IsFixedWidth(w) ? COLOR_FIXED : COLOR_FREE;

        // 단위 직선 파츠: RP_RAIL_V=(0,0)-(0,1), RP_BAR_H=(0,0)-(1,0). 스케일=길이.
        public static ObjectId EnsureUnitLine(Database db, Transaction tr, bool vertical)
        {
            string name = vertical ? "RP_RAIL_V" : "RP_BAR_H";
            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
            if (bt.Has(name)) return bt[name];
            if (!bt.IsWriteEnabled) bt.UpgradeOpen();
            var btr = new BlockTableRecord { Name = name, Origin = Point3d.Origin };
            ObjectId id = bt.Add(btr); tr.AddNewlyCreatedDBObject(btr, true);
            var e = new Line(Point3d.Origin, vertical ? new Point3d(0, 1, 0) : new Point3d(1, 0, 0));
            btr.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true);
            return id;
        }

        // 직선 → 단위 파츠 스케일 삽입 (세로/가로만; 길이=스케일)
        //  color: 0이면 색 지정 안 함(기존 동작)
        public static void AddLinePart(BlockTableRecord host, Transaction tr, Point3d p1, Point3d p2, short color)
        {
            Entity e = AddLinePartEnt(host, tr, p1, p2);
            if (e != null && color != 0) e.ColorIndex = color;
        }

        public static void AddLinePart(BlockTableRecord host, Transaction tr, Point3d p1, Point3d p2)
        {
            AddLinePartEnt(host, tr, p1, p2);
        }

        // 실제 생성 — 만든 엔티티를 돌려준다(색·태그 지정용)
        public static Entity AddLinePartEnt(BlockTableRecord host, Transaction tr, Point3d p1, Point3d p2)
        {
            Database db = host.Database;
            double dx = p2.X - p1.X, dy = p2.Y - p1.Y;
            if (Math.Abs(dx) < 0.001 && Math.Abs(dy) < 0.001) return null;
            BlockReference br;
            if (Math.Abs(dx) < 0.001)
            {
                double lo = Math.Min(p1.Y, p2.Y), len = Math.Abs(dy);
                br = new BlockReference(new Point3d(p1.X, lo, 0), EnsureUnitLine(db, tr, true))
                { ScaleFactors = new Scale3d(1, len, 1) };
            }
            else if (Math.Abs(dy) < 0.001)
            {
                double lo = Math.Min(p1.X, p2.X), len = Math.Abs(dx);
                br = new BlockReference(new Point3d(lo, p1.Y, 0), EnsureUnitLine(db, tr, false))
                { ScaleFactors = new Scale3d(len, 1, 1) };
            }
            else
            {
                var e = new Line(p1, p2);   // 대각선은 파츠(RP_X 계열)에서만 나옴 — 여기 올 일 없음
                host.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true); return e;
            }
            host.AppendEntity(br); tr.AddNewlyCreatedDBObject(br, true);
            return br;
        }

        static ObjectId EnsurePart(Database db, Transaction tr, int idx)
        {
            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
            string name = Rail34Manifest.PartNames[idx];
            if (bt.Has(name)) return bt[name];
            if (!name.StartsWith("RP_"))
                return BlockImport.Ensure(db, tr, name)[name];   // 카탈로그 부품(부품 세트 DXF에서 임포트)
            if (!bt.IsWriteEnabled) bt.UpgradeOpen();
            var btr = new BlockTableRecord { Name = name, Origin = Point3d.Origin };
            ObjectId id = bt.Add(btr); tr.AddNewlyCreatedDBObject(btr, true);
            foreach (var l in Rail34Manifest.PartLines[idx])
            { var e = new Line(new Point3d(l[0], l[1], 0), new Point3d(l[2], l[3], 0)); btr.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true); }
            foreach (var a in Rail34Manifest.PartArcs[idx])
            { var e = new Arc(new Point3d(a[0], a[1], 0), a[2], a[3] * Math.PI / 180.0, a[4] * Math.PI / 180.0); btr.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true); }
            return id;
        }

        public static void Fill(BlockTableRecord host, Transaction tr, int variantIdx, double L, double W)
        {
            var v = Rail34Manifest.Variants[variantIdx];
            if (L < MINLEN) L = MINLEN;
            if (W <= 0 || v.Wn <= 0) W = v.Wn;      // 4차선(Wn=0)은 폭 고정
            Database db = host.Database;
            double s = L / Rail34Manifest.L0;
            double dW = (v.Wn > 0) ? (W - v.Wn) : 0.0;
            // ya=2(중간): 그룹(G)은 강체, 그룹 사이 "빈 레일 구간"들이 전부 같은 비율 K로 신축.
            //  끝 고정존(F0/F1)은 불변(끝여백 1800 유지). G 없으면 전체 비율 y·L/L0 (2차선 등).
            int nG = v.G.Length;
            double[] gdy = new double[nG];
            if (nG > 0)
            {
                double sumH = 0;
                foreach (var g in v.G) sumH += g[1] - g[0];
                double freeN = (Rail34Manifest.L0 - v.F0 - v.F1) - sumH;
                double K = freeN > 1 ? ((L - v.F0 - v.F1) - sumH) / freeN : 1.0;
                double cur = v.F0, prevTop = v.F0;
                for (int j = 0; j < nG; j++)
                {
                    cur += (v.G[j][0] - prevTop) * K;
                    gdy[j] = cur - v.G[j][0];
                    cur += v.G[j][1] - v.G[j][0];
                    prevTop = v.G[j][1];
                }
            }
            double iden = Rail34Manifest.L0 - v.F0 - v.F1;
            double Ymid(double y)
            {
                for (int j = 0; j < nG; j++)
                    if (y >= v.G[j][0] - 600.0 && y <= v.G[j][1] + 600.0) return y + gdy[j];
                return iden > 1 ? v.F0 + (y - v.F0) * (L - v.F0 - v.F1) / iden : y * s;
            }
            double Y(double y, int ya) => ya == 0 ? y : (ya == 1 ? L - (Rail34Manifest.L0 - y) : Ymid(y));
            double X(double x, int xa) => xa == 1 ? x + dW : x;
            void Add(Entity e) { host.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true); }

            // 부품 레일조각 점유(월드) — 2)에서 레일 분할에 사용
            var spans = new List<double[]>();
            void Occupy(int pi, double ix, double iy, double psx, double psy)
            {
                if (pi < 0) return;
                foreach (var pr in Rail34Manifest.PartRails[pi])
                {
                    double a = iy + psy * pr[1], b = iy + psy * pr[2];
                    spans.Add(new[] { ix + psx * pr[0], Math.Min(a, b), Math.Max(a, b) });
                }
            }
            int PIdx(string nm) => Array.IndexOf(Rail34Manifest.PartNames, nm);

            // 1) 부품: 타깃 앵커(대각중심/호중심/바레벨)만 이동, 파츠는 강체.
            //    U턴 브릿지(2CH/4CH): 네이티브=파츠 원형, 900/1350 스냅=파츠 교체, 그 외(W2≥1300)=3피스.
            foreach (var i in v.I)
            {
                string pn = Rail34Manifest.PartNames[(int)i[0]];
                if (pn.StartsWith("DOUBLE BRANCH 2CH") || pn.StartsWith("DOUBLE BRANCH 4CH") || pn == "#BOWTIE")
                { Arch(host, tr, pn, i, dW); continue; }
                double sx = i.Length > 5 ? i[5] : 1.0, sy = i.Length > 6 ? i[6] : 1.0;
                var rf = Rail34Manifest.PartRef[(int)i[0]];
                double ix = X(i[1], (int)i[3]) - sx * rf[0];
                double iy = Y(i[2], (int)i[4]) - sy * rf[1];
                ObjectId pid = EnsurePart(db, tr, (int)i[0]);
                var br = new BlockReference(new Point3d(ix, iy, 0), pid);
                if (sx < 0 || sy < 0) br.ScaleFactors = new Scale3d(sx, sy, 1.0);
                Add(br);
                Occupy((int)i[0], ix, iy, sx, sy);
            }

            // 2) 직선: 수직(레일)은 부품 점유 구간을 현재 치수에서 빼고 분할, 그 외 그대로
            foreach (var l in v.L)
            {
                var p1 = new Point3d(X(l[0], (int)l[4]), Y(l[1], (int)l[6]), 0);
                var p2 = new Point3d(X(l[2], (int)l[5]), Y(l[3], (int)l[7]), 0);
                if (Math.Abs(p1.X - p2.X) < 0.6 && Math.Abs(p1.Y - p2.Y) > 0.6)
                {
                    double lo = Math.Min(p1.Y, p2.Y), hi = Math.Max(p1.Y, p2.Y);
                    var cut = new List<double[]>();
                    foreach (var sp in spans)
                        if (Math.Abs(sp[0] - p1.X) < 0.6) cut.Add(sp);
                    cut.Sort((a, b) => a[1].CompareTo(b[1]));
                    double cur = lo;
                    foreach (var sp in cut)
                    {
                        double a = Math.Max(sp[1], lo), b = Math.Min(sp[2], hi);
                        if (a - cur > 0.5) AddLinePart(host, tr, new Point3d(p1.X, cur, 0), new Point3d(p1.X, a, 0));
                        if (b > cur) cur = b;
                    }
                    if (hi - cur > 0.5) AddLinePart(host, tr, new Point3d(p1.X, cur, 0), new Point3d(p1.X, hi, 0));
                }
                else AddLinePart(host, tr, p1, p2);
            }

            // 3) 호 (원형 캡/보타이/플레어 포함)
            foreach (var a in v.A)
                Add(new Arc(new Point3d(X(a[0], (int)a[5]), Y(a[1], (int)a[6]), 0),
                            a[2], a[3] * Math.PI / 180.0, a[4] * Math.PI / 180.0));

            // 아치(U턴 브릿지·보타이) — I타깃 = (갭 좌레일 x, 하단 바레벨 y)
            //  #BOWTIE = W갭 원형 보타이(∩∪ 700): 네이티브=호-직-호 원형, 스냅=4CH 파츠, 그 외=DB_700 세로 조립
            void Arch(BlockTableRecord h2, Transaction t2, string pn, double[] i, double dw)
            {
                bool bow = pn == "#BOWTIE";
                bool four = bow || pn.Contains("4CH");
                double g0 = bow ? v.Wn : (pn.EndsWith("_900") ? 900.0 : 1350.0);   // 네이티브 갭
                double sy = four ? 1.0 : i[6];                       // 4CH는 ∩하단+∪상단 일체(정방향)
                double colx = X(i[1], (int)i[3]);                    // 타깃: 갭 좌레일 x (월드)
                double barY = Y(i[2], (int)i[4]);                    // 타깃: 하단 바레벨 (월드)
                double W2 = g0 + dw;                                 // 현재 갭
                if (bow && Math.Abs(dw) < 0.5)
                {
                    // 네이티브 = 호-직-호 원형 (레일 무분할)
                    ArcBridgeAt(h2, t2, colx, barY, W2, true, true, false);
                    return;
                }
                string pick = null;
                if (!bow && Math.Abs(dw) < 0.5) pick = pn;
                else if (Math.Abs(W2 - 1350.0) < 0.5) pick = four ? "DOUBLE BRANCH 4CH" : "DOUBLE BRANCH 2CH";
                else if (Math.Abs(W2 - 900.0) < 0.5) pick = four ? "DOUBLE BRANCH 4CH_900" : "DOUBLE BRANCH 2CH_900";
                if (pick != null)
                {
                    int pi = PIdx(pick);
                    var rf = pi >= 0 ? Rail34Manifest.PartRef[pi] : new[] { 0.0, 650.0 };
                    var defs = BlockImport.Ensure(h2.Database, t2, pick);
                    double ix = colx - rf[0], iy = barY - sy * rf[1];
                    var br = new BlockReference(new Point3d(ix, iy, 0), defs[pick]);
                    if (sy < 0) br.ScaleFactors = new Scale3d(1, -1, 1);
                    Add(br);
                    if (pi >= 0) Occupy(pi, ix, iy, 1, sy);
                    else spans.Add(new[] { colx, iy, iy + (pick.Contains("4CH") ? 2000.0 : 1035.0) });
                    return;
                }
                if (four)
                {
                    // 폭 1300 미만은 _700 파츠(스텁 650)가 안 들어감 → 호-직-호 (레일 무분할)
                    if (W2 < 1300.0) { ArcBridgeAt(h2, t2, colx, barY, W2, true, true, false); return; }
                    // 4CH/보타이 스트레치 = DOUBLE BRANCH_700(90°) - 직 - DOUBLE BRANCH_700(-90°) [사용자 규칙]
                    Funnel4At(h2, t2, colx, barY, W2);
                    spans.Add(new[] { colx, barY - 650.0, barY + 1350.0 });        // 세워진 파츠 레일(2000) 점유
                    spans.Add(new[] { colx + W2, barY - 650.0, barY + 1350.0 });
                    return;
                }
                Arch3(h2, t2, colx, barY, sy > 0, W2);
            }

            // 아치 3피스 = BRANCH RIGHT(좌 코너) + RP_BAR_H(가변 바) + BRANCH LEFT(우 코너). ∪=180° 회전.
            //  스텁 끝(바 접점) 블록 내 좌표: rot0 P=바끝−스텁 / rot180 P=바끝+스텁 (BlockRailGeom과 동일 문법)
            void Arch3(BlockTableRecord h2, Transaction t2, double colx, double barY, bool up, double W2)
            {
                // 폭 1300 미만 = BRANCH 코너(650×2)가 안 들어감 → 호-직-호 (레일조각 없으니 무분할)
                if (W2 < 1300.0) { ArcBridgeAt(h2, t2, colx, barY, W2, false, up, false); return; }
                var defs = BlockImport.Ensure(h2.Database, t2, "BRANCH LEFT", "BRANCH RIGHT");
                int piL = PIdx("BRANCH LEFT"), piR = PIdx("BRANCH RIGHT");
                double xL = colx + 650.0, xR = colx + W2 - 650.0;                 // 스텁 끝(바 양끝)
                const double SLX = 51330.7, SLY = 36027.1;                        // BRANCH LEFT 스텁 끝
                const double SRX = 52630.7, SRY = 33905.2;                        // BRANCH RIGHT 스텁 끝
                BlockReference c1, c2;
                if (up)
                {
                    c1 = new BlockReference(new Point3d(xL - SRX, barY - SRY, 0), defs["BRANCH RIGHT"]);
                    Add(c1); Occupy(piR, xL - SRX, barY - SRY, 1, 1);
                    c2 = new BlockReference(new Point3d(xR - SLX, barY - SLY, 0), defs["BRANCH LEFT"]);
                    Add(c2); Occupy(piL, xR - SLX, barY - SLY, 1, 1);
                }
                else
                {
                    c1 = new BlockReference(new Point3d(xL + SLX, barY + SLY, 0), defs["BRANCH LEFT"]) { Rotation = Math.PI };
                    Add(c1); Occupy(piL, xL + SLX, barY + SLY, -1, -1);
                    c2 = new BlockReference(new Point3d(xR + SRX, barY + SRY, 0), defs["BRANCH RIGHT"]) { Rotation = Math.PI };
                    Add(c2); Occupy(piR, xR + SRX, barY + SRY, -1, -1);
                }
                // 두 코너 = 논리 부품 1개(2CH)
                Tag(c1, t2, LogicalName(false), W2, 0);
                Tag(c2, t2, LogicalName(false), W2, 1);
                Entity bar2 = AddLinePartEnt(h2, t2, new Point3d(xL, barY, 0), new Point3d(xR, barY, 0));
                if (bar2 != null)
                {
                    short c2c = WidthColor(W2);
                    if (c2c != 0) bar2.ColorIndex = c2c;
                    Tag(bar2, t2, LogicalName(false), W2, 1);
                }
            }
        }

        // ── 신축 파츠 (kind=6): U분기형 파츠 단독 삽입 — 가로 직선(바)만 신축 ──
        //  원점 = 좌레일(스텁) 하단 기준 포트. count=패밀리 인덱스, width=현재 갭.
        public static readonly string[] PartFam = {
            "DOUBLE BRANCH 2CH", "DOUBLE BRANCH 4CH", "DOUBLE BRANCH 2CH_900", "DOUBLE BRANCH 4CH_900",
            "DOUBLE BRANCH", "DOUBLE BRANCH_700", "DOUBLE BRANCH_1000" };
        public static readonly double[] PartFamG = { 1350, 1350, 900, 900, 650, 700, 1000 };

        // 4CH 스트레치 = [DOUBLE BRANCH_700 90°(좌)] - 가로 바 2개 - [DOUBLE BRANCH_700 -90°(우)]
        //  (사용자 규칙: "Double branch-직-Double branch = 4CH". _700 바(2000)가 세워져 레일 2000이 됨)
        //  _700 내부(카탈로그): 바 y=31998.3, 좌스텁 x=50157.1(간격 700). colx=갭 좌레일, barY=하단 바레벨.
        public static void Funnel4At(BlockTableRecord host, Transaction tr, double colx, double barY, double W2)
        {
            var defs = BlockImport.Ensure(host.Database, tr, "DOUBLE BRANCH_700");
            const double FBY = 31998.3, FSX = 50157.1;
            void Add(Entity e) { host.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true); }
            var f1 = new BlockReference(new Point3d(colx + FBY, barY - FSX, 0), defs["DOUBLE BRANCH_700"]) { Rotation = Math.PI / 2 };
            var f2 = new BlockReference(new Point3d(colx + W2 - FBY, barY + FSX + 700.0, 0), defs["DOUBLE BRANCH_700"]) { Rotation = -Math.PI / 2 };
            Add(f1); Add(f2);
            // 세워진 _700 두 짝 = 논리적으로 4CH 1개
            Tag(f1, tr, LogicalName(true), W2, 0);
            Tag(f2, tr, LogicalName(true), W2, 1);
            short fc = WidthColor(W2);
            foreach (double by in new[] { barY, barY + 700.0 })
            {
                Entity bar4 = AddLinePartEnt(host, tr, new Point3d(colx + 650.0, by, 0), new Point3d(colx + W2 - 650.0, by, 0));
                if (bar4 == null) continue;
                if (fc != 0) bar4.ColorIndex = fc;
                Tag(bar4, tr, LogicalName(true), W2, 1);    // 바도 조립체 일부
            }
        }

        // ── 호-직-호 U턴 브릿지 (스텁 없는 원형 구성) — 폭 900 이상 임의 폭 ──
        //  BRANCH 코너는 호450+스텁200=650 을 먹어 두 개 마주 놓으면 최소 폭 1300 → 그 미만은 조립 불가.
        //  스텁을 빼고 호(450)+직선(W−900)+호(450) 로 그리면 수평 총합은 3피스와 동일(W)하면서 900까지 내려간다.
        //  W=900 이면 직선 0 = 반원(_900 파츠와 같은 형상).
        //  colx=좌레일 x, barY=(4CH는 하단)바 레벨, four=4CH(∩∪ 2벌·간격 700), up=∩(바가 호 위)
        //  withRails: 레일조각도 그림(kind6 단독 파츠용). 변형 조립은 레일 직선이 지나가므로 false.
        public static void ArcBridgeAt(BlockTableRecord host, Transaction tr,
                                       double colx, double barY, double W2, bool four, bool up, bool withRails)
        {
            const double R = 450.0, D = Math.PI / 180.0;
            double bx0 = colx + R, bx1 = colx + W2 - R;
            bool tagged = false;
            short col = WidthColor(W2);          // 고정폭이면 부품 표준색으로 통일
            // 조립체 구성 요소는 전부 태그한다 — 첫 것만 대표(0), 나머지는 종속(1).
            //  수량은 대표 1개로 세고, 직선/호 통계에서는 구성 요소 전부를 부품으로 보고 제외한다.
            void Add(Entity e)
            {
                if (col != 0) e.ColorIndex = col;
                host.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true);
                Tag(e, tr, LogicalName(four), W2, tagged ? 1 : 0);
                tagged = true;
            }
            // 한 벌(바 + 호 2개). cap=true 면 ∩(호가 바 아래), false 면 ∪(호가 바 위)
            void Unit(double by, bool cap)
            {
                double cy = cap ? by - R : by + R;
                Add(new Arc(new Point3d(bx0, cy, 0), R, (cap ? 90 : 180) * D, (cap ? 180 : 270) * D));
                Add(new Arc(new Point3d(bx1, cy, 0), R, (cap ? 0 : 270) * D, (cap ? 90 : 360) * D));
                if (W2 > 900.0 + 0.5)
                {
                    Entity bar = AddLinePartEnt(host, tr, new Point3d(bx0, by, 0), new Point3d(bx1, by, 0));
                    if (bar != null)
                    {
                        if (col != 0) bar.ColorIndex = col;
                        Tag(bar, tr, LogicalName(four), W2, 1);
                    }
                }
            }
            double s = up ? 1.0 : -1.0;
            Unit(barY, up);                                   // 첫 벌
            if (four) Unit(barY + s * 700.0, !up);            // 4CH: 반대 방향 한 벌 더 (간격 700)
            if (withRails)
            {
                double lo = barY - s * 650.0;                 // 레일 하단(호 접점에서 스텁 200 아래)
                double hi = barY + s * (four ? 1350.0 : 385.0);
                AddLinePart(host, tr, new Point3d(colx, lo, 0), new Point3d(colx, hi, 0));
                AddLinePart(host, tr, new Point3d(colx + W2, lo, 0), new Point3d(colx + W2, hi, 0));
            }
        }

        // 아치 3피스 배치 (공용): BRANCH RIGHT + 가변 바 + BRANCH LEFT. ∪=180°.
        //  폭 1300 미만은 3피스가 성립하지 않으므로 호-직-호로 대체.
        public static void Arch3At(BlockTableRecord host, Transaction tr, double colx, double barY, bool up, double W2)
        {
            if (W2 < 1300.0) { ArcBridgeAt(host, tr, colx, barY, W2, false, up, false); return; }
            var defs = BlockImport.Ensure(host.Database, tr, "BRANCH LEFT", "BRANCH RIGHT");
            double xL = colx + 650.0, xR = colx + W2 - 650.0;
            const double SLX = 51330.7, SLY = 36027.1;
            const double SRX = 52630.7, SRY = 33905.2;
            void Add(Entity e) { host.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true); }
            // 두 코너를 합쳐 논리 부품 1개(2CH)로 집계 — 앞것만 대표(0), 뒤것은 종속(1)
            BlockReference b1, b2;
            if (up)
            {
                b1 = new BlockReference(new Point3d(xL - SRX, barY - SRY, 0), defs["BRANCH RIGHT"]);
                b2 = new BlockReference(new Point3d(xR - SLX, barY - SLY, 0), defs["BRANCH LEFT"]);
            }
            else
            {
                b1 = new BlockReference(new Point3d(xL + SLX, barY + SLY, 0), defs["BRANCH LEFT"]) { Rotation = Math.PI };
                b2 = new BlockReference(new Point3d(xR + SRX, barY + SRY, 0), defs["BRANCH RIGHT"]) { Rotation = Math.PI };
            }
            Add(b1); Add(b2);
            Tag(b1, tr, LogicalName(false), W2, 0);
            Tag(b2, tr, LogicalName(false), W2, 1);
            Entity bar3 = AddLinePartEnt(host, tr, new Point3d(xL, barY, 0), new Point3d(xR, barY, 0));
            if (bar3 != null)
            {
                short c3 = WidthColor(W2);
                if (c3 != 0) bar3.ColorIndex = c3;
                Tag(bar3, tr, LogicalName(false), W2, 1);   // 바도 조립체 일부
            }
        }

        public static void FillPart(BlockTableRecord host, Transaction tr, int f, double W)
        {
            if (f < 0 || f >= PartFam.Length) f = 0;
            string nm = PartFam[f];
            double g0 = PartFamG[f];
            if (W <= 0) W = g0;
            double dw = W - g0;
            Database db = host.Database;
            void Add(Entity e) { host.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true); }
            if (f <= 3)
            {
                // U턴 브릿지: 네이티브/900/1350=파츠 원형, 그 외(W≥1300)=BRANCH 3피스 (바만 신축)
                bool four = nm.Contains("4CH");
                string pick = null;
                if (Math.Abs(dw) < 0.5) pick = nm;
                else if (Math.Abs(W - 1350.0) < 0.5) pick = four ? "DOUBLE BRANCH 4CH" : "DOUBLE BRANCH 2CH";
                else if (Math.Abs(W - 900.0) < 0.5) pick = four ? "DOUBLE BRANCH 4CH_900" : "DOUBLE BRANCH 2CH_900";
                if (pick != null)
                {
                    var defs = BlockImport.Ensure(db, tr, pick);
                    var rp = BlockCatalog.Parts[pick].RefOffset;
                    Add(new BlockReference(new Point3d(-rp.X, -rp.Y, 0), defs[pick]));
                    return;
                }
                // 폭 1300 미만은 3피스/_700 조립 불가 → 호-직-호 (단독 파츠라 레일조각도 직접 그림)
                if (W < 1300.0) ArcBridgeAt(host, tr, 0.0, 650.0, W, four, true, true);
                else if (four) Funnel4At(host, tr, 0.0, 650.0, W);
                else Arch3At(host, tr, 0.0, 650.0, true, W);
                return;
            }
            // 깔때기(DOUBLE BRANCH 650/700/1000): 네이티브=파츠, 신축=중앙 분할 복사 — 바만 신축, 호/스텁 강체
            var d2 = BlockImport.Ensure(db, tr, nm);
            var cat = BlockCatalog.Parts[nm];
            if (Math.Abs(dw) < 0.5)
            { Add(new BlockReference(new Point3d(-cat.RefOffset.X, -cat.RefOffset.Y, 0), d2[nm])); return; }
            var src = (BlockTableRecord)tr.GetObject(d2[nm], OpenMode.ForRead);
            double minx = double.MaxValue, maxx = double.MinValue;
            foreach (ObjectId id in src)
            {
                var en = tr.GetObject(id, OpenMode.ForRead);
                if (en is Line ln) { minx = Math.Min(minx, Math.Min(ln.StartPoint.X, ln.EndPoint.X)); maxx = Math.Max(maxx, Math.Max(ln.StartPoint.X, ln.EndPoint.X)); }
                else if (en is Arc ac) { minx = Math.Min(minx, ac.Center.X - ac.Radius); maxx = Math.Max(maxx, ac.Center.X + ac.Radius); }
            }
            double mid = (minx + maxx) / 2.0, ox = -cat.RefOffset.X, oy = -cat.RefOffset.Y;
            foreach (ObjectId id in src)
            {
                var en = tr.GetObject(id, OpenMode.ForRead);
                if (en is Line ln)
                {
                    double x1 = ln.StartPoint.X > mid ? ln.StartPoint.X + dw : ln.StartPoint.X;
                    double x2 = ln.EndPoint.X > mid ? ln.EndPoint.X + dw : ln.EndPoint.X;
                    var nl = new Line(new Point3d(ox + x1, oy + ln.StartPoint.Y, 0), new Point3d(ox + x2, oy + ln.EndPoint.Y, 0));
                    nl.ColorIndex = ln.ColorIndex;
                    Add(nl);
                }
                else if (en is Arc ac)
                {
                    double cx = ac.Center.X > mid ? ac.Center.X + dw : ac.Center.X;
                    var na = new Arc(new Point3d(ox + cx, oy + ac.Center.Y, 0), ac.Radius, ac.StartAngle, ac.EndAngle);
                    na.ColorIndex = ac.ColorIndex;
                    Add(na);
                }
            }
        }

        // 그립 배치용: 변형의 최우측 레일 x (W 반영)
        public static double RightX(int variantIdx, double W)
        {
            var v = Rail34Manifest.Variants[variantIdx];
            double dW = (v.Wn > 0 && W > 0) ? W - v.Wn : 0.0;
            double mx = 0;
            foreach (var l in v.L)
            {
                mx = Math.Max(mx, l[0] + ((int)l[4] == 1 ? dW : 0));
                mx = Math.Max(mx, l[2] + ((int)l[5] == 1 ? dW : 0));
            }
            return mx;
        }

        // 그립 배치용: 변형의 최좌측 레일 x (고정존)
        public static double LeftX(int variantIdx)
        {
            var v = Rail34Manifest.Variants[variantIdx];
            double mn = double.MaxValue;
            foreach (var l in v.L)
            {
                mn = Math.Min(mn, l[0]);
                mn = Math.Min(mn, l[2]);
            }
            return mn == double.MaxValue ? 0 : mn;
        }
    }
}
