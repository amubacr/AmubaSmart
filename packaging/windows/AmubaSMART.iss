; AmubaSMART.iss — Inno Setup: bungkus folder onedir PyInstaller jadi SATU
; installer klik-next (AmubaSMART-Setup-x.y.z.exe).
;
; Prasyarat build (di Windows):
;   1. venv aktif, lalu: pyinstaller packaging\windows\AmubaSMART.spec --noconfirm
;      -> menghasilkan dist\AmubaSMART\
;   2. Install Inno Setup 6: https://jrsoftware.org/isdl.php
;   3. Compile file ini:  ISCC.exe /DAppVersion=X.Y.Z packaging\windows\AmubaSMART.iss
;      -> menghasilkan Output\AmubaSMART-Setup-<versi>.exe   ← file yang dibagikan
;
; Versi (AppVersion) di-INJECT dari build.ps1 lewat /D, dibaca dari
; amubasmart\__init__.py (satu sumber kebenaran). Kalau compile manual tanpa /D,
; fallback di bawah dipakai supaya tetap jalan.

; Yang di-install SUDAH lengkap: Python runtime, PyQt6, semua Qt DLL, dan
; smartctl.exe. Mesin target TIDAK perlu pasang apa pun lagi.

#define AppName "AmubaSMART"
; AppVersion di-inject build.ps1: ISCC /DAppVersion=X.Y.Z. Fallback kalau manual.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; AppRelease = nomor build unik dari git (development). Ikut di nama file &
; AppVerName supaya tiap build kelihatan beda di Add/Remove Programs.
#ifndef AppRelease
  #define AppRelease "1"
#endif
#define AppPublisher "AmubaSMART"
#define AppExeName "AmubaSMART.exe"

[Setup]
AppId={{7C3A9F2E-4B1D-4E88-9A6C-DISKHEALTH01}}
AppName={#AppName}
AppVersion={#AppVersion}
; AppVerName tampil di Add/Remove Programs — sertakan release biar tiap build beda.
AppVerName={#AppName} {#AppVersion}-{#AppRelease}
AppPublisher={#AppPublisher}
; VersionInfoVersion butuh format X.Y.Z.W — aman untuk metadata file installer.
VersionInfoVersion={#AppVersion}.0
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; App butuh Administrator (baca SMART). Installer per-machine -> perlu admin juga.
PrivilegesRequired=admin
OutputDir=..\..\Output
OutputBaseFilename={#AppName}-Setup-{#AppVersion}-{#AppRelease}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Installer 64-bit; app PyInstaller mengikuti arsitektur Python build.
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; GPL smartmontools ditampilkan saat install (kewajiban lisensi).
LicenseFile=COPYING-smartmontools.txt
UninstallDisplayIcon={app}\{#AppExeName}
; --- Upgrade-aware: install baru MENIMPA folder lama dengan bersih ---
; AppId sama di atas = Inno mengenali instalasi sebelumnya sebagai app yang SAMA,
; jadi upgrade (bukan install ganda). Default DefaultDirName memakai path lama.
; Tutup app yang sedang jalan supaya file .exe tak terkunci saat ditimpa.
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll
RestartApplications=no

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

[Code]
// Deteksi versi lama & tampilkan dialog upgrade sebelum install dimulai.
//
// Inno sudah menangani upgrade secara teknis (AppId sama -> menimpa folder lama),
// tapi user minta KONFIRMASI eksplisit: "versi X sudah terpasang, timpa dengan Y?".
// GetInstalledVersion membaca versi lama dari registry uninstall Inno.

function GetInstalledVersion(): String;
var
  ver: String;
  key: String;
begin
  Result := '';
  // Inno menyimpan info uninstall di sini; {#SetupSetting("AppId")} = AppId kita.
  key := 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\' +
         '{7C3A9F2E-4B1D-4E88-9A6C-DISKHEALTH01}_is1';
  if RegQueryStringValue(HKLM, key, 'DisplayVersion', ver) then
    Result := ver
  else if RegQueryStringValue(HKCU, key, 'DisplayVersion', ver) then
    Result := ver;
end;

function InitializeSetup(): Boolean;
var
  oldVer: String;
  cmp: Integer;
begin
  Result := True;
  oldVer := GetInstalledVersion();
  if oldVer = '' then
    Exit;  // instalasi baru, tak ada yang perlu dikonfirmasi

  cmp := CompareStr(oldVer, '{#AppVersion}');
  if oldVer = '{#AppVersion}' then
  begin
    // Versi sama persis -> tawarkan install ulang (perbaiki file rusak).
    if MsgBox('AmubaSMART versi ' + oldVer + ' sudah terpasang.' + #13#10 +
              'Install ulang (timpa file yang ada)?',
              mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end
  else
  begin
    // Versi beda -> konfirmasi upgrade/downgrade, folder lama akan ditimpa.
    if MsgBox('Versi terpasang saat ini: ' + oldVer + #13#10 +
              'Versi installer ini: {#AppVersion}' + #13#10 + #13#10 +
              'Lanjutkan dan timpa instalasi yang ada?',
              mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;
