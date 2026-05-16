$src = 'G:\我的雲端硬碟\我的AI同步資料夾\receipts\'
$dst2025 = 'C:\Users\user\Documents\GitHub\-\600_Projects\報稅2025\receipts\'
$dst2026 = 'C:\Users\user\Documents\GitHub\-\600_Projects\報稅2026\receipts\'

$files2025 = @(
    '20260516_223756.jpg','20260516_223817.jpg','20260516_223826.jpg','20260516_223843.jpg',
    '20260516_223851.jpg','20260516_223928.jpg','20260516_224041.jpg','20260516_224053.jpg',
    '20260516_224104.jpg','20260516_224117.jpg','20260516_224123.jpg','20260516_224253.jpg',
    '20260516_224300.jpg','20260516_224311.jpg','20260516_224317.jpg','20260516_224326.jpg',
    '20260516_224337.jpg','20260516_224347.jpg','20260516_224400.jpg','20260516_224406.jpg',
    '20260516_224415.jpg','20260516_224425.jpg','20260516_224438.jpg','20260516_224541.jpg',
    '20260516_224547.jpg','20260516_224552.jpg','20260516_224557.jpg','20260516_224605.jpg',
    '20260516_224621.jpg','20260516_224627.jpg','20260516_224635.jpg','20260516_224642.jpg',
    '20260516_224649.jpg','20260516_224743.jpg','20260516_224749.jpg','20260516_224755.jpg',
    '20260516_224801.jpg','20260516_224824.jpg'
)

$files2026 = @(
    '20260516_223411.jpg','20260516_223438.jpg','20260516_223457.jpg','20260516_223514.jpg',
    '20260516_223639.jpg','20260516_223656.jpg','20260516_223705.jpg','20260516_223714.jpg',
    '20260516_223725.jpg','20260516_223738.jpg','20260516_223746.jpg','20260516_223943.jpg',
    '20260516_223953.jpg','20260516_224010.jpg','20260516_224019.jpg','20260516_224027.jpg',
    '20260516_224134.jpg','20260516_224144.jpg','20260516_224156.jpg','20260516_224203.jpg',
    '20260516_224217.jpg','20260516_224226.jpg','20260516_224235.jpg','20260516_224246.jpg'
)

New-Item -ItemType Directory -Force -Path $dst2025 | Out-Null
New-Item -ItemType Directory -Force -Path $dst2026 | Out-Null

$ok2025 = 0
foreach ($f in $files2025) {
    $s = $src + $f
    $d = $dst2025 + $f
    if (Test-Path $s) {
        Copy-Item $s $d -Force
        $ok2025++
    } else {
        Write-Host "NOT FOUND: $s"
    }
}
Write-Host "2025: copied $ok2025 / $($files2025.Count)"

$ok2026 = 0
foreach ($f in $files2026) {
    $s = $src + $f
    $d = $dst2026 + $f
    if (Test-Path $s) {
        Copy-Item $s $d -Force
        $ok2026++
    } else {
        Write-Host "NOT FOUND: $s"
    }
}
Write-Host "2026: copied $ok2026 / $($files2026.Count)"

if ($ok2025 -eq $files2025.Count -and $ok2026 -eq $files2026.Count) {
    Write-Host "ALL OK - deleting source files..."
    foreach ($f in $files2025) { Remove-Item ($src + $f) -Force }
    foreach ($f in $files2026) { Remove-Item ($src + $f) -Force }
    Write-Host "Done."
} else {
    Write-Host "COPY INCOMPLETE - source files kept."
}
