#!/usr/bin/python3
"""
smart_helper.py — komponen PRIVILEGED (root via pkexec / Administrator via UAC).

Prinsip least privilege: yang jalan sebagai root HANYA kode ini, dan tugasnya
cuma satu -- enumerasi disk + jalanin `smartctl -a -j` + validasi/retry.
Semua analisa (threshold, skor, warna) terjadi di proses GUI yang unprivileged.

Kenapa stdlib-only & self-contained (gak import dari package diskhealth)?
Saat terinstall di /usr/local/libexec, file ini dieksekusi root. Kalau dia
import modul dari folder yang writable user, siapa pun yang bisa nulis ke
folder itu = bisa jalanin kode sebagai root. Makanya has_smart_data()
sengaja DIDUPLIKASI di sini, bukan di-import dari analysis.py.

Protokol output: NDJSON (satu objek JSON per baris) ke stdout, di-flush tiap
baris supaya GUI bisa update progresif walau cuma SATU prompt password:
  {"type": "devices", "devices": ["/dev/sda", ...]}
  {"type": "begin",   "device": "/dev/sda"}
  {"type": "result",  "device": "/dev/sda", "ok": true, "data": {...},
                      "error": null, "attempts": 1}
  {"type": "fatal",   "error": "..."}

Exit code: 0 = selesai (walau ada drive gagal dibaca), 3 = smartctl tidak ada.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from typing import Any, TextIO

SMARTCTL_TIMEOUT_S = 90       # drive sekarat bisa lambat banget respon
RETRY_DELAY_S = 1.0           # jeda retry, sama kayak `sleep 1` di bash
MAX_DEVICES = 64              # batas wajar, cegah argv abuse

_IS_WINDOWS = os.name == "nt"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # cegah console flash di Windows

# Whitelist path device. Linux: /dev/<nama> polos (tanpa subfolder, tanpa '-' di
# depan -> gak mungkin kebaca sebagai opsi smartctl). Windows: sda, nvme0, csmi0,1.
_LINUX_DEV_RE = re.compile(r"^/dev/[A-Za-z0-9][A-Za-z0-9_-]*$")
_WIN_DEV_RE = re.compile(r"^/dev/[A-Za-z0-9][A-Za-z0-9_,]*$")


# ----------------------------------------------------------------------------
# Util
# ----------------------------------------------------------------------------

def _stdout() -> TextIO:
    # pythonw / build PyInstaller --windowed bisa punya sys.stdout=None walau fd 1
    # valid (di-pipe parent). Fallback buka fd 1 langsung.
    return sys.stdout if sys.stdout is not None else open(1, "w", closefd=False)  # noqa: SIM115


def emit(obj: dict[str, Any]) -> None:
    out = _stdout()
    out.write(json.dumps(obj, ensure_ascii=False) + "\n")
    out.flush()


def _set_parent_death_signal() -> None:
    """Linux: kalau GUI (parent) mati, helper otomatis dapat SIGTERM.

    Penting di mode pkexec: helper jalan sebagai root, jadi GUI (user biasa)
    gak bisa kill helper secara langsung (EPERM).
    """
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        pr_set_pdeathsig = 1
        libc.prctl(pr_set_pdeathsig, signal.SIGTERM)
        if os.getppid() == 1:  # parent sudah mati sebelum prctl terpasang
            sys.exit(0)
    except OSError:
        pass


def find_smartctl() -> str | None:
    # Di bawah pkexec, PATH sudah disanitasi (/usr/sbin:/usr/bin:/sbin:/bin),
    # jadi shutil.which aman dipakai.
    found = shutil.which("smartctl")
    if found:
        return found
    candidates = (
        [r"C:\Program Files\smartmontools\bin\smartctl.exe"]
        if _IS_WINDOWS
        else ["/usr/sbin/smartctl", "/usr/bin/smartctl"]
    )
    return next((c for c in candidates if os.path.isfile(c)), None)


def has_smart_data(data: Any) -> bool:
    """Ada data SMART beneran? (bukan cuma block .device kosongan).

    DUPLIKAT SENGAJA dari analysis.has_smart_data -- lihat docstring modul.
    Kasus nyata: SSD N-Tech via USB-SATA bridge, JSON cuma berisi .smartctl
    + .device kosong -> harus dianggap GAGAL BACA, bukan "protokol gak dikenal".
    """
    if not isinstance(data, dict):
        return False
    ata = data.get("ata_smart_attributes")
    return (
        (isinstance(ata, dict) and ata.get("table") is not None)
        or data.get("nvme_smart_health_information_log") is not None
        or data.get("scsi_error_counter_log") is not None
        or data.get("scsi_grown_defect_list") is not None
    )


def validate_device(dev: str) -> bool:
    if _IS_WINDOWS:
        return bool(_WIN_DEV_RE.match(dev))
    if not _LINUX_DEV_RE.match(dev):
        return False
    try:
        return stat.S_ISBLK(os.stat(dev).st_mode)  # harus block device beneran
    except OSError:
        return False


# ----------------------------------------------------------------------------
# Enumerasi & akuisisi
# ----------------------------------------------------------------------------

def enumerate_devices(smartctl: str) -> list[str]:
    if _IS_WINDOWS:
        # Windows gak punya lsblk; smartctl --scan tahu penamaan /dev/sdX & /dev/nvmeX.
        proc = subprocess.run(
            [smartctl, "--scan", "-j"],
            capture_output=True, timeout=30, creationflags=_NO_WINDOW, check=False,
        )
        devices = json.loads(proc.stdout or b"{}").get("devices", [])
        names = [str(d.get("name")) for d in devices if isinstance(d, dict) and d.get("name")]
        return list(dict.fromkeys(names))  # dedup, urutan tetap

    lsblk = shutil.which("lsblk") or "/usr/bin/lsblk"
    proc = subprocess.run(
        [lsblk, "-J", "-d", "-o", "NAME,TYPE"], capture_output=True, timeout=30, check=False
    )
    blockdevices = json.loads(proc.stdout or b"{}").get("blockdevices", [])
    return [
        f"/dev/{d['name']}"
        for d in blockdevices
        if d.get("type") == "disk" and not str(d.get("name", "")).startswith(("zram", "loop"))
    ]


def read_smart(smartctl: str, device: str) -> dict[str, Any]:
    """Terjemahan get_smart_json(): max 2 attempt, jeda 1 detik.

    Retry nangkep transient link-negotiation glitch (kasus nyata SSD N-Tech:
    gagal sekali, reseat -> normal). Tapi retry TIDAK menggantikan reseat fisik.
    """
    last_data: Any = None
    last_error: str | None = None

    for attempt in (1, 2):
        try:
            # SENGAJA tanpa check=True: exit code smartctl = BITMASK informasi
            # (mis. bit 4 = prefail <= threshold), bukan kegagalan eksekusi.
            proc = subprocess.run(
                [smartctl, "-a", "-j", device],
                capture_output=True, timeout=SMARTCTL_TIMEOUT_S,
                creationflags=_NO_WINDOW, check=False,
            )
        except subprocess.TimeoutExpired:
            # Gak di-retry: drive yang hang 90 dtk kemungkinan besar hang lagi,
            # retry cuma bikin user nunggu 3 menit.
            msg = f"smartctl timeout > {SMARTCTL_TIMEOUT_S} dtk (drive hang / sangat lambat)"
            return {"ok": False, "data": last_data, "attempts": attempt, "error": msg}

        try:
            data = json.loads(proc.stdout.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            data = None
            last_error = f"output smartctl bukan JSON valid (exit={proc.returncode})"

        if has_smart_data(data):
            return {"ok": True, "data": data, "error": None, "attempts": attempt}

        if data is not None:
            last_data, last_error = data, None
        if attempt == 1:
            time.sleep(RETRY_DELAY_S)

    return {"ok": False, "data": last_data, "error": last_error, "attempts": 2}


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def _run(argv: list[str]) -> int:
    smartctl = find_smartctl()
    if smartctl is None:
        hint = ("Install smartmontools for Windows" if _IS_WINDOWS
                else "sudo dnf install smartmontools")
        emit({"type": "fatal", "error": f"smartctl tidak ditemukan. {hint}"})
        return 3

    devices = argv[:MAX_DEVICES] if argv else enumerate_devices(smartctl)
    emit({"type": "devices", "devices": devices})

    for dev in devices:
        emit({"type": "begin", "device": dev})
        if not validate_device(dev):
            emit({"type": "result", "device": dev, "ok": False, "data": None, "attempts": 0,
                  "error": "path device ditolak helper (bukan block device valid)"})
            continue
        emit({"type": "result", "device": dev, **read_smart(smartctl, dev)})
    return 0


def main(argv: list[str] | None = None) -> int:
    _set_parent_death_signal()
    try:
        return _run(sys.argv[1:] if argv is None else argv)
    except BrokenPipeError:
        # GUI sudah nutup pipe (user cancel / app ditutup) -> keluar diam-diam.
        # dup2 ke devnull supaya flush saat interpreter shutdown gak error lagi.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        return 0


if __name__ == "__main__":
    sys.exit(main())
