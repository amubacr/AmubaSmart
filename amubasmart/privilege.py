"""
privilege.py — deteksi OS & strategi eskalasi hak akses.

Linux  : GUI jalan sebagai USER BIASA. Hanya helper yang dinaikkan via pkexec.
         (Jangan `sudo python main.py` — di Plasma Wayland app root gak bisa
         konek ke compositor, dan menjalankan seluruh stack Qt sebagai root
         = permukaan serangan besar untuk hal yang cuma butuh 1 syscall.)
Windows: Seluruh app di-elevate via UAC saat start (pola CrystalDiskInfo).
         ShellExecute "runas" gak bisa redirect stdout, jadi elevate helper
         saja = harus lewat file temp + polling. Elevate app lebih simpel & robust.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Lokasi helper produksi (root-owned) — dipasang oleh packaging/install-helper.sh
INSTALLED_HELPER = Path("/usr/local/libexec/amubasmart/amubasmart-helper")
DEV_HELPER = Path(__file__).resolve().with_name("smart_helper.py")
# Helper stdlib-only -> sengaja pakai python sistem, BUKAN python venv.
SYSTEM_PYTHON = "/usr/bin/python3"


class PrivilegeError(RuntimeError):
    """Eskalasi gak mungkin dilakukan — pesan sudah siap tampil ke user."""


class PrivilegeMode(Enum):
    DIRECT = "direct"   # proses sudah root/admin
    PKEXEC = "pkexec"


@dataclass(frozen=True)
class HelperCommand:
    argv: list[str]
    mode: PrivilegeMode


def is_windows() -> bool:
    return sys.platform == "win32"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))  # build PyInstaller


def is_admin() -> bool:
    if is_windows():
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return False
    return os.geteuid() == 0


def _self_helper_argv() -> list[str]:
    """Jalankan helper tanpa eskalasi (proses kita sudah privileged)."""
    if is_frozen():
        # Exe hasil PyInstaller gak bisa jalanin .py -> dispatch via flag di main.py
        return [sys.executable, "--smart-helper"]
    return [sys.executable, str(DEV_HELPER)]


def build_helper_command(devices: Iterable[str]) -> HelperCommand:
    devs = list(devices)
    if is_admin():
        return HelperCommand([*_self_helper_argv(), *devs], PrivilegeMode.DIRECT)

    if is_windows():
        raise PrivilegeError(
            "Butuh hak Administrator. Tutup aplikasi, jalankan ulang, lalu setujui prompt UAC.")

    pkexec = shutil.which("pkexec")
    if pkexec is None:
        raise PrivilegeError("pkexec tidak ditemukan. Install: sudo dnf install polkit")

    if INSTALLED_HELPER.is_file():
        # Produksi: policy polkit kita (auth_admin_keep) -> password di-cache ~5 menit.
        return HelperCommand([pkexec, str(INSTALLED_HELPER), *devs], PrivilegeMode.PKEXEC)
    # Development: action generik org.freedesktop.policykit.exec -> prompt TIAP scan.
    return HelperCommand([pkexec, SYSTEM_PYTHON, str(DEV_HELPER), *devs], PrivilegeMode.PKEXEC)


def describe_mode() -> str:
    if is_admin():
        return "Mode: langsung (proses sudah root/admin)"
    if is_windows():
        return "Mode: tanpa Administrator — scan akan gagal"
    if INSTALLED_HELPER.is_file():
        return "Mode: pkexec + helper terinstall (password di-cache polkit)"
    return "Mode: pkexec dev (password diminta tiap scan)"


def relaunch_as_admin_windows() -> bool:
    """Spawn ulang app via UAC. True = proses elevated berhasil dibuat."""
    exe = Path(sys.executable)
    if is_frozen():
        params = sys.argv[1:]
    else:
        pythonw = exe.with_name("pythonw.exe")  # hindari jendela console hitam
        if pythonw.is_file():
            exe = pythonw
        params = [str(Path(sys.argv[0]).resolve()), *sys.argv[1:]]
    rc = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
        None, "runas", str(exe), subprocess.list2cmdline(params), None, 1)
    return int(rc) > 32  # <= 32 = error (termasuk user klik "No")
