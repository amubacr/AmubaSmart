#!/usr/bin/env bash
# build-rpm.sh — bangun .rpm dari source. Jalankan dari root repo.
#   ./packaging/linux/build-rpm.sh
set -euo pipefail

VERSION=0.1.0
NAME=amubasmart
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TOPDIR="${HOME}/rpmbuild"

command -v rpmbuild >/dev/null || {
  echo "rpmbuild belum ada: sudo dnf install rpm-build python3-devel" >&2; exit 1; }

mkdir -p "${TOPDIR}"/{SOURCES,SPECS,BUILD,RPMS,SRPMS}

# Bikin tarball source dengan prefix folder yang cocok dgn %autosetup.
TARBALL="${TOPDIR}/SOURCES/${NAME}-${VERSION}.tar.gz"
tmp="$(mktemp -d)"
stage="${tmp}/${NAME}-${VERSION}"
mkdir -p "$stage"
# Sertakan HANYA yang dibutuhkan paket (bukan .git, dist, venv, dll).
cp -a "$ROOT/amubasmart" "$stage/"
cp -a "$ROOT/packaging" "$stage/"
cp -a "$ROOT/README.md" "$stage/" 2>/dev/null || echo "AmubaSMART" > "$stage/README.md"
cp -a "$ROOT/LICENSE" "$stage/" 2>/dev/null || echo "MIT" > "$stage/LICENSE"
# Buang cache python biar tarball bersih.
find "$stage" -name __pycache__ -type d -prune -exec rm -rf {} +
tar -C "$tmp" -czf "$TARBALL" "${NAME}-${VERSION}"
rm -rf "$tmp"

cp "$ROOT/packaging/linux/${NAME}.spec" "${TOPDIR}/SPECS/"
rpmbuild -ba "${TOPDIR}/SPECS/${NAME}.spec"

echo ""
echo "RPM siap:"
find "${TOPDIR}/RPMS" -name "${NAME}-${VERSION}*.rpm"
echo ""
echo "Install lokal (dnf urus dependency otomatis):"
echo "  sudo dnf install ./${NAME}-${VERSION}-1.*.noarch.rpm"
