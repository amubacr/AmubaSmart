# build.ps1 — build end-to-end di Windows: dari source -> installer 1-file.
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
#
# Prasyarat (sekali saja): Python 3.11+, Inno Setup 6, dan sudah menjalankan
# fetch-smartmontools.ps1 supaya smartctl.exe ada di folder bundle.

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $root

Write-Host "== 1/4  Venv + dependensi ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { py -m venv .venv }
& .\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt
pip install -q pyinstaller

if (-not (Test-Path "packaging\windows\smartmontools\smartctl.exe")) {
    Write-Warning "smartctl.exe belum ada di folder bundle."
    Write-Warning "Jalankan dulu: packaging\windows\fetch-smartmontools.ps1"
    Write-Warning "Build lanjut, tapi app akan bergantung pada smartctl di PATH sistem."
}

Write-Host "== 2/4  Test cepat ==" -ForegroundColor Cyan
python -m pytest -q

Write-Host "== 3/4  PyInstaller (onedir) ==" -ForegroundColor Cyan
if (Test-Path "dist\DiskHealth") { Remove-Item -Recurse -Force "dist\DiskHealth" }
pyinstaller packaging\windows\DiskHealth.spec --noconfirm

Write-Host "== 4/4  Inno Setup (bungkus jadi 1 installer) ==" -ForegroundColor Cyan
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "ISCC.exe tidak ketemu. Install Inno Setup 6 dari jrsoftware.org." }
& $iscc "packaging\windows\DiskHealth.iss"

Write-Host ""
Write-Host "SELESAI. Installer siap dibagikan:" -ForegroundColor Green
Get-ChildItem "Output\*.exe" | Select-Object Name, @{n="MB";e={[math]::Round($_.Length/1MB,1)}}
