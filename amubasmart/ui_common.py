"""
ui_common.py — util UI bersama: warna level yang sadar tema (Breeze Light/Dark)
dan QTableWidgetItem yang sort numerik.

Warna sengaja TIDAK di-hardcode satu set: hijau tua yang kebaca di Breeze Light
jadi gelap-gak-kebaca di Breeze Dark. Pilih set berdasarkan lightness palette.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QTableWidgetItem

from .analysis import Level

SORT_ROLE = Qt.ItemDataRole.UserRole + 1

_FG: dict[bool, dict[Level, str]] = {
    False: {Level.OK: "#1a7f37", Level.WARN: "#9a6700", Level.CRIT: "#cf222e"},  # tema terang
    True: {Level.OK: "#3fb950", Level.WARN: "#e3b341", Level.CRIT: "#ff7b72"},   # tema gelap
}
_TINT_ALPHA = {False: 38, True: 56}

LEVEL_TEXT = {Level.OK: "Sehat", Level.WARN: "Perlu perhatian",
              Level.CRIT: "Kritis", Level.NA: "Tidak dinilai"}


def is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.ColorRole.Base).lightness() < 128


def fg_color(level: Level, dark: bool) -> QColor | None:
    hex_code = _FG[dark].get(level)
    return QColor(hex_code) if hex_code else None


def row_tint(level: Level, dark: bool) -> QColor | None:
    """Warna latar transparan -> teks default tema tetap kontras."""
    color = fg_color(level, dark)
    if color is None:
        return None
    color.setAlpha(_TINT_ALPHA[dark])
    return color


def sort_key(text: str) -> tuple[int, Any]:
    """Angka di depan (dan urut numerik), sisanya string. Tipe tuple konsisten
    -> gak ada TypeError int-vs-str saat compare."""
    try:
        return (0, float(text))
    except ValueError:
        return (1, text.lower())


class SortableItem(QTableWidgetItem):
    """Sort pakai SORT_ROLE. Default QTableWidget sort string: '9%' > '10%'."""

    def __init__(self, text: str, key: Any = None) -> None:
        super().__init__(text)
        self.setData(SORT_ROLE, key if key is not None else sort_key(text))

    def __lt__(self, other: QTableWidgetItem) -> bool:
        a, b = self.data(SORT_ROLE), other.data(SORT_ROLE)
        try:
            return bool(a < b)
        except TypeError:
            return str(a) < str(b)
