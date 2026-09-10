# RailPlugin(AutoCAD) 설치 프로그램(exe) 빌드
#   플러그인 DLL 빌드 → DLL+부품DXF+번들 매니페스트를 내장한 단일 exe 생성.
#   산출물: dist\RailPluginSetup.exe  (이 파일 하나만 배포하면 됨)
#   ※ AutoCAD 가 켜져 있으면 DLL 이 잠겨 빌드/설치가 막히므로, 배포받는 쪽도 AutoCAD 종료 후 실행 권장.
# 사용법:  powershell -ExecutionPolicy Bypass -File build_installer.ps1
$ErrorActionPreference = "Stop"
$core = "$PSScriptRoot\RailPlugin.csproj"
$proj = "$PSScriptRoot\Installer\RailPluginSetup.csproj"
$out  = "$PSScriptRoot\Installer\bin\x64\Release\RailPluginSetup.exe"
$dist = "$PSScriptRoot\dist"

# 본체 먼저 (Installer 가 그 산출 DLL 을 리소스로 내장한다).
#  ※ net8.0-windows 본체를 net48 설치기에서 ProjectReference 로 걸 수 없어 여기서 순서대로 빌드.
Write-Host "[1/3] 빌드(본체 → 설치 프로그램)..." -ForegroundColor Cyan
dotnet build $core -c Release -p:Platform=x64 -v quiet --nologo
if ($LASTEXITCODE -ne 0) { throw "본체 빌드 실패" }
dotnet build $proj -c Release -p:Platform=x64 -v quiet --nologo
if ($LASTEXITCODE -ne 0) { throw "설치 프로그램 빌드 실패" }

if (-not (Test-Path $dist)) { New-Item -ItemType Directory -Force $dist | Out-Null }
Copy-Item $out $dist -Force
$f = Get-Item "$dist\RailPluginSetup.exe"

Write-Host "[2/3] 배포본: $($f.FullName)" -ForegroundColor Green
Write-Host ("        크기 {0:N1} MB / {1}" -f ($f.Length/1MB), $f.LastWriteTime)

Write-Host @"
[3/3] 사용법
   받는 사람은 RailPluginSetup.exe 를 더블클릭하면 끝입니다.
     · %APPDATA%\Autodesk\ApplicationPlugins\RailPlugin.bundle 에 DLL+부품DXF 설치
     · 번들 매니페스트(LoadOnAutoCADStartup)로 AutoCAD 켤 때마다 자동 로드 (NETLOAD 불필요)
     · AutoCAD 가 실행 중이면 COM 으로 즉시 로드
   옵션:  /silent (대화상자 없이)   /uninstall (자동 로드 해제 + 폴더 제거)
   결과 로그: %APPDATA%\Autodesk\ApplicationPlugins\RailPlugin.bundle\setup.log
"@ -ForegroundColor Cyan
