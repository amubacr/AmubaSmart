# amubasmart.spec — paket RPM untuk Fedora/RHEL.
#
# Filosofi: pakai PyQt6 & smartmontools dari repo distro (bukan di-bundle).
# Di Fedora ini justru yang BENAR — dapat style Breeze gratis, PyQt6 ikut
# update sistem, dan smartmontools di-maintain distro. RPM cukup memasang
# KODE kita + helper + policy polkit.
#
# Build:
#   sudo dnf install rpm-build python3-devel
#   # taruh source jadi tarball di ~/rpmbuild/SOURCES/ (lihat build-rpm.sh)
#   rpmbuild -ba packaging/linux/amubasmart.spec
#
# Hasil: ~/rpmbuild/RPMS/noarch/amubasmart-0.1.0-1.*.noarch.rpm

# Fallback kalau python3-rpm-macros belum menyediakan %python3_sitelib
# (di Fedora normal sudah ada; ini jaring pengaman biar spec portabel).
%{!?python3_sitelib: %global python3_sitelib %(python3 -c "import sysconfig; print(sysconfig.get_path('purelib'))")}

Name:           amubasmart
# Versi di-inject build-rpm.sh via --define "ver X.Y.Z" (dibaca dari
# amubasmart/__init__.py, satu sumber kebenaran). Fallback kalau dibuild manual.
%{!?ver: %global ver 0.0.0}
%{!?rel: %global rel 1}
Version:        %{ver}
Release:        %{rel}%{?dist}
Summary:        Analisa kesehatan SMART untuk SSD/HDD (GUI + CLI)

# Kode AmubaSMART: MIT (sesuaikan kalau beda). Catatan: paket ini TIDAK
# memaketkan smartmontools — ia hanya Requires, jadi GPL smartmontools tidak
# menular ke sini (dipanggil sebagai proses terpisah).
License:        MIT
URL:            https://example.com/amubasmart
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel

# Dependency runtime — dnf akan menariknya otomatis saat install:
Requires:       python3
Requires:       python3-pyqt6
Requires:       python3-reportlab
Requires:       smartmontools
Requires:       polkit
# lsblk (enumerasi disk) berasal dari util-linux (hampir selalu sudah ada).
Requires:       util-linux

%description
AmubaSMART membaca data SMART dari SSD/HDD via smartctl dan menghitung skor
kesehatan yang transparan (bukan "Health %" ajaib dari vendor). Tersedia mode
GUI (PyQt6/Qt6, native KDE Plasma) dan mode CLI untuk server headless / cron /
monitoring. Komponen pembaca berjalan sebagai helper privileged terpisah lewat
polkit (pkexec) — GUI sendiri berjalan sebagai user biasa.

%prep
%autosetup -n %{name}-%{version}

%build
# Murni Python, tidak ada langkah kompilasi.

%install
# --- Kode aplikasi -> /usr/lib/python.../site-packages/amubasmart ---
install -d %{buildroot}%{python3_sitelib}/amubasmart
cp -a amubasmart/*.py %{buildroot}%{python3_sitelib}/amubasmart/
# Aset (logo PDF) — ikut terpasang supaya laporan PDF punya kop.
install -d %{buildroot}%{python3_sitelib}/amubasmart/assets
cp -a amubasmart/assets/* %{buildroot}%{python3_sitelib}/amubasmart/assets/

# --- Helper privileged (root-owned) -> /usr/libexec/amubasmart/ ---
# Beda dari install-helper.sh manual yang pakai /usr/local: paket RPM WAJIB
# pakai /usr/libexec (dikelola paket, bukan /usr/local yang untuk admin lokal).
install -D -m 0755 amubasmart/smart_helper.py \
    %{buildroot}%{_libexecdir}/amubasmart/amubasmart-helper

# --- Launcher CLI/GUI -> /usr/bin/amubasmart ---
install -d %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/amubasmart <<'LAUNCH'
#!/usr/bin/python3
import sys
from amubasmart.__main__ import main
sys.exit(main())
LAUNCH
chmod 0755 %{buildroot}%{_bindir}/amubasmart

# --- Policy polkit (path helper disesuaikan ke /usr/libexec) ---
install -D -m 0644 packaging/id.amubasmart.helper.policy \
    %{buildroot}%{_datadir}/polkit-1/actions/id.amubasmart.helper.policy
# Policy source sudah menunjuk /usr/libexec. sed ini jaring pengaman: kalau
# %{_libexecdir} di suatu distro bukan /usr/libexec (mis. /usr/lib), path di
# annotate ikut disesuaikan supaya tetap COCOK dgn helper -> cache polkit jalan.
sed -i 's|/usr/libexec/amubasmart|%{_libexecdir}/amubasmart|' \
    %{buildroot}%{_datadir}/polkit-1/actions/id.amubasmart.helper.policy

# --- Desktop entry & metadata ---
install -D -m 0644 packaging/amubasmart.desktop \
    %{buildroot}%{_datadir}/applications/amubasmart.desktop

%files
%license LICENSE
%doc README.md
%{python3_sitelib}/amubasmart/
%{_bindir}/amubasmart
%{_libexecdir}/amubasmart/amubasmart-helper
%{_datadir}/polkit-1/actions/id.amubasmart.helper.policy
%{_datadir}/applications/amubasmart.desktop

%changelog
* Thu Sep 11 2025 ITSC Adil Komputer <admin@example.com> - 0.2.0-1
- Fitur baru: ekspor laporan teknis ke PDF (tombol GUI + opsi --pdf di CLI),
  dengan kop logo, badge status berwarna, dan tabel atribut lengkap per disk
- CRC error (ID 199) di-cap WARN, tak lagi memicu KRITIS keliru (masalah kabel)
- PDF: kolom Raw dirapikan (buang notasi ilmiah yang bertabrakan)
- Riwayat scan otomatis (SQLite per serial): lacak pergerakan health, realloc,
  CRC, suhu antar waktu; dialog Riwayat (Ctrl+H) menampilkan tren per drive
- Deteksi flashdisk (USB removable) -> label netral, bukan alarm GAGAL
- Auto-retry flag -d untuk drive di balik USB bridge (dock NVMe JMicron dll)

* Thu Sep 11 2025 ITSC Adil Komputer <admin@example.com> - 0.1.1-1
- Perbaikan skor health: attribute non-keausan (suhu, error-rate, performa) tidak
  lagi menyeret skor (kasus ADATA SU650: 51%% -> 88%%, sejalan CDI/HD Sentinel)
- Skip ZFS zvol (zd*) dari enumerasi disk
- Sistem versi satu-sumber; build script baca versi dari amubasmart/__init__.py

* Wed Sep 10 2025 ITSC Adil Komputer <admin@example.com> - 0.1.0-1
- Rilis awal: GUI PyQt6 + CLI headless, helper polkit, skor kesehatan transparan
