#requires -version 5
<#
  RailPlugin(AutoCAD) → RailPluginZw(ZWCAD) 소스 자동 변환.

  ../RailPlugin/*.cs 를 읽어 네임스페이스만 치환한 뒤 generated\ 에 기록한다.
  즉 ZWCAD 판은 별도 소스를 두지 않는다 — 원본 하나만 고치면 양쪽에 반영된다.
  (generated\ 는 산출물이므로 직접 편집 금지. .gitignore 대상.)

  치환 규칙(ZWCAD LM 2026 Kor 어셈블리 실측 기준):
    Autodesk.AutoCAD.*   → ZwSoft.ZwCAD.*     (ZwManaged.dll / ZwDatabaseMgd.dll)
    Autodesk.Windows.*   → ZwSoft.Windows.*   (ZdWindows.dll — 리본)
  그 외(클래스명·시그니처·XData 앱이름 RAILPLUGIN)는 1:1 동일하므로 손대지 않는다.

  사용법:  powershell -ExecutionPolicy Bypass -File port.ps1
           (deploy.ps1 / 빌드(PreBuild 타깃)에서 자동 호출되므로 보통 직접 실행할 일은 없음)
#>
$ErrorActionPreference = "Stop"

$srcDir = Join-Path $PSScriptRoot "..\RailPlugin"
$genDir = Join-Path $PSScriptRoot "generated"

if (-not (Test-Path $srcDir)) { throw "원본 폴더 없음: $srcDir" }
if (-not (Test-Path $genDir)) { New-Item -ItemType Directory -Force $genDir | Out-Null }

# 치환 맵 (순서 있음)
$rules = @(
    @{ From = 'Autodesk.AutoCAD'; To = 'ZwSoft.ZwCAD'  },
    @{ From = 'Autodesk.Windows'; To = 'ZwSoft.Windows' }
)

$srcFiles = Get-ChildItem $srcDir -Filter *.cs -File   # 최상위만 (bin/obj 제외)
$header = @"
// ============================================================================
//  자동 생성 파일 — 편집하지 마세요.
//  원본: code/RailPlugin/{0}
//  생성: code/RailPluginZw/port.ps1  (Autodesk.AutoCAD → ZwSoft.ZwCAD 치환)
//  고칠 내용은 원본 쪽을 고친 뒤 다시 빌드하면 됩니다.
// ============================================================================
"@

$changed = 0
foreach ($f in $srcFiles) {
    $text = Get-Content $f.FullName -Raw -Encoding UTF8
    foreach ($r in $rules) { $text = $text.Replace($r.From, $r.To) }
    $out = ($header -f $f.Name) + "`r`n" + $text

    $dst = Join-Path $genDir $f.Name
    $old = if (Test-Path $dst) { Get-Content $dst -Raw -Encoding UTF8 } else { $null }
    if ($old -ne $out) {
        # UTF-8 BOM 으로 기록 (한글 주석 안전)
        [System.IO.File]::WriteAllText($dst, $out, (New-Object System.Text.UTF8Encoding($true)))
        $changed++
        Write-Host ("  [갱신] {0}" -f $f.Name)
    }
}

# 원본에서 사라진 파일은 generated 에서도 제거 (stale 방지)
$srcNames = $srcFiles | ForEach-Object { $_.Name }
Get-ChildItem $genDir -Filter *.cs -File | Where-Object { $srcNames -notcontains $_.Name } | ForEach-Object {
    Remove-Item $_.FullName -Force
    Write-Host ("  [삭제] {0} (원본 없음)" -f $_.Name)
}

Write-Host ("[port] 원본 {0}개 → generated 반영, 변경 {1}개" -f $srcFiles.Count, $changed) -ForegroundColor Green
