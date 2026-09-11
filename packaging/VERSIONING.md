# Versioning AmubaSMART (development)

## Ringkas

- **Version** ditulis di satu tempat: `amubasmart/__init__.py` (`__version__`).
- **Release** dihitung OTOMATIS dari git tiap build — tak perlu diketik.
- Hasil: tiap commit menghasilkan versi paket unik, jadi `dnf upgrade` /
  `apt upgrade` selalu menerimanya. Tak perlu `reinstall`/`--reinstall` paksa lagi.

## Cara kerja

`packaging/get-release.py` menjalankan `git describe`:

    0.1.1-9-ga3f2c1
    └tag─┘ │  └hash┘
           └ 9 commit setelah tag 0.1.1

Menghasilkan Release `9.ga3f2c1`. Angka `9` naik tiap commit → selalu "lebih baru".
Kalau ada perubahan belum di-commit, ditambah `.dirty` (tanda build tak bersih).

## Alur harian

    # ngoprek, lalu commit
    git add -A && git commit -m "perbaiki X"

    # build — versi otomatis unik
    ./packaging/linux/build-rpm.sh
    sudo dnf upgrade ./~/rpmbuild/RPMS/noarch/amubasmart-*.noarch.rpm

Tidak perlu edit `__init__.py` untuk tiap rebuild kecil. Cukup commit.

## Kapan menaikkan Version (di __init__.py)?

Hanya saat ada perubahan berarti (SemVer):
- **PATCH** (0.1.1 → 0.1.2): kumpulan perbaikan bug.
- **MINOR** (0.1.x → 0.2.0): fitur baru (mis. ekspor PDF, tes tulis-baca FD).
- Lalu buat tag git yang cocok: `git tag 0.2.0` — supaya `git describe`
  menghitung dari tag terbaru.

## Windows / .deb

Sama: `build.ps1` dan `build-deb.sh` juga membaca release dari git otomatis.
Installer Windows & .deb tiap build dapat nomor unik dan bisa upgrade bersih.
