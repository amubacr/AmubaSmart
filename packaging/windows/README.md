# Build Installer Windows (1 file, self-contained)

Hasil akhir: **`AmubaSMART-Setup-0.1.0.exe`** — satu installer klik-next yang
sudah memuat Python runtime, PyQt6, semua Qt DLL, dan `smartctl.exe`. Mesin
target **tidak perlu** memasang Python maupun smartmontools.

## Yang perlu diinstall sekali di mesin BUILD (bukan mesin target)

| Alat | Kegunaan | Sumber |
|------|----------|--------|
| Python 3.11+ | interpreter + PyQt6 | python.org |
| Inno Setup 6 | membungkus jadi installer | jrsoftware.org/isdl.php |
| smartmontools | diambil binary-nya untuk di-bundle | smartmontools.org |

## Langkah build

```powershell
# 0. (sekali) ambil smartctl.exe ke folder bundle
powershell -ExecutionPolicy Bypass -File packaging\windows\fetch-smartmontools.ps1

# 1. build end-to-end: test -> PyInstaller -> Inno Setup
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

Selesai. Installer ada di `Output\AmubaSMART-Setup-0.1.0.exe`.

## Kenapa onedir + Inno Setup, bukan PyInstaller `--onefile`?

"Satu file" yang dilihat teknisi adalah **installer**-nya. Itu urusan distribusi,
bukan runtime. Untuk aplikasi yang **minta hak Administrator (UAC)**, exe onefile
justru bermasalah:

1. **AV/enterprise sering blokir eksekusi elevated dari `%TEMP%`.** Onefile
   mengekstrak diri ke `%TEMP%\_MEIxxxx` setiap start; saat dielevasi, sebagian
   environment korporat menolaknya.
2. **Start lebih lambat** (ekstraksi tiap run) — kerasa saat keliling nge-scan
   banyak PC.
3. **False-positive antivirus** lebih sering pada exe onefile PyInstaller.

Inno Setup tetap menghasilkan satu `Setup.exe`, jadi kita dapat "1 file untuk
dibagikan" **tanpa** kelemahan onefile saat app berjalan. Kode `_bundled_smartctl()`
tetap mengenali kedua layout (onedir & `sys._MEIPASS`), jadi kalau nanti kamu
memang mau onefile, tinggal ganti spec — logika pencarian smartctl tidak berubah.

## Lisensi (WAJIB dibaca)

`smartmontools` berlisensi **GPL-2.0**. Mendistribusikan binary-nya boleh, tapi
kamu wajib:
- menyertakan teks lisensi GPL (installer menampilkan `COPYING-smartmontools.txt`
  saat setup — sudah diatur di `.iss`), dan
- menawarkan akses ke source code smartmontools.

Aplikasi AmubaSMART memanggil `smartctl.exe` sebagai **proses terpisah**
(bukan me-link kodenya), sehingga kode AmubaSMART sendiri tidak otomatis tertular
GPL. Tetap sertakan pemberitahuan lisensi ini pada rilis.

## Signing (opsional tapi disarankan)

Tanpa **code signing certificate**, Windows SmartScreen akan menampilkan
peringatan "Unknown publisher" pada installer. Untuk pemakaian di banyak PC klien,
sebuah sertifikat (OV/EV) menghilangkan peringatan itu dan menurunkan
false-positive AV. Tanda tangani **dua-duanya**: `dist\AmubaSMART\AmubaSMART.exe`
(sebelum Inno Setup) dan `Output\...Setup.exe` (setelahnya), pakai `signtool`.

## Checklist verifikasi di mesin bersih

Uji di Windows yang **belum** pernah ada Python/smartmontools:

- [ ] Installer jalan tanpa error, menampilkan lisensi GPL.
- [ ] Shortcut Start Menu & Desktop terbuat.
- [ ] Klik app -> prompt UAC muncul -> tabel disk terisi (artinya `smartctl.exe`
      bundle kebaca).
- [ ] Cek log/detail: path smartctl menunjuk ke `{app}\smartmontools\` atau
      `{app}\`, **bukan** `C:\Program Files\smartmontools`.
- [ ] Uninstall via Add/Remove Programs bersih.
