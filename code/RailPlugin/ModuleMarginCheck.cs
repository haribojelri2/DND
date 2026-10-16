using System;
using System.Collections.Generic;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.EditorInput;

[assembly: CommandClass(typeof(RailPlugin.ModuleMarginCheck))]

namespace RailPlugin
{
    // 마진 검사 — 마주 보는 두 모듈 접속구 사이가 마진 합(M1·M2)보다 짧아 MAP NODE 가 엇갈리는 곳을 도면에 표시한다.
    //  판정은 변환기(DXFtoMAP.exe --margincheck)가 CAD→MAP 과 똑같이 한다 → 변환 때 나오는 "마진 겹침" 경고와 같은 위치.
    //  곡선 끝끼리처럼 사양상 U/N 링크 하나로 합쳐지는 곳은 정상이라 표시하지 않는다.
    //  표시 = 레이어 RAIL_MARGIN_WARN(자홍)에 원 + 설명 글자. 다시 검사하면 이전 표시를 지우고 새로 그린다.
    public class ModuleMarginCheck
    {
        public const string LAYER = "RAIL_MARGIN_WARN";
        public const short COLOR = 6;            // 자홍
        const double RADIUS = 400.0;
        const double TEXT_H = 150.0;

        [CommandMethod("RAILMODMARGIN")]
        public void RailModMargin()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            if (doc == null) return;
            Editor ed = doc.Editor;
            Database db = doc.Database;
            string title = "마진 검사";
            if (!ModuleParams.Has(db))
            {
                Show("도면에 모듈 파라미터(M1·M2)가 저장돼 있지 않습니다.\n[파라미터 설정]에서 저장한 뒤 다시 실행하세요.", title, true);
                return;
            }
            string exe = Cad2Map.Resolve();
            if (exe == null) { Show("변환기(" + Cad2Map.EXE + ")를 찾지 못했습니다.", title, true); return; }

            string dir = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "RailPlugin_margin", Guid.NewGuid().ToString("N").Substring(0, 8));
            System.IO.Directory.CreateDirectory(dir);
            string dxf = System.IO.Path.Combine(dir, "check.dxf");
            string json = System.IO.Path.Combine(dir, "check.json");
            ClearMarks(db);                                   // 이전 표시는 검사 대상에서 빼고 지운다
            db.DxfOut(dxf, 16, DwgVersion.Current);
            ed.WriteMessage("\n마진 검사 중... (도면 크기에 따라 수십 초 걸릴 수 있습니다)");
            try
            {
                var psi = new System.Diagnostics.ProcessStartInfo(exe)
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WorkingDirectory = System.IO.Path.GetDirectoryName(exe),
                    Arguments = "--margincheck \"" + dxf + "\" \"" + json + "\"",
                };
                using (var pr = System.Diagnostics.Process.Start(psi))
                {
                    if (!pr.WaitForExit(600000)) { try { pr.Kill(); } catch { } Show("10분 안에 끝나지 않아 중단했습니다.", title, true); return; }
                }
            }
            catch (System.Exception ex) { Show("변환기 실행 실패 - " + ex.Message, title, true); return; }

            List<Issue> issues;
            string err;
            if (!Read(json, out issues, out err)) { Show("검사 결과를 읽지 못했습니다." + (err != null ? "\n" + err : ""), title, true); return; }
            if (err != null) { Show(err, title, true); return; }
            int n = Mark(db, issues);
            try { System.IO.Directory.Delete(dir, true); } catch { }
            if (n == 0)
                Show("마진 때문에 NODE 가 엇갈리는 곳이 없습니다.", title, false);
            else
                Show($"마진 때문에 NODE 가 엇갈리는 곳이 {n}군데 있습니다.\n도면에 자홍색 원({LAYER} 레이어)으로 표시했습니다.\n\n" +
                     "두 모듈 사이를 마진 합(M1·M2)보다 넓히거나 마진 설정을 확인하세요. 이대로 변환하면 그 자리는 경고만 남고 진행 방향이 어긋날 수 있습니다.",
                     title, true);
        }

        sealed class Issue { public double X, Y; public string Text, Ha, Hb; }

        static bool Read(string path, out List<Issue> issues, out string err)
        {
            // 결과 구조가 단순해 정규식으로 읽는다 — ZWCAD 판(.NET Framework 4.8)에는 System.Text.Json 이 없다
            issues = new List<Issue>(); err = null;
            try
            {
                string s = System.IO.File.ReadAllText(path, System.Text.Encoding.UTF8);
                var inv = System.Globalization.CultureInfo.InvariantCulture;
                var me = System.Text.RegularExpressions.Regex.Match(s, "\"error\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");
                if (me.Success) err = System.Text.RegularExpressions.Regex.Unescape(me.Groups[1].Value);
                foreach (System.Text.RegularExpressions.Match m in System.Text.RegularExpressions.Regex.Matches(s,
                         "\\{\"x\"\\s*:\\s*([-0-9.eE+]+)\\s*,\\s*\"y\"\\s*:\\s*([-0-9.eE+]+)[^{}]*?\"text\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"[^{}]*\\}"))
                    issues.Add(new Issue
                    {
                        X = double.Parse(m.Groups[1].Value, inv),
                        Y = double.Parse(m.Groups[2].Value, inv),
                        Text = System.Text.RegularExpressions.Regex.Unescape(m.Groups[3].Value),
                        Ha = Field(m.Value, "ha"),
                        Hb = Field(m.Value, "hb"),
                    });
                return true;
            }
            catch (System.Exception ex) { err = ex.Message; return false; }
        }

        static string Field(string obj, string key)
        {
            var m = System.Text.RegularExpressions.Regex.Match(obj, "\"" + key + "\"\\s*:\\s*\"([0-9A-Fa-f]*)\"");
            return m.Success ? m.Groups[1].Value : "";
        }

        static ObjectId EnsureLayer(Database db, Transaction tr)
        {
            var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
            if (lt.Has(LAYER)) return lt[LAYER];
            lt.UpgradeOpen();
            var ltr = new LayerTableRecord
            {
                Name = LAYER,
                Color = Autodesk.AutoCAD.Colors.Color.FromColorIndex(Autodesk.AutoCAD.Colors.ColorMethod.ByAci, COLOR),
            };
            ObjectId id = lt.Add(ltr);
            tr.AddNewlyCreatedDBObject(ltr, true);
            return id;
        }

        public static void ClearMarks(Database db)
        {
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                foreach (ObjectId id in ms)
                {
                    var e = tr.GetObject(id, OpenMode.ForRead) as Entity;
                    if (e != null && e.Layer.Equals(LAYER, StringComparison.OrdinalIgnoreCase)) { e.UpgradeOpen(); e.Erase(); }
                }
                tr.Commit();
            }
        }

        // 표시 글자 스타일 — 기본 Standard(txt.shx)에는 한글이 없어 "??"로 나온다 → 한글 TrueType 글꼴(맑은 고딕)
        public const string STYLE = "RAIL_MARGIN_WARN";

        static ObjectId EnsureStyle(Database db, Transaction tr)
        {
            var st = (TextStyleTable)tr.GetObject(db.TextStyleTableId, OpenMode.ForRead);
            if (st.Has(STYLE)) return st[STYLE];
            st.UpgradeOpen();
            var rec = new TextStyleTableRecord { Name = STYLE };
            rec.Font = new Autodesk.AutoCAD.GraphicsInterface.FontDescriptor("Malgun Gothic", false, false, 0, 0);
            ObjectId id = st.Add(rec);
            tr.AddNewlyCreatedDBObject(rec, true);
            return id;
        }

        // 겹침에 걸린 두 모듈을 핸들로 찾아 모듈마다 원 하나(모듈 전체를 감쌈) + 설명. 같은 모듈이 여러 겹침에 걸리면 설명을 모은다.
        //  핸들로 못 찾으면(도면이 바뀜 등) 두 접속구 사이에 작은 원.
        static int Mark(Database db, List<Issue> issues)
        {
            int n = 0;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                ObjectId layer = EnsureLayer(db, tr);
                ObjectId style = EnsureStyle(db, tr);
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);
                var notes = new Dictionary<ObjectId, List<string>>();
                var order = new List<ObjectId>();
                foreach (var it in issues)
                {
                    bool any = false;
                    foreach (string h in new[] { it.Ha, it.Hb })
                    {
                        ObjectId id = ById(db, h);
                        if (id.IsNull) continue;
                        any = true;
                        if (!notes.ContainsKey(id)) { notes[id] = new List<string>(); order.Add(id); }
                        if (!notes[id].Contains(it.Text)) notes[id].Add(it.Text);
                    }
                    if (!any)
                    {
                        AddMark(ms, tr, layer, style, new Point3d(it.X, it.Y, 0), RADIUS, new List<string> { it.Text });
                        n++;
                    }
                }
                foreach (ObjectId id in order)
                {
                    var br = (Entity)tr.GetObject(id, OpenMode.ForRead);
                    Extents3d e;
                    try { e = br.GeometricExtents; } catch { continue; }
                    var c = new Point3d((e.MinPoint.X + e.MaxPoint.X) / 2, (e.MinPoint.Y + e.MaxPoint.Y) / 2, 0);
                    double r = 0.5 * e.MinPoint.DistanceTo(e.MaxPoint) + 150.0;
                    AddMark(ms, tr, layer, style, c, r, notes[id]);
                    n++;
                }
                tr.Commit();
            }
            return n;
        }

        static ObjectId ById(Database db, string hex)
        {
            if (string.IsNullOrEmpty(hex)) return ObjectId.Null;
            try
            {
                ObjectId id;
                if (db.TryGetObjectId(new Handle(Convert.ToInt64(hex, 16)), out id) && !id.IsErased) return id;
            }
            catch { }
            return ObjectId.Null;
        }

        static void AddMark(BlockTableRecord ms, Transaction tr, ObjectId layer, ObjectId style, Point3d c, double r, List<string> lines)
        {
            var circ = new Circle(c, Vector3d.ZAxis, r) { LayerId = layer };
            ms.AppendEntity(circ); tr.AddNewlyCreatedDBObject(circ, true);
            var t = new MText
            {
                Location = new Point3d(c.X + r * 0.75, c.Y + r * 0.75, 0),
                TextHeight = TEXT_H,
                Contents = string.Join("\\P", lines),         // MText 줄바꿈
                TextStyleId = style,
                LayerId = layer,
                Attachment = AttachmentPoint.BottomLeft,
            };
            ms.AppendEntity(t); tr.AddNewlyCreatedDBObject(t, true);
        }

        static void Show(string msg, string title, bool warn)
        {
            try { Application.DocumentManager.MdiActiveDocument?.Editor.WriteMessage("\n" + title + ": " + msg.Replace("\n", " ")); } catch { }
            if (Environment.GetEnvironmentVariable("RAILPLUGIN_NODIALOG") == "1") return;
            try
            {
                System.Windows.MessageBox.Show(msg, title, System.Windows.MessageBoxButton.OK,
                    warn ? System.Windows.MessageBoxImage.Warning : System.Windows.MessageBoxImage.Information);
            }
            catch { }
        }
    }
}
