"""detail_dialog.py — QDialog detail SMART satu disk (Ringkasan / Atribut / Raw JSON)."""
from __future__ import annotations

import html
import json

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase, QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel, QPlainTextEdit,
    QTableWidget, QTabWidget, QVBoxLayout, QWidget,
)

from .analysis import AttributeTable, DiskReport, Level
from .ui_common import LEVEL_TEXT, SortableItem, fg_color, is_dark, row_tint


def _readonly_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    table.setWordWrap(True)
    return table


class DetailDialog(QDialog):
    def __init__(self, report: DiskReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._report = report
        self.setWindowTitle(f"Detail SMART — {report.device}")
        self.resize(940, 640)
        dark = is_dark(self.palette())

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_header(report, dark))

        tabs = QTabWidget()
        tabs.addTab(self._build_summary(report, dark), "Ringkasan")
        if report.attributes and report.attributes.rows:
            tabs.addTab(self._build_attributes(report.attributes, dark),
                        f"Atribut SMART ({len(report.attributes.rows)})")
        tabs.addTab(self._build_raw(report), "Raw JSON")
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy_btn = buttons.addButton("Salin JSON", QDialogButtonBox.ButtonRole.ActionRole)
        copy_btn.clicked.connect(self._copy_json)
        copy_btn.setEnabled(report.raw_json is not None)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ tabs

    @staticmethod
    def _build_header(r: DiskReport, dark: bool) -> QLabel:
        color = fg_color(r.overall_level, dark)
        badge = (f"<span style='color:{color.name()}'>● {LEVEL_TEXT[r.overall_level]}</span>"
                 if color else LEVEL_TEXT[r.overall_level])
        label = QLabel(
            f"<span style='font-size:13pt; font-weight:600'>{html.escape(r.device)}</span>"
            f"&nbsp;&nbsp;{html.escape(r.model)}&nbsp;&nbsp;{badge}")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    @staticmethod
    def _build_summary(r: DiskReport, dark: bool) -> QTableWidget:
        table = _readonly_table(["Parameter", "Nilai"])
        table.setSortingEnabled(False)  # urutan detail bermakna, jangan di-sort
        table.setRowCount(len(r.details))
        bold = QFont()
        bold.setBold(True)
        for row, detail in enumerate(r.details):
            table.setItem(row, 0, SortableItem(detail.label))
            value = SortableItem(detail.value)
            value.setToolTip(detail.value)
            color = fg_color(detail.level, dark)
            if color is not None:
                value.setForeground(color)
                value.setFont(bold)
            table.setItem(row, 1, value)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.resizeRowsToContents()
        return table

    @staticmethod
    def _build_attributes(attrs: AttributeTable, dark: bool) -> QTableWidget:
        table = _readonly_table(attrs.headers)
        table.setRowCount(len(attrs.rows))
        for row, (cells, level) in enumerate(attrs.rows):
            tint = row_tint(level, dark) if level is not Level.NA else None
            for col, text in enumerate(cells):
                item = SortableItem(text)
                if tint is not None:
                    item.setBackground(tint)
                table.setItem(row, col, item)
        table.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        table.setSortingEnabled(True)  # set SETELAH diisi -> gak ada row-shuffle saat insert
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    @staticmethod
    def _build_raw(r: DiskReport) -> QPlainTextEdit:
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        view.setPlainText(json.dumps(r.raw_json, indent=2, ensure_ascii=False)
                          if r.raw_json is not None else "(smartctl tidak menghasilkan JSON)")
        return view

    def _copy_json(self) -> None:
        if self._report.raw_json is not None:
            QGuiApplication.clipboard().setText(
                json.dumps(self._report.raw_json, indent=2, ensure_ascii=False))
