#!/usr/bin/env bash
# build-rpm.sh — bangun .rpm dari source. Jalankan dari root repo.
#   ./packaging/linux/build-rpm.sh
set -euo pipefail

VERSION="$(python3 "$(dirname "$0")/../get-version.py")"
RELEASE="$(python3 "$(dirname "$0")/../get-release.py")"
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
rpmbuild -ba --define "ver ${VERSION}" --define "rel ${RELEASE}" \
  "${TOPDIR}/SPECS/${NAME}.spec"

echo ""
echo "RPM siap:"
find "${TOPDIR}/RPMS" -name "${NAME}-${VERSION}-${RELEASE}*.rpm"
echo ""
echo "Versi build ini: ${VERSION}-${RELEASE}"
echo "Install/upgrade (tiap build punya release unik dari git):"
echo "  sudo dnf install ./${NAME}-${VERSION}-${RELEASE}*.noarch.rpm"
