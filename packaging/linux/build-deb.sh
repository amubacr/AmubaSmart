#!/usr/bin/env bash
# build-deb.sh — bangun .deb dari source. Jalankan dari root repo.
#   ./packaging/linux/build-deb.sh
# Prasyarat: sudo apt install devscripts debhelper dh-python build-essential
set -euo pipefail

NAME=amubasmart
VERSION="$(python3 "$(dirname "$0")/../get-version.py")"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

command -v dpkg-buildpackage >/dev/null || {
  echo "Butuh: sudo apt install devscripts debhelper dh-python build-essential" >&2; exit 1; }

# Guard konsistensi versi: dpkg mengambil versi dari debian/changelog, BUKAN dari
# $VERSION. Kalau changelog tertinggal dari __init__.py, .deb-nya bakal salah versi
# tanpa peringatan. Cegah di sini.
CHANGELOG_VER="$(sed -n '1s/.*(\([0-9.]*\)-.*/\1/p' "$ROOT/packaging/linux/debian/debian/changelog")"
if [ "$CHANGELOG_VER" != "$VERSION" ]; then
  echo "VERSI TIDAK COCOK: __init__.py=$VERSION tapi debian/changelog=$CHANGELOG_VER" >&2
  echo "Tambahkan entri changelog untuk $VERSION dulu (lihat dch atau edit manual)." >&2
  exit 1
fi

BUILD="$(mktemp -d)/${NAME}-${VERSION}"
mkdir -p "$BUILD"
cp -a "$ROOT/amubasmart" "$BUILD/"
cp -a "$ROOT/packaging" "$BUILD/"
cp -a "$ROOT/README.md" "$BUILD/" 2>/dev/null || echo "AmubaSMART" > "$BUILD/README.md"
cp -a "$ROOT/packaging/linux/debian/debian" "$BUILD/debian"
find "$BUILD" -name __pycache__ -type d -prune -exec rm -rf {} +

( cd "$BUILD" && dpkg-buildpackage -us -uc -b )

echo ""
echo ".deb siap:"
find "$(dirname "$BUILD")" -maxdepth 1 -name "*.deb"
echo ""
echo "Install (apt urus dependency otomatis):"
echo "  sudo apt install ./${NAME}_${VERSION}-1_all.deb"
