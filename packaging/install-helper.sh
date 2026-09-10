#!/usr/bin/env bash
# install-helper.sh — pasang helper privileged + policy polkit (mode produksi).
#   sudo ./packaging/install-helper.sh             # install / update
#   sudo ./packaging/install-helper.sh --uninstall
set -euo pipefail

HELPER_DST=/usr/local/libexec/diskhealth/diskhealth-helper
POLICY_DST=/usr/share/polkit-1/actions/id.diskhealth.helper.policy
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

[ "$EUID" -eq 0 ] || { echo "Jalankan pakai sudo." >&2; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$HELPER_DST" "$POLICY_DST"
  rmdir --ignore-fail-on-non-empty "$(dirname "$HELPER_DST")" 2>/dev/null || true
  echo "Helper & policy dihapus."
  exit 0
fi

command -v smartctl >/dev/null || { echo "smartctl belum ada: dnf install smartmontools" >&2; exit 1; }

# COPY (bukan symlink) ke lokasi root-owned: kalau symlink ke folder home,
# siapa pun yang bisa edit file di home = bisa jalanin kode sebagai root.
install -D -m 0755 -o root -g root "$SRC_DIR/diskhealth/smart_helper.py" "$HELPER_DST"
install -D -m 0644 -o root -g root "$SRC_DIR/packaging/id.diskhealth.helper.policy" "$POLICY_DST"

# SELinux (Fedora enforcing): pastikan label file sesuai lokasi barunya.
command -v restorecon >/dev/null && restorecon -v "$HELPER_DST" "$POLICY_DST"

echo "OK — helper terpasang di $HELPER_DST"
echo "Ulangi script ini setiap kali smart_helper.py diubah."
