using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using Microsoft.Win32;

// RailPluginZw 설치 프로그램 — 더블클릭 한 번으로 ZWCAD 에 자동 로드되게 만든다.
//  1) 내장된 DLL + 부품 DXF 를 %APPDATA%\ZWSOFT\RailPluginZw 에 풀어놓고
//  2) NETLOAD 로더 LSP 를 만들어 APPLOAD "시작 도구 모음"(레지스트리)에 등록 → 다음 실행부터 자동 로드
//  3) 신뢰 경로(TRUSTEDPATHS)에 설치 폴더를 추가해 보안 차단을 막고
//  4) ZWCAD 가 이미 켜져 있으면 COM 으로 즉시 로드까지 시킨다.
//  관리자 권한 불필요 (HKCU + %APPDATA% 만 사용).
namespace RailPluginZwSetup
{
    static class Program
    {
        const string APPDIR = "RailPluginZw";
        const string DLLNAME = "RailPluginZw.dll";
        const string LSPNAME = "RailPluginZw_load.lsp";
        const string PARTSNAME = "분기 레일 형상 세트 정리 (레이아웃 설계) v0_260721.dxf";
        const string CONVNAME = "DXFtoMAP.exe";     // CAD→MAP 변환기 (리본 버튼이 DLL 옆에서 찾는다)
        const string CONFIGNAME = "config.json";    // 변환기 기본 설정 — 이미 있으면 사용자 설정 보존
        const string TITLE = "RailPluginZw 설치";

        [STAThread]
        static void Main(string[] args)
        {
            bool remove = args.Any(a => a.Equals("/uninstall", StringComparison.OrdinalIgnoreCase));
            bool silent = args.Any(a => a.Equals("/silent", StringComparison.OrdinalIgnoreCase));
            var log = new StringBuilder();
            try
            {
                string dir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "ZWSOFT", APPDIR);
                string dll = Path.Combine(dir, DLLNAME);
                string lsp = Path.Combine(dir, LSPNAME);

                if (remove) { Uninstall(dir, lsp, log); return; }

                Directory.CreateDirectory(dir);

                // 1) 내장 파일 풀기 — ZWCAD 가 DLL 을 물고 있으면 덮어쓰기가 막힌다.
                bool locked = false;
                if (!Extract(DLLNAME, dll)) locked = true;
                Extract("parts.dxf", Path.Combine(dir, PARTSNAME));
                // CAD→MAP 변환기 — 실행 중이면 덮어쓰기가 막히므로 따로 표시. 설정 파일은 처음 한 번만.
                bool convLocked = !Extract(CONVNAME, Path.Combine(dir, CONVNAME));
                string cfgPath = Path.Combine(dir, CONFIGNAME);
                if (!File.Exists(cfgPath)) Extract(CONFIGNAME, cfgPath);
                // 변환기 바로가기 (바탕화면·시작 메뉴) — CAD 없이 MAP→CAD·CAD→MAP 만 쓸 때
                bool lnk = MakeShortcuts(Path.Combine(dir, CONVNAME));

                // 2) 로더 LSP (경로에 한글이 있을 수 있어 시스템 ANSI 로 기록)
                File.WriteAllText(lsp, LoaderLisp(dll), Encoding.Default);

                // 3) 프로필마다 시작 도구 모음 + 신뢰 경로 등록
                int n = RegisterAll(lsp, dir, log);

                // 4) 실행 중인 ZWCAD 에 즉시 로드
                bool injected = !locked && TryInject(dll);

                var m = new StringBuilder();
                m.AppendLine(locked
                    ? "설치는 됐지만 DLL 을 갱신하지 못했습니다 (ZWCAD 가 사용 중)."
                    : "설치가 완료되었습니다.");
                m.AppendLine();
                m.AppendLine("설치 위치: " + dir);
                m.AppendLine(n > 0
                    ? $"자동 로드 등록: ZWCAD 프로필 {n}개 — 다음 실행부터 자동으로 올라옵니다."
                    : "자동 로드 등록: ZWCAD 프로필을 찾지 못했습니다. ZWCAD 를 한 번 실행한 뒤 다시 실행해 주세요.");
                if (injected) m.AppendLine("실행 중인 ZWCAD 에 지금 바로 로드했습니다.");
                else if (locked) m.AppendLine("ZWCAD 를 완전히 종료한 뒤 이 프로그램을 한 번 더 실행해 주세요.");
                if (convLocked) m.AppendLine("CAD→MAP 변환기(" + CONVNAME + ")가 실행 중이라 갱신하지 못했습니다. 닫고 다시 실행해 주세요.");
                m.AppendLine(lnk
                    ? "바탕화면·시작 메뉴에 '" + LNKNAME + "' 바로가기를 만들었습니다 (CAD 없이 MAP→CAD·CAD→MAP)."
                    : "변환기 바로가기를 만들지 못했습니다. 변환기 위치: " + Path.Combine(dir, CONVNAME));
                m.AppendLine();
                m.AppendLine("명령: DRAWRAILV(레일) / RAILPART(부품) / RAILW(폭) / RAILLEN(길이) / RAILFIX(복구) / CAD2MAP(변환기) / RAILMAP2CAD(MAP→CAD)");
                m.AppendLine("리본 'Module' 탭 [변환] 칸의 'CAD→MAP 변환기'·'MAP→CAD 복원' 버튼으로도 쓸 수 있습니다.");
                if (log.Length > 0) { m.AppendLine(); m.Append(log); }

                // 결과를 설치 폴더에 남긴다 (문제 진단용 / 무인 설치 확인용)
                try { File.WriteAllText(Path.Combine(dir, "setup.log"), m.ToString(), Encoding.UTF8); } catch { }
                if (!silent)
                    MessageBox.Show(m.ToString(), TITLE, MessageBoxButtons.OK,
                        locked ? MessageBoxIcon.Warning : MessageBoxIcon.Information);
            }
            catch (Exception ex)
            {
                if (silent) throw;
                MessageBox.Show("설치 중 오류가 발생했습니다.\n\n" + ex.Message + "\n\n" + log,
                    TITLE, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        // 내장 리소스 → 파일. 잠겨 있으면 false (기존 파일 유지)
        static bool Extract(string resName, string path)
        {
            var asm = Assembly.GetExecutingAssembly();
            string key = asm.GetManifestResourceNames().FirstOrDefault(n => n.EndsWith(resName, StringComparison.OrdinalIgnoreCase));
            if (key == null) throw new FileNotFoundException("내장 리소스 없음: " + resName);
            try
            {
                using (Stream src = asm.GetManifestResourceStream(key))
                using (var dst = new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.None))
                    src.CopyTo(dst);
                return true;
            }
            catch (IOException) { return false; }        // 사용 중
            catch (UnauthorizedAccessException) { return false; }
        }

        // ZWCAD 시작 시 실행될 로더. LISP 문자열이라 경로 구분자는 '/' 로 (역슬래시 이스케이프 회피)
        static string LoaderLisp(string dll)
        {
            string p = dll.Replace("\\", "/");
            return
                ";; RailPluginZw auto-loader (generated by RailPluginZwSetup)\n" +
                "(if (findfile \"" + p + "\")\n" +
                "  (progn\n" +
                "    (setvar \"FILEDIA\" 0)\n" +
                "    (command \"_.NETLOAD\" \"" + p + "\")\n" +
                "    (setvar \"FILEDIA\" 1)\n" +
                "    (princ \"\\nRailPluginZw loaded. DRAWRAILV / RAILPART / RAILW / RAILLEN\")\n" +
                "  )\n" +
                "  (princ \"\\nRailPluginZw: DLL not found - " + p + "\")\n" +
                ")\n(princ)\n";
        }

        // HKCU\Software\ZWSOFT 아래의 모든 프로필에 등록 (제품·버전·언어 구조가 달라도 되게 재귀 탐색)
        static int RegisterAll(string lsp, string dir, StringBuilder log)
        {
            int count = 0;
            // ★쓰기 가능으로 열어야 한다 — OpenSubKey(name) 은 읽기 전용이라 CreateSubKey 가 막힌다
            using (RegistryKey root = Registry.CurrentUser.OpenSubKey(@"Software\ZWSOFT", true))
            {
                if (root == null) return 0;
                foreach (string profPath in FindProfiles(root, "", 0))
                {
                    foreach (string prof in SubKeys(root, profPath))
                    {
                        string p = profPath + "\\" + prof;
                        try { AddStartup(root, p, lsp); AddTrusted(root, p, dir); count++; }
                        catch (Exception ex) { log.AppendLine("[건너뜀] " + p + " : " + ex.Message); }
                    }
                }
            }
            return count;
        }

        static IEnumerable<string> SubKeys(RegistryKey root, string sub)
        {
            using (RegistryKey k = root.OpenSubKey(sub))
                return k == null ? Enumerable.Empty<string>() : (IEnumerable<string>)k.GetSubKeyNames().ToList();
        }

        // 이름이 'Profiles' 인 키의 경로들을 찾는다
        static IEnumerable<string> FindProfiles(RegistryKey root, string sub, int depth)
        {
            if (depth > 5) yield break;
            foreach (string name in SubKeys(root, sub))
            {
                string path = string.IsNullOrEmpty(sub) ? name : sub + "\\" + name;
                if (name.Equals("Profiles", StringComparison.OrdinalIgnoreCase)) { yield return path; continue; }
                foreach (string r in FindProfiles(root, path, depth + 1)) yield return r;
            }
        }

        // APPLOAD 시작 도구 모음: NumStartup + 1Startup, 2Startup ... (전부 문자열)
        static void AddStartup(RegistryKey root, string prof, string lsp)
        {
            using (RegistryKey k = root.CreateSubKey(prof + @"\Dialogs\Appload\Startup"))
            {
                if (k == null) return;
                int num = 0;
                int.TryParse(k.GetValue("NumStartup") as string ?? "0", out num);
                var items = new List<string>();
                for (int i = 1; i <= num; i++)
                {
                    string v = k.GetValue(i + "Startup") as string;
                    // 우리 로더의 옛 등록은 걷어내고 새로 넣는다 (중복 방지)
                    if (!string.IsNullOrEmpty(v) &&
                        !Path.GetFileName(v).Equals(LSPNAME, StringComparison.OrdinalIgnoreCase))
                        items.Add(v);
                }
                items.Add(lsp);
                for (int i = 1; i <= Math.Max(num, items.Count); i++)
                {
                    if (i <= items.Count) k.SetValue(i + "Startup", items[i - 1], RegistryValueKind.String);
                    else k.DeleteValue(i + "Startup", false);
                }
                k.SetValue("NumStartup", items.Count.ToString(), RegistryValueKind.String);
            }
        }

        // 신뢰 경로 — SECURELOAD 가 켜져 있어도 로드되게
        static void AddTrusted(RegistryKey root, string prof, string dir)
        {
            using (RegistryKey k = root.CreateSubKey(prof + @"\Config"))
            {
                if (k == null) return;
                string cur = k.GetValue("TRUSTEDPATHS") as string ?? "";
                var parts = cur.Split(';').Where(s => !string.IsNullOrWhiteSpace(s)).ToList();
                if (parts.Any(s => s.TrimEnd('\\').Equals(dir.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))) return;
                parts.Add(dir);
                k.SetValue("TRUSTEDPATHS", string.Join(";", parts), RegistryValueKind.String);
            }
        }

        // 바로가기 이름 — AutoCAD·ZWCAD 판이 같은 이름을 쓴다(둘 다 설치하면 나중 것이 덮어씀, 내용은 같은 변환기)
        const string LNKNAME = "DXFtoMAP 변환기";

        static string[] ShortcutPaths() => new[]
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), LNKNAME + ".lnk"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), LNKNAME + ".lnk"),
        };

        // WScript.Shell COM 으로 .lnk 를 만든다 (관리자 권한 불필요 — 사용자 바탕화면·시작 메뉴만)
        static bool MakeShortcuts(string exe)
        {
            bool ok = true;
            foreach (string p in ShortcutPaths())
            {
                try
                {
                    dynamic sh = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
                    dynamic s = sh.CreateShortcut(p);
                    s.TargetPath = exe;
                    s.WorkingDirectory = Path.GetDirectoryName(exe);
                    s.Description = "CAD→MAP / MAP→CAD 변환기";
                    s.IconLocation = exe + ",0";
                    s.Save();
                }
                catch { ok = false; }
            }
            return ok;
        }

        // 제거: 이 설치 폴더의 변환기를 가리키는 바로가기만 지운다 (다른 CAD 판이 만든 것은 남김)
        static void RemoveShortcuts(string dir, StringBuilder m)
        {
            foreach (string p in ShortcutPaths())
            {
                try
                {
                    if (!File.Exists(p)) continue;
                    dynamic sh = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
                    string target = (string)sh.CreateShortcut(p).TargetPath;
                    if (target.StartsWith(dir, StringComparison.OrdinalIgnoreCase)) { File.Delete(p); m.AppendLine("바로가기 제거: " + p); }
                }
                catch { }
            }
        }

        // 이미 떠 있는 ZWCAD 에 COM 으로 NETLOAD 를 흘려넣는다 (없으면 조용히 실패)
        static bool TryInject(string dll)
        {
            foreach (string progId in new[] { "ZWCAD.Application", "ZwCAD.Application" })
            {
                try
                {
                    dynamic app = Marshal.GetActiveObject(progId);
                    dynamic doc = app.ActiveDocument;
                    string p = dll.Replace("\\", "/");
                    doc.SendCommand("(progn (setvar \"FILEDIA\" 0)(command \"_.NETLOAD\" \"" + p +
                                    "\")(setvar \"FILEDIA\" 1)(princ))\n");
                    return true;
                }
                catch { }
            }
            return false;
        }

        static void Uninstall(string dir, string lsp, StringBuilder log)
        {
            int n = 0;
            RemoveShortcuts(dir, log);
            using (RegistryKey root = Registry.CurrentUser.OpenSubKey(@"Software\ZWSOFT", true))
            {
                if (root != null)
                    foreach (string profPath in FindProfiles(root, "", 0))
                        foreach (string prof in SubKeys(root, profPath))
                        {
                            try
                            {
                                using (RegistryKey k = root.OpenSubKey(profPath + "\\" + prof + @"\Dialogs\Appload\Startup", true))
                                {
                                    if (k == null) continue;
                                    int num = 0;
                                    int.TryParse(k.GetValue("NumStartup") as string ?? "0", out num);
                                    var items = new List<string>();
                                    for (int i = 1; i <= num; i++)
                                    {
                                        string v = k.GetValue(i + "Startup") as string;
                                        if (!string.IsNullOrEmpty(v) &&
                                            !Path.GetFileName(v).Equals(LSPNAME, StringComparison.OrdinalIgnoreCase))
                                            items.Add(v);
                                    }
                                    for (int i = 1; i <= num; i++)
                                    {
                                        if (i <= items.Count) k.SetValue(i + "Startup", items[i - 1], RegistryValueKind.String);
                                        else k.DeleteValue(i + "Startup", false);
                                    }
                                    k.SetValue("NumStartup", items.Count.ToString(), RegistryValueKind.String);
                                    n++;
                                }
                            }
                            catch (Exception ex) { log.AppendLine(ex.Message); }
                        }
            }
            MessageBox.Show($"자동 로드 등록을 해제했습니다 (프로필 {n}개).\n\n" +
                            "설치 폴더는 그대로 둡니다:\n" + dir + (log.Length > 0 ? "\n\n" + log : ""),
                            TITLE, MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }
}
