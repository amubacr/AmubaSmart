# Paket Linux — AmubaSMART (RPM & .deb)

AmubaSMART berjalan **dua mode dari satu paket**:

- **GUI** (`amubasmart`) — PyQt6/Qt6, native KDE Plasma. Butuh display.
- **CLI** (`amubasmart --cli`) — mode teks untuk **server headless**, SSH, cron,
  monitoring. Tidak menyentuh PyQt6 sama sekali.

Deteksi otomatis: kalau dijalankan tanpa display (server), `amubasmart` langsung
jatuh ke mode CLI, bukan crash.

## Cara pakai CLI

```bash
amubasmart --cli                 # tabel ringkasan semua disk
amubasmart --cli /dev/sda        # detail satu disk
amubasmart --cli --json          # output JSON (buat cron/monitoring)
amubasmart --cli --json /dev/sda # JSON satu disk
```

Exit code CLI bermakna untuk scripting: `0` sehat semua, `1` ada yang perlu
perhatian (WARN), `2` ada yang kritis (CRIT), `3` error baca. Contoh cron:

```bash
# /etc/cron.daily/cek-disk — alert kalau ada disk CRIT
amubasmart --cli --json > /var/log/amubasmart-$(date +\%F).json || \
  echo "Disk warning di $(hostname)" | mail -s "SMART alert" admin@toko.local
```

## Build RPM (Fedora/RHEL)

```bash
sudo dnf install rpm-build python3-devel
./packaging/linux/build-rpm.sh
```

Hasil di `~/rpmbuild/RPMS/noarch/`. Install:

```bash
# Tingkat 1: bagikan file .rpm langsung. dnf urus dependency otomatis.
sudo dnf install ./amubasmart-0.1.0-1.*.noarch.rpm
```

## Build .deb (Debian/Ubuntu)

```bash
sudo apt install devscripts debhelper dh-python build-essential
./packaging/linux/build-deb.sh
sudo apt install ./amubasmart_0.1.0-1_all.deb
```

## Kenapa pakai dependency distro (bukan bundle)?

Berbeda dari installer Windows yang mem-bundle Python + PyQt6 + smartctl, paket
Linux sengaja hanya **mendeklarasikan** dependency (`Requires`/`Depends`):

- **PyQt6 dari distro** → dapat style Breeze otomatis di KDE, dan ikut update
  keamanan sistem. Bundle PyQt6 sendiri justru sering salah style & tertinggal patch.
- **smartmontools dari distro** → di-maintain distro, tidak ada urusan lisensi GPL
  bundling (dipanggil sebagai proses terpisah).

Paket kita jadi kecil (noarch, hanya kode) dan "benar" secara distro.

## Distribusi lebih luas (opsional, nanti)

- **Fedora COPR** (gratis): upload `.spec`, COPR yang build & hosting. Pengguna:
  `sudo dnf copr enable namamu/amubasmart && sudo dnf install amubasmart`. Update
  ikut `dnf upgrade` otomatis.
- **Ubuntu PPA (Launchpad)**: padanan COPR untuk `.deb`.

Untuk beberapa mesin di toko sendiri, **cukup Tingkat 1** (bagikan file). Naik ke
COPR/PPA hanya kalau butuh distribusi luas atau update otomatis.

## Path terpasang

| Komponen | Lokasi |
|----------|--------|
| Launcher | `/usr/bin/amubasmart` |
| Modul Python | `%{python3_sitelib}/amubasmart/` |
| Helper (root) | `/usr/libexec/amubasmart/amubasmart-helper` |
| Policy polkit | `/usr/share/polkit-1/actions/id.amubasmart.helper.policy` |
| Desktop entry | `/usr/share/applications/amubasmart.desktop` |

Helper dipasang oleh paket (bukan `install-helper.sh` manual), jadi setelah
`dnf install` semuanya langsung siap — password polkit di-cache ~5 menit
(`auth_admin_keep`).
