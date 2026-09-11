# build.ps1 — build end-to-end di Windows: dari source -> installer 1-file.
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
#
# Prasyarat (sekali saja): Python 3.11+, Inno Setup 6, dan sudah menjalankan
# fetch-smartmontools.ps1 supaya smartctl.exe ada di folder bundle.

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $root

# Versi bersih dari __init__.py + release unik dari git (development).
# AppVersion (bersih) dipakai untuk metadata; AppVerName (dgn release) tampil
# di Add/Remove Programs supaya tiap build kelihatan beda & bisa upgrade.
$AppVersion = (python packaging\get-version.py).Trim()
$AppRelease = (python packaging\get-release.py).Trim()
Write-Host "Versi build: $AppVersion-$AppRelease" -ForegroundColor Cyan

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
# PENTING: hapus dist\ DAN build\. Folder build\ berisi cache bytecode
# PyInstaller — kalau tidak dihapus, rebuild bisa memakai kode LAMA walau
# source sudah berubah (jebakan klasik: fix di .py tak muncul di .exe).
# Flag --clean jadi jaring pengaman kedua.
foreach ($dir in @("dist\AmubaSMART", "build")) {
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
}
pyinstaller packaging\windows\AmubaSMART.spec --noconfirm --clean

# Sanity check: pastikan exe hasil build menjalankan kode TERBARU, bukan cache.
# --version cepat & tak butuh disk fisik; kalau exe gagal jalan, hentikan di sini
# daripada terlanjur membungkus installer yang rusak.
Write-Host "Verifikasi exe..." -ForegroundColor Cyan
& "dist\AmubaSMART\AmubaSMART.exe" --version
if ($LASTEXITCODE -ne 0) { throw "AmubaSMART.exe gagal dijalankan (exit $LASTEXITCODE)." }

Write-Host "== 4/4  Inno Setup (bungkus jadi 1 installer) ==" -ForegroundColor Cyan
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "ISCC.exe tidak ketemu. Install Inno Setup 6 dari jrsoftware.org." }
& $iscc "/DAppVersion=$AppVersion" "/DAppRelease=$AppRelease" "packaging\windows\AmubaSMART.iss"

Write-Host ""
Write-Host "SELESAI. Installer siap dibagikan:" -ForegroundColor Green
Get-ChildItem "Output\*.exe" | Select-Object Name, @{n="MB";e={[math]::Round($_.Length/1MB,1)}}
