"""main_window.py — UI UTAMA. Tabel ringkasan semua disk + kontrol scan."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, QThread, QTimer, pyqtSlot
from PyQt6.QtGui import QAction, QCloseEvent, QFont, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QMainWindow, QMessageBox, QProgressBar,
    QTableWidget, QToolBar, QVBoxLayout, QWidget,
)

from .analysis import DiskReport, Level
from .detail_dialog import DetailDialog
from .privilege import describe_mode
from .ui_common import SortableItem, fg_color, is_dark, row_tint
from .worker import ScanWorker

DEVICE_ROLE = Qt.ItemDataRole.UserRole
HEADERS = ("Device", "Model", "Protokol", "Suhu", "Status", "Kesehatan", "Key Metric")
COL_DEVICE, COL_MODEL, COL_PROTO, COL_TEMP, COL_STATUS, COL_HEALTH, COL_METRIC = range(7)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AmubaSMART — SMART Analyzer")
        self.resize(1150, 540)

        self._reports: dict[str, DiskReport] = {}
        self._pending: set[str] = set()          # device yang belum dapat hasil
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._cancelled = False

        self._build_actions()
        self._build_central()
        self._build_statusbar()
        self._set_busy(False)
        QTimer.singleShot(0, self.scan_all)      # auto-scan setelah window tampil

    # ================================================================ build UI

    def _build_actions(self) -> None:
        toolbar = QToolBar("Aksi")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        def make(text: str, icon: str, shortcut: QKeySequence | str, slot) -> QAction:
            # Ikon dari tema sistem (Breeze di KDE); di Windows jatuh ke teks saja.
            action = QAction(QIcon.fromTheme(icon), text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(slot)
            toolbar.addAction(action)
            return action

        self.act_scan = make("Scan semua", "view-refresh", QKeySequence.StandardKey.Refresh,
                             self.scan_all)
        self.act_rescan = make("Scan ulang disk terpilih", "drive-harddisk", "Ctrl+R",
                               self.rescan_selected)
        self.act_detail = make("Lihat detail", "document-properties", "Return",
                               lambda: self.open_detail())
        toolbar.addSeparator()
        self.act_cancel = make("Batalkan scan", "process-stop", "Esc", self.cancel_scan)

    def _build_central(self) -> None:
        table = QTableWidget(0, len(HEADERS))
        table.setHorizontalHeaderLabels(HEADERS)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(False)  # diagnosis panjang di-elide, teks penuh ada di tooltip
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_METRIC, QHeaderView.ResizeMode.Stretch)
        # Default indikator sort Qt6 = descending -> /dev/sdd di atas /dev/sda. Paksa ascending.
        header.setSortIndicator(COL_DEVICE, Qt.SortOrder.AscendingOrder)
        table.cellDoubleClicked.connect(lambda row, _col: self.open_detail(row))
        table.itemSelectionChanged.connect(self._update_actions)
        self.table = table

        self.legend = QLabel(
            "* Model gak ketemu di drivedb smartctl — VALUE/THRESH bisa aja gak pernah "
            "di-update firmware. Jangan telan mentah-mentah, cek raw count di detail.")
        self.legend.setWordWrap(True)
        self.legend.setEnabled(False)  # tampil redup ala teks sekunder
        self.legend.hide()

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(table, 1)
        layout.addWidget(self.legend)
        self.setCentralWidget(container)

    def _build_statusbar(self) -> None:
        self.status_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setTextVisible(True)
        bar = self.statusBar()
        bar.addWidget(self.status_label, 1)
        bar.addPermanentWidget(self.progress)
        bar.addPermanentWidget(QLabel(describe_mode()))

    # ================================================================ scanning

    @pyqtSlot()
    def scan_all(self) -> None:
        if self._is_scanning():
            return
        self.table.setRowCount(0)
        self._reports.clear()
        self._start_scan(None)

    @pyqtSlot()
    def rescan_selected(self) -> None:
        device = self._selected_device()
        if device and not self._is_scanning():
            self._start_scan([device])

    @pyqtSlot()
    def cancel_scan(self) -> None:
        if self._worker is not None:
            self._cancelled = True
            self._worker.stop()
            self.status_label.setText("Membatalkan…")

    def _start_scan(self, devices: list[str] | None) -> None:
        self._pending = set(devices or [])
        self._cancelled = False
        self._thread = QThread(self)
        self._worker = ScanWorker(devices)
        self._worker.moveToThread(self._thread)

        # Pola worker-object: run() jalan di thread baru saat thread start.
        self._thread.started.connect(self._worker.run)
        self._worker.devices_found.connect(self._on_devices_found)
        self._worker.scanning.connect(self._on_scanning)
        self._worker.disk_ready.connect(self._on_disk_ready)
        self._worker.failed.connect(self._on_failed)
        # Teardown berurutan: worker selesai -> thread quit -> hapus keduanya.
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)

        self._set_busy(True)
        self.status_label.setText("Menunggu autentikasi / enumerasi disk…")
        self.progress.setRange(0, 0)  # mode "busy" sampai jumlah disk diketahui
        self._thread.start()

    def _is_scanning(self) -> bool:
        return self._thread is not None

    # ============================================================ worker slots

    @pyqtSlot(list)
    def _on_devices_found(self, devices: list[str]) -> None:
        if not devices:
            self.status_label.setText("Gak ada disk fisik yang kedeteksi.")
            return
        self._pending = set(devices)
        for device in devices:
            self._set_placeholder(self._ensure_row(device), "Antri")
        self.progress.setRange(0, len(devices))
        self.progress.setValue(0)

    @pyqtSlot(str, int, int)
    def _on_scanning(self, device: str, index: int, total: int) -> None:
        self.status_label.setText(f"Membaca {device} ({index}/{total})…")
        self._set_placeholder(self._ensure_row(device), "Membaca…")

    @pyqtSlot(object)
    def _on_disk_ready(self, report: DiskReport) -> None:
        self._reports[report.device] = report
        self._pending.discard(report.device)
        self._fill_row(self._ensure_row(report.device), report)
        self.progress.setValue(self.progress.value() + 1)
        self.legend.setVisible(any(r.not_in_db for r in self._reports.values()))
        self._update_actions()

    @pyqtSlot(str)
    def _on_failed(self, message: str) -> None:
        self.status_label.setText("Scan gagal — lihat pesan error.")
        QMessageBox.warning(self, "Scan gagal", message)

    @pyqtSlot()
    def _on_thread_finished(self) -> None:
        for device in self._pending:  # sisa yang gak sempat kebaca (cancel / error)
            row = self._row_for_device(device)
            if row is not None:
                self._set_placeholder(row, "Dibatalkan")
        self._pending.clear()
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = self._worker = None
        self._set_busy(False)
        if self._cancelled:
            self.status_label.setText("Scan dibatalkan.")
        elif self.status_label.text().startswith(("Membaca", "Menunggu")):
            self.status_label.setText(f"Selesai — {len(self._reports)} disk.")

    # ============================================================= table ops

    def _row_for_device(self, device: str) -> int | None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_DEVICE)
            if item is not None and item.data(DEVICE_ROLE) == device:
                return row
        return None

    def _ensure_row(self, device: str) -> int:
        row = self._row_for_device(device)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._set_placeholder(row, "Antri", device)
        return row

    def _set_item(self, row: int, col: int, text: str, key: object, device: str) -> None:
        item = SortableItem(text, key)
        item.setData(DEVICE_ROLE, device)
        if col == COL_METRIC:
            item.setToolTip(text)  # diagnosis bisa panjang
        self.table.setItem(row, col, item)

    def _set_placeholder(self, row: int, status: str, device: str | None = None) -> None:
        device = device or self.table.item(row, COL_DEVICE).data(DEVICE_ROLE)
        values = (device, "-", "-", "-", status, "-", "")
        keys = (device, "", "", -1.0, -1, -1.0, "")
        for col, (text, key) in enumerate(zip(values, keys, strict=True)):
            self._set_item(row, col, text, key, device)

    def _fill_row(self, row: int, r: DiskReport) -> None:
        # baris gagal baca: jangan tampilkan "?"/"N/A" yang menyesatkan.
        # FD: read_ok=False tapi punya model/kapasitas -> tetap tampilkan labelnya.
        ok = r.read_ok or r.dtype == "flashdrive"
        cells = (
            (r.device, r.device),
            (r.model, r.model.lower()),
            (r.protocol_label if ok else "-", r.protocol_label if ok else ""),
            (r.temperature_text if r.read_ok else "-",
             float(r.temperature) if r.temperature is not None else -1.0),
            (r.status, int(r.status_level)),
            (r.health_text, float(r.health) if r.health is not None else -1.0),
            (r.key_metric, r.key_metric),
        )
        for col, (text, key) in enumerate(cells):
            self._set_item(row, col, text, key, r.device)
        self._apply_colors(row, r)

    def _apply_colors(self, row: int, r: DiskReport) -> None:
        dark = is_dark(self.palette())
        tint = row_tint(r.overall_level, dark)
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item is not None:
                item.setData(Qt.ItemDataRole.BackgroundRole, tint)
        bold = QFont()
        bold.setBold(True)
        for col, level in ((COL_STATUS, r.status_level), (COL_HEALTH, r.health_level)):
            item = self.table.item(row, col)
            if item is not None and level is not Level.NA:
                item.setData(Qt.ItemDataRole.ForegroundRole, fg_color(level, dark))
                item.setFont(bold)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (API Qt)
        # User ganti Breeze Light <-> Dark saat app jalan -> hitung ulang warna.
        if event.type() == QEvent.Type.PaletteChange:
            for device, report in self._reports.items():
                row = self._row_for_device(device)
                if row is not None:
                    self._apply_colors(row, report)
        super().changeEvent(event)

    # ================================================================ misc UI

    def _selected_device(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), COL_DEVICE)
        return item.data(DEVICE_ROLE) if item else None

    def open_detail(self, row: int | None = None) -> None:
        if row is None:
            device = self._selected_device()
        else:
            item = self.table.item(row, COL_DEVICE)
            device = item.data(DEVICE_ROLE) if item else None
        report = self._reports.get(device or "")
        if report is None:
            return  # masih antri / dibaca
        dialog = DetailDialog(report, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()  # non-modal: bisa buka beberapa disk untuk dibandingkan

    def _set_busy(self, busy: bool) -> None:
        # Sorting dimatikan selama scan: kalau aktif, setiap setItem() bisa
        # memindah baris & indeks row yang kita pegang jadi basi.
        self.table.setSortingEnabled(not busy)
        self.act_scan.setEnabled(not busy)
        self.act_cancel.setEnabled(busy)
        self.progress.setVisible(busy)
        self._update_actions()

    def _update_actions(self) -> None:
        device = self._selected_device()
        self.act_rescan.setEnabled(device is not None and not self._is_scanning())
        self.act_detail.setEnabled(device in self._reports)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (API Qt)
        if self._thread is not None and self._worker is not None:
            self._worker.stop()
            self._thread.quit()
            # Selector di worker ber-timeout 0.2 dtk -> 3 dtk lebih dari cukup.
            # Kalau QThread dihancurkan saat masih jalan, Qt abort (crash).
            if not self._thread.wait(3000):
                QMessageBox.information(self, "Scan masih berjalan",
                                        "Tunggu sebentar lalu tutup lagi.")
                event.ignore()
                return
        event.accept()
