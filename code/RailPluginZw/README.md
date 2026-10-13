# RailPluginZw — ZWCAD LM 2026 용 레일 플러그인

AutoCAD 용 `code/RailPlugin` 의 **ZWCAD 판**. 기능·명령·리본은 완전히 동일하다.

## 핵심: 소스는 하나만 유지한다

ZWCAD 판은 별도 소스를 두지 않는다. 빌드할 때 `port.ps1` 이
`../RailPlugin/*.cs` 를 읽어 **네임스페이스만 치환**한 뒤 `generated\` 에 기록하고, 그걸 컴파일한다.

```
code/RailPlugin/*.cs   ──port.ps1(치환)──▶   code/RailPluginZw/generated/*.cs   ──▶  RailPluginZw.dll
   (원본 = 유일한 진실)                          (자동 생성물, 편집 금지, git 제외)
```

기능 수정은 **항상 `code/RailPlugin/` 원본만** 고치면 된다. 다음 빌드에서 ZWCAD 판에 자동 반영된다.

## 포팅 매핑 (ZWCAD LM 2026 Kor 어셈블리 실측 확인)

| AutoCAD 2026 | ZWCAD LM 2026 | 비고 |
|---|---|---|
| `Autodesk.AutoCAD.*` | `ZwSoft.ZwCAD.*` | 네임스페이스 1:1 |
| `Autodesk.Windows.*` | `ZwSoft.Windows.*` | 리본 |
| `acmgd.dll` | `ZwManaged.dll` | |
| `acdbmgd.dll` | `ZwDatabaseMgd.dll` | `GripOverrule`/`GripData` 포함 확인 |
| `accoremgd.dll` | (대응 없음) | 이 플러그인은 미사용 |
| `AdWindows.dll` | `ZdWindows.dll` | `ComponentManager`/`RibbonTab`/`RibbonSplitButton` 등 전부 존재 |
| `net8.0-windows` | `net48` | ZWCAD .NET API 는 .NET Framework 4.7/4.8 |

클래스명·시그니처는 동일해서 **코드 수정은 0줄**이다(빌드 경고 0 / 오류 0).
드래그 리사이즈 그립(`GripOverrule`)도 그대로 동작하는 구조.

## 빌드 · 배포

```powershell
# 빌드만
dotnet build RailPluginZw.csproj -c Release -p:Platform=x64

# 빌드 + %APPDATA%\ZWSOFT\RailPluginZw 로 배포 (ZWCAD 종료 상태에서)
powershell -ExecutionPolicy Bypass -File deploy.ps1
```

ZWCAD 설치 경로는 csproj 가 자동 탐지한다(`refs\` → LM → 일반 → Mechanical 2026).
다른 경로면 `dotnet build -p:ZwDir="C:\Program Files\ZWSOFT\..."`.

### ZWCAD 가 안 깔린 PC 에서 빌드하기

참조 어셈블리 3개만 있으면 된다. `refs\` 폴더를 만들고 넣으면 자동으로 잡힌다.

```
code/RailPluginZw/refs/
    ZwManaged.dll        (ZWCAD 설치 폴더에서 복사)
    ZwDatabaseMgd.dll
    ZdWindows.dll
```

셋 다 런타임이 제공하는 어셈블리라 참조용으로만 쓰이고 배포물에는 포함되지 않는다.

## 배포 — 설치 프로그램(권장)

```powershell
powershell -ExecutionPolicy Bypass -File build_installer.ps1
```

→ `dist\RailPluginZwSetup.exe` (약 8.1MB). **이 파일 하나만 전달**하면 되고, 받는 사람은 더블클릭만 하면 된다.

설치 프로그램이 하는 일:

1. 내장된 DLL + 부품 DXF 를 `%APPDATA%\ZWSOFT\RailPluginZw` 에 풀어놓고
2. NETLOAD 로더 `RailPluginZw_load.lsp` 를 만들어 **APPLOAD 시작 도구 모음**(레지스트리 `Dialogs\Appload\Startup`)에 등록 → ZWCAD 켤 때마다 자동 로드
3. **TRUSTEDPATHS** 에 설치 폴더를 추가 → SECURELOAD 차단 회피
4. ZWCAD 가 이미 실행 중이면 **COM(`ZWCAD.Application`)으로 즉시 로드**

관리자 권한이 필요 없고(HKCU + %APPDATA%), 여러 번 실행해도 중복 등록되지 않는다.
설치된 ZWCAD 프로필을 전부 찾아 등록하므로 제품/버전/언어가 달라도 동작한다.

| 옵션 | 동작 |
|---|---|
| (없음) | 설치 후 결과 대화상자 |
| `/silent` | 대화상자 없이 설치 |
| `/uninstall` | 자동 로드 등록 해제 (파일은 남김) |

결과 로그: `%APPDATA%\ZWSOFT\RailPluginZw\setup.log`

> ZWCAD 가 켜져 있으면 DLL 이 잠겨 **갱신이 막힌다**. 새 버전을 넣을 땐 ZWCAD 를 종료하고 실행할 것.

### 수동으로 로드하려면

- 매번 : `NETLOAD` → `%APPDATA%\ZWSOFT\RailPluginZw\RailPluginZw.dll`
- 자동 : `APPLOAD` → **시작 도구 모음(Startup Suite)** 에 위 DLL 등록

로드되면 리본에 **Rail** 탭이 생긴다.

## 명령

| 명령 | 기능 |
|---|---|
| `DRAWRAILV` | 레일 변형 생성 (2차선 8종 / 3차선 12종 / 4차선 18종). 이름 = `레일 네이밍 규칙.xlsx` (`R{차선}_W{N분기폭}_{H}H_{N}N_{D}D`) |
| `RAILPART` | 부품 블록 삽입 |
| `RAILW` | 레일 폭 변경 |
| `RAILLEN` | 길이 재지정(그립 대신 명령으로 정확히) |
| `RAILFIX` | 보정 |
| `CAD2MAP` | 현재 도면을 **저장 없이** DXF 로 내보내(저장 위치는 대화상자에서 지정) CAD→MAP 변환기(`DXFtoMAP.exe`)를 그 파일로 연다 — 리본 'CAD→MAP 변환기' 버튼과 동일. map 은 DXF 와 같은 폴더에 생성 |
| `RAILMODSET` / `RAILMOD` / `RAILMODDEL` / `RAILMODEDIT` | 기본 모듈 15종: 규격 설정 후 배치 / 저장된 규격으로 배치 / 삭제 / 규격 변경 — 리본 **Module** 탭. 배치 시 기존 끝점에 자동 접합 (자세한 내용은 `code/RailPlugin/README.md`) |
| `DRAWRAIL2` / `DRAWRAIL3` | 2/3차선 절차적 생성 |
| `DRAWRAILB3` / `DRAWRAILB4` | 3/4차선 블록 조립 |
| `RAILTEST` / `RAILTEST3` / `RAILTESTM` | 헤드리스 검증용 |

## 주의

- `RAILPART` / 블록 조립 명령은 부품 DXF
  (`분기 레일 형상 세트 정리 (레이아웃 설계) v0_260721.dxf`)를 **DLL 과 같은 폴더**에서 찾는다.
  `deploy.ps1` 이 함께 복사한다.
- 리본 'CAD→MAP 변환기' 버튼(`CAD2MAP`)은 **DLL 과 같은 폴더의 `DXFtoMAP.exe`** 를 실행한다(설치 프로그램이 `config.json` 과 함께 풀어둠).
  개발 중 다른 위치의 변환기를 쓰려면 같은 폴더에 `DXFtoMAP.path` 텍스트 파일(첫 줄 = exe 경로)을 둔다.
- `generated\` 를 직접 고치면 다음 빌드에서 덮어써진다.
- 치환 규칙 추가가 필요해지면 `port.ps1` 의 `$rules` 에만 넣는다.
