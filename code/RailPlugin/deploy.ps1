# RailPlugin 배포 스크립트
#   빌드(x64 Release) → %APPDATA% 의 .bundle 자동로드 폴더에 DLL 복사.
#   .bundle 은 LoadOnAutoCADStartup=True 라 AutoCAD 시작 시 자동 로드(NETLOAD 불필요).
#   ※ AutoCAD 가 켜져 있으면 DLL 이 잠겨 복사 실패 → 먼저 AutoCAD 종료.
# 사용법:  powershell -File deploy.ps1
$ErrorActionPreference = "Stop"
$proj   = "$PSScriptRoot\RailPlugin.csproj"
$src    = "$PSScriptRoot\bin\x64\Release\RailPlugin.dll"
$bundle = "$env:APPDATA\Autodesk\ApplicationPlugins\RailPlugin.bundle"
$dst    = "$bundle\Contents\RailPlugin.dll"

# 1) AutoCAD 실행 중이면 중단 (DLL 잠금)
if (Get-Process acad -ErrorAction SilentlyContinue) {
    Write-Host "[중단] AutoCAD 실행 중 — 종료 후 다시 실행하세요." -ForegroundColor Red
    exit 1
}

# 2) 빌드
Write-Host "[1/3] 빌드(x64 Release)..." -ForegroundColor Cyan
dotnet build $proj -c Release -p:Platform=x64 -v quiet --nologo
if ($LASTEXITCODE -ne 0) { throw "빌드 실패" }

# 3) .bundle 없으면 생성(PackageContents.xml 은 최초 1회 수동/여기서 유지)
if (-not (Test-Path "$bundle\Contents")) { New-Item -ItemType Directory -Force "$bundle\Contents" | Out-Null }

# 4) 복사 (기존본 백업) + 부품 블록 DXF 번들 (DRAWRAILB/RAILPART 필요)
if (Test-Path $dst) { Copy-Item $dst "$dst.bak" -Force }
Copy-Item $src $dst -Force
$partsDxf = "$PSScriptRoot\..\zwcad_lm\dist\분기 레일 형상 세트 정리 (레이아웃 설계) v0_260721.dxf"
Copy-Item $partsDxf "$bundle\Contents\" -Force
Write-Host "[2/3] 배포 완료: $dst (+부품 DXF)" -ForegroundColor Green
(Get-Item $dst | Select-Object LastWriteTime, Length | Format-List | Out-String).Trim()
Write-Host "[3/3] AutoCAD 재시작 → DRAWRAILB(베이)/RAILW(폭)/RAILPART(부품)/RAILLEN 확인." -ForegroundColor Cyan
