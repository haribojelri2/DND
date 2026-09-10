using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

// RailPlugin 설치 프로그램 — 더블클릭 한 번으로 AutoCAD 에 자동 로드되게 만든다.
//  1) 내장된 DLL + 부품 DXF + PackageContents.xml 를
//     %APPDATA%\Autodesk\ApplicationPlugins\RailPlugin.bundle 에 풀어놓고
//  2) 그걸로 끝이다 — .bundle 의 LoadOnAutoCADStartup="True" 가 자동 로드를 담당한다.
//     (ZWCAD 판처럼 로더 LSP·시작 도구 모음 레지스트리 등록이 필요 없다.)
//  3) AutoCAD 가 이미 켜져 있으면 COM 으로 즉시 로드까지 시킨다.
//  관리자 권한 불필요 (%APPDATA% 만 사용, 레지스트리는 건드리지 않는다).
//  ※ ApplicationPlugins 폴더는 AutoCAD 가 기본 신뢰(SECURELOAD)하므로 TRUSTEDPATHS 등록도 하지 않는다.
namespace RailPluginSetup
{
    static class Program
    {
        const string BUNDLE = "RailPlugin.bundle";
        const string DLLNAME = "RailPlugin.dll";
        const string MANIFEST = "PackageContents.xml";
        const string PARTSNAME = "분기 레일 형상 세트 정리 (레이아웃 설계) v0_260721.dxf";
        const string CONVNAME = "DXFtoMAP.exe";     // CAD→MAP 변환기 (리본 버튼이 DLL 옆에서 찾는다)
        const string CONFIGNAME = "config.json";    // 변환기 기본 설정 — 이미 있으면 사용자 설정 보존
        const string TITLE = "RailPlugin 설치";

        [STAThread]
        static void Main(string[] args)
        {
            bool remove = args.Any(a => a.Equals("/uninstall", StringComparison.OrdinalIgnoreCase));
            bool silent = args.Any(a => a.Equals("/silent", StringComparison.OrdinalIgnoreCase));
            try
            {
                string dir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "Autodesk", "ApplicationPlugins", BUNDLE);
                string contents = Path.Combine(dir, "Contents");
                string dll = Path.Combine(contents, DLLNAME);

                if (remove) { Uninstall(dir, silent); return; }

                Directory.CreateDirectory(contents);   // 번들은 2단 구조 (루트=매니페스트 / Contents=DLL+DXF)

                // 1) 내장 파일 풀기 — AutoCAD 가 DLL 을 물고 있으면 덮어쓰기가 막힌다.
                bool locked = !Extract(DLLNAME, dll);
                Extract("parts.dxf", Path.Combine(contents, PARTSNAME));   // DLL 옆에 있어야 RAILPART 가 찾는다
                Extract(MANIFEST, Path.Combine(dir, MANIFEST));            // 이 파일이 자동 로드를 켠다
                // CAD→MAP 변환기 — 실행 중이면 덮어쓰기가 막히므로 따로 표시. 설정 파일은 처음 한 번만.
                bool convLocked = !Extract(CONVNAME, Path.Combine(contents, CONVNAME));
                string cfgPath = Path.Combine(contents, CONFIGNAME);
                if (!File.Exists(cfgPath)) Extract(CONFIGNAME, cfgPath);

                // 2) 실행 중인 AutoCAD 에 즉시 로드
                bool injected = !locked && TryInject(dll);

                var m = new StringBuilder();
                m.AppendLine(locked
                    ? "설치는 됐지만 DLL 을 갱신하지 못했습니다 (AutoCAD 가 사용 중)."
                    : "설치가 완료되었습니다.");
                m.AppendLine();
                m.AppendLine("설치 위치: " + dir);
                m.AppendLine("자동 로드: 등록 완료 — AutoCAD 를 켤 때마다 자동으로 올라옵니다.");
                if (injected) m.AppendLine("실행 중인 AutoCAD 에 지금 바로 로드했습니다.");
                else if (locked) m.AppendLine("AutoCAD 를 완전히 종료한 뒤 이 프로그램을 한 번 더 실행해 주세요.");
                if (convLocked) m.AppendLine("CAD→MAP 변환기(" + CONVNAME + ")가 실행 중이라 갱신하지 못했습니다. 닫고 다시 실행해 주세요.");
                m.AppendLine();
                m.AppendLine("명령: DRAWRAILV(레일) / RAILPART(부품) / RAILW(폭) / RAILLEN(길이) / RAILFIX(복구) / CAD2MAP(변환기)");
                m.AppendLine("리본 'Rail' 탭에서도 쓸 수 있습니다. 'CAD→MAP 변환기' 버튼이 DXFtoMAP.exe 를 실행합니다.");

                // 결과를 설치 폴더에 남긴다 (문제 진단용 / 무인 설치 확인용)
                try { File.WriteAllText(Path.Combine(dir, "setup.log"), m.ToString(), Encoding.UTF8); } catch { }
                if (!silent)
                    MessageBox.Show(m.ToString(), TITLE, MessageBoxButtons.OK,
                        locked ? MessageBoxIcon.Warning : MessageBoxIcon.Information);
            }
            catch (Exception ex)
            {
                if (silent) throw;
                MessageBox.Show("설치 중 오류가 발생했습니다.\n\n" + ex.Message,
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

        // 이미 떠 있는 AutoCAD 에 COM 으로 NETLOAD 를 흘려넣는다 (없으면 조용히 실패)
        static bool TryInject(string dll)
        {
            try
            {
                dynamic app = Marshal.GetActiveObject("AutoCAD.Application");
                dynamic doc = app.ActiveDocument;
                string p = dll.Replace("\\", "/");     // LISP 문자열이라 '/' 로 (역슬래시 이스케이프 회피)
                doc.SendCommand("(progn (setvar \"FILEDIA\" 0)(command \"_.NETLOAD\" \"" + p +
                                "\")(setvar \"FILEDIA\" 1)(princ))\n");
                return true;
            }
            catch { return false; }
        }

        // 자동 로드 해제 — 매니페스트만 지워도 로드가 끊긴다(이 파일은 AutoCAD 가 잠그지 않는다).
        // 이어서 폴더째 지워보되, DLL 이 잠겨 있으면 남겨둔다.
        static void Uninstall(string dir, bool silent)
        {
            var m = new StringBuilder();
            string manifest = Path.Combine(dir, MANIFEST);
            if (!Directory.Exists(dir))
            {
                m.AppendLine("설치된 흔적이 없습니다: " + dir);
            }
            else
            {
                try { if (File.Exists(manifest)) File.Delete(manifest); m.AppendLine("자동 로드 등록을 해제했습니다."); }
                catch (Exception ex) { m.AppendLine("[실패] 매니페스트 삭제: " + ex.Message); }

                try { Directory.Delete(dir, true); m.AppendLine("설치 폴더도 제거했습니다: " + dir); }
                catch { m.AppendLine("설치 폴더는 남겨둡니다 (사용 중일 수 있음): " + dir); }
            }
            if (!silent)
                MessageBox.Show(m.ToString(), TITLE, MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }
}
