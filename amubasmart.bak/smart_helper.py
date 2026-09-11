#!/usr/bin/python3
"""
smart_helper.py — komponen PRIVILEGED (root via pkexec / Administrator via UAC).

Prinsip least privilege: yang jalan sebagai root HANYA kode ini, dan tugasnya
cuma satu -- enumerasi disk + jalanin `smartctl -a -j` + validasi/retry.
Semua analisa (threshold, skor, warna) terjadi di proses GUI yang unprivileged.

Kenapa stdlib-only & self-contained (gak import dari package amubasmart)?
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

# Flag -d yang dicoba saat drive di balik USB bridge tak terdeteksi otomatis.
# Urutan berdasar pengalaman lapangan (yang paling sering berhasil didahulukan):
# dock JMicron (mis. SSK DK201, bridge 0x152d) butuh sntjmicron; casing NVMe lain
# realtek/asmedia; -d sat & -d scsi buat enclosure SATA. smartctl mengembalikan
# error cepat kalau flag salah, jadi mencoba berurutan tetap ringan.
USB_BRIDGE_DTYPES: tuple[str, ...] = (
    "sat",          # enclosure SATA paling umum
    "sntjmicron",   # dock NVMe JMicron (SSK DK201 dll)
    "sntrealtek",   # casing NVMe Realtek
    "sntasmedia",   # casing NVMe ASMedia
    "scsi",         # fallback generik
)
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


def _bundled_smartctl() -> str | None:
    """smartctl yang dipaketkan bareng aplikasi (installer Windows).

    Prioritas #1: dengan begitu di mesin teknisi kita SELALU pakai versi yang
    sudah dites, bukan smartctl lain yang kebetulan nyangkut di PATH. Dicari di:
      - folder exe (build PyInstaller onedir), dan
      - sys._MEIPASS (build onefile — folder ekstraksi sementara).
    """
    exe_name = "smartctl.exe" if _IS_WINDOWS else "smartctl"
    roots: list[str] = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(sys.executable))
    meipass = getattr(sys, "_MEIPASS", None)  # onefile: root ekstraksi runtime
    if meipass:
        roots.append(meipass)
    # Layout installer: exe di root, smartctl di subfolder smartmontools\.
    for root in list(roots):
        roots.append(os.path.join(root, "smartmontools"))
    return next((os.path.join(r, exe_name)
                 for r in roots if os.path.isfile(os.path.join(r, exe_name))), None)


def find_smartctl() -> str | None:
    bundled = _bundled_smartctl()
    if bundled:
        return bundled
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
    """Daftar nama device saja (kompatibilitas). Metadata via enumerate_with_meta."""
    return [d["device"] for d in enumerate_with_meta(smartctl)]


def enumerate_with_meta(smartctl: str) -> list[dict[str, Any]]:
    """Enumerasi disk + metadata lsblk yang dipakai untuk mengenali flashdisk.

    Tiap entri: {"device": "/dev/sdX", "tran", "removable", "readonly",
    "size", "model"}. Di Windows lsblk tak ada -> metadata kosong (deteksi FD
    lewat lsblk khusus Linux; Windows mengandalkan smartctl saja).
    """
    if _IS_WINDOWS:
        proc = subprocess.run(
            [smartctl, "--scan", "-j"],
            capture_output=True, timeout=30, creationflags=_NO_WINDOW, check=False,
        )
        devices = json.loads(proc.stdout or b"{}").get("devices", [])
        names = list(dict.fromkeys(
            str(d.get("name")) for d in devices if isinstance(d, dict) and d.get("name")))
        return [{"device": n} for n in names]

    lsblk = shutil.which("lsblk") or "/usr/bin/lsblk"
    proc = subprocess.run(
        [lsblk, "-J", "-d", "-o", "NAME,TYPE,TRAN,RM,RO,SIZE,MODEL"],
        capture_output=True, timeout=30, check=False,
    )
    blockdevices = json.loads(proc.stdout or b"{}").get("blockdevices", [])
    out: list[dict[str, Any]] = []
    for d in blockdevices:
        name = str(d.get("name", ""))
        # zram/loop = memori/file virtual; zd* = ZFS zvol (tak punya SMART, cuma
        # bikin baris GAGAL yang membingungkan). Semua di-skip dari enumerasi.
        if d.get("type") != "disk" or name.startswith(("zram", "loop", "zd")):
            continue
        out.append({
            "device": f"/dev/{name}",
            "tran": d.get("tran"),               # 'usb', 'sata', 'nvme', ...
            "removable": str(d.get("rm")) in ("1", "True"),
            "readonly": str(d.get("ro")) in ("1", "True"),
            "size": d.get("size"),
            "model": d.get("model"),
        })
    return out


def is_flashdrive(meta: dict[str, Any]) -> bool:
    """Device ini flashdisk USB (removable) yang tak punya SMART?

    Penanda andal: TRAN=usb DAN removable(RM=1). SSD/HDD di dock USB umumnya
    RM=0 (fixed), jadi TIDAK kena — mereka tetap dicoba SMART lewat flag -d.
    Kartu SD sering muncul sebagai TRAN=usb (via reader) + RM=1 -> ikut ke sini,
    yang memang benar (SD juga tak punya SMART).
    """
    return meta.get("tran") == "usb" and bool(meta.get("removable"))


def _run_smartctl(smartctl: str, args: list[str]) -> tuple[Any, str, int | None]:
    """Jalankan smartctl sekali. Return (data_json_atau_None, stdout_text, exit_code).

    SENGAJA tanpa check=True: exit code smartctl = BITMASK informasi
    (mis. bit 4 = prefail <= threshold), bukan kegagalan eksekusi.
    """
    proc = subprocess.run(
        [smartctl, *args], capture_output=True, timeout=SMARTCTL_TIMEOUT_S,
        creationflags=_NO_WINDOW, check=False,
    )
    text = proc.stdout.decode("utf-8", "replace")
    try:
        return json.loads(text), text, proc.returncode
    except json.JSONDecodeError:
        return None, text, proc.returncode


def _looks_like_usb_bridge(data: Any) -> bool:
    """Output smartctl menandakan drive di balik USB bridge yang tak dikenal?

    Kasus nyata SSK DK201: "Unknown USB bridge [0x152d:0xa586]. Please specify
    device type with the -d option." smartctl menaruh pesan ini di messages JSON.
    """
    if not isinstance(data, dict):
        return False
    for msg in data.get("smartctl", {}).get("messages", []):
        if isinstance(msg, dict) and "usb bridge" in str(msg.get("string", "")).lower():
            return True
    return False


def read_smart(smartctl: str, device: str) -> dict[str, Any]:
    """Baca SMART: auto-detect dulu, lalu retry transient, lalu coba flag -d USB.

    Tiga lapis:
      1. `smartctl -a -j <dev>` — cukup untuk drive langsung (SATA/NVMe internal).
      2. Retry sekali (jeda 1 dtk) — nangkep transient link glitch (kasus N-Tech:
         gagal sekali, reseat -> normal). TIDAK menggantikan reseat fisik.
      3. Kalau output bilang "Unknown USB bridge", coba daftar flag -d
         (USB_BRIDGE_DTYPES) — kasus dock/casing USB seperti SSK DK201.
    """
    last_data: Any = None
    last_error: str | None = None
    saw_bridge = False

    # Lapis 1 & 2: auto-detect + retry transient.
    for attempt in (1, 2):
        try:
            data, _text, rc = _run_smartctl(smartctl, ["-a", "-j", device])
        except subprocess.TimeoutExpired:
            # Gak di-retry: drive yang hang 90 dtk kemungkinan besar hang lagi.
            msg = f"smartctl timeout > {SMARTCTL_TIMEOUT_S} dtk (drive hang / sangat lambat)"
            return {"ok": False, "data": last_data, "attempts": attempt, "error": msg}

        if has_smart_data(data):
            return {"ok": True, "data": data, "error": None, "attempts": attempt}

        if data is not None:
            last_data, last_error = data, None
        if _looks_like_usb_bridge(data):
            saw_bridge = True
            break  # percuma retry auto-detect; langsung ke flag -d
        if attempt == 1:
            time.sleep(RETRY_DELAY_S)

    # Lapis 3: USB bridge -> coba flag -d satu per satu.
    if saw_bridge:
        for dtype in USB_BRIDGE_DTYPES:
            try:
                data, _text, rc = _run_smartctl(smartctl, ["-a", "-j", "-d", dtype, device])
            except subprocess.TimeoutExpired:
                continue  # flag ini bikin hang; coba flag berikutnya
            if has_smart_data(data):
                # Sisipkan tipe yang berhasil supaya GUI/CLI bisa menampilkannya.
                if isinstance(data, dict):
                    data.setdefault("amubasmart", {})["usb_bridge_dtype"] = dtype
                return {"ok": True, "data": data, "error": None, "attempts": 2, "dtype": dtype}
        last_error = ("drive di balik USB bridge yang tak didukung — sudah dicoba flag: "
                      + ", ".join(USB_BRIDGE_DTYPES)
                      + ". Colok drive langsung ke SATA/M.2 untuk cek SMART.")

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

    # Pakai metadata lsblk supaya bisa kenali flashdisk. Kalau device diberikan
    # eksplisit (argv), tetap ambil metadata semua disk lalu cocokkan by path.
    all_meta = enumerate_with_meta(smartctl)
    meta_by_dev = {m["device"]: m for m in all_meta}
    if argv:
        devices = argv[:MAX_DEVICES]
    else:
        devices = [m["device"] for m in all_meta]
    emit({"type": "devices", "devices": devices})

    for dev in devices:
        emit({"type": "begin", "device": dev})
        if not validate_device(dev):
            emit({"type": "result", "device": dev, "ok": False, "data": None, "attempts": 0,
                  "error": "path device ditolak helper (bukan block device valid)"})
            continue
        meta = meta_by_dev.get(dev, {})
        # Flashdisk/kartu SD: tak punya SMART. Jangan buang waktu ke smartctl —
        # kirim hasil khusus supaya UI melabelinya "normal", bukan alarm GAGAL.
        if is_flashdrive(meta):
            emit({"type": "result", "device": dev, "ok": False, "data": None,
                  "attempts": 0, "flashdrive": True, "meta": meta,
                  "error": "flashdisk/USB removable — tidak mendukung SMART (normal)"})
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
