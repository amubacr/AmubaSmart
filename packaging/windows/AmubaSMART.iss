; AmubaSMART.iss — Inno Setup: bungkus folder onedir PyInstaller jadi SATU
; installer klik-next (AmubaSMART-Setup-x.y.z.exe).
;
; Prasyarat build (di Windows):
;   1. venv aktif, lalu: pyinstaller packaging\windows\AmubaSMART.spec --noconfirm
;      -> menghasilkan dist\AmubaSMART\
;   2. Install Inno Setup 6: https://jrsoftware.org/isdl.php
;   3. Compile file ini:  ISCC.exe packaging\windows\AmubaSMART.iss
;      -> menghasilkan Output\AmubaSMART-Setup-0.1.0.exe   ← file yang dibagikan
;
; Yang di-install SUDAH lengkap: Python runtime, PyQt6, semua Qt DLL, dan
; smartctl.exe. Mesin target TIDAK perlu pasang apa pun lagi.

#define AppName "AmubaSMART"
#define AppVersion "0.1.0"
#define AppPublisher "AmubaSMART"
#define AppExeName "AmubaSMART.exe"

[Setup]
AppId={{7C3A9F2E-4B1D-4E88-9A6C-DISKHEALTH01}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; App butuh Administrator (baca SMART). Installer per-machine -> perlu admin juga.
PrivilegesRequired=admin
OutputDir=..\..\Output
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Installer 64-bit; app PyInstaller mengikuti arsitektur Python build.
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; GPL smartmontools ditampilkan saat install (kewajiban lisensi).
LicenseFile=COPYING-smartmontools.txt
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Buat shortcut di Desktop"; GroupDescription: "Shortcut:"

[Files]
; Seluruh isi folder onedir PyInstaller (exe + DLL + smartctl + Qt plugins).
Source: "..\..\dist\AmubaSMART\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}";        Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";  Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Tawarkan langsung jalankan setelah install. runascurrentuser supaya prompt UAC
; app-nya sendiri yang muncul (bukan mewarisi token installer), konsisten dgn
; cara app dijalankan dari shortcut nanti.
Filename: "{app}\{#AppExeName}"; Description: "Jalankan {#AppName} sekarang"; \
    Flags: nowait postinstall skipifsilent runascurrentuser
