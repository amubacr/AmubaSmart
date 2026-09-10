#!/usr/bin/env python3
"""main.py — entry point DiskHealth GUI."""
from __future__ import annotations

import sys


def main() -> int:
    # Dispatch mode helper SEBELUM import Qt (start cepat, tanpa GUI).
    # Dipakai build PyInstaller: exe tunggal berperan ganda sebagai helper.
    if len(sys.argv) > 1 and sys.argv[1] == "--smart-helper":
        from diskhealth.smart_helper import main as helper_main
        return helper_main(sys.argv[2:])

    from diskhealth import privilege

    if privilege.is_windows() and not privilege.is_admin():
        if privilege.relaunch_as_admin_windows():
            return 0  # instance elevated sudah jalan, instance ini pamit
        # User klik "No" di UAC -> tetap buka GUI; scan akan kasih error yang jelas.

    from PyQt6.QtWidgets import QApplication

    from diskhealth.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("DiskHealth")
    app.setOrganizationName("DiskHealth")
    app.setDesktopFileName("diskhealth")  # Wayland: cocokkan ikon via diskhealth.desktop
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
