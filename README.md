# AmubaSMART

Analisa kesehatan SMART untuk SSD/HDD — **GUI (PyQt6/Qt6) + CLI**. Menerjemahkan
logika `disk-health.sh` ke Python murni: membaca `smartctl -j`, menghitung skor
kesehatan yang transparan (bukan "Health %" ajaib dari vendor), dan menandai
attribute kritis dengan color coding.

- **GUI** — native KDE Plasma (Fedora), portabel ke Windows.
- **CLI** — `amubasmart --cli`, untuk server headless / SSH / cron / monitoring.
  Tidak menyentuh PyQt6, jadi jalan di mesin tanpa Qt.

Komponen pembaca berjalan sebagai **helper privileged terpisah** (pkexec di
Linux, UAC di Windows); GUI sendiri berjalan sebagai user biasa.

## Jalan cepat dari source (development)

```bash
# Fedora KDE — pakai PyQt6 dari sistem supaya dapat style Breeze
sudo dnf install python3-pyqt6 smartmontools polkit
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

python -m pytest -q          # jalankan test
python main.py               # GUI (sebagai user biasa)
python main.py --cli         # CLI
```

## Mode CLI

```bash
amubasmart --cli                 # tabel ringkasan semua disk
amubasmart --cli /dev/sda        # detail satu disk
amubasmart --cli --json          # output JSON (buat cron/monitoring)
```

Exit code: `0` sehat semua, `1` ada WARN, `2` ada CRIT, `3` error baca.

---

# Build & Distribusi

Tiga target: **Windows (installer .exe)**, **Fedora/RHEL (.rpm)**,
**Debian/Ubuntu (.deb)**. Filosofinya berbeda per platform (lihat catatan di
tiap bagian).

## Windows — installer 1-file (.exe)

Hasil akhir: satu **`AmubaSMART-Setup-0.1.0.exe`** yang sudah memuat Python
runtime, PyQt6, semua Qt DLL, dan `smartctl.exe`. Mesin target **tidak perlu**
memasang Python maupun smartmontools.

### Yang perlu diinstall sekali di mesin BUILD (bukan mesin target)

| Alat | Kegunaan | Sumber |
|------|----------|--------|
| Python 3.11+ | interpreter + PyQt6 | python.org |
| Inno Setup 6 | membungkus jadi installer | jrsoftware.org/isdl.php |
| smartmontools | diambil binary-nya untuk di-bundle | smartmontools.org |

### Langkah build

```powershell
# 0. (sekali) ambil smartctl.exe ke folder bundle
powershell -ExecutionPolicy Bypass -File packaging\windows\fetch-smartmontools.ps1

# 1. build end-to-end: test -> PyInstaller -> Inno Setup
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

Hasil ada di `Output\AmubaSMART-Setup-0.1.0.exe`. Jalankan di mesin bersih untuk
verifikasi.

Kalau ingin manual per-langkah:

```powershell
pyinstaller packaging\windows\AmubaSMART.spec --noconfirm   # -> dist\AmubaSMART\
ISCC.exe packaging\windows\AmubaSMART.iss                    # -> Output\...Setup.exe
```

### Kenapa onedir + Inno Setup, bukan PyInstaller `--onefile`?

"Satu file" yang dibagikan adalah **installer**-nya (urusan distribusi), bukan exe
runtime. Untuk app yang minta UAC (Administrator), onefile bermasalah: ia
mengekstrak diri ke `%TEMP%` tiap start, dan sebagian environment AV/enterprise
**memblokir eksekusi elevated dari `%TEMP%`**. Onedir menghindari itu, start lebih
cepat, dan lebih jarang kena false-positive antivirus. Inno Setup tetap
menghasilkan satu `Setup.exe`, jadi tujuan "1 file" tercapai tanpa kelemahan
onefile. Detail lengkap: `packaging/windows/README.md`.

### Lisensi & signing (penting)

- **smartmontools GPL-2.0**: mendistribusikan binary-nya boleh, tapi wajib
  menyertakan teks lisensi (installer sudah menampilkannya). AmubaSMART memanggil
  `smartctl.exe` sebagai proses terpisah, jadi kode kita tidak tertular GPL.
- **Tanpa code signing**, Windows SmartScreen menampilkan peringatan "Unknown
  publisher". Untuk pemakaian di banyak PC klien, sebuah sertifikat menghilangkan
  peringatan itu.

## Fedora / RHEL — .rpm

```bash
sudo dnf install rpm-build python3-devel
./packaging/linux/build-rpm.sh
sudo dnf install ./~/rpmbuild/RPMS/noarch/amubasmart-0.1.0-1.*.noarch.rpm
```

## Debian / Ubuntu — .deb

```bash
sudo apt install devscripts debhelper dh-python python3-all build-essential
export LC_ALL=C.UTF-8            # cegah warning locale di container/Distrobox
./packaging/linux/build-deb.sh
sudo apt install ./amubasmart_0.1.0-1_all.deb
```

### Kenapa Linux pakai dependency distro, bukan bundle seperti Windows?

Paket Linux hanya **mendeklarasikan** dependency (`Requires`/`Depends`), tidak
mem-bundle. PyQt6 dari distro memberi style Breeze otomatis dan ikut update
keamanan; smartmontools di-maintain distro. Paket jadi kecil (noarch, hanya kode)
dan "benar" secara distro. Detail: `packaging/linux/README.md`.

## Struktur proyek

```
amubasmart/
├── main.py                    # entry point (source & PyInstaller)
├── amubasmart/
│   ├── __main__.py            # dispatch helper/CLI/GUI (dipakai paket terinstall)
│   ├── analysis.py            # logika SMART murni (tanpa Qt/subprocess)
│   ├── cli.py                 # frontend CLI (tanpa PyQt6)
│   ├── main_window.py         # GUI utama
│   ├── detail_dialog.py       # dialog detail per disk
│   ├── worker.py              # QThread backend
│   ├── privilege.py           # deteksi OS, pkexec/UAC
│   ├── smart_helper.py        # komponen privileged (stdlib-only)
│   └── ui_common.py           # util UI (warna tema, sort)
├── packaging/
│   ├── windows/               # PyInstaller spec, Inno Setup, build.ps1
│   ├── linux/                 # RPM spec, debian/, build scripts
│   ├── amubasmart.desktop
│   ├── id.amubasmart.helper.policy
│   └── install-helper.sh      # pasang helper manual (mode dev, non-paket)
└── tests/
```

### PERHATIAN
Project ini masih dalam tahap pengembangan, dimohon untuk tidak menggunakan project ini karena status project masih belum stabil / pre-release
