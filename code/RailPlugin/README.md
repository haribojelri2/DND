# RailPlugin — AutoCAD 2026 용 레일 플러그인

이 폴더가 **원본**이다. ZWCAD 판(`code/RailPluginZw`)은 빌드 시 여기 `*.cs` 를
네임스페이스만 치환해 컴파일하므로, 기능 수정은 항상 여기서만 한다.

## 배포 — 설치 프로그램(권장)

```powershell
powershell -ExecutionPolicy Bypass -File build_installer.ps1
```

→ `dist\RailPluginSetup.exe` (약 8.1MB). **이 파일 하나만 전달**하면 되고, 받는 사람은 더블클릭만 하면 된다.

설치 프로그램이 하는 일:

1. 내장된 DLL + 부품 DXF 를 `%APPDATA%\Autodesk\ApplicationPlugins\RailPlugin.bundle\Contents` 에 풀고
2. 번들 매니페스트 `PackageContents.xml` 을 함께 풀어놓는다 →
   `LoadOnAutoCADStartup="True"` 라 **AutoCAD 켤 때마다 자동 로드**(NETLOAD 불필요)
3. AutoCAD 가 이미 실행 중이면 **COM(`AutoCAD.Application`)으로 즉시 로드**

관리자 권한이 필요 없고(`%APPDATA%` 만 사용), 레지스트리는 건드리지 않는다.
`ApplicationPlugins` 는 AutoCAD 가 기본 신뢰하는 위치라 `TRUSTEDPATHS` 등록도 불필요하다.
(ZWCAD 판은 `.bundle` 자동 로드가 없어 로더 LSP + 시작 도구 모음 레지스트리 등록이 필요하다 — 그게 유일한 차이.)

| 옵션 | 동작 |
|---|---|
| (없음) | 설치 후 결과 대화상자 |
| `/silent` | 대화상자 없이 설치 |
| `/uninstall` | 매니페스트 삭제로 자동 로드 해제 + 번들 폴더 제거 |

결과 로그: `%APPDATA%\Autodesk\ApplicationPlugins\RailPlugin.bundle\setup.log`

> AutoCAD 가 켜져 있으면 DLL 이 잠겨 **갱신이 막힌다**(부품 DXF·매니페스트는 갱신되고 DLL 만 기존본 유지).
> 이 경우 설치 프로그램이 경고를 띄우니, AutoCAD 를 종료하고 한 번 더 실행하면 된다.

## 개발용 빌드 · 배포

```powershell
# 빌드만
dotnet build RailPlugin.csproj -c Release -p:Platform=x64

# 빌드 + 번들 폴더로 바로 복사 (AutoCAD 종료 상태에서)
powershell -File deploy.ps1
```

AutoCAD 관리 어셈블리는 `C:\Program Files\Autodesk\AutoCAD 2026` 에서 참조한다(csproj 의 `HintPath`).

`Installer\` 는 별도 프로젝트(`RailPluginSetup`, net48)다. 본체는 `net8.0-windows` 라
`ProjectReference` 로 걸 수 없어 `build_installer.ps1` 이 순서대로 빌드한다.

## 명령

| 명령 | 기능 |
|---|---|
| `DRAWRAILV` | 레일 변형 생성 (2차선 8종 / 3차선 12종 / 4차선 18종). 이름 = `레일 네이밍 규칙.xlsx` (`R{차선}_W{N분기폭}_{H}H_{N}N_{D}D`) |
| `RAILPART` | 부품 블록 삽입 |
| `RAILW` | 레일 폭 변경 |
| `RAILLEN` | 길이 재지정(그립 대신 명령으로 정확히) |
| `RAILFIX` | 보정 |
| `RAILCOUNT` | 부품 수량 집계 |
| `CAD2MAP` | 현재 도면을 **저장 없이** DXF 로 내보내(저장 위치는 대화상자에서 지정) CAD→MAP 변환기(`DXFtoMAP.exe`)를 그 파일로 연다 — 리본 'CAD→MAP 변환기' 버튼과 동일. map 은 DXF 와 같은 폴더에 생성 |
| `RAILMODSET` | 모듈 **규격 설정** 대화상자 → 적용하면 이어서 배치 (리본 `Module` > 규격 설정) |
| `RAILMOD` | 저장된 규격으로 모듈 **생성** (리본 `Module` > 모듈 생성) |
| `RAILMODREMOVE` | [모듈 생성] 에 만들어 둔 **규격(버튼) 삭제** — 목록에서 골라 지운다 (리본 `Module` > 규격 삭제) |
| `RAILMODCLEAR` | 규격 목록 통째로 비우기 → [모듈 생성] 패널이 다시 빈 상태가 된다 |
| `RAILMODDEL` | 도면에 그린 모듈 삭제 + 안 쓰는 블록 정의 정리 (명령으로만) |
| `RAILMODP` | 규격을 명령창으로 입력 (대화상자를 못 쓰는 환경·스크립트용) |
| `RAILMODEDIT` | 이미 그린 모듈의 규격 변경 |
| `RAILMODTEST` / `RAILMODSPECTEST` / `RAILMODJOINTEST` | 헤드리스 검증용 |

## 기본 모듈 (리본 `Module` 탭)

「기본 모듈 정의.pptx」의 표준 분기 8종 + 특수 분기 7종을 **파라미터로 계산해** 그린다
(고정 블록이 아니라 코드 생성이라 임의 치수로 만들 수 있다).

리본 구성 — 모듈마다 버튼이 두 곳에 하나씩 있다(5개씩 3줄).

| 패널 | 하는 일 |
|---|---|
| **규격 설정 · 표준/특수 분기** | 모듈 15종 큰 버튼(항상 표시, 아이콘 = 그 모듈의 실제 형상). 누르면 규격 대화상자 → **적용하면 [모듈 생성] 에 항목이 추가되고 이어서 배치**된다 |
| **모듈 생성** | **처음엔 비어 있다.** 규격을 정할 때마다 그 규격의 버튼이 하나씩 늘어난다. 같은 모듈이라도 규격이 다르면 버튼이 따로 생긴다 |
| **편집** | 규격 변경 / **규격 삭제**(만들어 둔 [모듈 생성] 버튼 지우기) / 규격 목록 비우기 |

- 규격 목록은 **도면마다 따로**이고 **저장하지 않는다**. 새 도면을 만들거나 CAD 를 새로 켜면 목록은 비어 있고 규격 초기값은 전부 `0` 이다.
- 버튼 이름은 `CURVE L` 아래에 `R450 L1000` 처럼 그 규격이 붙어 어떤 규격인지 바로 보인다.

- **접속구 그립**: 모듈을 선택하면 **연결되는 끝점마다 그립**이 생긴다. 선의 끝점 그립처럼
  그 점을 잡아 끌면(객체 스냅 사용) 모듈 전체가 따라와 다른 모듈 끝점에 딱 붙는다.
  접속구 = 열린 끝점만 — 본선 중간에 닿는 T 접합점은 제외한다(예: BRANCH LEFT 3개, N LEFT 4개, U 2개).
- **끝점 접합(배치)**: 배치할 때 찍은 지점 근처(500mm 이내)에 기존 레일·모듈의 끝점이 있으면
  기준 접속구(가장 아래, 같으면 왼쪽)가 **그 끝점에 정확히 붙는다**.
- **크기 조절 그립은 없다.** 그립은 이동(접속)만 한다. 치수를 바꾸려면
  `규격 변경`(RAILMODEDIT), 지우려면 `모듈 삭제`(RAILMODDEL).
- **블록 정의는 규격마다 하나** — 같은 규격이면 정의를 공유하고(`RAILMOD_<모듈>_R450_L1000…`),
  **규격이 바뀔 때만 새 정의가 생긴다**. 삭제하면 참조가 없어진 정의도 함께 정리된다.

| 파라미터 | 뜻 | 초기값 |
|---|---|---|
| `R` | 호 반지름 (두 직선에 접하는 원의 반지름) | 0 (직접 입력, 0 보다 커야 함) |
| `L` | 직선(접속 스텁) 길이 | 0 |
| `W` | 레일 간격 / 가로 이동 폭 | 0 (하한까지 자동으로 올라감) |
| `A` | S자 중간 직선과 세로 선 사이의 각도(°) | 0 (쓰는 모듈은 0 보다 커야 함) |

- **표준 분기(R·L)**: CURVE LEFT/RIGHT, BRANCH LEFT/RIGHT, U, DOUBLE BRANCH, U BRANCH LEFT/RIGHT — 아치 계열은 `W` 도 사용.
- **특수 분기(R·L·W·A)**: N LEFT/RIGHT, BY PASS LEFT/RIGHT, S LEFT/RIGHT, Y(R·L).
- 규격은 도면(XData)에도 함께 기록되어 `RAILMODEDIT` 가 현재 값을 읽는다.
- 하한 자동 보정: 아치 계열 `W ≥ 2R`, S 계열 `0 < A < 90` 및 `W ≥ 2R(1−cos A)`.
- 검산: `R=450·A=45°·W=900·L=198.6` 이면 레일조각 1670 = 표준 부품 `BRANCH N` 의 도면 기입 치수와 일치한다.
- 대화상자는 XAML 없이 코드로만 만든다 — `port.ps1` 이 `.cs` 만 옮기므로 ZWCAD 판도 같은 화면이 된다.
| `DRAWRAIL2` / `DRAWRAIL3` | 2/3차선 절차적 생성 |
| `DRAWRAILB3` / `DRAWRAILB4` | 3/4차선 블록 조립 |
| `RAILTEST` / `RAILTEST3` / `RAILTESTM` / `RAILTESTW` | 헤드리스 검증용 |

로드되면 리본에 **Rail** 탭이 생긴다.

## 주의

- `RAILPART` / 블록 조립 명령은 부품 DXF
  (`분기 레일 형상 세트 정리 (레이아웃 설계) v0_260721.dxf`)를 **DLL 과 같은 폴더**에서 찾는다.
  설치 프로그램과 `deploy.ps1` 이 함께 복사한다.
- 리본 'CAD→MAP 변환기' 버튼(`CAD2MAP`)은 **DLL 과 같은 폴더의 `DXFtoMAP.exe`** 를 실행한다(설치 프로그램이 `config.json` 과 함께 풀어둠, `config.json` 은 기존 것이 있으면 보존).
  개발 중 다른 위치의 변환기를 쓰려면 같은 폴더에 `DXFtoMAP.path` 텍스트 파일(첫 줄 = exe 경로)을 둔다.
  변환기 재빌드: `code\` 에서 `python -m PyInstaller DXFtoMAP.spec --noconfirm` → `code\dist\DXFtoMAP.exe` (설치 프로그램이 이 파일을 내장).
- `Installer\PackageContents.xml` 의 `ProductCode` GUID 는 바꾸지 말 것(같은 제품 식별자).
