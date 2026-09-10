using System;
using System.Collections.Generic;
using System.Globalization;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.EditorInput;

[assembly: CommandClass(typeof(RailPlugin.ModuleCommands))]

namespace RailPlugin
{
    // 규격 목록 — "규격 설정" 에서 값을 정할 때마다 항목이 하나 생기고,
    // 그 항목이 그대로 리본 [모듈 생성] 패널의 버튼이 된다.
    //  · 도면(문서)마다 따로 관리한다 → 새 도면을 만들면 목록이 비어 있다.
    //  · 파일로 저장하지 않는다 → CAD 를 새로 켜도 초기화된다.
    public static class ModuleSpec
    {
        public sealed class Entry
        {
            public int Idx;
            public double R, L, W, A;
            public Entry(int idx, double r, double l, double w, double a)
            { Idx = idx; R = r; L = l; W = w; A = a; }

            public bool SameAs(Entry o)
                => o != null && o.Idx == Idx && Eq(o.R, R) && Eq(o.L, L) && Eq(o.W, W) && Eq(o.A, A);

            static bool Eq(double x, double y) => Math.Abs(x - y) < 1e-6;

            // 버튼 두 번째 줄 / 툴팁에 쓰는 규격 표기 — 그 모듈이 쓰는 항목만
            public string Digest()
            {
                var d = ModuleGeom.Defs[Idx];
                string s = "R" + F(R) + " L" + F(L);
                if (d.UsesW) s += " W" + F(W);
                if (d.UsesA) s += " A" + F(A);
                return s;
            }
        }

        // 문서별 목록. 문서가 닫히면 항목은 그대로 남지만(참조만 유지) 새 문서는 항상 빈 목록이다.
        static readonly Dictionary<Document, List<Entry>> _byDoc = new Dictionary<Document, List<Entry>>();

        static List<Entry> ListFor(Document doc)
        {
            if (doc == null) return new List<Entry>();
            List<Entry> list;
            if (!_byDoc.TryGetValue(doc, out list)) { list = new List<Entry>(); _byDoc[doc] = list; }
            return list;
        }

        // CAD 런타임을 못 쓰는 상황(문서 없음 등)에서도 죽지 않게 별도 메서드로 분리해 호출한다.
        //  (같은 메서드 안에 두면 JIT 단계에서 나는 예외를 try 로 잡을 수 없다.)
        [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
        static Document ActiveDoc() => Application.DocumentManager.MdiActiveDocument;

        public static List<Entry> Current
        {
            get
            {
                try { return ListFor(ActiveDoc()); }
                catch { return new List<Entry>(); }
            }
        }

        /// <summary>그 모듈로 마지막에 정한 규격(대화상자 초기값용). 없으면 null.</summary>
        public static Entry Last(int idx)
        {
            var list = Current;
            for (int i = list.Count - 1; i >= 0; i--)
                if (list[i].Idx == idx) return list[i];
            return null;
        }

        /// <summary>규격 항목을 추가한다. 이미 같은 규격이 있으면 그걸 돌려준다.</summary>
        public static Entry Add(int idx, double r, double l, double w, double a)
        {
            ModuleGeom.Clamp(idx, ref r, ref l, ref w, ref a);
            var e = new Entry(idx, r, l, w, a);
            var list = Current;
            foreach (Entry x in list) if (x.SameAs(e)) return x;
            list.Add(e);
            return e;
        }

        /// <summary>규격 항목(=[모듈 생성] 버튼) 하나를 목록에서 뺀다.</summary>
        public static bool Remove(Entry e)
        {
            if (e == null) return false;
            var list = Current;
            for (int i = 0; i < list.Count; i++)
                if (ReferenceEquals(list[i], e) || list[i].SameAs(e)) { list.RemoveAt(i); return true; }
            return false;
        }

        public static void Clear() { Current.Clear(); }

        public static string F(double v) => v.ToString("0.##", CultureInfo.InvariantCulture);

        public static bool TryParse(string text, out double value)
        {
            text = (text ?? "").Trim();
            return double.TryParse(text, NumberStyles.Float, CultureInfo.CurrentCulture, out value)
                || double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out value);
        }
    }

    // 규격 설정 대화상자 — XAML 없이 코드로만 구성(포팅 스크립트가 .cs 만 옮기므로 ZWCAD 판에도 그대로 간다).
    //  대상 모듈이 실제로 쓰는 항목만 보여준다: R·L 공통, W·A 는 해당 모듈만. 초기값은 0(아직 정한 규격이 없을 때).
    public class ModuleSpecDialog : System.Windows.Window
    {
        readonly int _idx;
        readonly System.Windows.Controls.TextBox _r, _l, _w, _a;

        public double ValR, ValL, ValW, ValA;

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

        // 현재 도면에서 그 모듈로 마지막에 정한 규격을 초기값으로 (없으면 전부 0)
        public ModuleSpecDialog(int idx) : this(idx, ModuleSpec.Last(idx)) { }

        ModuleSpecDialog(int idx, ModuleSpec.Entry last)
            : this(idx, last != null ? last.R : 0.0, last != null ? last.L : 0.0,
                        last != null ? last.W : 0.0, last != null ? last.A : 0.0) { }

        /// <summary>초기값을 직접 주는 생성자(미리보기·테스트용 — CAD 문서 없이도 만들 수 있다).</summary>
        public ModuleSpecDialog(int idx, double r0, double l0, double w0, double a0)
        {
            _idx = idx;
            var def = ModuleGeom.Defs[idx];

            Title = def.Name + " — 규격 설정";
            Width = 440;
            SizeToContent = System.Windows.SizeToContent.Height;
            ResizeMode = System.Windows.ResizeMode.NoResize;
            WindowStartupLocation = System.Windows.WindowStartupLocation.CenterScreen;
            Background = Bg;
            Foreground = Fg;
            FontFamily = new System.Windows.Media.FontFamily("Malgun Gothic, Segoe UI");
            FontSize = 13;
            ShowInTaskbar = false;

            var root = new System.Windows.Controls.StackPanel { Margin = new System.Windows.Thickness(18) };

            var grid = new System.Windows.Controls.Grid();
            grid.ColumnDefinitions.Add(new System.Windows.Controls.ColumnDefinition());
            grid.ColumnDefinitions.Add(new System.Windows.Controls.ColumnDefinition { Width = new System.Windows.GridLength(14) });
            grid.ColumnDefinitions.Add(new System.Windows.Controls.ColumnDefinition());

            var fields = new List<Tuple<string, double>> {
                Tuple.Create("호 반지름 R (mm)", r0),
                Tuple.Create("직선 길이 L (mm)", l0),
            };
            if (def.UsesW) fields.Add(Tuple.Create("레일 간격 W (mm)", w0));
            if (def.UsesA) fields.Add(Tuple.Create("대각 각도 A (°)", a0));

            var boxes = new List<System.Windows.Controls.TextBox>();
            for (int i = 0; i < fields.Count; i++)
            {
                int row = i / 2, col = (i % 2) * 2;
                while (grid.RowDefinitions.Count <= row)
                    grid.RowDefinitions.Add(new System.Windows.Controls.RowDefinition());

                var cell = new System.Windows.Controls.StackPanel { Margin = new System.Windows.Thickness(0, 0, 0, 14) };
                cell.Children.Add(new System.Windows.Controls.TextBlock
                {
                    Text = fields[i].Item1,
                    Foreground = Muted,
                    Margin = new System.Windows.Thickness(2, 0, 0, 5),
                });
                var tb = new System.Windows.Controls.TextBox
                {
                    Text = ModuleSpec.F(fields[i].Item2),
                    Background = Card,
                    Foreground = Fg,
                    BorderBrush = Line,
                    BorderThickness = new System.Windows.Thickness(1),
                    Padding = new System.Windows.Thickness(8, 6, 8, 6),
                    CaretBrush = Fg,
                };
                cell.Children.Add(tb);
                boxes.Add(tb);
                System.Windows.Controls.Grid.SetRow(cell, row);
                System.Windows.Controls.Grid.SetColumn(cell, col);
                grid.Children.Add(cell);
            }
            _r = boxes[0];
            _l = boxes[1];
            _w = def.UsesW ? boxes[2] : null;
            _a = def.UsesA ? boxes[def.UsesW ? 3 : 2] : null;
            root.Children.Add(grid);

            root.Children.Add(new System.Windows.Controls.TextBlock
            {
                Text = "※ [적용] 하면 이 규격이 [모듈 생성] 에 추가되고 바로 배치로 넘어갑니다."
                       + (def.UsesW || def.UsesA ? "  하한: " + LimitText(def) : ""),
                Foreground = Muted,
                FontSize = 11,
                TextWrapping = System.Windows.TextWrapping.Wrap,
                Margin = new System.Windows.Thickness(2, 0, 0, 16),
            });

            var bar = new System.Windows.Controls.StackPanel
            {
                Orientation = System.Windows.Controls.Orientation.Horizontal,
                HorizontalAlignment = System.Windows.HorizontalAlignment.Right,
            };
            var cancel = MakeButton("취소", Card, Fg);
            cancel.IsCancel = true;
            cancel.Click += (s, e) => { DialogResult = false; };
            var ok = MakeButton("적용", Accent, System.Windows.Media.Brushes.White);
            ok.IsDefault = true;
            ok.Click += OnApply;
            bar.Children.Add(cancel);
            bar.Children.Add(ok);
            root.Children.Add(bar);

            Content = root;
            Loaded += (s, e) => { _r.Focus(); _r.SelectAll(); };
        }

        static string LimitText(ModuleGeom.Def def)
            => def.UsesA ? "0 < A < 90, W ≥ 2R(1−cos A)" : "W ≥ 2R";

        static System.Windows.Controls.Button MakeButton(string text, System.Windows.Media.Brush bg, System.Windows.Media.Brush fg)
            => new System.Windows.Controls.Button
            {
                Content = text,
                Background = bg,
                Foreground = fg,
                BorderBrush = Line,
                BorderThickness = new System.Windows.Thickness(1),
                Padding = new System.Windows.Thickness(22, 7, 22, 7),
                Margin = new System.Windows.Thickness(8, 0, 0, 0),
                MinWidth = 92,
            };

        void OnApply(object sender, System.Windows.RoutedEventArgs e)
        {
            var def = ModuleGeom.Defs[_idx];
            double r = 0, l = 0, w = 0, a = 0;
            if (!Read(_r, ref r, "호 반지름 R")) return;
            if (!Read(_l, ref l, "직선 길이 L")) return;
            if (def.UsesW && !Read(_w, ref w, "레일 간격 W")) return;
            if (def.UsesA && !Read(_a, ref a, "대각 각도 A")) return;

            if (r <= 0) { Warn("호 반지름 R 은 0 보다 커야 합니다.", _r); return; }
            if (l < 0) { Warn("직선 길이 L 은 0 이상이어야 합니다.", _l); return; }
            if (def.UsesA && a <= 0) { Warn("대각 각도 A 는 0 보다 커야 합니다.", _a); return; }

            ValR = r; ValL = l; ValW = w; ValA = a;
            DialogResult = true;
        }

        void Warn(string msg, System.Windows.Controls.TextBox box)
        {
            System.Windows.MessageBox.Show(this, msg, "규격 설정",
                System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Warning);
            if (box != null) { box.Focus(); box.SelectAll(); }
        }

        bool Read(System.Windows.Controls.TextBox box, ref double value, string label)
        {
            if (box == null) return true;
            double v;
            if (!ModuleSpec.TryParse(box.Text, out v)) { Warn(label + " 값이 숫자가 아닙니다.", box); return false; }
            value = v;
            return true;
        }

        /// <summary>대화상자를 띄우고 입력값을 규격 목록에 추가한다. 반환 null = 취소/실패.</summary>
        public static ModuleSpec.Entry Open(int idx)
        {
            ModuleSpecDialog dlg;
            try { dlg = new ModuleSpecDialog(idx); }
            catch { return null; }                               // WPF 를 못 쓰는 환경 → RAILMODP 로 안내
            bool? r = null;
            try { r = Application.ShowModalWindow(dlg); }        // CAD 창을 부모로 (권장 경로)
            catch { try { r = dlg.ShowDialog(); } catch { } }    // 실패 시 순수 WPF 모달
            if (r != true) return null;
            return ModuleSpec.Add(idx, dlg.ValR, dlg.ValL, dlg.ValW, dlg.ValA);
        }
    }

    // [모듈 생성] 목록 관리 대화상자 — 만들어 둔 규격(버튼)을 골라 지운다.
    public class ModuleListDialog : System.Windows.Window
    {
        readonly System.Windows.Controls.ListBox _list;

        static readonly System.Windows.Media.Brush Bg = B(0x2B, 0x2E, 0x33);
        static readonly System.Windows.Media.Brush Card = B(0x33, 0x37, 0x3D);
        static readonly System.Windows.Media.Brush Fg = B(0xE6, 0xE8, 0xEB);
        static readonly System.Windows.Media.Brush Muted = B(0x9A, 0xA1, 0xAA);
        static readonly System.Windows.Media.Brush Line = B(0x4A, 0x50, 0x58);
        static readonly System.Windows.Media.Brush Danger = B(0xC0, 0x45, 0x45);

        static System.Windows.Media.Brush B(byte r, byte g, byte b)
        {
            var br = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(r, g, b));
            br.Freeze();
            return br;
        }

        public ModuleListDialog(List<ModuleSpec.Entry> entries)
        {
            Title = "모듈 생성 목록 — 규격 삭제";
            Width = 460;
            SizeToContent = System.Windows.SizeToContent.Height;
            ResizeMode = System.Windows.ResizeMode.NoResize;
            WindowStartupLocation = System.Windows.WindowStartupLocation.CenterScreen;
            Background = Bg;
            Foreground = Fg;
            FontFamily = new System.Windows.Media.FontFamily("Malgun Gothic, Segoe UI");
            FontSize = 13;
            ShowInTaskbar = false;

            var root = new System.Windows.Controls.StackPanel { Margin = new System.Windows.Thickness(18) };
            root.Children.Add(new System.Windows.Controls.TextBlock
            {
                Text = "지울 규격을 고르세요. [모듈 생성] 에서 그 버튼만 없어지고, 도면에 이미 그린 모듈은 그대로입니다.",
                Foreground = Muted,
                FontSize = 11,
                TextWrapping = System.Windows.TextWrapping.Wrap,
                Margin = new System.Windows.Thickness(2, 0, 0, 10),
            });

            _list = new System.Windows.Controls.ListBox
            {
                Background = Card,
                Foreground = Fg,
                BorderBrush = Line,
                BorderThickness = new System.Windows.Thickness(1),
                Height = 190,
                SelectionMode = System.Windows.Controls.SelectionMode.Extended,
            };
            foreach (ModuleSpec.Entry en in entries)
                _list.Items.Add(new System.Windows.Controls.ListBoxItem
                {
                    Content = ModuleGeom.Defs[en.Idx].Name + "   ·   " + en.Digest(),
                    Tag = en,
                    Foreground = Fg,
                    Padding = new System.Windows.Thickness(8, 5, 8, 5),
                });
            if (_list.Items.Count > 0) _list.SelectedIndex = 0;
            root.Children.Add(_list);

            var bar = new System.Windows.Controls.StackPanel
            {
                Orientation = System.Windows.Controls.Orientation.Horizontal,
                HorizontalAlignment = System.Windows.HorizontalAlignment.Right,
                Margin = new System.Windows.Thickness(0, 16, 0, 0),
            };
            var close = Btn("닫기", Card, Fg);
            close.IsCancel = true;
            close.Click += (s, e) => { DialogResult = false; };
            var del = Btn("삭제", Danger, System.Windows.Media.Brushes.White);
            del.IsDefault = true;
            del.Click += OnDelete;
            bar.Children.Add(close);
            bar.Children.Add(del);
            root.Children.Add(bar);

            Content = root;
        }

        static System.Windows.Controls.Button Btn(string text, System.Windows.Media.Brush bg, System.Windows.Media.Brush fg)
            => new System.Windows.Controls.Button
            {
                Content = text,
                Background = bg,
                Foreground = fg,
                BorderBrush = Line,
                BorderThickness = new System.Windows.Thickness(1),
                Padding = new System.Windows.Thickness(22, 7, 22, 7),
                Margin = new System.Windows.Thickness(8, 0, 0, 0),
                MinWidth = 92,
            };

        public int Removed { get; private set; }

        void OnDelete(object sender, System.Windows.RoutedEventArgs e)
        {
            var picked = new List<System.Windows.Controls.ListBoxItem>();
            foreach (object o in _list.SelectedItems)
            {
                var it = o as System.Windows.Controls.ListBoxItem;
                if (it != null) picked.Add(it);
            }
            if (picked.Count == 0) { DialogResult = false; return; }
            foreach (var it in picked)
            {
                if (ModuleSpec.Remove(it.Tag as ModuleSpec.Entry)) Removed++;
                _list.Items.Remove(it);
            }
            DialogResult = true;
        }

        /// <summary>목록 대화상자를 띄운다. 반환 = 지운 개수(-1 은 열지 못함).</summary>
        public static int Open()
        {
            var entries = new List<ModuleSpec.Entry>(ModuleSpec.Current);
            ModuleListDialog dlg;
            try { dlg = new ModuleListDialog(entries); }
            catch { return -1; }
            try { Application.ShowModalWindow(dlg); }
            catch { try { dlg.ShowDialog(); } catch { return -1; } }
            return dlg.Removed;
        }
    }

    public class ModuleCommands
    {
        // 리본 버튼 → 명령 브릿지
        public static int PendingModule = -1;                  // 규격 설정할 모듈
        public static ModuleSpec.Entry PendingEntry = null;    // 생성할 규격 항목

        // 배치할 때 기존 끝점에 달라붙는 거리 (mm). 객체 스냅으로 정확히 찍으면 거리 0 이라 항상 붙는다.
        public const double JOIN_TOL = 500.0;

        // 규격 설정: 대화상자에서 값을 정하면 [모듈 생성] 에 항목이 추가되고, 이어서 바로 배치한다.
        [CommandMethod("RAILMODSET")]
        public void RailModSet()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            int mi = PendingModule; PendingModule = -1;
            if (mi < 0 || mi >= ModuleGeom.Defs.Length) { mi = AskModule(ed, "규격을 설정할 모듈 번호"); if (mi < 0) return; }

            ModuleSpec.Entry entry = ModuleSpecDialog.Open(mi);
            if (entry == null)
            {
                ed.WriteMessage("\nRAILMODSET: 취소됨(대화상자를 못 열면 RAILMODP 로 입력하세요).");
                return;
            }
            ModuleRibbon.RefreshMake();
            ed.WriteMessage($"\nRAILMODSET: {ModuleGeom.Defs[mi].Name} — {entry.Digest()} (모듈 생성에 추가됨)");
            Place(doc, entry);
        }

        // 저장된 규격으로 배치 (리본 [모듈 생성] 버튼)
        [CommandMethod("RAILMOD")]
        public void RailMod()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            ModuleSpec.Entry entry = PendingEntry; PendingEntry = null;
            if (entry == null)
            {
                int mi = AskModule(ed, "모듈 번호");
                if (mi < 0) return;
                entry = ModuleSpec.Last(mi);
                if (entry == null)
                {
                    ed.WriteMessage($"\n{ModuleGeom.Defs[mi].Name} 규격이 아직 없습니다. RAILMODSET(규격 설정) 을 먼저 하세요.");
                    return;
                }
            }
            Place(doc, entry);
        }

        // 공통 배치 — 위치를 찍으면 기존 모듈/레일의 끝점에 접속구가 달라붙는다.
        static void Place(Document doc, ModuleSpec.Entry entry)
        {
            Editor ed = doc.Editor; Database db = doc.Database;
            var def = ModuleGeom.Defs[entry.Idx];
            ed.WriteMessage($"\n{def.Name} 규격: {entry.Digest()}");
            PromptPointResult p0 = ed.GetPoint($"\n{def.Name} 접속 위치(기존 끝점에 자동으로 붙습니다): ");
            if (p0.Status != PromptStatus.OK) return;

            bool joined = PlaceAt(db, entry.Idx, p0.Value, entry.R, entry.L, entry.W, entry.A);
            ed.WriteMessage(joined
                ? $"\nRAILMOD: {def.Name} 생성 — 기존 끝점에 접합."
                : $"\nRAILMOD: {def.Name} 생성.");
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

        // 규격을 명령창으로 입력 (대화상자를 못 쓰는 환경·스크립트용)
        [CommandMethod("RAILMODP")]
        public void RailModP()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            int mi = AskModule(ed, "규격을 설정할 모듈 번호");
            if (mi < 0) return;

            var def = ModuleGeom.Defs[mi];
            var last = ModuleSpec.Last(mi);
            double r = last != null ? last.R : 0, l = last != null ? last.L : 0;
            double w = last != null ? last.W : 0, a = last != null ? last.A : 0;
            if (!AskDouble(ed, "\nR (호 반지름)", ref r)) return;
            if (!AskDouble(ed, "\nL (직선 길이)", ref l)) return;
            if (def.UsesW && !AskDouble(ed, "\nW (레일 간격)", ref w)) return;
            if (def.UsesA && !AskDouble(ed, "\nA (대각 각도, °)", ref a)) return;
            if (r <= 0) { ed.WriteMessage("\nR 은 0 보다 커야 합니다."); return; }
            if (def.UsesA && a <= 0) { ed.WriteMessage("\nA 는 0 보다 커야 합니다."); return; }

            var entry = ModuleSpec.Add(mi, r, l, w, a);
            ModuleRibbon.RefreshMake();
            ed.WriteMessage($"\nRAILMODP: {def.Name} — {entry.Digest()} (모듈 생성에 추가됨)");
        }

        // 이미 그린 모듈의 규격 변경 → 그 자리에서 다른 규격의 정의로 바꿔 끼운다
        [CommandMethod("RAILMODEDIT")]
        public void RailModEdit()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;

            var peo = new PromptEntityOptions("\n모듈 선택: ");
            peo.SetRejectMessage("\n기본 모듈(블록)만.");
            peo.AddAllowedClass(typeof(BlockReference), false);
            PromptEntityResult per = ed.GetEntity(peo);
            if (per.Status != PromptStatus.OK) return;

            int mi;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var br = (BlockReference)tr.GetObject(per.ObjectId, OpenMode.ForRead);
                if (RailFactory.GetKind(br) != 7) { ed.WriteMessage("\n기본 모듈이 아닙니다 (RAILMOD 로 만든 모듈만)."); return; }
                mi = RailFactory.GetCount(br);
                // 선택한 모듈의 현재 값을 대화상자 초기값으로 (목록에도 올려둔다)
                ModuleSpec.Add(mi, RailFactory.GetModR(br), RailFactory.GetLength(br),
                               RailFactory.GetWidth(br), RailFactory.GetModA(br));
                tr.Commit();
            }
            if (mi < 0 || mi >= ModuleGeom.Defs.Length) return;

            ModuleSpec.Entry entry = ModuleSpecDialog.Open(mi);
            if (entry == null) { ed.WriteMessage("\nRAILMODEDIT: 취소됨."); return; }
            ModuleRibbon.RefreshMake();

            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var br = (BlockReference)tr.GetObject(per.ObjectId, OpenMode.ForWrite);
                RailFactory.SetModuleParams(tr, br, entry.R, entry.L, entry.W, entry.A);
                tr.Commit();
            }
            ed.WriteMessage($"\nRAILMODEDIT: {ModuleGeom.Defs[mi].Name} — {entry.Digest()}");
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
                    if (br == null) { skipped++; continue; }
                    if (RailFactory.GetKind(br) != 7) { skipped++; continue; }
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

        // [모듈 생성] 목록에서 규격(버튼) 삭제 — 도면에 그린 모듈은 건드리지 않는다.
        [CommandMethod("RAILMODREMOVE")]
        public void RailModRemove()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            if (ModuleSpec.Current.Count == 0)
            {
                ed.WriteMessage("\nRAILMODREMOVE: [모듈 생성] 목록이 비어 있습니다.");
                return;
            }
            int n = ModuleListDialog.Open();
            if (n < 0) { ed.WriteMessage("\nRAILMODREMOVE: 대화상자를 열지 못했습니다."); return; }
            if (n == 0) { ed.WriteMessage("\nRAILMODREMOVE: 취소됨."); return; }
            ModuleRibbon.RefreshMake();
            ed.WriteMessage($"\nRAILMODREMOVE: 규격 {n}개를 [모듈 생성] 에서 지웠습니다.");
        }

        // 규격 목록 비우기 — [모듈 생성] 패널이 다시 빈 상태가 된다(도면의 모듈은 그대로).
        [CommandMethod("RAILMODCLEAR")]
        public void RailModClear()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            ModuleSpec.Clear();
            ModuleRibbon.RefreshMake();
            if (doc != null) doc.Editor.WriteMessage("\nRAILMODCLEAR: 규격 목록을 비웠습니다.");
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
            var pdo = new PromptDoubleOptions($"{msg} <{ModuleSpec.F(value)}>: ")
            { AllowNone = true, UseDefaultValue = true, DefaultValue = value };
            PromptDoubleResult r = ed.GetDouble(pdo);
            if (r.Status == PromptStatus.None) return true;      // Enter = 기존값 유지
            if (r.Status != PromptStatus.OK) return false;
            value = r.Value;
            return true;
        }

        // ── 헤드리스 검증용 ──────────────────────────────────────────────────
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

        // 규격 목록(추가·중복 제거·모듈별 마지막 값)과 그 규격으로의 생성 검증
        [CommandMethod("RAILMODSPECTEST")]
        public void RailModSpecTest()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor; Database db = doc.Database;
            ModuleSpec.Clear();
            ed.WriteMessage($"\n초기 규격 목록 개수: {ModuleSpec.Current.Count} (0 이어야 정상)");

            int n = ModuleGeom.Defs.Length;
            for (int i = 0; i < n; i++)
            {
                var e = ModuleSpec.Add(i, 400 + i * 20, 300 + i * 50, 1000 + i * 100, 20 + i * 3);
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    RailFactory.PlaceModule(db, tr, new Point3d(i * 12000.0, 80000.0, 0), i, e.R, e.L, e.W, e.A);
                    tr.Commit();
                }
            }
            ModuleSpec.Add(0, 400, 300, 1000, 20);                    // 같은 규격 → 추가되면 안 됨
            var extra = ModuleSpec.Add(0, 700, 300, 1000, 20);        // 규격이 다르면 → 추가돼야 함
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                RailFactory.PlaceModule(db, tr, new Point3d(0, 120000.0, 0), 0, extra.R, extra.L, extra.W, extra.A);
                tr.Commit();
            }
            ed.WriteMessage($"\nRAILMODSPECTEST: 규격 목록 {ModuleSpec.Current.Count}개 ({n + 1} 이어야 정상), 모듈 {n + 1}개 생성.");
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
    }

    // 리본 [규격 설정] 버튼 → 해당 모듈의 대화상자
    public class ModuleSpecHandler : System.Windows.Input.ICommand
    {
        readonly int _mi;
        public ModuleSpecHandler(int mi) { _mi = mi; }
        public event System.EventHandler CanExecuteChanged { add { } remove { } }
        public bool CanExecute(object p) => true;
        public void Execute(object p)
        {
            ModuleCommands.PendingModule = _mi;
            Document doc = Application.DocumentManager.MdiActiveDocument;
            if (doc != null) doc.SendStringToExecute("RAILMODSET ", true, false, true);
        }
    }

    // 리본 [모듈 생성] 버튼 → 그 규격 항목으로 배치
    public class ModuleMakeHandler : System.Windows.Input.ICommand
    {
        readonly ModuleSpec.Entry _entry;
        public ModuleMakeHandler(ModuleSpec.Entry entry) { _entry = entry; }
        public event System.EventHandler CanExecuteChanged { add { } remove { } }
        public bool CanExecute(object p) => true;
        public void Execute(object p)
        {
            ModuleCommands.PendingEntry = _entry;
            Document doc = Application.DocumentManager.MdiActiveDocument;
            if (doc != null) doc.SendStringToExecute("RAILMOD ", true, false, true);
        }
    }

    // "Module" 탭
    //  · [규격 설정] : 모듈 15종 버튼(항상 표시) → 규격 대화상자
    //  · [모듈 생성] : 처음엔 비어 있고, 규격을 정할 때마다 그 규격의 버튼이 하나씩 늘어난다
    //  · [편집]      : 규격 변경 / 모듈 삭제 / 규격 목록 비우기
    //  도면(문서)이 바뀌면 [모듈 생성] 목록도 그 도면 것으로 다시 그린다 → 새 도면은 빈 상태.
    public static class ModuleRibbon
    {
        const string TAB_ID = "RAILPLUGIN_MODULE_TAB";
        const int PER_ROW = 5;

        static Autodesk.Windows.RibbonPanelSource _makeSrc;   // [모듈 생성] 패널 (동적 갱신)
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

                // ① 규격 설정 — 모듈 15종 (고정). 표준/특수로 패널을 나눠 큰 버튼으로 배치한다.
                var srcStd = new Autodesk.Windows.RibbonPanelSource { Title = "규격 설정 · 표준 분기" };
                var srcSpc = new Autodesk.Windows.RibbonPanelSource { Title = "규격 설정 · 특수 분기" };
                for (int i = 0; i < ModuleGeom.Defs.Length; i++)
                    (ModuleGeom.Defs[i].Std ? srcStd : srcSpc).Items.Add(MakeSpecButton(i));
                tab.Panels.Add(new Autodesk.Windows.RibbonPanel { Source = srcStd });
                tab.Panels.Add(new Autodesk.Windows.RibbonPanel { Source = srcSpc });

                // ② 모듈 생성 — 규격을 정한 만큼만 (처음엔 비어 있음)
                _makeSrc = new Autodesk.Windows.RibbonPanelSource { Title = "모듈 생성" };
                tab.Panels.Add(new Autodesk.Windows.RibbonPanel { Source = _makeSrc });
                RefreshMake();

                // ③ 편집
                var srcE = new Autodesk.Windows.RibbonPanelSource { Title = "편집" };
                srcE.Items.Add(MakeCmdButton("규격\n변경", "RAILMODEDIT", "도면에 이미 그린 모듈을 골라 규격을 바꾼다"));
                srcE.Items.Add(MakeCmdButton("규격\n삭제", "RAILMODREMOVE", "[모듈 생성] 에 만들어 둔 규격(버튼)을 골라 지운다 — 도면의 모듈은 그대로"));
                srcE.Items.Add(MakeCmdButton("규격 목록\n비우기", "RAILMODCLEAR", "[모듈 생성] 목록을 통째로 비운다 — 도면의 모듈은 그대로"));
                tab.Panels.Add(new Autodesk.Windows.RibbonPanel { Source = srcE });

                rc.Tabs.Add(tab);
                HookDocumentEvents();
            }
            catch { }
        }

        // 도면을 새로 만들거나 전환하면 [모듈 생성] 을 그 도면의 목록으로 다시 그린다
        static void HookDocumentEvents()
        {
            if (_hooked) return;
            try
            {
                Application.DocumentManager.DocumentActivated += (s, e) => RefreshMake();
                Application.DocumentManager.DocumentCreated += (s, e) => RefreshMake();
                _hooked = true;
            }
            catch { }
        }

        /// <summary>[모듈 생성] 패널을 현재 도면의 규격 목록으로 다시 만든다.</summary>
        public static void RefreshMake()
        {
            try
            {
                if (_makeSrc == null) return;
                _makeSrc.Items.Clear();
                var list = ModuleSpec.Current;
                if (list.Count == 0)
                {
                    _makeSrc.Items.Add(new Autodesk.Windows.RibbonLabel
                    {
                        Text = "규격 설정에서 규격을 정하면\n여기에 버튼이 생깁니다.",
                    });
                    return;
                }
                var row = new Autodesk.Windows.RibbonRowPanel();
                for (int i = 0; i < list.Count; i++)
                {
                    if (i > 0 && i % PER_ROW == 0) row.Items.Add(new Autodesk.Windows.RibbonRowBreak());
                    row.Items.Add(MakeMakeButton(list[i]));
                }
                _makeSrc.Items.Add(row);
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
                _makeSrc = null;
            }
            catch { }
        }

        static Autodesk.Windows.RibbonButton MakeSpecButton(int mi)
        {
            var def = ModuleGeom.Defs[mi];
            string uses = "R, L" + (def.UsesW ? ", W" : "") + (def.UsesA ? ", A" : "");
            var b = new Autodesk.Windows.RibbonButton
            {
                Text = def.Label,                      // 줄바꿈 포함 전체 이름 (예: CURVE\nLEFT)
                ShowText = true,
                ShowImage = true,
                Size = Autodesk.Windows.RibbonItemSize.Large,
                Orientation = System.Windows.Controls.Orientation.Vertical,
                ToolTip = def.Name + " (" + (def.Std ? "표준 분기" : "특수 분기") + ")\n"
                          + "규격 설정 — 입력 항목: " + uses,
                CommandHandler = new ModuleSpecHandler(mi),
            };
            try { b.LargeImage = MakeIcon(mi, 32); b.Image = MakeIcon(mi, 16); }
            catch { b.ShowImage = false; }
            return b;
        }

        static Autodesk.Windows.RibbonButton MakeMakeButton(ModuleSpec.Entry entry)
        {
            var def = ModuleGeom.Defs[entry.Idx];
            var b = new Autodesk.Windows.RibbonButton
            {
                Text = def.Name + "\n" + entry.Digest(),
                ShowText = true,
                ShowImage = true,
                Size = Autodesk.Windows.RibbonItemSize.Large,
                Orientation = System.Windows.Controls.Orientation.Vertical,
                ToolTip = def.Name + "\n규격: " + entry.Digest() + "\n이 규격으로 배치합니다(기존 끝점에 자동 접합).",
                CommandHandler = new ModuleMakeHandler(entry),
            };
            try { b.LargeImage = MakeIcon(entry.Idx, 32); b.Image = MakeIcon(entry.Idx, 16); }
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
