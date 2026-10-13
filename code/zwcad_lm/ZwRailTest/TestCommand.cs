using ZwSoft.ZwCAD.Runtime;
using ZwSoft.ZwCAD.ApplicationServices;
using ZwSoft.ZwCAD.EditorInput;

// ZWCAD LM 2026 에서 .NET 로드가 실제로 되는지 확인하는 최소 스모크 테스트.
// NETLOAD 로 이 DLL 을 올린 뒤 명령창에 ZWRAILTEST 입력 → 메시지가 뜨면 .NET 실행 확정.
[assembly: CommandClass(typeof(ZwRailTest.TestCommand))]

namespace ZwRailTest
{
    public class TestCommand
    {
        [CommandMethod("ZWRAILTEST")]
        public void Run()
        {
            Document doc = Application.DocumentManager.MdiActiveDocument;
            Editor ed = doc.Editor;
            ed.WriteMessage("\n[ZwRailTest] .NET 로드 성공! ZWCAD LM 에서 .NET 플러그인이 실행됩니다.");
        }
    }
}
