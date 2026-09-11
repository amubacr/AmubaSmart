#!/usr/bin/env bash
# install-helper.sh — pasang helper privileged + policy polkit TANPA paket RPM/.deb.
#
# KAPAN dipakai: hanya kalau kamu menjalankan AmubaSMART dari source (tanpa
# install RPM/.deb). Kalau kamu pakai RPM/.deb, JANGAN jalankan script ini —
# paket sudah memasang helper di /usr/libexec, dan menaruh salinan kedua bikin
# pkexec bingung (path tak cocok dengan policy -> cache password mati).
#
#   sudo ./packaging/install-helper.sh             # install / update
#   sudo ./packaging/install-helper.sh --uninstall
set -euo pipefail

# Sengaja SAMA dengan lokasi paket RPM/.deb (/usr/libexec, bukan /usr/local)
# supaya path yang dieksekusi pkexec cocok dengan annotate di policy -> cache jalan.
HELPER_DST=/usr/libexec/amubasmart/amubasmart-helper
POLICY_DST=/usr/share/polkit-1/actions/id.amubasmart.helper.policy
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

[ "$EUID" -eq 0 ] || { echo "Jalankan pakai sudo." >&2; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$HELPER_DST" "$POLICY_DST"
  rmdir --ignore-fail-on-non-empty "$(dirname "$HELPER_DST")" 2>/dev/null || true
  # Bersihkan juga lokasi lama (/usr/local) dari versi script sebelumnya.
  rm -rf /usr/local/libexec/amubasmart
  echo "Helper & policy dihapus."
  exit 0
fi

# Tabrakan check: kalau paket RPM/.deb sudah memasang AmubaSMART, script ini
# tak diperlukan dan malah bisa menimpa file milik paket.
if command -v rpm >/dev/null && rpm -q amubasmart >/dev/null 2>&1; then
  echo "Paket 'amubasmart' sudah terpasang via RPM — helper sudah ada." >&2
  echo "Script ini TIDAK diperlukan. Batal." >&2
  exit 1
fi
if command -v dpkg >/dev/null && dpkg -s amubasmart >/dev/null 2>&1; then
  echo "Paket 'amubasmart' sudah terpasang via .deb — helper sudah ada." >&2
  echo "Script ini TIDAK diperlukan. Batal." >&2
  exit 1
fi

command -v smartctl >/dev/null || { echo "smartctl belum ada: dnf install smartmontools" >&2; exit 1; }

# Bersihkan lokasi lama /usr/local (dari versi script sebelumnya) supaya tak ada
# dua helper yang bertabrakan.
if [ -e /usr/local/libexec/amubasmart ]; then
  echo "Membersihkan helper lama di /usr/local/libexec/amubasmart ..."
  rm -rf /usr/local/libexec/amubasmart
fi

# COPY (bukan symlink) ke lokasi root-owned: kalau symlink ke folder home,
# siapa pun yang bisa edit file di home = bisa jalanin kode sebagai root.
install -D -m 0755 -o root -g root "$SRC_DIR/amubasmart/smart_helper.py" "$HELPER_DST"
install -D -m 0644 -o root -g root "$SRC_DIR/packaging/id.amubasmart.helper.policy" "$POLICY_DST"

# Policy source sudah menunjuk /usr/libexec (= HELPER_DST), jadi path di annotate
# COCOK -> pkexec pakai action kita (auth_admin_keep) -> password di-cache ~5 menit.

# SELinux (Fedora enforcing): pastikan label file sesuai lokasi barunya.
command -v restorecon >/dev/null && restorecon -v "$HELPER_DST" "$POLICY_DST"

echo "OK — helper terpasang di $HELPER_DST"
echo "Ulangi script ini setiap kali smart_helper.py diubah."
