"""
worker.py — BACKEND. QObject yang di-moveToThread() ke QThread.

Alur: spawn helper (1x pkexec = 1x prompt password) -> baca NDJSON baris per
baris -> analyze() di thread ini -> emit DiskReport ke GUI thread (signal
cross-thread otomatis QueuedConnection, jadi aman).
"""
from __future__ import annotations

import json
import os
import selectors
import subprocess
import tempfile
import threading
from collections.abc import Iterator

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from .analysis import DEFAULT_THRESHOLDS, Thresholds, analyze
from .privilege import PrivilegeError, PrivilegeMode, build_helper_command

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_POLL_INTERVAL_S = 0.2
PKEXEC_DISMISSED = 126       # user klik Cancel di dialog auth
PKEXEC_NOT_AUTHORIZED = 127  # password salah / gak ada polkit agent / error


class ScanWorker(QObject):
    devices_found = pyqtSignal(list)        # list[str]
    scanning = pyqtSignal(str, int, int)    # device, index (1-based), total
    disk_ready = pyqtSignal(object)         # DiskReport
    failed = pyqtSignal(str)                # pesan error siap tampil
    finished = pyqtSignal()

    def __init__(self, devices: list[str] | None = None,
                 thresholds: Thresholds = DEFAULT_THRESHOLDS) -> None:
        super().__init__()
        self._devices = list(devices or [])   # kosong = helper enumerasi sendiri
        self._thresholds = thresholds
        self._stop = threading.Event()
        self._proc_lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None

    # ------------------------------------------------------------------ API

    def stop(self) -> None:
        """Thread-safe. Dipanggil LANGSUNG dari GUI thread (bukan via signal),
        karena event loop thread worker sedang keblok di run()."""
        self._stop.set()
        with self._proc_lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                # Mode pkexec: helper = root -> user biasa dapat EPERM. Aman:
                # loop baca pakai selector ber-timeout jadi tetap keluar <=0.2 dtk,
                # dan helper mati sendiri (EPIPE saat nulis / PDEATHSIG).
                pass

    @pyqtSlot()
    def run(self) -> None:
        try:
            self._scan()
        except Exception as exc:  # noqa: BLE001 — jangan biarkan thread mati diam-diam
            self.failed.emit(f"Error tak terduga di worker: {exc!r}")
        finally:
            self.finished.emit()

    # ------------------------------------------------------------ internal

    def _scan(self) -> None:
        try:
            cmd = build_helper_command(self._devices)
        except PrivilegeError as exc:
            self.failed.emit(str(exc))
            return

        # stderr ke file temp, BUKAN PIPE: PIPE yang gak dibaca bisa penuh (64 KiB)
        # lalu helper keblok nulis -> deadlock.
        with tempfile.TemporaryFile() as err_file:
            proc = subprocess.Popen(
                cmd.argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=err_file, creationflags=_NO_WINDOW,
            )
            with self._proc_lock:
                self._proc = proc
            if self._stop.is_set():  # race: cancel diklik sebelum proc tercatat
                self.stop()

            got_result, fatal_seen = self._consume(proc)

            if self._stop.is_set():
                if proc.stdout:
                    proc.stdout.close()  # helper dapat EPIPE di write berikutnya
                return

            try:
                rc: int | None = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                rc = None
            err_file.seek(0)
            stderr = err_file.read().decode("utf-8", "replace").strip()

        if not fatal_seen:
            self._report_exit(cmd.mode, rc, stderr, got_result)

    def _consume(self, proc: subprocess.Popen[bytes]) -> tuple[bool, bool]:
        total, index = len(self._devices), 0
        got_result = fatal_seen = False
        for line in self._iter_lines(proc):
            try:
                msg = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue  # baris sampah (mis. warning Python) -> abaikan
            kind = msg.get("type")
            if kind == "devices":
                devices = [str(d) for d in msg.get("devices", [])]
                total = len(devices)
                self.devices_found.emit(devices)
            elif kind == "begin":
                index += 1
                self.scanning.emit(str(msg.get("device", "?")), index, total)
            elif kind == "result":
                got_result = True
                report = analyze(str(msg.get("device", "?")), msg.get("data"),
                                 bool(msg.get("ok")), msg.get("error"), self._thresholds)
                self.disk_ready.emit(report)
            elif kind == "fatal":
                fatal_seen = True
                self.failed.emit(str(msg.get("error", "helper error")))
        return got_result, fatal_seen

    def _iter_lines(self, proc: subprocess.Popen[bytes]) -> Iterator[bytes]:
        assert proc.stdout is not None
        if os.name == "nt":
            # Pipe Windows gak bisa di-select(). Di Windows proses helper milik kita
            # sendiri (app sudah elevated) -> stop() pakai kill() -> readline dapat EOF.
            for line in iter(proc.stdout.readline, b""):
                if self._stop.is_set():
                    return
                yield line
            return

        # POSIX: select() ber-timeout supaya cancel tetap responsif walau smartctl
        # lagi nunggu drive sekarat (bisa puluhan detik) dan helper gak bisa di-kill.
        fd = proc.stdout.fileno()
        buf = b""
        with selectors.DefaultSelector() as sel:
            sel.register(fd, selectors.EVENT_READ)
            while not self._stop.is_set():
                if not sel.select(timeout=_POLL_INTERVAL_S):
                    continue
                chunk = os.read(fd, 65536)
                if not chunk:  # EOF: helper selesai
                    break
                buf += chunk
                *lines, buf = buf.split(b"\n")
                yield from (ln for ln in lines if ln.strip())
        if buf.strip() and not self._stop.is_set():
            yield buf

    def _report_exit(self, mode: PrivilegeMode, rc: int | None, stderr: str,
                     got_result: bool) -> None:
        detail = f"\n\nstderr:\n{stderr}" if stderr else ""
        if mode is PrivilegeMode.PKEXEC and rc == PKEXEC_DISMISSED:
            self.failed.emit("Autentikasi dibatalkan — scan tidak dijalankan.")
        elif mode is PrivilegeMode.PKEXEC and rc == PKEXEC_NOT_AUTHORIZED and not got_result:
            self.failed.emit(
                "pkexec menolak (exit 127): password salah / tidak diotorisasi, atau "
                "polkit agent tidak jalan di sesi ini (mis. via SSH)." + detail)
        elif rc not in (0, None) and not got_result:
            self.failed.emit(f"Helper keluar dengan kode {rc}." + detail)
        elif rc is None:
            self.failed.emit("Helper tidak berhenti setelah output selesai (timeout 10 dtk).")
