#!/usr/bin/env python3
"""Cetak nomor RELEASE untuk paket, dihitung dari git — supaya tiap build unik.

Kenapa Release, bukan Version? Version (0.1.1) = versi software (dari __init__.py).
Release = nomor build/rebuild dari versi yang sama. Menaruh info git di Release
menjaga Version tetap bersih, dan bikin package manager SELALU menganggap build
baru sebagai lebih baru (tak perlu `dnf reinstall` paksa).

Format: <commits>.g<hash>[.dirty]
  commits = jumlah commit sejak tag terakhir (naik otomatis tiap commit)
  hash    = commit pendek sekarang
  .dirty  = ada perubahan belum di-commit (tanda build tak reproducible)

Contoh: 9.ga3f2c1  atau  9.ga3f2c1.dirty

Fallback (bukan repo git / git tak ada): "1" — biar build tetap jalan dari tarball.
RPM Release harus diawali digit & tak boleh ada '-', jadi kita pakai '.' & 'g<hash>'.
"""
import re
import subprocess
import sys


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True,
                             timeout=10, check=False)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def release() -> str:
    # Jumlah commit sejak tag terakhir. Kalau belum ada tag sama sekali,
    # pakai total jumlah commit sebagai gantinya.
    described = _git("describe", "--tags", "--long", "--always", "--dirty")
    if described is None:
        return "1"  # bukan repo git (mis. build dari tarball rilis)

    dirty = described.endswith("-dirty")
    # Format git describe --long: <tag>-<commits>-g<hash>[-dirty]
    m = re.match(r"^.*-(\d+)-g([0-9a-f]+)(?:-dirty)?$", described)
    if m:
        commits, short = m.group(1), m.group(2)
    else:
        # Belum ada tag: described = "<hash>" atau "<hash>-dirty".
        short = described.replace("-dirty", "")
        commits = _git("rev-list", "--count", "HEAD") or "0"

    rel = f"{commits}.g{short}"
    if dirty:
        rel += ".dirty"
    return rel


if __name__ == "__main__":
    sys.stdout.write(release() + "\n")
