#!/usr/bin/env python3
"""main.py — entry point AmubaSMART untuk dijalankan dari source (dev) & PyInstaller.

Logika dispatch sebenarnya ada di amubasmart/__main__.py supaya identik antara
"jalan dari source" dan "jalan setelah terinstall paket". File ini hanya jembatan.
"""
from __future__ import annotations

import sys

from amubasmart.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
