# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec — build "onedir" (BUKAN onefile) untuk AmubaSMART.
#
# Kenapa onedir, padahal maunya "1 file"?
#   "1 file" yang dilihat teknisi = installer Inno Setup (di bawah). Itu urusan
#   distribusi. Untuk aplikasi yang JALAN, onedir jauh lebih baik daripada exe
#   onefile, KHUSUSNYA di sini karena app minta hak Administrator (UAC):
#
#   1. Onefile mengekstrak diri ke %TEMP%\_MEIxxxx tiap kali start. Saat app
#      di-elevate lewat UAC, %TEMP% jadi milik profil admin, dan sebagian
#      environment AV/enterprise MEMBLOKIR eksekusi dari %TEMP% yang dielevasi.
#   2. Start lebih lambat (ekstraksi tiap run) — kerasa pas keliling nge-scan
#      banyak PC.
#   3. Antivirus lebih sering false-positive ke exe onefile PyInstaller.
#   Inno Setup toh membungkus seluruh folder onedir jadi satu Setup.exe, jadi
#   kita dapat "1 file buat dibagikan" TANPA kelemahan onefile saat runtime.
#
# Build (di Windows, venv aktif):
#   pyinstaller packaging\windows\AmubaSMART.spec --noconfirm
# Output: dist\AmubaSMART\  (berisi AmubaSMART.exe + semua DLL + smartctl)

import os
from pathlib import Path

block_cipher = None

# Root proyek (dua level di atas file spec: packaging\windows\ -> root).
ROOT = Path(SPECPATH).resolve().parents[1]

# Sisipkan smartctl.exe kalau ada di packaging\windows\smartmontools\.
# (Lihat fetch-smartmontools.ps1 untuk mengunduhnya.) Kalau folder ini kosong,
# build tetap jalan — app akan jatuh ke smartctl PATH sistem sebagai fallback.
smart_dir = Path(SPECPATH) / "smartmontools"
smart_binaries = [
    (str(p), "smartmontools")            # (sumber, folder tujuan di dalam bundle)
    for p in smart_dir.glob("*")
    if p.suffix.lower() in (".exe", ".dll")
] if smart_dir.is_dir() else []

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=smart_binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # Pangkas modul Qt yang gak dipakai -> ukuran turun ~30-40 MB & AV lebih adem.
    excludes=[
        "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtQuick3D", "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets", "PyQt6.QtMultimedia", "PyQt6.QtBluetooth",
        "PyQt6.QtNetwork", "PyQt6.QtPositioning", "PyQt6.QtSql", "PyQt6.QtTest",
        "tkinter", "unittest", "pydoc",
    ],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,               # onedir: DLL ditaruh di folder, bukan di exe
    name="AmubaSMART",
    console=False,                       # aplikasi GUI, tanpa jendela console hitam
    # KUNCI: manifest UAC ditanam di exe -> Windows minta elevasi sejak start,
    # jadi relaunch_as_admin_windows() jadi jaring pengaman, bukan jalur utama.
    uac_admin=True,
    disable_windowed_traceback=False,
    icon=str(ROOT / "packaging" / "windows" / "amubasmart.ico")
         if (ROOT / "packaging" / "windows" / "amubasmart.ico").is_file() else None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,              # JANGAN upx: bikin flag antivirus makin sering
    name="AmubaSMART",
)
