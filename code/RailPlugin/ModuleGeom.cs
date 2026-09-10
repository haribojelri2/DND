using System;
using System.Collections.Generic;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace RailPlugin
{
    // 기본 모듈 (「기본 모듈 정의.pptx」) — 파라미터로 형상을 계산해 그리는 표준 분기 8종 + 특수 분기 7종. kind=7.
    //
    //  파라미터
    //    R : 호 반지름 (두 직선에 접하는 원의 반지름)
    //    L : 직선(접속 스텁) 길이 — 호 접점 바깥으로 뻗는 직선
    //    W : 레일 간격(아치 계열) / 가로 이동량(S·N·BY PASS 계열)
    //    A : S자 중간 직선과 세로 선 사이의 각도(°) — N·BY PASS·S 계열만 사용
    //
    //  좌표계: 본선은 +Y(위) 방향, 삽입점(0,0) = 좌측 아래 기준점. 좌/우(LEFT/RIGHT)는 +Y 로 진행할 때의 방향.
    //
    //  ★검산: R=450·A=45°·W=900 이면 대각 길이 900, 세로 점유 1272.8 → 스텁 L=198.6 에서
    //    레일조각 1670 = 표준 부품 BRANCH N / BY PASS 의 도면 기입 치수와 정확히 일치한다.
    public static class ModuleGeom
    {
        const double D2R = Math.PI / 180.0;
        const double EPS = 1e-6;

        public sealed class Def
        {
            public string Name;        // 식별자(영문, 명령·XData 용)
            public string Label;       // 큰 버튼 표시(줄바꿈 포함)
            public string Short;       // 작은 버튼 표시(한 줄)
            public bool Std;           // true=표준 분기, false=특수 분기
            public bool UsesW, UsesA;  // 사용하는 파라미터
            public Def(string name, string label, string shortLabel, bool std, bool usesW, bool usesA)
            { Name = name; Label = label; Short = shortLabel; Std = std; UsesW = usesW; UsesA = usesA; }
        }

        // 리본/명령 목록 순서 = 정의 슬라이드 순서
        public static readonly Def[] Defs =
        {
            // ── 표준 분기 8종 (R, L) ──
            new Def("CURVE LEFT",     "CURVE\nLEFT",     "CURVE L",   true,  false, false),
            new Def("CURVE RIGHT",    "CURVE\nRIGHT",    "CURVE R",   true,  false, false),
            new Def("BRANCH LEFT",    "BRANCH\nLEFT",    "BRANCH L",  true,  false, false),
            new Def("BRANCH RIGHT",   "BRANCH\nRIGHT",   "BRANCH R",  true,  false, false),
            new Def("U",              "U",               "U",         true,  true,  false),
            new Def("DOUBLE BRANCH",  "DOUBLE\nBRANCH",  "DOUBLE BR", true,  true,  false),
            new Def("U BRANCH LEFT",  "U BRANCH\nLEFT",  "U BR L",    true,  true,  false),
            new Def("U BRANCH RIGHT", "U BRANCH\nRIGHT", "U BR R",    true,  true,  false),
            // ── 특수 분기 7종 (R, L, W, A) ──
            new Def("N LEFT",         "N\nLEFT",         "N L",       false, true,  true),
            new Def("N RIGHT",        "N\nRIGHT",        "N R",       false, true,  true),
            new Def("BY PASS LEFT",   "BY PASS\nLEFT",   "BYPASS L",  false, true,  true),
            new Def("BY PASS RIGHT",  "BY PASS\nRIGHT",  "BYPASS R",  false, true,  true),
            new Def("S LEFT",         "S\nLEFT",         "S L",       false, true,  true),
            new Def("S RIGHT",        "S\nRIGHT",        "S R",       false, true,  true),
            new Def("Y",              "Y",               "Y",         false, false, false),
        };

        public static int IndexOf(string name)
        {
            for (int i = 0; i < Defs.Length; i++)
                if (string.Equals(Defs[i].Name, name, StringComparison.OrdinalIgnoreCase)) return i;
            return -1;
        }

        // ── 파라미터 기본값 (리본 입력 상자의 초기값) ────────────────────────
        public const double DEF_R = 450.0;    // 표준 호 반지름
        public const double DEF_L = 1000.0;   // 접속 직선
        public const double DEF_W = 900.0;    // 표준 레일 간격 (= 2R → U 는 반원)
        public const double DEF_A = 45.0;     // 표준 대각 각도

        // ── 파라미터 보정 (물리적으로 불가능한 값 방어) ──────────────────────
        //  아치 계열: W ≥ 2R (호 두 개가 맞닿는 것이 최소)
        //  S 계열   : 0 < A < 90, W ≥ 2R(1−cosA) (대각 길이 d ≥ 0)
        public static void Clamp(int idx, ref double r, ref double l, ref double w, ref double a)
        {
            if (r < 1.0) r = 1.0;
            if (l < 0.0) l = 0.0;
            var def = Defs[idx];
            if (def.UsesA)
            {
                if (a < 1.0) a = 1.0;
                if (a > 89.0) a = 89.0;
                double wmin = 2.0 * r * (1.0 - Math.Cos(a * D2R));
                if (w < wmin) w = wmin;
            }
            else if (def.UsesW)
            {
                if (w < 2.0 * r) w = 2.0 * r;
            }
        }

        // 모듈 전체 높이(세로 점유) — 그립·검증용
        public static double Height(int idx, double r, double l, double w, double a)
        {
            Clamp(idx, ref r, ref l, ref w, ref a);
            var def = Defs[idx];
            if (def.UsesA) return 2.0 * l + CrossRise(r, w, a);
            switch (def.Name)
            {
                case "CURVE LEFT":
                case "CURVE RIGHT":
                case "U":
                case "Y":
                    return l + r + (def.Name == "U" ? 0.0 : l);   // U 는 아치 꼭대기까지
                default:
                    return 2.0 * l + r;
            }
        }

        // S자(대각) 구간의 세로 점유와 대각 직선 길이
        static double CrossRun(double r, double w, double a)   // 대각 직선 길이 d
        {
            double ar = a * D2R;
            return (w - 2.0 * r * (1.0 - Math.Cos(ar))) / Math.Sin(ar);
        }
        static double CrossRise(double r, double w, double a)  // 세로 점유
        {
            double ar = a * D2R;
            return 2.0 * r * Math.Sin(ar) + CrossRun(r, w, a) * Math.Cos(ar);
        }

        // ── 접속구(포트) ─────────────────────────────────────────────────────
        //  모듈의 "열린 끝점" = 다른 모듈과 이어 붙는 자리. 배치할 때 이 점이 기존 끝점에 달라붙는다.
        public static List<Point3d> Ports(int idx, double r, double l, double w, double a)
        {
            const double TOL = 1e-5;
            var ents = Build(idx, r, l, w, a);
            var pts = new List<Point3d>();
            foreach (Entity e in ents)
            {
                var ln = e as Line;
                if (ln != null) { pts.Add(ln.StartPoint); pts.Add(ln.EndPoint); }
                else
                {
                    var ac = e as Arc;
                    if (ac != null) { pts.Add(ac.StartPoint); pts.Add(ac.EndPoint); }
                }
            }
            var ports = new List<Point3d>();
            for (int i = 0; i < pts.Count; i++)
            {
                // ① 다른 끝점과 만나면 내부 접합점
                bool joined = false;
                for (int j = 0; j < pts.Count && !joined; j++)
                    if (j != i && pts[i].DistanceTo(pts[j]) < TOL) joined = true;
                if (joined) continue;
                // ② 다른 선/호의 중간에 닿아 있으면 T 접합점(본선에 붙은 분기 시작점) — 접속구가 아니다
                bool onBody = false;
                foreach (Entity e in ents) if (OnBody(pts[i], e, TOL)) { onBody = true; break; }
                if (onBody) continue;
                // ③ 같은 좌표가 이미 있으면 건너뜀
                bool dup = false;
                foreach (Point3d q in ports) if (q.DistanceTo(pts[i]) < TOL) { dup = true; break; }
                if (!dup) ports.Add(pts[i]);
            }
            foreach (Entity e in ents) e.Dispose();
            return ports;
        }

        // 점이 그 선/호의 "중간"에 놓여 있는가 (끝점은 제외)
        static bool OnBody(Point3d p, Entity e, double tol)
        {
            var ln = e as Line;
            if (ln != null)
            {
                Point3d s = ln.StartPoint, t = ln.EndPoint;
                if (p.DistanceTo(s) < tol || p.DistanceTo(t) < tol) return false;
                Vector3d ab = t - s, ap = p - s;
                double len2 = ab.LengthSqrd;
                if (len2 < 1e-12) return false;
                double u = ap.DotProduct(ab) / len2;
                if (u <= 0.0 || u >= 1.0) return false;
                return (s + ab * u).DistanceTo(p) < tol;
            }
            var ac = e as Arc;
            if (ac != null)
            {
                if (p.DistanceTo(ac.StartPoint) < tol || p.DistanceTo(ac.EndPoint) < tol) return false;
                if (Math.Abs(p.DistanceTo(ac.Center) - ac.Radius) > tol) return false;
                double ang = Math.Atan2(p.Y - ac.Center.Y, p.X - ac.Center.X);
                double sweep = ac.EndAngle - ac.StartAngle;
                while (sweep <= 0) sweep += 2 * Math.PI;
                double d = ang - ac.StartAngle;
                while (d < 0) d += 2 * Math.PI;
                return d > 0 && d < sweep;
            }
            return false;
        }

        // ── 블록 정의 이름 ───────────────────────────────────────────────────
        //  같은 규격이면 같은 이름 → 블록 정의는 규격이 바뀔 때만 새로 생긴다.
        public static string BlockName(int idx, double r, double l, double w, double a)
        {
            Clamp(idx, ref r, ref l, ref w, ref a);
            var def = Defs[idx];
            string s = "RAILMOD_" + def.Name.Replace(' ', '-')
                     + "_R" + Num(r) + "_L" + Num(l);
            if (def.UsesW) s += "_W" + Num(w);
            if (def.UsesA) s += "_A" + Num(a);
            return s;
        }

        static string Num(double v)
            => v.ToString("0.##", System.Globalization.CultureInfo.InvariantCulture).Replace('.', 'p').Replace("-", "m");

        /// <summary>규격에 해당하는 블록 정의를 찾고, 없으면 만든다.</summary>
        public static ObjectId EnsureBlock(Database db, Transaction tr, int idx, double r, double l, double w, double a)
        {
            Clamp(idx, ref r, ref l, ref w, ref a);
            string name = BlockName(idx, r, l, w, a);
            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
            if (bt.Has(name)) return bt[name];
            if (!bt.IsWriteEnabled) bt.UpgradeOpen();
            var btr = new BlockTableRecord { Name = name, Origin = Point3d.Origin };
            ObjectId id = bt.Add(btr);
            tr.AddNewlyCreatedDBObject(btr, true);
            Fill(btr, tr, idx, r, l, w, a);
            return id;
        }

        // ── 엔티티 생성 ──────────────────────────────────────────────────────
        static Line Ln(double x1, double y1, double x2, double y2)
            => new Line(new Point3d(x1, y1, 0), new Point3d(x2, y2, 0));

        static Arc Ar(double cx, double cy, double r, double a0, double a1)
        {
            while (a1 <= a0) a1 += 360.0;
            return new Arc(new Point3d(cx, cy, 0), r, a0 * D2R, a1 * D2R);
        }

        /// <summary>모듈 형상을 만들어 블록 정의에 채운다. count = 모듈 인덱스.</summary>
        public static void Fill(BlockTableRecord btr, Transaction tr, int idx, double r, double l, double w, double a)
        {
            if (idx < 0 || idx >= Defs.Length) return;
            foreach (Entity e in Build(idx, r, l, w, a))
            { btr.AppendEntity(e); tr.AddNewlyCreatedDBObject(e, true); }
        }

        public static List<Entity> Build(int idx, double r, double l, double w, double a)
        {
            Clamp(idx, ref r, ref l, ref w, ref a);
            var e = new List<Entity>();
            switch (Defs[idx].Name)
            {
                // ── 표준 분기 ────────────────────────────────────────────────
                case "CURVE LEFT":                       // 위로 올라가 좌회전(90°)
                    e.Add(Ln(0, 0, 0, l));
                    e.Add(Ar(-r, l, r, 0, 90));
                    e.Add(Ln(-r, l + r, -r - l, l + r));
                    break;

                case "CURVE RIGHT":                      // 위로 올라가 우회전(90°)
                    e.Add(Ln(0, 0, 0, l));
                    e.Add(Ar(r, l, r, 90, 180));
                    e.Add(Ln(r, l + r, r + l, l + r));
                    break;

                case "BRANCH LEFT":                      // 본선 관통 + 좌측 분기
                    e.Add(Ln(0, 0, 0, 2 * l + r));
                    e.Add(Ar(-r, l, r, 0, 90));
                    e.Add(Ln(-r, l + r, -r - l, l + r));
                    break;

                case "BRANCH RIGHT":                     // 본선 관통 + 우측 분기
                    e.Add(Ln(0, 0, 0, 2 * l + r));
                    e.Add(Ar(r, l, r, 90, 180));
                    e.Add(Ln(r, l + r, r + l, l + r));
                    break;

                case "U":                                // 180° 되돌림 (양쪽 다리 아래로)
                    e.Add(Ln(0, 0, 0, l));
                    e.Add(Ln(w, 0, w, l));
                    Arch(e, r, l, w);
                    break;

                case "DOUBLE BRANCH":                    // 두 본선 관통 + 상부 아치
                    e.Add(Ln(0, 0, 0, 2 * l + r));
                    e.Add(Ln(w, 0, w, 2 * l + r));
                    Arch(e, r, l, w);
                    break;

                case "U BRANCH LEFT":                    // 본선=우측 관통, 좌측으로 U 분기
                    e.Add(Ln(w, 0, w, 2 * l + r));
                    e.Add(Ln(0, 0, 0, l));
                    Arch(e, r, l, w);
                    break;

                case "U BRANCH RIGHT":                   // 본선=좌측 관통, 우측으로 U 분기
                    e.Add(Ln(0, 0, 0, 2 * l + r));
                    e.Add(Ln(w, 0, w, l));
                    Arch(e, r, l, w);
                    break;

                // ── 특수 분기 ────────────────────────────────────────────────
                case "N LEFT":                           // 크로스오버(두 레일 관통), 우→좌
                    {
                        double h = CrossRise(r, w, a);
                        e.Add(Ln(0, 0, 0, 2 * l + h));
                        e.Add(Ln(w, 0, w, 2 * l + h));
                        CrossLeft(e, r, l, w, a);
                        break;
                    }

                case "N RIGHT":                          // 크로스오버, 좌→우
                    {
                        double h = CrossRise(r, w, a);
                        e.Add(Ln(0, 0, 0, 2 * l + h));
                        e.Add(Ln(w, 0, w, 2 * l + h));
                        CrossRight(e, r, l, w, a);
                        break;
                    }

                case "BY PASS LEFT":                     // 합류(우측 레일이 접합부에서 끝남), 우→좌
                    {
                        double h = CrossRise(r, w, a);
                        e.Add(Ln(0, 0, 0, 2 * l + h));
                        e.Add(Ln(w, 0, w, l));
                        CrossLeft(e, r, l, w, a);
                        break;
                    }

                case "BY PASS RIGHT":                    // 합류(좌측 레일이 접합부에서 끝남), 좌→우
                    {
                        double h = CrossRise(r, w, a);
                        e.Add(Ln(w, 0, w, 2 * l + h));
                        e.Add(Ln(0, 0, 0, l));
                        CrossRight(e, r, l, w, a);
                        break;
                    }

                case "S LEFT":                           // 레일 한 줄이 위로 가며 좌측으로 W 이동
                    {
                        double h = CrossRise(r, w, a);
                        e.Add(Ln(w, 0, w, l));
                        CrossLeft(e, r, l, w, a);
                        e.Add(Ln(0, l + h, 0, 2 * l + h));
                        break;
                    }

                case "S RIGHT":                          // 우측으로 W 이동
                    {
                        double h = CrossRise(r, w, a);
                        e.Add(Ln(0, 0, 0, l));
                        CrossRight(e, r, l, w, a);
                        e.Add(Ln(w, l + h, w, 2 * l + h));
                        break;
                    }

                case "Y":                                // 한 줄이 좌·우 두 갈래로 갈라짐
                    e.Add(Ln(0, 0, 0, l));
                    e.Add(Ar(-r, l, r, 0, 90));
                    e.Add(Ln(-r, l + r, -r - l, l + r));
                    e.Add(Ar(r, l, r, 90, 180));
                    e.Add(Ln(r, l + r, r + l, l + r));
                    break;
            }
            return e;
        }

        // 상부 아치: (0,l) ↔ (w,l) 를 호(r)-직선-호(r) 로 잇는다. w = 2r 이면 직선 0 = 반원.
        static void Arch(List<Entity> e, double r, double l, double w)
        {
            e.Add(Ar(r, l, r, 90, 180));            // 좌: (0,l) → (r, l+r)
            if (w - 2.0 * r > EPS)
                e.Add(Ln(r, l + r, w - r, l + r));  // 상부 직선
            e.Add(Ar(w - r, l, r, 0, 90));          // 우: (w,l) → (w−r, l+r)
        }

        // 크로스 커브 (우측 레일 → 좌측 레일): (w, l) → (0, l+rise). 호(r) + 대각(A) + 호(r), 접선 연속.
        static void CrossLeft(List<Entity> e, double r, double l, double w, double a)
        {
            double ar = a * D2R, ca = Math.Cos(ar), sa = Math.Sin(ar);
            double d = CrossRun(r, w, a);
            e.Add(Ar(w - r, l, r, 0, a));                       // (w,l) → P1
            double p1x = w - r + r * ca, p1y = l + r * sa;
            double p2x = p1x - d * sa, p2y = p1y + d * ca;
            if (d > EPS) e.Add(Ln(p1x, p1y, p2x, p2y));         // 대각 직선
            double c2x = p2x + r * ca, c2y = p2y + r * sa;
            e.Add(Ar(c2x, c2y, r, 180, 180 + a));               // P2 → (0, l+rise)
        }

        // 크로스 커브 (좌측 레일 → 우측 레일): (0, l) → (w, l+rise)
        static void CrossRight(List<Entity> e, double r, double l, double w, double a)
        {
            double ar = a * D2R, ca = Math.Cos(ar), sa = Math.Sin(ar);
            double d = CrossRun(r, w, a);
            e.Add(Ar(r, l, r, 180 - a, 180));                   // (0,l) → P1
            double p1x = r - r * ca, p1y = l + r * sa;
            double p2x = p1x + d * sa, p2y = p1y + d * ca;
            if (d > EPS) e.Add(Ln(p1x, p1y, p2x, p2y));         // 대각 직선
            double c2x = p2x - r * ca, c2y = p2y + r * sa;
            e.Add(Ar(c2x, c2y, r, 360 - a, 360));               // P2 → (w, l+rise)
        }
    }
}
