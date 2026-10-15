using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.EditorInput;

[assembly: CommandClass(typeof(RailPlugin.ModuleCommands))]

namespace RailPlugin
{
    // 모듈 파라미터 — 도면(파일)당 1세트. MODULE FORMAT 의 MODULEPARAM(R/L/W1/W2/A/M1/M2) 과 같은 항목.
    //  한 번 정하면 모든 모듈 형상에 맞게 적용된다(R·L 공통, 폭을 쓰는 모듈은 W1 또는 W2, 대각 모듈은 A).
    //  M1·M2 는 형상이 아니라 MAP 이격 마진이다(변환기가 쓴다) — 도면에 함께 저장만 한다.
    //  도면의 Named Objects Dictionary 에 XRecord 로 저장 → 도면을 저장하면 같이 남는다.
    public static class ModuleParams
    {
        public const string KEY = "RAILPLUGIN_MODULEPARAM";

        public sealed class P
        {
            public double R = 450, L = 200, W1 = 600, W2 = 900, A = 45, M1 = 150, M2 = 520;
            public P Clone() => (P)MemberwiseClone();
            public string Digest()
                => $"R{F(R)} L{F(L)} W1 {F(W1)} W2 {F(W2)} A{F(A)} M1 {F(M1)} M2 {F(M2)}";
        }

        public static string F(double v) => v.ToString("0.##", CultureInfo.InvariantCulture);

        public static bool TryParse(string text, out double value)
        {
            text = (text ?? "").Trim();
            return double.TryParse(text, NumberStyles.Float, CultureInfo.CurrentCulture, out value)
                || double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out value);
        }

        /// <summary>도면에 저장된 파라미터. 없으면 기본값(가이드 예시: 450/200/600/900/45/150/520).</summary>
        public static P Get(Database db)
        {
            var p = new P();
            try
            {
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    var nod = (DBDictionary)tr.GetObject(db.NamedObjectsDictionaryId, OpenMode.ForRead);
                    if (nod.Contains(KEY))
                    {
                        var xr = (Xrecord)tr.GetObject(nod.GetAt(KEY), OpenMode.ForRead);
                        var v = new List<double>();
                        if (xr.Data != null) foreach (TypedValue tv in xr.Data)
                            if (tv.TypeCode == (int)DxfCode.Real) v.Add((double)tv.Value);
                        if (v.Count >= 7) { p.R = v[0]; p.L = v[1]; p.W1 = v[2]; p.W2 = v[3]; p.A = v[4]; p.M1 = v[5]; p.M2 = v[6]; }
                    }
                    tr.Commit();
                }
            }
            catch { }
            return p;
        }

        /// <summary>도면에 파라미터가 저장돼 있는지 (없으면 Get 은 기본값을 돌려준다).</summary>
        public static bool Has(Database db)
        {
            try
            {
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    var nod = (DBDictionary)tr.GetObject(db.NamedObjectsDictionaryId, OpenMode.ForRead);
                    bool ok = false;
                    if (nod.Contains(KEY))
                    {
                        var xr = (Xrecord)tr.GetObject(nod.GetAt(KEY), OpenMode.ForRead);
                        int n = 0;
                        if (xr.Data != null) foreach (TypedValue tv in xr.Data)
                            if (tv.TypeCode == (int)DxfCode.Real) n++;
                        ok = n >= 7;
                    }
                    tr.Commit();
                    return ok;
                }
            }
            catch { return false; }
        }

        public static void Set(Database db, P p)
        {
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var nod = (DBDictionary)tr.GetObject(db.NamedObjectsDictionaryId, OpenMode.ForWrite);
                Xrecord xr;
                if (nod.Contains(KEY)) xr = (Xrecord)tr.GetObject(nod.GetAt(KEY), OpenMode.ForWrite);
                else
                {
                    xr = new Xrecord();
                    nod.SetAt(KEY, xr);
                    tr.AddNewlyCreatedDBObject(xr, true);
                }
                xr.Data = new ResultBuffer(
                    new TypedValue((int)DxfCode.Real, p.R), new TypedValue((int)DxfCode.Real, p.L),
                    new TypedValue((int)DxfCode.Real, p.W1), new TypedValue((int)DxfCode.Real, p.W2),
                    new TypedValue((int)DxfCode.Real, p.A), new TypedValue((int)DxfCode.Real, p.M1),
                    new TypedValue((int)DxfCode.Real, p.M2));
                tr.Commit();
            }
        }

        /// <summary>입력값 검사. 문제가 있으면 사용자에게 보일 문장, 없으면 null.</summary>
        public static string Validate(P p)
        {
            if (p.R <= 0) return "호 반지름 R 은 0 보다 커야 합니다.";
            if (p.L < 0) return "직선 길이 L 은 0 이상이어야 합니다.";
            if (p.A <= 0 || p.A >= 90) return "대각 각도 A 는 0 과 90 사이여야 합니다.";
            if (p.W1 <= 0 || p.W2 <= 0) return "폭 W1·W2 는 0 보다 커야 합니다.";
            if (p.M1 < 0 || p.M2 < 0) return "마진 M1·M2 는 0 이상이어야 합니다.";
            return null;
        }
    }

    // 파라미터 대화상자 — XAML 없이 코드로만 구성(포팅 스크립트가 .cs 만 옮기므로 ZWCAD 판에도 그대로 간다).
    public class ModuleParamDialog : System.Windows.Window
    {
        readonly System.Windows.Controls.TextBox[] _box = new System.Windows.Controls.TextBox[7];
        readonly System.Windows.Controls.CheckBox _applyAll;
        public ModuleParams.P Value;
        public bool ApplyToExisting;

        static readonly System.Windows.Media.Brush Bg = Br(0x2B, 0x2E, 0x33);
        static readonly System.Windows.Media.Brush Card = Br(0x33, 0x37, 0x3D);
        static readonly System.Windows.Media.Brush Fg = Br(0xE6, 0xE8, 0xEB);
        static readonly System.Windows.Media.Brush Muted = Br(0x9A, 0xA1, 0xAA);
        static readonly System.Windows.Media.Brush Line = Br(0x4A, 0x50, 0x58);
        static readonly System.Windows.Media.Brush Accent = Br(0x2F, 0x7C, 0xD6);

        static System.Windows.Media.Brush Br(byte r, byte g, byte b)
        {
            var br = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(r, g, b));
            br.Freeze();
            return br;
        }

        static readonly string[] Labels = {
            "호 반지름 R (mm)", "직선 길이 L (mm)", "평행선 간격 W1 (mm)", "평행선 간격 W2 (mm)",
            "대각 중심각 A (°)", "이격 마진 M1 (mm)", "이격 마진 M2 (mm)" };

        /// <param name="note">대화상자 위쪽 안내(도면 추출 결과 등). null 이면 생략.</param>
        public ModuleParamDialog(ModuleParams.P init, string note, bool applyDefault)
        {
            Title = "모듈 파라미터";
            Width = 520;
            SizeToContent = System.Windows.SizeToContent.Height;
            ResizeMode = System.Windows.ResizeMode.NoResize;
            WindowStartupLocation = System.Windows.WindowStartupLocation.CenterScreen;
            Background = Bg; Foreground = Fg;
            FontFamily = new System.Windows.Media.FontFamily("Malgun Gothic, Segoe UI");
            FontSize = 13;
            ShowInTaskbar = false;

            var root = new System.Windows.Controls.StackPanel { Margin = new System.Windows.Thickness(18) };
            if (!string.IsNullOrEmpty(note))
                root.Children.Add(new System.Windows.Controls.TextBlock
                {
                    Text = note, Foreground = Muted, FontSize = 12, TextWrapping = System.Windows.TextWrapping.Wrap,
                    Margin = new System.Windows.Thickness(2, 0, 0, 14),
                });

            var grid = new System.Windows.Controls.Grid();
            grid.ColumnDefinitions.Add(new System.Windows.Controls.ColumnDefinition());
            grid.ColumnDefinitions.Add(new System.Windows.Controls.ColumnDefinition { Width = new System.Windows.GridLength(14) });
            grid.ColumnDefinitions.Add(new System.Windows.Controls.ColumnDefinition());
            double[] vals = { init.R, init.L, init.W1, init.W2, init.A, init.M1, init.M2 };
            for (int i = 0; i < 7; i++)
            {
                int row = i / 2, col = (i % 2) * 2;
                while (grid.RowDefinitions.Count <= row) grid.RowDefinitions.Add(new System.Windows.Controls.RowDefinition());
                var cell = new System.Windows.Controls.StackPanel { Margin = new System.Windows.Thickness(0, 0, 0, 14) };
                cell.Children.Add(new System.Windows.Controls.TextBlock
                { Text = Labels[i], Foreground = Muted, Margin = new System.Windows.Thickness(2, 0, 0, 5) });
                var tb = new System.Windows.Controls.TextBox
                {
                    Text = ModuleParams.F(vals[i]), Background = Card, Foreground = Fg, BorderBrush = Line,
                    BorderThickness = new System.Windows.Thickness(1), Padding = new System.Windows.Thickness(8, 6, 8, 6),
                    CaretBrush = Fg,
                };
                cell.Children.Add(tb);
                _box[i] = tb;
                System.Windows.Controls.Grid.SetRow(cell, row);
                System.Windows.Controls.Grid.SetColumn(cell, col);
                grid.Children.Add(cell);
            }
            root.Children.Add(grid);

            root.Children.Add(new System.Windows.Controls.TextBlock
            {
                Text = "※ R·L 은 모든 모듈 공통, W1·W2 는 폭을 쓰는 모듈(U·DOUBLE BRANCH·U BRANCH·N·BY PASS·S)이 배치할 때 "
                     + "둘 중 하나를 고릅니다. A 는 대각(N·BY PASS·S) 모듈. M1·M2 는 MAP 이격 마진(형상에는 안 씀).",
                Foreground = Muted, FontSize = 11, TextWrapping = System.Windows.TextWrapping.Wrap,
                Margin = new System.Windows.Thickness(2, 0, 0, 12),
            });
            _applyAll = new System.Windows.Controls.CheckBox
            {
                Content = "도면에 이미 있는 모듈에도 일괄 적용", IsChecked = applyDefault, Foreground = Fg,
                Margin = new System.Windows.Thickness(2, 0, 0, 16),
            };
            root.Children.Add(_applyAll);

            var bar = new System.Windows.Controls.StackPanel
            { Orientation = System.Windows.Controls.Orientation.Horizontal, HorizontalAlignment = System.Windows.HorizontalAlignment.Right };
            var cancel = Btn("취소", Card, Fg); cancel.IsCancel = true; cancel.Click += (s, e) => { DialogResult = false; };
            var ok = Btn("적용", Accent, System.Windows.Media.Brushes.White); ok.IsDefault = true; ok.Click += OnApply;
            bar.Children.Add(cancel); bar.Children.Add(ok);
            root.Children.Add(bar);
            Content = root;
            Loaded += (s, e) => { _box[0].Focus(); _box[0].SelectAll(); };
        }

        static System.Windows.Controls.Button Btn(string text, System.Windows.Media.Brush bg, System.Windows.Media.Brush fg)
            => new System.Windows.Controls.Button
            {
                Content = text, Background = bg, Foreground = fg, BorderBrush = Line,
                BorderThickness = new System.Windows.Thickness(1), Padding = new System.Windows.Thickness(22, 7, 22, 7),
                Margin = new System.Windows.Thickness(8, 0, 0, 0), MinWidth = 92,
            };

        void OnApply(object sender, System.Windows.RoutedEventArgs e)
        {
            var v = new double[7];
            for (int i = 0; i < 7; i++)
                if (!ModuleParams.TryParse(_box[i].Text, out v[i])) { Warn(Labels[i] + " 값이 숫자가 아닙니다.", _box[i]); return; }
            var p = new ModuleParams.P { R = v[0], L = v[1], W1 = v[2], W2 = v[3], A = v[4], M1 = v[5], M2 = v[6] };
            string err = ModuleParams.Validate(p);
            if (err != null) { Warn(err, null); return; }
            Value = p;
            ApplyToExisting = _applyAll.IsChecked == true;
            DialogResult = true;
        }

        void Warn(string msg, System.Windows.Controls.TextBox box)
        {
            System.Windows.MessageBox.Show(this, msg, "모듈 파라미터",
                System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Warning);
            if (box != null) { box.Focus(); box.SelectAll(); }
        }

        /// <summary>대화상자를 띄운다. 반환 null = 취소/대화상자 사용 불가.</summary>
        public static ModuleParamDialog Open(ModuleParams.P init, string note, bool applyDefault)
        {
            ModuleParamDialog dlg;
            try { dlg = new ModuleParamDialog(init, note, applyDefault); }
            catch { return null; }
            bool? r = null;
            try { r = Application.ShowModalWindow(dlg); }
            catch { try { r = dlg.ShowDialog(); } catch { } }
            return r == true ? dlg : null;
        }
    }

    // 도면 분석 → 파라미터 추출
    //  · 모듈이 이미 있으면 그 XData(R·L·W·A)를 그대로 모은다.
    //  · 선·호만 있으면 형상을 읽는다: R = 가장 많은 호 반지름, 호-(직선)-호가 같은 쪽으로 180° 돌면 되돌림(폭 = 두 끝 거리),
    //    반대쪽으로 같은 각을 돌면 차선 이동(폭 = 옆 방향 거리, A = 호 각도). 폭은 가장 많은 두 값을 W1<W2 로.
    //  · L·M1·M2 는 선·호 모양만으로 정할 수 없다(모듈 경계가 도면에 없음, 마진은 규칙) → 현재 값 유지.
    public static class ModuleParamExtractor
    {
        sealed class Seg
        {
            public bool IsArc;
            public Point2d P0, P1, C;
            public double R, Sweep;       // Sweep: P0→P1 부호 있는 각(라디안, + 반시계)
            public Vector2d TangentAt(Point2d p)
            {
                if (!IsArc) { var d = (P1 - P0).GetNormal(); return p.GetDistanceTo(P0) < p.GetDistanceTo(P1) ? d : -d; }
                double sg = Sweep > 0 ? 1 : -1;
                if (p.GetDistanceTo(P1) < p.GetDistanceTo(P0)) sg = -sg;
                var rad = (p - C).GetNormal();
                return new Vector2d(-sg * rad.Y, sg * rad.X);   // p 에서 이 조각이 뻗는 방향
            }
            public int TurnFrom(Point2d from) => ((Sweep > 0) ^ (from.GetDistanceTo(P1) < from.GetDistanceTo(P0))) ? 1 : -1;
        }

        public sealed class Result
        {
            public ModuleParams.P P;
            public string Summary;
            public bool Changed;
        }

        static void Collect(Transaction tr, Entity ent, Matrix3d xf, List<Seg> segs, List<BlockReference> mods, int depth)
        {
            var ln = ent as Line;
            var ac = ent as Arc;
            if (ln != null)
            {
                var a = ln.StartPoint.TransformBy(xf); var b = ln.EndPoint.TransformBy(xf);
                segs.Add(new Seg { P0 = new Point2d(a.X, a.Y), P1 = new Point2d(b.X, b.Y) });
                return;
            }
            if (ac != null)
            {
                var a = ac.StartPoint.TransformBy(xf); var b = ac.EndPoint.TransformBy(xf);
                var c = ac.Center.TransformBy(xf);
                var n = ac.Normal.TransformBy(xf);
                double sw = ac.TotalAngle * (n.Z >= 0 ? 1 : -1);
                // 변환이 대칭(음의 배율)이면 방향이 뒤집힌다
                if (xf.GetDeterminant2D() < 0) sw = -sw;
                segs.Add(new Seg { IsArc = true, P0 = new Point2d(a.X, a.Y), P1 = new Point2d(b.X, b.Y),
                                   C = new Point2d(c.X, c.Y), R = ac.Radius * ScaleOf(xf), Sweep = sw });
                return;
            }
            var br = ent as BlockReference;
            if (br == null || depth > 4) return;
            if (br.GetXDataForApplication(RailFactory.APP) != null && RailFactory.GetKind(br) == 7) { mods.Add(br); return; }
            var bdef = tr.GetObject(br.BlockTableRecord, OpenMode.ForRead) as BlockTableRecord;
            if (bdef == null) return;
            Matrix3d x2 = xf * br.BlockTransform;
            foreach (ObjectId id in bdef)
            {
                var e = tr.GetObject(id, OpenMode.ForRead) as Entity;
                if (e != null) Collect(tr, e, x2, segs, mods, depth + 1);
            }
        }

        static double ScaleOf(Matrix3d m) => new Vector3d(1, 0, 0).TransformBy(m).Length;

        static double GetDeterminant2D(this Matrix3d m) => m[0, 0] * m[1, 1] - m[0, 1] * m[1, 0];

        static List<KeyValuePair<double, int>> Hist(IEnumerable<double> vals, double step)
        {
            var d = new Dictionary<double, int>();
            foreach (double v in vals)
            {
                double k = Math.Round(v / step) * step;
                int c; d.TryGetValue(k, out c); d[k] = c + 1;
            }
            return d.OrderByDescending(kv => kv.Value).ThenBy(kv => kv.Key).ToList();
        }

        static string H(List<KeyValuePair<double, int>> h, int n = 4)
            => string.Join(", ", h.Take(n).Select(kv => ModuleParams.F(kv.Key) + "×" + kv.Value));

        public static Result Run(Database db, ModuleParams.P cur, IEnumerable<ObjectId> only)
        {
            var segs = new List<Seg>();
            var mods = new List<BlockReference>();
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                IEnumerable<ObjectId> ids = only;
                if (ids == null)
                {
                    var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                    var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                    ids = ms.Cast<ObjectId>().ToList();
                }
                foreach (ObjectId id in ids)
                {
                    var e = tr.GetObject(id, OpenMode.ForRead) as Entity;
                    if (e != null) Collect(tr, e, Matrix3d.Identity, segs, mods, 0);
                }
                var p = cur.Clone();
                var lines = new List<string>();
                if (mods.Count > 0)
                {
                    var hr = Hist(mods.Select(RailFactory.GetModR), 0.1);
                    var hl = Hist(mods.Select(RailFactory.GetLength), 0.1);
                    var ha = Hist(mods.Where(b => ModuleGeom.Defs[RailFactory.GetCount(b)].UsesA).Select(RailFactory.GetModA), 0.1);
                    var hw = Hist(mods.Where(b => ModuleGeom.Defs[RailFactory.GetCount(b)].UsesW).Select(RailFactory.GetWidth), 0.1);
                    p.R = hr[0].Key; p.L = hl[0].Key;
                    if (ha.Count > 0) p.A = ha[0].Key;
                    SetWidths(p, hw);
                    lines.Add($"도면의 모듈 {mods.Count}개에서 읽음: R {H(hr)} / L {H(hl)}"
                              + (hw.Count > 0 ? $" / 폭 {H(hw)}" : "") + (ha.Count > 0 ? $" / A {H(ha)}" : ""));
                    if (hr.Count > 1 || hl.Count > 1) lines.Add("※ 모듈마다 R·L 이 달라 가장 많은 값을 골랐습니다.");
                    if (hw.Count > 2) lines.Add($"※ 폭 종류가 {hw.Count}개 — 가장 많은 두 폭만 W1·W2 로 씁니다.");
                }
                else
                {
                    var arcs = segs.Where(s => s.IsArc).ToList();
                    if (arcs.Count == 0) { tr.Commit(); return new Result { P = cur, Summary = "선택 범위에 호가 없어 파라미터를 추출할 수 없습니다.", Changed = false }; }
                    var hr = Hist(arcs.Select(s => s.R), 1.0);
                    p.R = hr[0].Key;
                    var widths = new List<double>();
                    var angles = new List<double>();
                    int arches = 0, crosses = 0;
                    Analyse(segs, widths, angles, ref arches, ref crosses);
                    var hw = Hist(widths, 1.0);
                    var ha = Hist(angles, 0.5);
                    SetWidths(p, hw);
                    if (ha.Count > 0) p.A = ha[0].Key;
                    lines.Add($"선 {segs.Count - arcs.Count}개 · 호 {arcs.Count}개 분석 — 호 반지름 {H(hr)}");
                    lines.Add($"되돌림(호-직선-호 180°) {arches}곳, 차선 이동(호-대각-호) {crosses}곳"
                              + (hw.Count > 0 ? $" — 폭 {H(hw)}" : " — 폭을 찾지 못해 현재 W1·W2 유지")
                              + (ha.Count > 0 ? $", 대각 각도 {H(ha)}" : ""));
                    if (hr.Count > 1) lines.Add("※ 호 반지름이 여러 가지라 가장 많은 값을 골랐습니다.");
                    if (hw.Count > 2) lines.Add($"※ 폭 종류가 {hw.Count}개 — 가장 많은 두 폭만 W1·W2 로 씁니다.");
                    lines.Add("※ L 과 M1·M2 는 선·호 모양으로 정할 수 없어 현재 값을 유지했습니다.");
                }
                tr.Commit();
                bool changed = p.R != cur.R || p.L != cur.L || p.W1 != cur.W1 || p.W2 != cur.W2 || p.A != cur.A;
                return new Result { P = p, Summary = string.Join("\n", lines), Changed = changed };
            }
        }

        static void SetWidths(ModuleParams.P p, List<KeyValuePair<double, int>> hw)
        {
            if (hw.Count == 0) return;
            var two = hw.Take(2).Select(kv => kv.Key).OrderBy(v => v).ToList();
            p.W1 = two[0];
            p.W2 = two.Count > 1 ? two[1] : two[0];
        }

        // 호-(직선)-호 사슬을 찾아 폭·각도를 모은다(진행 방향이 이어지는 것만).
        static void Analyse(List<Seg> segs, List<double> widths, List<double> angles, ref int arches, ref int crosses)
        {
            const double tol = 10.0;
            Func<Point2d, Point2d, bool> near = (a, b) => a.GetDistanceTo(b) <= tol;
            var used = new HashSet<Seg>();
            foreach (Seg a in segs.Where(s => s.IsArc))
            {
                if (used.Contains(a)) continue;
                foreach (var pa in new[] { a.P0, a.P1 })
                {
                    Point2d Ja = pa.GetDistanceTo(a.P0) < 1e-9 ? a.P1 : a.P0;
                    Vector2d arrive = -a.TangentAt(pa);
                    Seg partner = null, mid = null; Point2d Jb = default(Point2d);
                    foreach (Seg b in segs)
                    {
                        if (b == a || used.Contains(b)) continue;
                        Point2d at = near(b.P0, pa) ? b.P0 : (near(b.P1, pa) ? b.P1 : new Point2d(double.NaN, 0));
                        if (double.IsNaN(at.X) || arrive.DotProduct(b.TangentAt(at)) < 0.999) continue;
                        Point2d far = at == b.P0 ? b.P1 : b.P0;
                        if (b.IsArc) { partner = b; Jb = far; break; }
                        Vector2d arrive2 = -b.TangentAt(far);
                        foreach (Seg c in segs)
                        {
                            if (!c.IsArc || c == a || used.Contains(c)) continue;
                            Point2d at2 = near(c.P0, far) ? c.P0 : (near(c.P1, far) ? c.P1 : new Point2d(double.NaN, 0));
                            if (double.IsNaN(at2.X) || arrive2.DotProduct(c.TangentAt(at2)) < 0.999) continue;
                            partner = c; mid = b; Jb = at2 == c.P0 ? c.P1 : c.P0;
                            break;
                        }
                        if (partner != null) break;
                    }
                    if (partner == null || Math.Abs(partner.R - a.R) > tol) continue;
                    int ta = a.TurnFrom(Ja), tb = -partner.TurnFrom(Jb);
                    double sa = Math.Abs(a.Sweep) * 180 / Math.PI, sb = Math.Abs(partner.Sweep) * 180 / Math.PI;
                    Vector2d chord = Jb - Ja;
                    if (ta == tb && Math.Abs(sa + sb - 180) <= 1.0)
                    { widths.Add(chord.Length); arches++; }
                    else if (ta != tb && Math.Abs(sa - sb) <= 1.0 && sa < 89.0)
                    {
                        Vector2d lane = a.TangentAt(Ja);
                        widths.Add(Math.Abs(lane.X * chord.Y - lane.Y * chord.X));
                        angles.Add(sa);
                        crosses++;
                    }
                    else continue;
                    used.Add(a); used.Add(partner); if (mid != null) used.Add(mid);
                    break;
                }
            }
        }
    }

    public class ModuleCommands
    {
        // 리본 버튼 → 명령 브릿지
        public static int PendingModule = -1;                  // 배치할 모듈

        // 배치할 때 기존 끝점에 달라붙는 거리 (mm). 객체 스냅으로 정확히 찍으면 거리 0 이라 항상 붙는다.
        public const double JOIN_TOL = 500.0;

        // ── 파라미터 ──────────────────────────────────────────────────────────
        [CommandMethod("RAILMODPARAM")]
        public void RailModParam()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            var cur = ModuleParams.Get(db);
            var dlg = ModuleParamDialog.Open(cur, null, false);
            if (dlg == null) { ed.WriteMessage("\nRAILMODPARAM: 취소됨(대화상자를 못 열면 RAILMODPARAMP 로 입력하세요)."); return; }
            Commit(doc, cur, dlg.Value, dlg.ApplyToExisting, "RAILMODPARAM");
        }

        // 명령창 입력판(대화상자를 못 쓰는 환경·스크립트용)
        [CommandMethod("RAILMODPARAMP")]
        public void RailModParamP()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            var cur = ModuleParams.Get(db);
            var p = cur.Clone();
            if (!AskDouble(ed, "\nR (호 반지름)", ref p.R)) return;
            if (!AskDouble(ed, "\nL (직선 길이)", ref p.L)) return;
            if (!AskDouble(ed, "\nW1 (평행선 간격 1)", ref p.W1)) return;
            if (!AskDouble(ed, "\nW2 (평행선 간격 2)", ref p.W2)) return;
            if (!AskDouble(ed, "\nA (대각 중심각, °)", ref p.A)) return;
            if (!AskDouble(ed, "\nM1 (이격 마진 1)", ref p.M1)) return;
            if (!AskDouble(ed, "\nM2 (이격 마진 2)", ref p.M2)) return;
            string err = ModuleParams.Validate(p);
            if (err != null) { ed.WriteMessage("\n" + err); return; }
            var pko = new PromptKeywordOptions("\n도면에 이미 있는 모듈에도 적용할까요? [예(Y)/아니오(N)] <N>: ");
            pko.Keywords.Add("Y"); pko.Keywords.Add("N"); pko.Keywords.Default = "N"; pko.AllowNone = true;
            var kr = ed.GetKeywords(pko);
            Commit(doc, cur, p, kr.Status == PromptStatus.OK && kr.StringResult == "Y", "RAILMODPARAMP");
        }

        static void Commit(Document doc, ModuleParams.P oldP, ModuleParams.P p, bool applyExisting, string tag)
        {
            Editor ed = doc.Editor;
            using (doc.LockDocument()) ModuleParams.Set(doc.Database, p);
            ModuleRibbon.RefreshParam();
            ed.WriteMessage($"\n{tag}: 모듈 파라미터 {p.Digest()}");
            if (applyExisting)
            {
                int n = ApplyAll(doc, oldP, p, null);
                ed.WriteMessage($"\n{tag}: 도면의 모듈 {n}개에 일괄 적용." + FollowNote());
            }
        }

        /// <summary>모듈들을 파라미터로 다시 만든다. 폭은 각 모듈의 현재 폭이 옛 W1·W2 중 가까운 쪽 → 새 W1·W2.</summary>
        public static int ApplyAll(Document doc, ModuleParams.P oldP, ModuleParams.P p, IEnumerable<ObjectId> only)
        {
            Database db = doc.Database;
            int n = 0;
            using (doc.LockDocument())
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                IEnumerable<ObjectId> ids = only;
                if (ids == null)
                {
                    var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                    ids = ((BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead)).Cast<ObjectId>().ToList();
                }
                var moves = new List<KeyValuePair<Point3d, Point3d>>();   // 접속구 예전 위치 → 새 위치
                var anchors = new List<Point3d>();                          // 그 접속구 모듈의 곡선 기준점(첫 호 중심)
                var dirs = new List<Vector3d>();                            // 접속구에서 모듈 바깥쪽 방향
                var owners = new List<int>();                               // 접속구가 속한 모듈 번호
                var oldLegs = new List<Tuple<Point3d, Point3d>>();          // L 만 바뀌는 모듈의 옛 직선(월드)
                var newLegs = new List<Tuple<Point3d, Point3d>>();          // 그 모듈의 새 직선(월드)
                foreach (ObjectId id in ids)
                {
                    var br = tr.GetObject(id, OpenMode.ForRead) as BlockReference;
                    if (br == null || br.GetXDataForApplication(RailFactory.APP) == null || RailFactory.GetKind(br) != 7) continue;
                    int mi = RailFactory.GetCount(br);
                    if (mi < 0 || mi >= ModuleGeom.Defs.Length) continue;
                    double w = RailFactory.GetWidth(br);
                    double nw = Math.Abs(w - oldP.W1) <= Math.Abs(w - oldP.W2) ? p.W1 : p.W2;
                    double r1 = p.R, l1 = p.L, w1 = ModuleGeom.Defs[mi].UsesW ? nw : p.W1, a1 = p.A;
                    // 예전·새 접속구(같은 순서로 나온다) — 붙어 있던 흰색 선을 따라 옮기기 위해
                    double r0 = RailFactory.GetModR(br), l0 = RailFactory.GetLength(br), w0 = w, a0 = RailFactory.GetModA(br);
                    Matrix3d xf = br.BlockTransform;
                    var oldPorts = ModuleGeom.Ports(mi, r0, l0, w0, a0);
                    ModuleGeom.Clamp(mi, ref r1, ref l1, ref w1, ref a1);
                    var newPorts = ModuleGeom.Ports(mi, r1, l1, w1, a1);
                    // 곡선 고정: 첫 호의 중심이 예전 자리에 남도록 모듈을 옮긴다 → L 만 바뀌면 곡선은 그대로, 직선 다리만 바깥으로 신축
                    Vector3d shift = ArcAnchor(mi, r0, l0, w0, a0) - ArcAnchor(mi, r1, l1, w1, a1);
                    Point3d anchorW = ArcAnchor(mi, r0, l0, w0, a0).TransformBy(xf);
                    var newDirs = PortDirs(mi, r1, l1, w1, a1, newPorts);
                    // L 만 바뀌는 모듈: 모듈을 풀어 선·호로 보고(옛 다리 + 흰 선 = 원래 레일), 새 L 모듈이 덮는 직선만 빼고
                    //  나머지를 흰 선으로 다시 그린다 → 레일 모양 그대로, 모듈 경계만 바뀐다(빈틈·겹침 보정 불필요)
                    var defM = ModuleGeom.Defs[mi];   // 그 모듈이 쓰는 값만 비교(폭·각도를 안 쓰는 모듈의 저장값은 의미 없음)
                    bool lOnly = Math.Abs(r1 - r0) < 1e-6 && (!defM.UsesW || Math.Abs(w1 - w0) < 1e-6) && (!defM.UsesA || Math.Abs(a1 - a0) < 1e-6);
                    if (lOnly)
                    {
                        foreach (var s in LineSegs(ModuleGeom.Build(mi, r0, l0, w0, a0), Vector3d.ZAxis * 0, xf)) oldLegs.Add(s);
                        foreach (var s in LineSegs(ModuleGeom.Build(mi, r1, l1, w1, a1), shift, xf)) newLegs.Add(s);
                    }
                    if (!lOnly && oldPorts.Count == newPorts.Count)
                        for (int k = 0; k < oldPorts.Count; k++)
                        {
                            moves.Add(new KeyValuePair<Point3d, Point3d>(oldPorts[k].TransformBy(xf), (newPorts[k] + shift).TransformBy(xf)));
                            anchors.Add(anchorW);
                            dirs.Add(newDirs[k].TransformBy(xf));
                            owners.Add(n);
                        }
                    RailFactory.SetModuleParams(tr, br, r1, l1, w1, a1);
                    if (shift.Length > 1e-9)
                    {
                        if (!br.IsWriteEnabled) br.UpgradeOpen();
                        br.TransformBy(Matrix3d.Displacement(shift.TransformBy(xf)));
                    }
                    n++;
                }
                FollowPorts(db, tr, moves, anchors, dirs, owners);
                Recover(db, tr, oldLegs, newLegs);
                tr.Commit();
            }
            PurgeModuleBlocks(db);
            return n;
        }

        static List<Tuple<Point3d, double>> WorldArcs(Database db, List<ObjectId> mods)
        {
            var res = new List<Tuple<Point3d, double>>();
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                foreach (var id in mods)
                {
                    var br = (BlockReference)tr.GetObject(id, OpenMode.ForRead);
                    var bdef = (BlockTableRecord)tr.GetObject(br.BlockTableRecord, OpenMode.ForRead);
                    foreach (ObjectId eid in bdef)
                        if (tr.GetObject(eid, OpenMode.ForRead) is Arc ac)
                            res.Add(Tuple.Create(ac.Center.TransformBy(br.BlockTransform), ac.Radius));
                }
                tr.Commit();
            }
            return res;
        }

        // 접속구마다 모듈 바깥쪽 방향(그 끝을 가진 선·호의 접선, 바깥 향) — Ports 와 같은 순서
        static List<Vector3d> PortDirs(int mi, double r, double l, double w, double a, List<Point3d> ports)
        {
            var ents = ModuleGeom.Build(mi, r, l, w, a);
            var res = new List<Vector3d>();
            foreach (var q in ports)
            {
                Vector3d d = Vector3d.XAxis;
                foreach (Entity e in ents)
                {
                    var c = e as Curve;
                    if (c == null) continue;
                    try
                    {
                        if (c.StartPoint.DistanceTo(q) < 1e-5) { d = -c.GetFirstDerivative(c.StartParam).GetNormal(); break; }
                        if (c.EndPoint.DistanceTo(q) < 1e-5) { d = c.GetFirstDerivative(c.EndParam).GetNormal(); break; }
                    }
                    catch { }
                }
                res.Add(d);
            }
            foreach (Entity e in ents) e.Dispose();
            return res;
        }

        // 모듈 기준 좌표에서 첫 호의 중심 (호가 없으면 원점) — 파라미터를 바꿀 때 곡선 위치를 고정하는 기준
        static Point3d ArcAnchor(int mi, double r, double l, double w, double a)
        {
            Point3d c = Point3d.Origin;
            bool found = false;
            foreach (Entity e in ModuleGeom.Build(mi, r, l, w, a))
            {
                if (!found && e is Arc ac) { c = ac.Center; found = true; }
                e.Dispose();
            }
            return c;
        }

        // 결과 보고용: 마지막 ApplyAll 에서 끝을 옮긴 선 수 / 자동으로 못 이은 곳(호 끝, 모듈끼리 맞닿은 곳)
        public static int LastLinesMoved, LastArcsLeft, LastModuleGaps, LastBridged, LastLinesRemoved;

        static string FollowNote()
            => (LastRecovered > 0 ? $" 모듈을 풀어 새 L 로 다시 그렸습니다(흰 선 {LastRecovered}개로 정리)." : "")
             + (LastLinesMoved > 0 ? $" 붙어 있던 선 {LastLinesMoved}개를 따라 늘였습니다." : "")
             + (LastBridged > 0 ? $" 맞닿아 있던 모듈 사이 틈 {LastBridged}곳을 직선으로 이었습니다." : "")
             + (LastLinesRemoved > 0 ? $" 다리가 늘어나 덮인 선 {LastLinesRemoved}개를 지웠습니다." : "")
             + (LastArcsLeft + LastModuleGaps > 0
                ? $" 자동으로 잇지 못한 곳: 호 끝 {LastArcsLeft}곳, 모듈끼리 맞닿았던 곳 {LastModuleGaps}곳 — 확인하세요." : "");

        // 헤드리스 검증: CURVE·BRANCH 를 놓고 접속구마다 바깥으로 흰 선을 붙인 뒤 R·L 을 바꿔 일괄 적용 → 선 끝이 새 접속구에 붙어 있어야 함
        [CommandMethod("RAILMODAPPLYTEST")]
        public void RailModApplyTest()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Database db = doc.Database; Editor ed = doc.Editor;
            var p = new ModuleParams.P { R = 450, L = 20, W1 = 900, W2 = 1350, A = 45, M1 = 150, M2 = 520 };
            ModuleParams.Set(db, p);
            var placed = new List<ObjectId>();
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);
                foreach (var (mi, x) in new[] { (0, 0.0), (2, 10000.0), (5, 20000.0) })
                {
                    var id = RailFactory.PlaceModule(db, tr, new Point3d(x, 0, 0), mi, p.R, p.L, p.W1, p.A);
                    placed.Add(id);
                    var br = (BlockReference)tr.GetObject(id, OpenMode.ForRead);
                    var ports = ModuleGeom.Ports(mi, p.R, p.L, p.W1, p.A);
                    var pdirs = PortDirs(mi, p.R, p.L, p.W1, p.A, ports);
                    for (int qi = 0; qi < ports.Count; qi++)
                    {
                        Point3d w = ports[qi].TransformBy(br.BlockTransform);
                        Vector3d d = pdirs[qi].TransformBy(br.BlockTransform) * 3000;   // 실제 레일처럼 다리 방향으로 곧게 이어지는 흰 선
                        var ln = new Line(w, w + d);
                        ms.AppendEntity(ln); tr.AddNewlyCreatedDBObject(ln, true);
                    }
                }
                tr.Commit();
            }
            var arcsBefore = WorldArcs(db, placed);
            var p2 = p.Clone(); p2.L = 200;                 // 사용자 상황: R·A 그대로, L 20 → 200
            int n = ApplyAll(doc, p, p2, null);
            var arcsAfter = WorldArcs(db, placed);
            int arcSame = 0;
            foreach (var a in arcsBefore)
                if (arcsAfter.Exists(b => b.Item1.DistanceTo(a.Item1) < 1e-3 && Math.Abs(b.Item2 - a.Item2) < 1e-3)) arcSame++;
            ed.WriteMessage($"\nRAILMODAPPLYTEST: 곡선 {arcsBefore.Count}개 중 위치·반지름 그대로 {arcSame}개.");
            int ok = 0, bad = 0;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var ends = new List<Point3d>();
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                foreach (ObjectId id in ms)
                    if (tr.GetObject(id, OpenMode.ForRead) is Line ln) { ends.Add(ln.StartPoint); ends.Add(ln.EndPoint); }
                foreach (var id in placed)
                {
                    var br = (BlockReference)tr.GetObject(id, OpenMode.ForRead);
                    int mi = RailFactory.GetCount(br);
                    foreach (var q in ModuleGeom.Ports(mi, RailFactory.GetModR(br), RailFactory.GetLength(br), RailFactory.GetWidth(br), RailFactory.GetModA(br)))
                    {
                        Point3d w = q.TransformBy(br.BlockTransform);
                        if (ends.Exists(e => e.DistanceTo(w) < 1e-3)) ok++; else bad++;
                    }
                }
                tr.Commit();
            }
            ed.WriteMessage($"\nRAILMODAPPLYTEST: 모듈 {n}개 적용, 접속구 {ok + bad}개 중 선이 붙어 있음 {ok} / 끊어짐 {bad}." + FollowNote());
        }

        // 헤드리스 검증 2: 모듈끼리 직접 맞닿은 쌍(L 200) → L 20 으로 줄이면 틈을 직선으로 이음 → 다시 L 200 이면 그 직선이 지워지고 다시 맞닿음
        [CommandMethod("RAILMODAPPLYTEST2")]
        public void RailModApplyTest2()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Database db = doc.Database; Editor ed = doc.Editor;
            var p = new ModuleParams.P { R = 450, L = 200, W1 = 900, W2 = 1350, A = 45, M1 = 150, M2 = 520 };
            ModuleParams.Set(db, p);
            var placed = new List<ObjectId>();
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                foreach (var (mi, x) in new[] { (0, 0.0), (2, 10000.0) })
                {
                    var a = RailFactory.PlaceModule(db, tr, new Point3d(x, 0, 0), mi, p.R, p.L, p.W1, p.A);
                    var ba = (BlockReference)tr.GetObject(a, OpenMode.ForRead);
                    Point3d end = ModuleGeom.Ports(mi, p.R, p.L, p.W1, p.A)[0].TransformBy(ba.BlockTransform);
                    var b = RailFactory.PlaceModule(db, tr, new Point3d(x, 0, 0), mi, p.R, p.L, p.W1, p.A);
                    var bb = (BlockReference)tr.GetObject(b, OpenMode.ForWrite);
                    bb.TransformBy(Matrix3d.Rotation(Math.PI, Vector3d.ZAxis, end));   // 끝점끼리만 맞닿는 쌍
                    placed.Add(a); placed.Add(b);
                }
                tr.Commit();
            }
            var arcs0 = WorldArcs(db, placed);
            var p2 = p.Clone(); p2.L = 20;
            ApplyAll(doc, p, p2, null);
            string note1 = FollowNote();
            int joined1 = CountJoined(db, placed);
            var p3 = p2.Clone(); p3.L = 200;
            ApplyAll(doc, p2, p3, null);
            string note2 = FollowNote();
            var arcs2 = WorldArcs(db, placed);
            int same = 0;
            foreach (var a in arcs0)
                if (arcs2.Exists(b => b.Item1.DistanceTo(a.Item1) < 1e-3 && Math.Abs(b.Item2 - a.Item2) < 1e-3)) same++;
            int lines = 0;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                foreach (ObjectId id in ms) if (tr.GetObject(id, OpenMode.ForRead) is Line) lines++;
                tr.Commit();
            }
            ed.WriteMessage($"\nRAILMODAPPLYTEST2: L200->20 접속구 연결 {joined1}/{placed.Count * 0 + 2}쌍 |{note1}");
            ed.WriteMessage($"\nRAILMODAPPLYTEST2: L20->200 남은 흰 선 {lines}개(0 기대), 곡선 원위치 {same}/{arcs0.Count} |{note2}");
        }

        // 맞닿은 쌍(placed 의 2개씩)의 첫 접속구가 흰 선 하나로 이어져 있는지 센다
        static int CountJoined(Database db, List<ObjectId> placed)
        {
            int ok = 0;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var lines = new List<Line>();
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                foreach (ObjectId id in ms) if (tr.GetObject(id, OpenMode.ForRead) is Line ln) lines.Add(ln);
                for (int k = 0; k + 1 < placed.Count; k += 2)
                {
                    var pa = PortsW(tr, placed[k]); var pb = PortsW(tr, placed[k + 1]);
                    bool hit = lines.Exists(ln => pa.Exists(q => q.DistanceTo(ln.StartPoint) < 1e-3 || q.DistanceTo(ln.EndPoint) < 1e-3)
                                               && pb.Exists(q => q.DistanceTo(ln.StartPoint) < 1e-3 || q.DistanceTo(ln.EndPoint) < 1e-3));
                    if (hit) ok++;
                }
                tr.Commit();
            }
            return ok;
        }

        static List<Point3d> PortsW(Transaction tr, ObjectId id)
        {
            var br = (BlockReference)tr.GetObject(id, OpenMode.ForRead);
            var res = new List<Point3d>();
            foreach (var q in ModuleGeom.Ports(RailFactory.GetCount(br), RailFactory.GetModR(br), RailFactory.GetLength(br), RailFactory.GetWidth(br), RailFactory.GetModA(br)))
                res.Add(q.TransformBy(br.BlockTransform));
            return res;
        }

        static IEnumerable<Tuple<Point3d, Point3d>> LineSegs(List<Entity> ents, Vector3d shiftLocal, Matrix3d xf)
        {
            var res = new List<Tuple<Point3d, Point3d>>();
            foreach (Entity e in ents)
            {
                if (e is Line ln)
                    res.Add(Tuple.Create((ln.StartPoint + shiftLocal).TransformBy(xf), (ln.EndPoint + shiftLocal).TransformBy(xf)));
                e.Dispose();
            }
            return res;
        }

        public static int LastRecovered;

        sealed class LineGroup
        {
            public Vector3d U, N; public double C;
            public List<double[]> OldI = new List<double[]>(), NewI = new List<double[]>();
            public List<Tuple<ObjectId, double, double, string>> White = new List<Tuple<ObjectId, double, double, string>>();
        }

        // "모듈 해제 → 새 L 로 다시 그리기": 같은 직선 위의 (옛 모듈 다리 ∪ 거기 이어진 흰 선) 구간에서 새 모듈 다리가 덮는
        //  부분을 뺀 나머지를 흰 선으로 다시 그린다. 원래 흰 선의 끝점(호가 닿는 곳 등)은 그대로 끊어 둔다.
        static void Recover(Database db, Transaction tr, List<Tuple<Point3d, Point3d>> oldLegs, List<Tuple<Point3d, Point3d>> newLegs)
        {
            const double TOL = 1.0;
            LastRecovered = 0;
            if (oldLegs.Count == 0) return;
            var groups = new List<LineGroup>();
            Func<Point3d, Point3d, bool, LineGroup> find = (a, b, create) =>
            {
                Vector3d u = b - a;
                if (u.Length < 1e-6) return null;
                u = u.GetNormal();
                if (u.X < -1e-9 || (Math.Abs(u.X) <= 1e-9 && u.Y < 0)) u = -u;
                var nrm = new Vector3d(-u.Y, u.X, 0);
                double c = nrm.DotProduct(a.GetAsVector());
                foreach (var g in groups)
                    if (Math.Abs(g.U.X * u.Y - g.U.Y * u.X) < 1e-7 && Math.Abs(g.C - c) < 0.5) return g;
                if (!create) return null;
                var ng = new LineGroup { U = u, N = nrm, C = c };
                groups.Add(ng);
                return ng;
            };
            Func<LineGroup, Point3d, double> tOf = (g, p) => g.U.DotProduct(p.GetAsVector());
            foreach (var s in oldLegs) { var g = find(s.Item1, s.Item2, true); if (g != null) g.OldI.Add(Sorted(tOf(g, s.Item1), tOf(g, s.Item2))); }
            foreach (var s in newLegs) { var g = find(s.Item1, s.Item2, true); if (g != null) g.NewI.Add(Sorted(tOf(g, s.Item1), tOf(g, s.Item2))); }

            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
            var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);
            foreach (ObjectId id in ms)
            {
                if (!(tr.GetObject(id, OpenMode.ForRead) is Line ln) || ln.IsErased) continue;
                var g = find(ln.StartPoint, ln.EndPoint, false);
                if (g == null) continue;
                var iv = Sorted(tOf(g, ln.StartPoint), tOf(g, ln.EndPoint));
                g.White.Add(Tuple.Create(id, iv[0], iv[1], ln.Layer));
            }

            foreach (var g in groups)
            {
                if (g.OldI.Count == 0) continue;
                // 옛 다리 구간에서 시작해, 닿거나 겹치는 흰 선을 차례로 붙여 원래 레일 구간을 만든다
                var comps = Merge(g.OldI, TOL);
                var used = new List<Tuple<ObjectId, double, double, string>>();
                bool grew = true;
                while (grew)
                {
                    grew = false;
                    foreach (var w in g.White)
                    {
                        if (used.Contains(w)) continue;
                        if (comps.Exists(c => w.Item2 <= c[1] + TOL && w.Item3 >= c[0] - TOL))
                        {
                            used.Add(w);
                            comps.Add(new[] { w.Item2, w.Item3 });
                            comps = Merge(comps, TOL);
                            grew = true;
                        }
                    }
                }
                // 남길 구간 = 원래 레일 구간 − 새 모듈 다리. 원래 흰 선 끝점에서는 끊어 둔다.
                var newI = Merge(g.NewI, TOL);
                var cuts = new List<double>();
                foreach (var w in used) { cuts.Add(w.Item2); cuts.Add(w.Item3); }
                string layer = used.Count > 0 ? used[0].Item4 : "0";
                foreach (var w in used)
                {
                    var e = (Entity)tr.GetObject(w.Item1, OpenMode.ForWrite);
                    e.Erase();
                }
                foreach (var c in comps)
                    foreach (var piece in Subtract(c, newI, TOL))
                        foreach (var sp in SplitAt(piece, cuts, TOL))
                        {
                            if (sp[1] - sp[0] <= TOL) continue;
                            Point3d a = Point3d.Origin + g.N * g.C + g.U * sp[0];
                            Point3d b = Point3d.Origin + g.N * g.C + g.U * sp[1];
                            var nl = new Line(a, b) { Layer = layer };
                            ms.AppendEntity(nl);
                            tr.AddNewlyCreatedDBObject(nl, true);
                            LastRecovered++;
                        }
            }
        }

        static double[] Sorted(double a, double b) => a <= b ? new[] { a, b } : new[] { b, a };

        static List<double[]> Merge(List<double[]> iv, double tol)
        {
            var s = iv.OrderBy(x => x[0]).ToList();
            var res = new List<double[]>();
            foreach (var x in s)
            {
                if (res.Count > 0 && x[0] <= res[res.Count - 1][1] + tol)
                    res[res.Count - 1][1] = Math.Max(res[res.Count - 1][1], x[1]);
                else res.Add(new[] { x[0], x[1] });
            }
            return res;
        }

        static List<double[]> Subtract(double[] c, List<double[]> holes, double tol)
        {
            var res = new List<double[]> { new[] { c[0], c[1] } };
            foreach (var h in holes)
            {
                var next = new List<double[]>();
                foreach (var r in res)
                {
                    if (h[1] <= r[0] + tol || h[0] >= r[1] - tol) { next.Add(r); continue; }
                    if (h[0] > r[0] + tol) next.Add(new[] { r[0], h[0] });
                    if (h[1] < r[1] - tol) next.Add(new[] { h[1], r[1] });
                }
                res = next;
            }
            return res;
        }

        static List<double[]> SplitAt(double[] r, List<double> cuts, double tol)
        {
            var pts = new List<double> { r[0] };
            foreach (var c in cuts.OrderBy(x => x)) if (c > pts[pts.Count - 1] + tol && c < r[1] - tol) pts.Add(c);
            pts.Add(r[1]);
            var res = new List<double[]>();
            for (int i = 0; i + 1 < pts.Count; i++) res.Add(new[] { pts[i], pts[i + 1] });
            return res;
        }

        // 모듈 접속구에 붙어 있던 흰색 선(LINE, 열린 폴리선)의 끝을 새 접속구 위치로 옮긴다.
        //  호는 끝만 옮기면 모양이 깨지므로 세기만 한다. 두 모듈의 접속구가 맞닿아 있었는데 새 위치가 다르면 틈으로 센다.
        static void FollowPorts(Database db, Transaction tr, List<KeyValuePair<Point3d, Point3d>> moves, List<Point3d> anchors,
                                List<Vector3d> dirs, List<int> owners)
        {
            const double TOL = 1.0;
            LastLinesMoved = LastArcsLeft = LastModuleGaps = LastBridged = LastLinesRemoved = 0;
            Func<Point3d, Point3d?> target = q =>
            {
                foreach (var m in moves)
                    if (m.Key.DistanceTo(q) <= TOL) return m.Value;
                return null;
            };
            // 같은 직선 위에서 서로 마주 보는 두 모듈의 접속구: 반영 전엔 맞닿거나 다리가 포개져 있었는데(틈 ≤ 0)
            //  반영 후 벌어졌으면(다리가 짧아짐) 그 사이는 직선 레일 → 흰 선으로 잇는다.
            //  맞닿아 있던 쌍이 서로 파고들게 되면(다리가 길어짐) 잇지 않고 센다(겹침은 빨간색으로 보인다).
            var bridges = new List<KeyValuePair<Point3d, Point3d>>();
            for (int i = 0; i < moves.Count; i++)
                for (int j = i + 1; j < moves.Count; j++)
                {
                    if (owners[i] == owners[j]) continue;
                    Vector3d di = dirs[i], dj = dirs[j];
                    if (di.DotProduct(dj) > -0.999) continue;                       // 마주 보지 않음
                    Vector3d oldV = moves[j].Key - moves[i].Key, newV = moves[j].Value - moves[i].Value;
                    if ((oldV - di * oldV.DotProduct(di)).Length > TOL) continue;     // 같은 직선 위가 아님(예전)
                    if ((newV - di * newV.DotProduct(di)).Length > TOL) continue;     // 같은 직선 위가 아님(새)
                    double oldGap = oldV.DotProduct(di), newGap = newV.DotProduct(di);
                    if (oldGap > TOL) continue;                                       // 예전에도 떨어져 있었음(사이에 흰 선)
                    if (oldGap < -2 * Math.Max(1.0, moves[i].Key.DistanceTo(anchors[i]))) continue;   // 너무 깊이 포개짐 = 다른 레일
                    if (newGap > TOL) bridges.Add(new KeyValuePair<Point3d, Point3d>(moves[i].Value, moves[j].Value));
                    else if (Math.Abs(oldGap) <= TOL && newGap < -TOL) LastModuleGaps++;
                }
            if (moves.Count == 0) return;
            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
            var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
            foreach (ObjectId id in ms)
            {
                var ent = tr.GetObject(id, OpenMode.ForRead) as Entity;
                if (ent is Line ln)
                {
                    Point3d? s = target(ln.StartPoint), e = target(ln.EndPoint);
                    if (s == null && e == null) continue;
                    ln.UpgradeOpen();
                    Vector3d before = ln.EndPoint - ln.StartPoint;
                    Point3d ns = s ?? ln.StartPoint, ne = e ?? ln.EndPoint;
                    Vector3d after = ne - ns;
                    // 양 끝이 다 옮겨져 길이가 0 이 되거나 방향이 뒤집혔으면 = 늘어난 다리가 이 선을 덮었다 → 지운다
                    if (s != null && e != null && (after.Length <= TOL || after.DotProduct(before) <= 0))
                    {
                        ln.Erase();
                        LastLinesRemoved++;
                        continue;
                    }
                    ln.StartPoint = ns;
                    ln.EndPoint = ne;
                    LastLinesMoved++;
                }
                else if (ent is Polyline pl && !pl.Closed && pl.NumberOfVertices >= 2)
                {
                    int last = pl.NumberOfVertices - 1;
                    Point3d? s = target(pl.StartPoint), e = target(pl.EndPoint);
                    if (s == null && e == null) continue;
                    pl.UpgradeOpen();
                    if (s != null) pl.SetPointAt(0, new Point2d(s.Value.X, s.Value.Y));
                    if (e != null) pl.SetPointAt(last, new Point2d(e.Value.X, e.Value.Y));
                    LastLinesMoved++;
                }
                else if (ent is Arc ac)
                {
                    if (target(ac.StartPoint) != null || target(ac.EndPoint) != null) LastArcsLeft++;
                }
            }
            if (bridges.Count > 0)
            {
                ms.UpgradeOpen();
                foreach (var b in bridges)
                {
                    var ln = new Line(b.Key, b.Value) { Layer = "0" };     // 흰 선(0 레이어)
                    ms.AppendEntity(ln);
                    tr.AddNewlyCreatedDBObject(ln, true);
                    LastBridged++;
                }
            }
        }

        // 도면의 모든 모듈에 현재 파라미터 일괄 적용 — 명령 줄에서 범위를 묻지 않는다
        [CommandMethod("RAILMODAPPLY")]
        public void RailModApply()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            var p = ModuleParams.Get(db);
            int n = ApplyAll(doc, p, p, null);
            ed.WriteMessage($"\nRAILMODAPPLY: 모듈 {n}개를 {p.Digest()} 로 다시 만들었습니다." + FollowNote());
        }

        // 도면 분석 → 파라미터 추출 → 확인 후 적용
        [CommandMethod("RAILMODEXTRACT")]
        public void RailModExtract() { Extract(true); }

        // 헤드리스 검증용: 대화상자 없이 추출값을 바로 저장
        [CommandMethod("RAILMODEXTRACTP")]
        public void RailModExtractP() { Extract(false); }

        static void Extract(bool dialog)
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            // 도면 전체를 분석한다 — 명령 줄에서 범위를 묻지 않고, 결과는 대화상자로만 보여준다
            var cur = ModuleParams.Get(db);
            var res = ModuleParamExtractor.Run(db, cur, null);
            if (!dialog)
            {
                foreach (string ln in res.Summary.Split('\n')) ed.WriteMessage("\n  " + ln);
                ed.WriteMessage($"\n  추출 결과: {res.P.Digest()}");
                Commit(doc, cur, res.P, false, "RAILMODEXTRACTP");
                return;
            }
            var dlg = ModuleParamDialog.Open(res.P, "도면 분석 결과\n" + res.Summary, false);
            if (dlg == null) { ed.WriteMessage("\nRAILMODEXTRACT: 적용하지 않음."); return; }
            Commit(doc, cur, dlg.Value, dlg.ApplyToExisting, "RAILMODEXTRACT");
        }

        // ── 배치 ──────────────────────────────────────────────────────────────
        // 폭을 쓰는 모듈이 배치될 폭 — 리본 [폭 W1/W2] 버튼으로 전환 (묻지 않음).
        public static bool UseW2;

        // 리본 [폭] 버튼: W1 ↔ W2 전환.
        [CommandMethod("RAILMODW")]
        public void RailModW()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            UseW2 = !UseW2;
            ModuleRibbon.RefreshParam();
            var p = ModuleParams.Get(doc.Database);
            doc.Editor.WriteMessage($"\nRAILMODW: 폭 {(UseW2 ? "W2" : "W1")}({ModuleParams.F(UseW2 ? p.W2 : p.W1)}) 로 배치합니다.");
        }

        // 파라미터로 배치 (리본 모듈 버튼). 폭을 쓰는 모듈은 리본에서 고른 W1/W2 로 바로 배치.
        [CommandMethod("RAILMOD")]
        public void RailMod()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            int mi = PendingModule; PendingModule = -1;
            if (mi < 0 || mi >= ModuleGeom.Defs.Length) { mi = AskModule(ed, "모듈 번호"); if (mi < 0) return; }
            var def = ModuleGeom.Defs[mi];
            var p = ModuleParams.Get(db);
            double w = UseW2 ? p.W2 : p.W1;
            ed.WriteMessage($"\n{def.Name}: R{ModuleParams.F(p.R)} L{ModuleParams.F(p.L)}"
                            + (def.UsesW ? $" W{ModuleParams.F(w)}" : "") + (def.UsesA ? $" A{ModuleParams.F(p.A)}" : ""));
            PromptPointResult p0 = ed.GetPoint($"\n{def.Name} 접속 위치(기존 끝점에 자동으로 붙습니다): ");
            if (p0.Status != PromptStatus.OK) return;
            bool joined = PlaceAt(db, mi, p0.Value, p.R, p.L, w, p.A);
            ed.WriteMessage(joined ? $"\nRAILMOD: {def.Name} 생성 - 기존 끝점에 접합." : $"\nRAILMOD: {def.Name} 생성.");
        }

        // 선·호 → 모듈 치환: 현재 도면을 DXF 로 내보내 변환기(DXFtoMAP.exe --cad2mod)로 치환하고 결과 도면을 연다.
        //  도면에 저장된 파라미터 한 세트(R·L·W1·W2·A)로만 치환 — 안 맞는 곳은 흰색 선·호로 남는다.
        //  파라미터가 저장돼 있지 않으면 알리기만 한다.
        [CommandMethod("RAILMODCONV", CommandFlags.Session)]
        public void RailModConv()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            if (doc == null) return;
            Editor ed = doc.Editor;
            if (!ModuleParams.Has(doc.Database))
            {
                string m = "도면에 모듈 파라미터가 저장돼 있지 않습니다.\n[파라미터 설정] 또는 [도면에서 추출]로 저장한 뒤 다시 실행하세요.";
                ed.WriteMessage("\nRAILMODCONV: " + m.Replace("\n", " "));
                try { System.Windows.MessageBox.Show(m, "선·호 → 모듈 치환", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Warning); } catch { }
                return;
            }
            string exe = Cad2Map.Resolve();
            if (exe == null) { ed.WriteMessage("\nRAILMODCONV: 변환기(" + Cad2Map.EXE + ")를 찾지 못했습니다."); return; }
            // 항상 도면 전체(모든 레이어)를 치환한다 — 명령 줄에서 레이어를 묻지 않는다
            string outp = RunConvert(doc, exe, "");
            if (outp == null) return;
            try { Application.DocumentManager.Open(outp, false); }
            catch (System.Exception ex) { ed.WriteMessage("\nRAILMODCONV: 결과 도면 열기 실패 - " + ex.Message + " (" + outp + ")"); }
        }

        // 치환 본체: DXF 내보내기 → 변환기 --cad2mod → 보고 출력. 성공하면 결과 도면 경로, 아니면 null.
        static string RunConvert(Document doc, string exe, string layer)
        {
            Editor ed = doc.Editor;
            string dxf;
            try { dxf = Cad2Map.ExportCurrent(doc, "선·호 → 모듈 치환: 원본 DXF 저장 위치 (결과는 같은 폴더의 _modules.dxf)"); }
            catch (System.Exception ex) { ed.WriteMessage("\nRAILMODCONV: 도면 내보내기 실패 - " + ex.Message); return null; }
            if (dxf == null) return null;
            string outp = System.IO.Path.Combine(System.IO.Path.GetDirectoryName(dxf),
                                                 System.IO.Path.GetFileNameWithoutExtension(dxf) + "_modules.dxf");
            string report = outp.Substring(0, outp.Length - 4) + "_result.txt";
            try { if (System.IO.File.Exists(report)) System.IO.File.Delete(report); } catch { }
            ed.WriteMessage("\nRAILMODCONV: 치환 중... (" + System.IO.Path.GetFileName(outp) + ")");
            int code;
            try
            {
                var psi = new System.Diagnostics.ProcessStartInfo(exe)
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WorkingDirectory = System.IO.Path.GetDirectoryName(exe),
                    Arguments = "--cad2mod \"" + dxf + "\" \"" + outp + "\" --layer \"" + layer + "\"",
                };
                using (var pr = System.Diagnostics.Process.Start(psi))
                {
                    if (!pr.WaitForExit(600000)) { try { pr.Kill(); } catch { } ed.WriteMessage("\nRAILMODCONV: 10분 안에 끝나지 않아 중단했습니다."); return null; }
                    code = pr.ExitCode;
                }
            }
            catch (System.Exception ex) { ed.WriteMessage("\nRAILMODCONV: 변환기 실행 실패 - " + ex.Message); return null; }
            string text = "";
            try { if (System.IO.File.Exists(report)) text = System.IO.File.ReadAllText(report, System.Text.Encoding.UTF8).Trim(); } catch { }
            foreach (string ln in text.Split('\n')) ed.WriteMessage("\n  " + ln.TrimEnd('\r'));
            if (code != 0 || !System.IO.File.Exists(outp))
            {
                try { System.Windows.MessageBox.Show(text.Length > 0 ? text : "치환하지 못했습니다 (코드 " + code + ").", "선·호 → 모듈 치환", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Warning); } catch { }
                return null;
            }
            return outp;
        }

        // 헤드리스 검증용: RAILMODCONV 와 같은 본체(전체 레이어, 결과 도면은 열지 않음)
        [CommandMethod("RAILMODCONVTEST")]
        public void RailModConvTest()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            if (!ModuleParams.Has(doc.Database)) { ed.WriteMessage("\nRAILMODCONVTEST: 파라미터 없음 - 치환 안 함"); return; }
            string exe = Cad2Map.Resolve();
            if (exe == null) { ed.WriteMessage("\nRAILMODCONVTEST: 변환기 없음"); return; }
            string outp = RunConvert(doc, exe, "");
            ed.WriteMessage("\nRAILMODCONVTEST: " + (outp ?? "실패"));
        }

        // 모듈 삭제: 선택한 모듈을 지우고, 참조가 없어진 모듈 블록 정의도 정리한다.
        [CommandMethod("RAILMODDEL")]
        public void RailModDel()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            var pso = new PromptSelectionOptions { MessageForAdding = "\n삭제할 모듈 선택" };
            PromptSelectionResult psr = ed.GetSelection(pso);
            if (psr.Status != PromptStatus.OK) return;
            int erased = 0, skipped = 0;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                foreach (SelectedObject so in psr.Value)
                {
                    if (so == null) continue;
                    var br = tr.GetObject(so.ObjectId, OpenMode.ForWrite) as BlockReference;
                    if (br == null || RailFactory.GetKind(br) != 7) { skipped++; continue; }
                    br.Erase();
                    erased++;
                }
                tr.Commit();
            }
            int purged = PurgeModuleBlocks(db);
            ed.WriteMessage($"\nRAILMODDEL: 모듈 {erased}개 삭제"
                          + (skipped > 0 ? $" (모듈이 아닌 것 {skipped}개 제외)" : "")
                          + (purged > 0 ? $", 안 쓰는 블록 정의 {purged}개 정리" : "") + ".");
        }

        /// <summary>지정 위치에 배치한다. 근처에 기존 끝점이 있으면 거기에 붙인다. 반환 true = 접합됨.</summary>
        public static bool PlaceAt(Database db, int mi, Point3d pick, double r, double l, double w, double a)
        {
            bool joined;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                Point3d basePort = BasePort(mi, r, l, w, a);
                Point3d target = NearestExistingEnd(db, tr, pick, out joined);
                RailFactory.PlaceModule(db, tr, target - basePort.GetAsVector(), mi, r, l, w, a);
                tr.Commit();
            }
            return joined;
        }

        // 모듈의 기준 접속구 = 가장 아래(같으면 가장 왼쪽) 끝점. 이 점이 클릭 위치/기존 끝점에 온다.
        static Point3d BasePort(int mi, double r, double l, double w, double a)
        {
            var ports = ModuleGeom.Ports(mi, r, l, w, a);
            Point3d best = Point3d.Origin;
            bool first = true;
            foreach (Point3d p in ports)
            {
                if (first || p.Y < best.Y - 1e-6 || (Math.Abs(p.Y - best.Y) < 1e-6 && p.X < best.X))
                { best = p; first = false; }
            }
            return first ? Point3d.Origin : best;
        }

        // 클릭 위치 근처(JOIN_TOL)에서 기존 레일/모듈의 끝점을 찾는다. 없으면 클릭 위치 그대로.
        static Point3d NearestExistingEnd(Database db, Transaction tr, Point3d pick, out bool found)
        {
            found = false;
            Point3d best = pick;
            double bestD = JOIN_TOL;
            try
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                foreach (ObjectId id in ms)
                {
                    var br = tr.GetObject(id, OpenMode.ForRead) as BlockReference;
                    if (br == null) continue;
                    if (br.GetXDataForApplication(RailFactory.APP) == null) continue;   // 우리 레일/모듈만
                    try
                    {
                        var ext = br.GeometricExtents;                                  // 먼 블록은 빠르게 제외
                        if (pick.X < ext.MinPoint.X - JOIN_TOL || pick.X > ext.MaxPoint.X + JOIN_TOL ||
                            pick.Y < ext.MinPoint.Y - JOIN_TOL || pick.Y > ext.MaxPoint.Y + JOIN_TOL) continue;
                    }
                    catch { }
                    var bdef = tr.GetObject(br.BlockTableRecord, OpenMode.ForRead) as BlockTableRecord;
                    if (bdef == null) continue;
                    Matrix3d xf = br.BlockTransform;
                    foreach (ObjectId eid in bdef)
                    {
                        var ent = tr.GetObject(eid, OpenMode.ForRead) as Entity;
                        var ln = ent as Line;
                        var ac = ent as Arc;
                        if (ln == null && ac == null) continue;
                        Point3d q1 = (ln != null ? ln.StartPoint : ac.StartPoint).TransformBy(xf);
                        Point3d q2 = (ln != null ? ln.EndPoint : ac.EndPoint).TransformBy(xf);
                        foreach (Point3d q in new[] { q1, q2 })
                        {
                            double d = q.DistanceTo(pick);
                            if (d < bestD) { bestD = d; best = q; found = true; }
                        }
                    }
                }
            }
            catch { }
            return best;
        }

        // 참조가 하나도 없는 RAILMOD_* 블록 정의 제거
        static int PurgeModuleBlocks(Database db)
        {
            int n = 0;
            try
            {
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                    foreach (ObjectId id in bt)
                    {
                        var btr = tr.GetObject(id, OpenMode.ForRead) as BlockTableRecord;
                        if (btr == null || btr.IsLayout) continue;
                        if (!btr.Name.StartsWith("RAILMOD_", StringComparison.OrdinalIgnoreCase)) continue;
                        if (btr.GetBlockReferenceIds(true, true).Count > 0) continue;
                        btr.UpgradeOpen();
                        btr.Erase();
                        n++;
                    }
                    tr.Commit();
                }
            }
            catch { }
            return n;
        }

        static int AskModule(Editor ed, string prompt)
        {
            for (int i = 0; i < ModuleGeom.Defs.Length; i++)
                ed.WriteMessage($"\n {i + 1,2}. {ModuleGeom.Defs[i].Name}{(ModuleGeom.Defs[i].Std ? "" : "   (특수)")}");
            var pio = new PromptIntegerOptions($"\n{prompt}: ") { LowerLimit = 1, UpperLimit = ModuleGeom.Defs.Length };
            PromptIntegerResult pir = ed.GetInteger(pio);
            return pir.Status == PromptStatus.OK ? pir.Value - 1 : -1;
        }

        static bool AskDouble(Editor ed, string msg, ref double value)
        {
            var pdo = new PromptDoubleOptions($"{msg} <{ModuleParams.F(value)}>: ")
            { AllowNone = true, UseDefaultValue = true, DefaultValue = value };
            PromptDoubleResult r = ed.GetDouble(pdo);
            if (r.Status == PromptStatus.None) return true;      // Enter = 기존값 유지
            if (r.Status != PromptStatus.OK) return false;
            value = r.Value;
            return true;
        }


        [CommandMethod("RAILMODTEST")]
        public void RailModTest()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Database db = doc.Database;
            int n = ModuleGeom.Defs.Length;
            for (int i = 0; i < n; i++)
                PlaceAt(db, i, new Point3d(i * 12000.0, 0, 0), 450, 1000, 900, 45);
            var ids = new List<ObjectId>();
            for (int i = 0; i < n; i++)
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    ids.Add(RailFactory.PlaceModule(db, tr, new Point3d(i * 12000.0, 40000.0, 0), i, 450, 1000, 900, 45));
                    tr.Commit();
                }
            for (int i = 0; i < ids.Count; i++)
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    var br = (BlockReference)tr.GetObject(ids[i], OpenMode.ForWrite);
                    RailFactory.SetModuleParams(tr, br, 600, 500, 1600, 30);
                    tr.Commit();
                }
            doc.Editor.WriteMessage($"\nRAILMODTEST: 모듈 {n}종 × 2세트 생성(2세트는 R600·L500·W1600·A30 으로 재생성).");
        }

        // 레일 탭 부품(RAILPART, kind6) 폭 그립이 형상의 실제 양 끝에 오는지 확인
        [CommandMethod("RAILPARTGRIPTEST")]
        public void RailPartGripTest()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            double[] widths = { 0, 900, 1150, 1350, 2000 };   // 0 = 그 패밀리의 기본 폭
            for (int f = 0; f < Rail34Geom.PartFam.Length; f++)
            {
                foreach (double w in widths)
                {
                    double ww = w <= 0 ? Rail34Geom.PartFamG[f] : w;
                    if (f >= 4 && w > 0 && w < 200) continue;
                    ObjectId id;
                    using (Transaction tr = db.TransactionManager.StartTransaction())
                    { id = RailFactory.CreateRail(db, tr, new Point3d(f * 9000.0, w * 6, 0), 0, f, 6, ww, 2); tr.Commit(); }

                    using (Transaction tr = db.TransactionManager.StartTransaction())
                    {
                        var br = (BlockReference)tr.GetObject(id, OpenMode.ForRead);
                        Point3d lp, rp;
                        bool ok = RailGripOverrule.EndPointsX(br, out lp, out rp);
                        // 형상 경계와 비교
                        var ext = br.GeometricExtents;
                        double gx0 = ext.MinPoint.X - br.Position.X, gx1 = ext.MaxPoint.X - br.Position.X;
                        ed.WriteMessage($"\n  {Rail34Geom.PartFam[f],-22} W={ww,6:0} 그립 좌({lp.X,7:0.#},{lp.Y,6:0.#}) 우({rp.X,7:0.#},{rp.Y,6:0.#})"
                                      + $"  형상 x {gx0:0.#}~{gx1:0.#}  {(ok ? "" : "★계산 실패")}");
                        tr.Commit();
                    }
                }
            }
            ed.WriteMessage("\nRAILPARTGRIPTEST 완료.");
        }

        // 접속구(그립이 생기는 끝점) 개수 확인
        [CommandMethod("RAILMODPORTTEST")]
        public void RailModPortTest()
        {
            Editor ed = Application.DocumentManager.MdiActiveDocument.Editor;
            for (int i = 0; i < ModuleGeom.Defs.Length; i++)
            {
                var ports = ModuleGeom.Ports(i, 450, 1000, 900, 45);
                string s = "";
                foreach (Point3d p in ports) s += $" ({p.X:0},{p.Y:0})";
                ed.WriteMessage($"\n  {ModuleGeom.Defs[i].Name,-15} 접속구 {ports.Count}개:{s}");
            }
            ed.WriteMessage("\nRAILMODPORTTEST 완료.");
        }

        [CommandMethod("RAILMODJOINTEST")]
        public void RailModJoinTest()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            double R = 450, L = 1000, W = 900, A = 45;

            bool jA = PlaceAt(db, 0, new Point3d(0, 0, 0), R, L, W, A);
            Point3d aFar = new Point3d(-(R + L), L + R, 0);
            bool jB = PlaceAt(db, 2, new Point3d(aFar.X + 300, aFar.Y - 300, 0), R, L, W, A);
            bool jC = PlaceAt(db, 0, new Point3d(60000, 0, 0), R, L, W, A);
            bool jD = PlaceAt(db, 0, new Point3d(90000, 0, 0), 600, L, W, A);
            ed.WriteMessage($"\n접합 결과 A={jA} B={jB} C={jC} D={jD} (B 만 true 여야 정상)");

            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                foreach (ObjectId id in ms)
                {
                    var br = tr.GetObject(id, OpenMode.ForRead) as BlockReference;
                    if (br == null) continue;
                    if (Math.Abs(br.Position.X - 90000) < 1.0) { br.UpgradeOpen(); br.Erase(); }
                }
                tr.Commit();
            }
            int purged = PurgeModuleBlocks(db);
            ed.WriteMessage($"\nRAILMODJOINTEST: D 삭제 후 블록 정의 {purged}개 정리(1 이어야 정상).");
        }
            // 파라미터 일괄 적용·추출 검증: 파라미터 저장 → 15종 배치 → 추출(모듈 XData) → 새 파라미터로 일괄 적용
        [CommandMethod("RAILMODPARAMTEST")]
        public void RailModParamTest()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            var p = new ModuleParams.P { R = 450, L = 200, W1 = 900, W2 = 1350, A = 45, M1 = 150, M2 = 520 };
            ModuleParams.Set(db, p);
            var back = ModuleParams.Get(db);
            ed.WriteMessage($"\n저장·읽기: {back.Digest()} ({(back.W2 == 1350 ? "정상" : "오류")})");
            for (int i = 0; i < ModuleGeom.Defs.Length; i++)
                PlaceAt(db, i, new Point3d(i * 12000.0, 200000.0, 0), p.R, p.L, i % 2 == 0 ? p.W1 : p.W2, p.A);
            var res = ModuleParamExtractor.Run(db, new ModuleParams.P(), null);
            ed.WriteMessage($"\n추출: {res.P.Digest()}\n  {res.Summary.Replace("\n", "\n  ")}");
            var p2 = p.Clone(); p2.R = 480; p2.L = 300; p2.W1 = 960; p2.W2 = 1440;
            int n = ApplyAll(doc, p, p2, null);
            var res2 = ModuleParamExtractor.Run(db, new ModuleParams.P(), null);
            ed.WriteMessage($"\n일괄 적용 {n}개 후 추출: {res2.P.Digest()}");
        }
    }

    // 리본 모듈 버튼 → 그 모듈을 현재 파라미터로 배치
    public class ModulePlaceHandler : System.Windows.Input.ICommand
    {
        readonly int _mi;
        public ModulePlaceHandler(int mi) { _mi = mi; }
        public event System.EventHandler CanExecuteChanged { add { } remove { } }
        public bool CanExecute(object p) => true;
        public void Execute(object p)
        {
            ModuleCommands.PendingModule = _mi;
            Document doc = Application.DocumentManager.MdiActiveDocument;
            if (doc != null) doc.SendStringToExecute("RAILMOD ", true, false, false);   // 명령 줄에 명령 이름을 찍지 않는다
        }
    }

    // "Module" 탭
    //  · [파라미터] : 파라미터 설정 / 도면에서 추출 / 도면 모듈에 일괄 적용 + 현재 값 표시
    //  · [표준 분기] [특수 분기] : 모듈 15종 — 누르면 현재 파라미터로 바로 배치
    //  · [편집] : 모듈 삭제
    public static class ModuleRibbon
    {
        const string TAB_ID = "RAILPLUGIN_MODULE_TAB";

        static Autodesk.Windows.RibbonLabel _paramLabel;
        static Autodesk.Windows.RibbonButton _widthButton;
        static bool _hooked;

        public static void Ensure()
        {
            try
            {
                var rc = Autodesk.Windows.ComponentManager.Ribbon;
                if (rc == null) return;
                foreach (Autodesk.Windows.RibbonTab t in rc.Tabs)
                    if (t.Id == TAB_ID) return;                 // 멱등

                var tab = new Autodesk.Windows.RibbonTab { Title = "Module", Id = TAB_ID };

                var srcP = new Autodesk.Windows.RibbonPanelSource { Title = "파라미터" };
                srcP.Items.Add(MakeCmdButton("파라미터\n설정", "RAILMODPARAM",
                    "R·L·W1·W2·A·M1·M2 를 한 번 정하면 모든 모듈에 형상에 맞게 적용됩니다(도면에 저장)"));
                srcP.Items.Add(MakeCmdButton("도면에서\n추출", "RAILMODEXTRACT",
                    "선·호 도면(또는 모듈 도면)을 분석해 R·W1·W2·A 를 뽑아 파라미터로 적용합니다"));
                srcP.Items.Add(MakeCmdButton("도면 모듈에\n일괄 적용", "RAILMODAPPLY",
                    "도면에 이미 그린 모든 모듈을 현재 파라미터로 다시 만듭니다"));
                _widthButton = MakeCmdButton("폭\nW1", "RAILMODW",
                    "폭을 쓰는 모듈(U, DOUBLE BRANCH, U BRANCH, N, BY PASS, S)을 W1 / W2 중 어느 폭으로 배치할지 전환합니다. 배치할 때는 묻지 않습니다");
                srcP.Items.Add(_widthButton);
                _paramLabel = new Autodesk.Windows.RibbonLabel { Text = "" };
                srcP.Items.Add(new Autodesk.Windows.RibbonRowBreak());
                srcP.Items.Add(_paramLabel);
                tab.Panels.Add(new Autodesk.Windows.RibbonPanel { Source = srcP });

                var srcStd = new Autodesk.Windows.RibbonPanelSource { Title = "표준 분기" };
                var srcSpc = new Autodesk.Windows.RibbonPanelSource { Title = "특수 분기" };
                for (int i = 0; i < ModuleGeom.Defs.Length; i++)
                    (ModuleGeom.Defs[i].Std ? srcStd : srcSpc).Items.Add(MakeModuleButton(i));
                tab.Panels.Add(new Autodesk.Windows.RibbonPanel { Source = srcStd });
                tab.Panels.Add(new Autodesk.Windows.RibbonPanel { Source = srcSpc });

                var srcE = new Autodesk.Windows.RibbonPanelSource { Title = "편집" };
                srcE.Items.Add(MakeCmdButton("선·호 →\n모듈 치환", "RAILMODCONV",
                    "선·호로 그린 도면을 도면 파라미터 한 세트로 모듈로 바꾼 새 도면(_modules.dxf)을 엽니다. 안 맞는 곳은 흰색 선·호로 남깁니다"));
                srcE.Items.Add(MakeCmdButton("모듈\n삭제", "RAILMODDEL", "선택한 모듈을 지우고 안 쓰는 블록 정의를 정리합니다"));
                srcE.Items.Add(MakeCmdButton("겹침\n검사", "RAILMODOVERLAP",
                    "서로 겹쳐 그려진 모듈을 빨간색으로 표시하고, 겹침이 풀린 모듈은 원래 색으로 되돌립니다. 모듈을 놓거나 옮길 때도 자동으로 검사합니다"));
                tab.Panels.Add(new Autodesk.Windows.RibbonPanel { Source = srcE });

                rc.Tabs.Add(tab);
                RefreshParam();
                HookDocumentEvents();
            }
            catch { }
        }

        static void HookDocumentEvents()
        {
            if (_hooked) return;
            try
            {
                Application.DocumentManager.DocumentActivated += (s, e) => RefreshParam();
                Application.DocumentManager.DocumentCreated += (s, e) => RefreshParam();
                _hooked = true;
            }
            catch { }
        }

        /// <summary>리본의 현재 파라미터 표시를 활성 도면 값으로 갱신.</summary>
        public static void RefreshParam()
        {
            try
            {
                if (_paramLabel == null) return;
                Document doc = Application.DocumentManager.MdiActiveDocument;
                _paramLabel.Text = doc == null ? "" : "현재: " + ModuleParams.Get(doc.Database).Digest();
                if (_widthButton != null)
                {
                    string wk = ModuleCommands.UseW2 ? "W2" : "W1";
                    if (doc == null) _widthButton.Text = "폭\n" + wk;
                    else
                    {
                        var p = ModuleParams.Get(doc.Database);
                        _widthButton.Text = "폭 " + wk + "\n" + ModuleParams.F(ModuleCommands.UseW2 ? p.W2 : p.W1);
                    }
                }
            }
            catch { }
        }

        public static void Remove()
        {
            try
            {
                var rc = Autodesk.Windows.ComponentManager.Ribbon;
                if (rc == null) return;
                Autodesk.Windows.RibbonTab found = null;
                foreach (Autodesk.Windows.RibbonTab t in rc.Tabs)
                    if (t.Id == TAB_ID) { found = t; break; }
                if (found != null) rc.Tabs.Remove(found);
                _paramLabel = null;
                _widthButton = null;
            }
            catch { }
        }

        static Autodesk.Windows.RibbonButton MakeModuleButton(int mi)
        {
            var def = ModuleGeom.Defs[mi];
            string uses = "R, L" + (def.UsesW ? ", 폭(리본에서 고른 W1/W2)" : "") + (def.UsesA ? ", A" : "");
            var b = new Autodesk.Windows.RibbonButton
            {
                Text = def.Label,
                ShowText = true,
                ShowImage = true,
                Size = Autodesk.Windows.RibbonItemSize.Large,
                Orientation = System.Windows.Controls.Orientation.Vertical,
                ToolTip = def.Name + " (" + (def.Std ? "표준 분기" : "특수 분기") + ")\n"
                          + "현재 파라미터로 배치 — 쓰는 항목: " + uses,
                CommandHandler = new ModulePlaceHandler(mi),
            };
            try { b.LargeImage = MakeIcon(mi, 32); b.Image = MakeIcon(mi, 16); }
            catch { b.ShowImage = false; }
            return b;
        }

        static Autodesk.Windows.RibbonButton MakeCmdButton(string text, string cmd, string tip)
            => new Autodesk.Windows.RibbonButton
            {
                Text = text,
                ShowText = true,
                ShowImage = false,
                Size = Autodesk.Windows.RibbonItemSize.Large,
                Orientation = System.Windows.Controls.Orientation.Vertical,
                ToolTip = tip + " (" + cmd + ")",
                CommandHandler = new RailCmdHandler(cmd),
            };

        // 모듈 형상을 그대로 축소해 아이콘으로 그린다 (형상 = 버튼 그림이라 목록에서 바로 구분된다).
        //  ★직선(L)을 짧게 잡는다: 실제 비율(L=1000)로 그리면 세로로 길쭉해져 32px 에서 선 몇 개로만 보인다.
        //   L=250 이면 대부분 정사각형에 가까워져 32px 에서도 형상이 구분된다.
        static System.Windows.Media.ImageSource MakeIcon(int mi, int sz)
        {
            var ents = ModuleGeom.Build(mi, 450, 250, 900, 45);
            double x0 = double.MaxValue, y0 = double.MaxValue, x1 = double.MinValue, y1 = double.MinValue;
            var polys = new List<List<System.Windows.Point>>();
            foreach (Entity e in ents)
            {
                var pts = new List<System.Windows.Point>();
                var ln = e as Line;
                if (ln != null)
                {
                    pts.Add(new System.Windows.Point(ln.StartPoint.X, ln.StartPoint.Y));
                    pts.Add(new System.Windows.Point(ln.EndPoint.X, ln.EndPoint.Y));
                }
                else
                {
                    var ac = e as Arc;
                    if (ac == null) continue;
                    // ★CAD 는 호 각도를 0~2π 로 정규화한다 → 끝각이 시작각보다 작을 수 있다.
                    //  그대로 보간하면 반대쪽(큰 쪽) 호를 그려 형상이 뒤집힌다. 한 바퀴 더해 보정.
                    double a0 = ac.StartAngle, a1 = ac.EndAngle;
                    if (a1 <= a0) a1 += 2.0 * Math.PI;
                    for (int k = 0; k <= 24; k++)
                    {
                        double t = a0 + (a1 - a0) * k / 24.0;
                        pts.Add(new System.Windows.Point(ac.Center.X + ac.Radius * Math.Cos(t),
                                                         ac.Center.Y + ac.Radius * Math.Sin(t)));
                    }
                }
                foreach (var p in pts)
                {
                    if (p.X < x0) x0 = p.X; if (p.X > x1) x1 = p.X;
                    if (p.Y < y0) y0 = p.Y; if (p.Y > y1) y1 = p.Y;
                }
                polys.Add(pts);
            }
            foreach (Entity e in ents) e.Dispose();

            double wSpan = Math.Max(x1 - x0, 1.0), hSpan = Math.Max(y1 - y0, 1.0);
            double pad = sz * 0.1, avail = sz - 2 * pad;
            double s = Math.Min(avail / wSpan, avail / hSpan);
            double ox = pad + (avail - wSpan * s) / 2.0, oy = pad + (avail - hSpan * s) / 2.0;
            Func<System.Windows.Point, System.Windows.Point> map = p =>
                new System.Windows.Point(ox + (p.X - x0) * s, sz - (oy + (p.Y - y0) * s));   // 화면 Y 반전

            var pen = new System.Windows.Media.Pen(
                new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xE8, 0x9A, 0x3C)),
                Math.Max(1.6, sz / 12.0))
            { StartLineCap = System.Windows.Media.PenLineCap.Round, EndLineCap = System.Windows.Media.PenLineCap.Round };
            var dv = new System.Windows.Media.DrawingVisual();
            using (var dc = dv.RenderOpen())
                foreach (var poly in polys)
                    for (int k = 0; k + 1 < poly.Count; k++)
                        dc.DrawLine(pen, map(poly[k]), map(poly[k + 1]));

            var rtb = new System.Windows.Media.Imaging.RenderTargetBitmap(
                sz, sz, 96, 96, System.Windows.Media.PixelFormats.Pbgra32);
            rtb.Render(dv);
            rtb.Freeze();
            return rtb;
        }
    }
}
