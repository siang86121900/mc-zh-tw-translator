# 一次上架多個不在 CurseForge 上的整合包（整包分享）。由擁有者本人執行：上架是公開動作。
# 用法（在專案資料夾的 PowerShell）：.\scripts\publish_full_packs.ps1
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'src;scripts'
$env:PYTHONIOENCODING = 'utf-8'
$python = Join-Path $PSScriptRoot '..\.venv-desktop\Scripts\python.exe'
$drive = 'G:\我的雲端硬碟\Minecraft_mod'
$root = 'C:\Users\User\curseforge\minecraft\Instances'
$packs = @('The Foll v0.3.0', 'Chapter of Yuusha v3.13.15', 'Elemental Awakening v1.4.6', 'VEFV2.7.1')
$failed = @()
foreach ($pack in $packs) {
    Write-Host "`n===== 上架：$pack =====" -ForegroundColor Cyan
    & $python (Join-Path $PSScriptRoot 'publish_translation.py') (Join-Path $root $pack) --full --drive-folder $drive --translator 'MC Translator'
    if ($LASTEXITCODE -ne 0) { $failed += $pack; Write-Host "沒有上架：$pack（原因在上面）" -ForegroundColor Red }
}
if ($failed.Count) { Write-Host "`n沒有上架的：$($failed -join '、')" -ForegroundColor Red } else { Write-Host "`n全部上架完成。" -ForegroundColor Green }
