#!/usr/bin/env python3
"""Cetak versi AmubaSMART dari amubasmart/__init__.py — satu sumber kebenaran.

Dipakai build script (RPM/.deb). Sengaja TIDAK `import amubasmart` (itu bakal
menarik dependency); cukup baca __version__ dari file sebagai teks.
"""
import pathlib
import re
import sys

init = pathlib.Path(__file__).resolve().parent.parent / "amubasmart" / "__init__.py"
m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init.read_text(), re.M)
if not m:
    sys.exit("Gagal membaca __version__ dari amubasmart/__init__.py")
print(m.group(1))
