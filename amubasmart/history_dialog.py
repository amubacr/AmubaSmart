"""history_dialog.py — QDialog menampilkan riwayat scan per drive + tren."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QTableWidget, QVBoxLayout, QWidget,
)

from .history import History, Snapshot, level_from_name
from .ui_common import SortableItem, fg_color, is_dark

# Metrik yang tren-nya ditampilkan, label -> atribut Snapshot.
_TREND_FIELDS = [
    ("Kesehatan", "health", "%"),
    ("Suhu", "temperature", " °C"),
    ("Realloc (ID 5)", "realloc", ""),
    ("Pending (ID 197)", "pending", ""),
    ("CRC (ID 199)", "crc", ""),
    ("Power On Hours", "power_on_hours", " jam"),
]


def _fmt(v: object, suffix: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        v = int(v) if v.is_integer() else round(v, 1)
    return f"{v}{suffix}"


class HistoryDialog(QDialog):
    def __init__(self, history: History, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._history = history
        self.setWindowTitle("Riwayat Scan")
        self.resize(880, 560)
        self._dark = is_dark(self.palette())

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Riwayat tersimpan otomatis tiap scan, dikunci per serial number. "
            "Pilih drive untuk melihat pergerakan metrik dari waktu ke waktu."))

        body = QHBoxLayout()
        # Kiri: daftar drive
        self.drive_list = QListWidget()
        self.drive_list.setMaximumWidth(280)
        self.drive_list.currentItemChanged.connect(self._on_drive_selected)
        body.addWidget(self.drive_list)

        # Kanan: tabel snapshot
        self.snap_table = QTableWidget(0, len(_TREND_FIELDS) + 1)
        self.snap_table.setHorizontalHeaderLabels(
            ["Tanggal"] + [lbl for lbl, _f, _s in _TREND_FIELDS])
        self.snap_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.snap_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.snap_table.verticalHeader().setVisible(False)
        self.snap_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        body.addWidget(self.snap_table, 1)
        layout.addLayout(body, 1)

        # Ringkasan tren (delta)
        self.trend_label = QLabel()
        self.trend_label.setWordWrap(True)
        self.trend_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.trend_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.btn_export = buttons.addButton("Ekspor CSV…",
                                            QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_export.clicked.connect(self._export_menu)
        self.btn_export.setEnabled(False)
        self.btn_purge = buttons.addButton("Hapus riwayat drive ini",
                                           QDialogButtonBox.ButtonRole.DestructiveRole)
        self.btn_purge.clicked.connect(self._purge_current)
        self.btn_purge.setEnabled(False)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_drives()

    # ------------------------------------------------------------------ data

    def _load_drives(self) -> None:
        self.drive_list.clear()
        drives = self._history.drives()
        if not drives:
            self.drive_list.addItem("(belum ada riwayat)")
            self.drive_list.setEnabled(False)
            return
        for d in drives:
            item = QListWidgetItem(f"{d['model']}\n{d['serial']}")
            item.setData(Qt.ItemDataRole.UserRole, d["serial"])
            color = fg_color(level_from_name(d["level"] or "NA"), self._dark)
            if color is not None:
                item.setForeground(color)
            self.drive_list.addItem(item)
        self.drive_list.setCurrentRow(0)

    def _on_drive_selected(self, current: QListWidgetItem | None, _prev=None) -> None:
        serial = current.data(Qt.ItemDataRole.UserRole) if current else None
        if not serial:
            self.btn_purge.setEnabled(False)
            return
        self.btn_purge.setEnabled(True)
        self.btn_export.setEnabled(True)
        snaps = self._history.history_for(serial)
        self._fill_table(snaps)
        self._fill_trend(serial)

    def _fill_table(self, snaps: list[Snapshot]) -> None:
        self.snap_table.setRowCount(len(snaps))
        for row, s in enumerate(snaps):
            date = s.scanned_at[:16].replace("T", " ")
            self.snap_table.setItem(row, 0, SortableItem(date))
            values = [
                (s.health_text or _fmt(s.health), ""),
                (_fmt(s.temperature, " °C"), ""),
                (_fmt(s.realloc), ""), (_fmt(s.pending), ""),
                (_fmt(s.crc), ""), (_fmt(s.power_on_hours, " jam"), ""),
            ]
            for col, (text, _s) in enumerate(values, start=1):
                item = SortableItem(text)
                # Warnai baris teratas (terbaru) sesuai level
                if row == 0:
                    color = fg_color(level_from_name(s.level), self._dark)
                    if color is not None:
                        item.setForeground(color)
                self.snap_table.setItem(row, col, item)

    def _fill_trend(self, serial: str) -> None:
        """Ringkasan pergerakan: naik/turun tiap metrik penting."""
        parts: list[str] = []
        for label, field, suffix in _TREND_FIELDS:
            if field == "power_on_hours":
                continue  # POH selalu naik, tak informatif sebagai tren
            try:
                d = self._history.delta(serial, field)
            except ValueError:
                continue
            if d is None or d == 0:
                continue
            # realloc/pending/crc naik = memburuk (merah); health naik = membaik (hijau)
            worsening = (field in ("realloc", "pending", "crc") and d > 0) or \
                        (field == "health" and d < 0)
            color = "#cf222e" if worsening else "#1a7f37"
            arrow = "↑" if d > 0 else "↓"
            parts.append(
                f"<span style='color:{color}'>{label}: {arrow} "
                f"{'+' if d > 0 else ''}{_fmt(d, suffix)}</span>")
        if parts:
            self.trend_label.setText("<b>Pergerakan (terlama → terbaru):</b> &nbsp; "
                                     + " &nbsp;|&nbsp; ".join(parts))
        else:
            self.trend_label.setText(
                "<i>Belum ada pergerakan tercatat (butuh minimal 2 scan).</i>")

    def _export_menu(self) -> None:
        """Menu kecil: ekspor drive ini saja, atau semua drive."""
        menu = QMenu(self)
        act_one = menu.addAction("Drive ini saja")
        menu.addAction("Semua drive")
        chosen = menu.exec(self.btn_export.mapToGlobal(self.btn_export.rect().bottomLeft()))
        if chosen is None:
            return
        item = self.drive_list.currentItem()
        serial = item.data(Qt.ItemDataRole.UserRole) if item else None
        self._do_export(serial if chosen is act_one else None)

    def _do_export(self, serial: str | None) -> None:
        from datetime import datetime
        stamp = f"{datetime.now():%Y%m%d-%H%M}"
        default = (f"riwayat-amubasmart-{stamp}.csv" if serial is None
                   else f"riwayat-{serial}-{stamp}.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Simpan CSV", default, "CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            n = self._history.export_csv(path, serial)
        except OSError as exc:
            QMessageBox.warning(self, "Ekspor gagal", f"Gagal menulis CSV: {exc}")
            return
        QMessageBox.information(self, "Ekspor selesai",
                                f"{n} baris riwayat disimpan ke:\n{path}")

    def _purge_current(self) -> None:
        item = self.drive_list.currentItem()
        serial = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not serial:
            return
        confirm = QMessageBox.question(
            self, "Hapus riwayat",
            f"Hapus seluruh riwayat untuk drive ini?\n{item.text()}\n\n"
            "Tindakan ini tidak bisa dibatalkan.")
        if confirm == QMessageBox.StandardButton.Yes:
            self._history.purge(serial)
            self.snap_table.setRowCount(0)
            self.trend_label.clear()
            self._load_drives()
