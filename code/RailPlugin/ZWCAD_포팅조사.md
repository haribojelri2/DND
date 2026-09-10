# RailPlugin → ZWCAD LM 이식 가능성 조사

조사일: 2026-07-06 · 대상: `code/RailPlugin` (AutoCAD 2026 .NET8 관리형 플러그인)

---

## ⛔ 게이트 결과 확정 (2026-07-06, 사용자 확인)

**ZWCAD LM은 .NET / ZRX / VBA 불가. LM에서 쓸 수 있는 것은 오직 ① LISP ② 플렉시블 블록(Flexible Block)뿐이다.**

→ 따라서 **현재 .NET 플러그인(RailPlugin)을 LM으로 "이식"하는 것은 불가능**하다. LM에서는 동일 기능을 **LISP + 플렉시블 블록으로 재구현(reimplement)** 해야 한다. 아래 "LM 재구현 전략" 섹션 참조. (그 아래 .NET 포팅 계획은 Pro/MFG로 라이선스 상향 시에만 유효 — 참고용으로 보존.)

---

## 한 줄 결론 (원 조사 시점 — 게이트 미확정)

**"ZWCAD LM 전용"으로 이식하는 것은 조건부다.** 기술적으로 AutoCAD .NET → ZWCAD .NET 이식은 충분히 가능(중간 규모 작업)하지만, **LM 에디션이 .NET/ZRX 플러그인을 로드할 수 있는지 자체가 불확실**하다. 이 한 가지가 나머지 모든 것을 좌우하는 **게이트**이며, 현재 증거는 오히려 부정적 쪽으로 기운다. 코드 포팅 세부보다 이 게이트를 먼저 해소해야 한다. **(→ 위 게이트 결과에서 부정으로 확정됨.)**

---

## ★ LM 재구현 전략 (LISP + 플렉시블 블록)

LM에서 쓸 수 있는 두 도구를 현재 플러그인의 기능에 매핑:

| 현재 .NET 기능 | LM 대체 | 비고 |
|---|---|---|
| `DRAWRAIL2/3` 명령 (레일 생성) | **LISP `defun c:DRAWRAIL2`** | RailGeom/RailGeom3의 Line/Arc 좌표 수식이 그대로 이식됨(순수 산술). `entmake`/`command "_.LINE"/"_.ARC"` 또는 블록 정의 생성. |
| `RAILLEN` 명령 (길이 변경, 재정의) | **LISP `defun c:RAILLEN`** | 선택→새 길이→기존 지우고 재계산 재생성. **현재 SetLength 로직(2차선 조인트 비율 이동 / 3차선 station 중앙 고정·직선 신축)을 100% 재현 가능.** |
| XData(length·count·kind) | **LISP XData** (`entmake`의 `-3` 그룹, `regapp`) | LISP도 확장데이터 읽기/쓰기 지원. 레일 식별·길이 저장에 사용. |
| `GripOverrule` 드래그 리사이즈 | **플렉시블 블록** 선형 파라미터+스트레치, 또는 **RAILLEN 명령** | Overrule은 LM에 없음. 드래그 UX는 플렉시블 블록으로 근사하거나 RAILLEN으로 대체. |
| 리본 탭/버튼(`RibbonBuilder`) | **CUI로 리본 저작 + LISP 명령 연결(가능)** | .NET 리본 생성은 불가하나, ZWCAD `CUI` 대화상자로 커스텀 탭/패널/버튼을 프로그래밍 없이 만들고 버튼 매크로 `^C^CDRAWRAIL2`로 LISP 명령 호출. CUIX로 배포. 결과물(리본)은 동일. LM에 CUI 리본편집기 포함 여부만 실물 확인 권장. |

### 플렉시블 블록의 한계 (중요)
플렉시블 블록 = ZWCAD의 다이나믹 블록. 네이티브 그립 리사이즈를 **코드 없이** 제공하지만, 현재 로직의 복잡한 거동은 표준 스트레치로 완전 재현이 어렵다:
- **2차선**: 조인트가 길이에 **비례 재배치**(개수 고정, 균등 분포) → 각 조인트에 서로 다른 **거리 배수(distance multiplier)** move/stretch 액션을 하나의 선형 파라미터에 물려야 함. 저작이 까다롭고 배수 지원 확인 필요.
- **3차선**: 내부 station이 **중앙 rigid 고정**(길이/2 위치 유지) → station move 액션에 배수 0.5, 양 끝 그룹 스트레치. 역시 배수 저작 필요.

→ **완벽 재현은 LISP 재생성(RAILLEN 방식)이 확실**하다. 플렉시블 블록은 "빠른 시각적 드래그" 편의 레이어로 병행하되, 정확한 파라메트릭 리사이즈의 근거는 LISP로 두는 것을 권장.

### 권장 아키텍처
1. **LISP 코어(가장 확실·1순위)**: RailGeom/RailGeom3 좌표 수식 → `.lsp` 이식. `c:DRAWRAIL2`, `c:DRAWRAIL3`, `c:RAILLEN`(정확한 재생성) 구현. XData로 length/kind/count 저장. **순수 `entmake`/`command` 방식이라 vlax/COM 없이도 동작** → LM 제한과 무관하게 안전.
2. **그립 UX(선택)**: 단순 신축이 충분하면 플렉시블 블록으로 저작해 드래그 그립 제공. 복잡 거동은 RAILLEN 명령으로.
3. **호출 UI**: APPLOAD/Startup Suite로 `.lsp` 자동 로드, CUI로 메뉴/툴바 버튼 추가.

### ⚠️ LISP과 플렉시블 블록은 "레이어링"이 아니라 사실상 "택일"일 수 있음
LISP로 플렉시블 블록의 **파라미터(길이)를 코드로 조종**하려면 Visual LISP ActiveX 브리지(`vl-load-com`, `vlax-*`, dynamic block properties 컬렉션)가 필요하다. 그런데 **LM의 "리습 일부 제한" + COM 티어 부재**로 `vlax-*`가 빠졌을 가능성이 있다. 그렇다면 LISP는 **날 지오메트리 그리기만** 가능하고 플렉시블 블록을 제어하지 못한다 → 둘의 깔끔한 조합이 성립 안 함.
- **다행히 순수 `entmake`/`command` 기반 RAILLEN 재생성은 vlax가 전혀 필요 없다** → 제한과 무관하게 견고. 그래서 이 경로를 1순위로 둔다.

### 빌드 전 확인 2가지 (LM 명령창에서 즉시 테스트)
- **T1 — LM LISP에 `vl-load-com`/`vlax-*`가 있는가?** → LISP↔플렉시블블록 조합 가능 여부 결정.
- **T2 — 플렉시블 블록 저작에서 스트레치/무브 액션의 "거리 배수(distance multiplier)"를 지원하는가?** → 조인트 비율 재배치·station 중앙 고정을 플렉시블 블록으로 근사 가능한지 결정. 없으면 복잡 거동은 전부 LISP 재생성 담당.

### 사용자 결정 2가지 (아키텍처를 가름)
- **D1 — 실시간 드래그 그립 리사이즈가 필수인가, RAILLEN "길이 입력" 명령으로 충분한가?** 정확도 우선→순수 LISP RAILLEN(확실). 드래그 UX 우선→플렉시블 블록(근사+T2 리스크).
- **D2 — 반드시 LM 안에서 대화식으로 그려야 하는가, 아니면 외부(Python+ezdxf)에서 레일 DXF 생성 후 INSERT해도 되는가?** 후자면 이미 있는 파이썬 스택 재활용이 최선일 수 있음.

### RAILLEN 구현 방식 선택 (초기에 결정)
- **(a) 블록 기반 재정의**: 현재 .NET처럼 블록 정의를 다시 채워 모든 참조 갱신. LISP에선 블록 재정의가 다소 까다로움.
- **(b) 날 지오메트리 + XData 태그**: 선택한 한 인스턴스만 지우고 재계산 재생성("기존 지우고 재생성"). 단일 인스턴스엔 간단·견고. 다중 인스턴스 동시 갱신은 안 됨.
- → 레일을 어떻게 태그/검색할지가 (a)/(b)에 따라 달라지므로 **초기에 확정**.

### 대안: LM에 의존하지 않는 외부 생성기 (검토 가치 있음)
이 저장소는 **이미 Python + ezdxf**를 사용한다(CadToMap 파이프라인). 레일 지오메트리(RailGeom/RailGeom3)를 **Python으로 생성해 DXF 블록으로 내보내고 LM에 `INSERT`** 하면 CAD API 의존이 0이 된다. 인캐드 실시간 편집은 없고 "원하는 길이로 재생성" 방식이지만, 기존 스택을 재활용하고 에디션/라이선스에 전혀 묶이지 않는 장점. LISP 재구현과 병행 검토 권장.

---

## (참고 보존) 게이트 ⚠️ : LM 에디션이 .NET(ZRX.NET)을 지원하는가?

ZWCAD KOREA 공식 LM 페이지 문구 (그대로 인용):

> **"ZWCAD LM : MFG 제조/기계 분야 제한(Limited) 버전으로 타 분야 기능, 3D, 응용 프로그램 & 리습, 기계 전문 기능이 일부 제한됩니다."**

즉 LM은 **"응용 프로그램 & 리습"이 일부 제한**되는 에디션이다. 에디션별 API 지원을 종합하면:

| 에디션 | .NET / ZRX / VBA | LISP | 비고 |
|--------|:---:|:---:|------|
| Standard (LT) | ✗ 없음 | ✓ | LISP만 |
| Professional (FULL) | ✓ 전체 | ✓ | .NET/ActiveX/COM 명시 지원 |
| MFG (Mechanical) | ✓ 전체 | ✓ | FULL + 기계 기능 |
| **LM (Limited Manufacturing)** | **? 제한** | **일부 제한** | MFG에서 3D·응용·LISP 일부 제한 |

- 공식/리셀러 어디에도 **LM이 .NET/ZRX를 지원한다는 명시가 없다.** FULL만 ".NET, ActiveX, COM"을 명시.
- "응용 프로그램 & 리습이 일부 제한" = LISP조차 제한된다는 뜻 → .NET/ZRX 표면은 더 좁을 가능성.
- **LM이 .NET 모듈(NETLOAD)을 아예 못 올린다면, 아래의 네임스페이스 교체·리본 재작성 등 모든 세부는 무의미해진다.**

### ▶ 최우선 액션 (블로킹)
ZWCAD KOREA / 배급사에 다음을 문의해 확정:
1. **"ZWCAD LM에서 .NET(ZRX.NET) 커스텀 명령 DLL을 `NETLOAD`로 로드할 수 있는가?"**
2. 가능하다면 **Overrule / GripOverrule** 및 **리본 커스터마이징 .NET API**가 LM에서도 동작하는지.

이 답에 따라 두 갈래로 갈린다:
- **(A) LM이 .NET 지원** → 아래 기술 이식 계획대로 포팅.
- **(B) LM이 .NET 미지원** → ① **Professional / MFG로 라이선스 상향**, 또는 ② LM의 (제한된) **LISP로 재구현**. 사용자가 이미 LM 라이선스를 구매했다면 이 트레이드오프를 먼저 결정해야 함.

---

## (A안 전제) ZWCAD .NET API는 AutoCAD와 매우 유사

ZWCAD의 .NET API(=**ZRX.NET**)는 AutoCAD ObjectARX .NET을 의도적으로 미러링한다. ZWSOFT는 "자주 쓰이는 .NET API를 거의 다 커버, 대부분의 앱을 쉽게 이식 가능"이라고 공식 홍보하며, 실사용 개발자 후기도 **"네임스페이스만 바꾸면 대부분 그대로 동작"**이라고 보고.

| 항목 | AutoCAD (현재) | ZWCAD |
|------|----------------|-------|
| 네임스페이스 | `Autodesk.AutoCAD.*` | `ZwSoft.ZwCAD.*` |
| 관리형 DLL | `acmgd` / `acdbmgd` / `accoremgd` | `ZwManaged.dll` / `ZwDatabaseMgd.dll` |
| UI/리본 DLL | `AdWindows.dll` | `ZcWindows.dll` / `ZdWindows.dll` / `ZcCui.dll` |
| Interop | — | `ZwSoft.ZwCAD.Interop*.dll` |
| NuGet | (Autodesk.AutoCAD.NET) | `ZWCAD.NetApi` (예: 20.25.0 = ZWCAD 2025) |

이 플러그인에서 쓰는 대부분의 타입은 1:1 대응이 존재한다: `CommandMethod`/`CommandClass`/`ExtensionApplication`, `Transaction`·`BlockTable`·`BlockTableRecord`·`BlockReference`, `XData`·`ResultBuffer`·`TypedValue`·`DxfCode`, `Line`·`Arc`·`Point3d`·`Vector3d`, `Editor.GetPoint/GetEntity/GetDouble`, `RegAppTable` 등.

---

## 기술 블로커 (위험도 순)

### 1. .NET 타겟 재지정: `net8.0-windows` → `net48` — ✅ 확실·기계적
- ZWCAD .NET API는 **.NET Framework** 기반이다. .NET 8 / .NET Core 아님.
  - ZWCAD 2021 = .NET 4.6.1, ZWCAD 2025 NuGet(`ZWCAD.NetApi 20.25.0`) = **.NET Framework 4.7/4.8**.
- 현재 `.csproj`의 `<TargetFramework>net8.0-windows</TargetFramework>` → **`net48`** 로 변경.
- 참조 4개(acmgd/acdbmgd/accoremgd/AdWindows)를 ZWCAD DLL(ZwManaged/ZwDatabaseMgd/ZcWindows 등)로 교체.
- 리본 아이콘의 WPF 코드(`RenderTargetBitmap`, `DrawingVisual`, `System.Windows.Media`)는 **net48에서 그대로 동작**(WPF는 .NET Framework 3.0+). `<UseWPF>true</UseWPF>` 유지.
- 리스크 낮음 — 프레임워크 다운타겟 + 참조 교체 + 네임스페이스 치환 수준.

### 2. 리본 UI 재작성 (`RibbonBuilder`) — ⚠️ 중간, 재작성 필요
- 현재 코드는 `Autodesk.Windows.ComponentManager.Ribbon`, `RibbonTab`, `RibbonPanelSource`, `RibbonButton`(AdWindows.dll)에 직접 의존.
- ZWCAD도 **2021+부터 .NET 리본 API**로 탭/패널/버튼 추가·삭제·편집을 지원하지만, **네임스페이스/어셈블리가 다르다**(`ZcWindows.dll`/`ZdWindows.dll`, `Autodesk.Windows` 아님).
- 따라서 `RibbonBuilder`는 find-replace가 아니라 **ZWCAD 리본 API로 재작성**. 최악의 경우 리본 대신 CUI/메뉴 커스터마이징으로 대체 가능(명령 자체는 항상 타이핑으로 동작하므로 UI는 부가 기능).

### 3. Overrule / GripOverrule — 🔴 최고 위험·미확인
- 커스텀 그립(`RailGripOverrule : GripOverrule`, `RailGrip : GripData`) + `PluginApp`의 `Overrule.AddOverrule(...)`가 **양 끝 드래그 리사이즈**의 핵심.
- **ZWCAD가 .NET Overrule/GripOverrule을 지원하는지 공식 문서에서 확인되지 않음**(검색 2회 모두 비확정). Overrule은 고급/니치 API라 ZWCAD 미구현 가능성 존재.
- 권장: **가장 먼저 Overrule 스파이크**(엔티티 1종에 DrawOverrule/GripOverrule 최소 예제)를 만들어 동작 여부 검증.
- **폴백이 이미 존재해 리스크가 크게 완화됨** → 그립이 안 되면 커스텀 그립을 버리고, 코드에 이미 있는 **`RAILLEN` 명령**(레일 선택 → 새 길이 입력 → 재정의)으로 리사이즈. 기능 손실은 "드래그 UX"뿐, 리사이즈 자체는 유지.

---

## 권장 실행 순서

1. **[게이트]** 배급사에 LM의 .NET/ZRX 로드 가능 여부 확인. → 미지원이면 Pro/MFG 상향 또는 LISP 재구현 결정.
2. **[스파이크]** net48 프로젝트 생성, `ZwManaged`/`ZwDatabaseMgd` 참조, 네임스페이스 `Autodesk.AutoCAD`→`ZwSoft.ZwCAD` 치환, **`DRAWRAIL2` 하나만** 포팅해 `NETLOAD`로 로드·실행 검증.
3. **[스파이크]** Overrule/GripOverrule 동작 검증 → 실패 시 `RAILLEN` 폴백 확정.
4. 리본(`RibbonBuilder`) ZWCAD API로 재작성(또는 CUI 대체).
5. 나머지 명령(`DRAWRAIL3`, `RAILLEN`, 테스트 명령) 전체 포팅 + 헤드리스 검증 방식(accoreconsole 대응 = ZWCAD의 헤드리스/스크립트 실행) 확인.

## 판단 요약
- **AutoCAD → ZWCAD 이식 자체는 가능** (네임스페이스 교체 + net48 다운타겟 + 리본 재작성 + Overrule 검증).
- **단, "LM 에디션"이라는 조건이 붙으면 불확실** — LM의 응용프로그램 API 제한이 게이트. 이걸 먼저 확정할 것.

---

### 출처
- ZWCAD KOREA LM 제품 페이지 — https://zwsoft.co.kr/product-a/ZWCAD_LM.asp
- ZWCAD 에디션 비교(리셀러) — https://softpln.com/zwcad/ , https://softchoice.co.kr/product/zwcad-2023-lmlimited-manufacturing/4253/display/2/
- ZWCAD 글로벌 가격/에디션(.NET/ZRX 지원 표기) — https://www.zwsoft.com/product/zwcad/pricing
- ZWCAD.NetApi NuGet(타겟 프레임워크·DLL 목록) — https://www.nuget.org/packages/ZWCAD.NetApi/20.25.0
- ZWCAD 개발 지원(ZRX.NET 등 API 목록) — https://www.zwsoft.com/support/zwcad-devdoc
- ZWCAD 2021 리본 .NET 커스터마이징 — https://www.zwsoft.com/news/corporate/customize-your-zwcad-2021-easy-peasy
- .NET 이식 후기(네임스페이스만 변경) — https://www.zwsoft.com/zwcad/expert-review/zwcad-great-compatibility-easy-online-workflow-and-impressive-net-api
