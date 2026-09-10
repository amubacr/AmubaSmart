# fetch-smartmontools.ps1 — unduh smartctl.exe + DLL resmi ke folder bundle.
#
# Jalankan SEKALI sebelum build (PowerShell, dari root proyek):
#   powershell -ExecutionPolicy Bypass -File packaging\windows\fetch-smartmontools.ps1
#
# Hasil: packaging\windows\smartmontools\{smartctl.exe, *.dll}
# PyInstaller spec akan otomatis memungutnya.
#
# CATATAN LISENSI: smartmontools berlisensi GPL-2.0. Mendistribusikan
# binary-nya diperbolehkan, TAPI kamu wajib menyertakan teks lisensi GPL dan
# menawarkan source. Installer di bawah sudah memasang COPYING-smartmontools.txt.
# Isi $Version & $Url sesuai rilis terbaru dari https://www.smartmontools.org/

$ErrorActionPreference = "Stop"
$Version = "7.4"
$Url  = "https://sourceforge.net/projects/smartmontools/files/smartmontools/$Version/smartmontools-$Version-1.win32-setup.exe/download"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $here "smartmontools"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

Write-Host "Install smartmontools $Version dulu (klik-next), lalu skrip ini menyalin"
Write-Host "smartctl.exe + DLL dari lokasi install ke: $dest"
Write-Host ""

# Cara paling andal & sesuai lisensi: install resmi lalu SALIN binary-nya.
# (Isi installer smartmontools terkompresi NSIS; menyalin dari hasil install
#  jauh lebih aman daripada mengekstrak paksa.)
$src = "C:\Program Files\smartmontools\bin"
if (-not (Test-Path $src)) {
    Write-Host "smartmontools belum terpasang. Mengunduh installer resmi..."
    $tmp = Join-Path $env:TEMP "smartmontools-setup.exe"
    Invoke-WebRequest -Uri $Url -OutFile $tmp
    Write-Host "Menjalankan installer (silent)..."
    Start-Process -FilePath $tmp -ArgumentList "/S" -Wait
}
if (-not (Test-Path $src)) { throw "Folder $src tidak ditemukan setelah install." }

Copy-Item "$src\smartctl.exe" $dest -Force
Copy-Item "$src\*.dll" $dest -Force -ErrorAction SilentlyContinue
Copy-Item "C:\Program Files\smartmontools\doc\COPYING.txt" `
          (Join-Path $here "COPYING-smartmontools.txt") -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Selesai. Isi folder bundle:"
Get-ChildItem $dest | Select-Object Name, Length | Format-Table -AutoSize
