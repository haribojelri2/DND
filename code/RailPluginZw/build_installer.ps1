# RailPluginZw 설치 프로그램(exe) 빌드
#   원본 소스 치환(port.ps1) → 플러그인 DLL 빌드 → DLL+부품DXF 를 내장한 단일 exe 생성.
#   산출물: Installer\bin\x64\Release\RailPluginZwSetup.exe  (CAD→MAP 변환기 DXFtoMAP.exe 내장, 약 52MB — 이 파일 하나만 배포하면 됨)
#   ※ 변환기(code\dist\DXFtoMAP.exe)가 오래됐으면 먼저 재빌드: code\ 에서  python -m PyInstaller DXFtoMAP.spec --noconfirm
#   ※ ZWCAD 가 켜져 있으면 DLL 이 잠겨 설치 시 갱신이 막히므로, 배포받는 쪽도 ZWCAD 종료 후 실행 권장.
# 사용법:  powershell -ExecutionPolicy Bypass -File build_installer.ps1
$ErrorActionPreference = "Stop"
$core  = "$PSScriptRoot\RailPluginZw.csproj"
$proj  = "$PSScriptRoot\Installer\RailPluginZwSetup.csproj"
$out   = "$PSScriptRoot\Installer\bin\x64\Release\RailPluginZwSetup.exe"
$dist  = "$PSScriptRoot\dist"

# 본체 먼저 (port.ps1 이 AutoCAD 원본 소스를 치환해 가져온다).
#  ※ Installer 에서 ProjectReference 로 걸면 자식 빌드에서 ZwDir 자동 탐지가 안 되므로 여기서 순서대로 빌드.
Write-Host "[1/3] 빌드(본체 → 설치 프로그램)..." -ForegroundColor Cyan
dotnet build $core -c Release -p:Platform=x64 -v quiet --nologo
if ($LASTEXITCODE -ne 0) { throw "본체 빌드 실패" }
dotnet build $proj -c Release -p:Platform=x64 -v quiet --nologo
if ($LASTEXITCODE -ne 0) { throw "설치 프로그램 빌드 실패" }

if (-not (Test-Path $dist)) { New-Item -ItemType Directory -Force $dist | Out-Null }
Copy-Item $out $dist -Force
$f = Get-Item "$dist\RailPluginZwSetup.exe"

Write-Host "[2/3] 배포본: $($f.FullName)" -ForegroundColor Green
Write-Host ("        크기 {0:N1} MB / {1}" -f ($f.Length/1MB), $f.LastWriteTime)

Write-Host @"
[3/3] 사용법
   받는 사람은 RailPluginZwSetup.exe 를 더블클릭하면 끝입니다.
     · %APPDATA%\ZWSOFT\RailPluginZw 에 DLL+부품DXF 설치
     · APPLOAD 시작 도구 모음에 등록 → ZWCAD 켤 때마다 자동 로드
     · 신뢰 경로(TRUSTEDPATHS) 등록 → 보안 차단 회피
     · ZWCAD 가 실행 중이면 COM 으로 즉시 로드
   옵션:  /silent (대화상자 없이)   /uninstall (자동 로드 해제)
   결과 로그: %APPDATA%\ZWSOFT\RailPluginZw\setup.log
"@ -ForegroundColor Cyan
