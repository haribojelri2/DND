# RailPluginZw 배포 스크립트 (ZWCAD LM 2026)
#   원본 소스 치환(port.ps1) → 빌드(x64 Release) → %APPDATA%\ZWSOFT\RailPluginZw 로 DLL + 부품 DXF 복사.
#   ZWCAD 에는 AutoCAD 의 .bundle 자동로드 폴더가 없으므로, 최초 1회만 ZWCAD 에서
#     APPLOAD → "시작 도구 모음(Startup Suite)" 에 이 DLL 을 등록하면 이후 자동 로드된다.
#     (그냥 NETLOAD 로 매번 올려도 동작)
#   ※ ZWCAD 가 켜져 있으면 DLL 이 잠겨 복사 실패 → 먼저 ZWCAD 종료.
# 사용법:  powershell -ExecutionPolicy Bypass -File deploy.ps1
$ErrorActionPreference = "Stop"
$proj = "$PSScriptRoot\RailPluginZw.csproj"
$src  = "$PSScriptRoot\bin\x64\Release\RailPluginZw.dll"
$dstDir = "$env:APPDATA\ZWSOFT\RailPluginZw"
$dst    = "$dstDir\RailPluginZw.dll"

# 1) ZWCAD 실행 중이면 중단 (DLL 잠금)
if (Get-Process ZWCAD -ErrorAction SilentlyContinue) {
    Write-Host "[중단] ZWCAD 실행 중 — 종료 후 다시 실행하세요." -ForegroundColor Red
    exit 1
}

# 2) 빌드 (csproj 의 PreBuild 타깃이 port.ps1 을 먼저 돌려 ../RailPlugin 최신본을 반영)
Write-Host "[1/3] 빌드(net48 / x64 Release)..." -ForegroundColor Cyan
dotnet build $proj -c Release -p:Platform=x64 -v quiet --nologo
if ($LASTEXITCODE -ne 0) { throw "빌드 실패" }

# 3) 복사 (기존본 백업) + 부품 블록 DXF (DRAWRAILB/RAILPART 가 DLL 옆에서 찾음)
if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Force $dstDir | Out-Null }
if (Test-Path $dst) { Copy-Item $dst "$dst.bak" -Force }
Copy-Item $src $dst -Force

$partsDxf = "$PSScriptRoot\..\zwcad_lm\dist\분기 레일 형상 세트 정리 (레이아웃 설계) v0_260721.dxf"
if (Test-Path $partsDxf) {
    Copy-Item $partsDxf $dstDir -Force
} else {
    Write-Host "[경고] 부품 DXF 를 찾지 못했습니다: $partsDxf" -ForegroundColor Yellow
}

Write-Host "[2/3] 배포 완료: $dst (+부품 DXF)" -ForegroundColor Green
(Get-Item $dst | Select-Object LastWriteTime, Length | Format-List | Out-String).Trim()

Write-Host @"
[3/3] ZWCAD 에서:
   최초 1회 : NETLOAD → $dst  (또는 APPLOAD → 시작 도구 모음에 등록하면 이후 자동 로드)
   확인     : 리본 'Rail' 탭, 명령 DRAWRAILV / RAILPART / RAILW / RAILLEN
"@ -ForegroundColor Cyan
