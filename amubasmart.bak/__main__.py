"""__main__.py — memungkinkan `python -m amubasmart` dan dipakai launcher /usr/bin.

Logika dispatch (helper / CLI / GUI) tinggal di sini supaya saat terinstall
sebagai paket, tidak bergantung pada main.py di root repo. File main.py di root
tetap ada untuk menjalankan langsung dari source (dev) & untuk PyInstaller.
"""
from __future__ import annotations

import os
import sys

_CLI_FLAGS = {"--cli", "--json", "--detail", "-V", "--version", "-h", "--help"}


def _wants_cli(argv: list[str]) -> bool:
    if any(arg in _CLI_FLAGS for arg in argv):
        return True
    if sys.platform.startswith("linux"):
        return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return False


def main() -> int:
    argv = sys.argv[1:]

    if argv and argv[0] == "--smart-helper":
        from amubasmart.smart_helper import main as helper_main
        return helper_main(argv[1:])

    if _wants_cli(argv):
        from amubasmart.cli import run_cli
        return run_cli([a for a in argv if a != "--cli"])

    from amubasmart import privilege

    if privilege.is_windows() and not privilege.is_admin():
        if privilege.relaunch_as_admin_windows():
            return 0

    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        print("PyQt6 tidak terpasang — jalankan mode teks dengan: amubasmart --cli",
              file=sys.stderr)
        return 4

    from amubasmart.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("AmubaSMART")
    app.setOrganizationName("AmubaSMART")
    app.setDesktopFileName("amubasmart")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
