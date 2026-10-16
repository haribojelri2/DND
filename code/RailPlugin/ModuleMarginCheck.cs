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

        sealed class Issue { public double X, Y; public string Text; }

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
                    });
                return true;
            }
            catch (System.Exception ex) { err = ex.Message; return false; }
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

        static int Mark(Database db, List<Issue> issues)
        {
            int n = 0;
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                ObjectId layer = EnsureLayer(db, tr);
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);
                foreach (var it in issues)
                {
                    var c = new Circle(new Point3d(it.X, it.Y, 0), Vector3d.ZAxis, RADIUS) { LayerId = layer };
                    ms.AppendEntity(c); tr.AddNewlyCreatedDBObject(c, true);
                    var t = new DBText
                    {
                        Position = new Point3d(it.X + RADIUS * 1.1, it.Y + RADIUS * 0.6, 0),
                        Height = TEXT_H,
                        TextString = it.Text,
                        LayerId = layer,
                    };
                    ms.AppendEntity(t); tr.AddNewlyCreatedDBObject(t, true);
                    n++;
                }
                tr.Commit();
            }
            return n;
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
