"""
history.py — riwayat scan per drive (SQLite lokal).

Tujuan: dari "potret sesaat" ke "diagnosa pergerakan". Tiap scan disimpan
otomatis, dikunci per SERIAL NUMBER (identitas drive lintas waktu, tak berubah
walau /dev/sdX berganti). Lalu tren bisa dilihat: "Realloc bulan lalu 0, sekarang 5".

Desain:
- Murni stdlib (sqlite3) — tak nambah dependency, jalan di server headless.
- Kunci = serial. Drive tanpa serial (mis. beberapa flashdisk) TIDAK dicatat —
  tak ada identitas stabil untuk melacaknya, mencatatnya cuma bikin sampah.
- Batas otomatis: simpan MAX_SNAPSHOTS terakhir per drive. Snapshot lama dibuang
  (FIFO) supaya DB tak tumbuh tanpa batas. Tren beberapa bulan tetap terjaga.
- Yang disimpan: metrik KUNCI yang ingin dilacak pergerakannya (health, suhu,
  realloc, pending, CRC, POH, dll) — bukan seluruh raw_json (itu boros & jarang
  perlu di-query historis). raw_json terakhir boleh disimpan opsional untuk detail.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis import DiskReport, Level, ata_raw_clean, find_ata_attr, _get, _num

MAX_SNAPSHOTS = 200          # per drive; ~cukup untuk scan harian >6 bulan
SCHEMA_VERSION = 1


def default_db_path() -> Path:
    """Lokasi DB: XDG data dir user (Linux) / LOCALAPPDATA (Windows).

    Per-user, bukan sistem: riwayat milik teknisi yang menjalankan, dan tak butuh
    root untuk menulis (GUI jalan sebagai user biasa).
    """
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "amubasmart" / "history.db"


@dataclass
class Snapshot:
    """Satu titik riwayat untuk satu drive."""
    scanned_at: str          # ISO 8601 UTC
    device: str              # /dev/sdX saat itu (bisa berubah antar scan)
    model: str
    health: float | None
    health_text: str
    level: str               # nama Level: OK/WARN/CRIT/NA
    temperature: float | None
    power_on_hours: int | None
    realloc: int | None      # ID 5
    pending: int | None      # ID 197
    crc: int | None          # ID 199
    percentage_used: int | None  # NVMe


# ----------------------------------------------------------------- ekstraksi

def _int_or_none(v: Any) -> int | None:
    n = _num(v)
    return int(n) if n is not None else None


def _extract_metrics(report: DiskReport) -> dict[str, Any]:
    """Ambil metrik kunci yang ingin dilacak dari DiskReport + raw_json."""
    data = report.raw_json or {}
    poh = _int_or_none(_get(data, "power_on_time", "hours"))
    if poh is None:
        poh = _int_or_none(_get(data, "nvme_smart_health_information_log", "power_on_hours"))
    realloc = ata_raw_clean(find_ata_attr(data, 5)) if report.dtype == "sata" else None
    pending = ata_raw_clean(find_ata_attr(data, 197)) if report.dtype == "sata" else None
    crc = ata_raw_clean(find_ata_attr(data, 199)) if report.dtype == "sata" else None
    pct_used = _int_or_none(
        _get(data, "nvme_smart_health_information_log", "percentage_used"))
    return {
        "model": report.model,
        "health": report.health,
        "health_text": report.health_text,
        "level": report.overall_level.name,
        "temperature": report.temperature,
        "power_on_hours": poh,
        "realloc": realloc,
        "pending": pending,
        "crc": crc,
        "percentage_used": pct_used,
    }


def serial_of(report: DiskReport) -> str | None:
    """Serial number sebagai identitas stabil. None kalau tak ada -> tak dilacak."""
    s = _get(report.raw_json or {}, "serial_number")
    s = str(s).strip() if s is not None else ""
    return s or None


# ----------------------------------------------------------------- DB core

class History:
    """Akses riwayat scan. Aman dipakai dari GUI thread (koneksi per operasi)."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.path = db_path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY, value TEXT
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    serial TEXT NOT NULL,
                    scanned_at TEXT NOT NULL,
                    device TEXT, model TEXT,
                    health REAL, health_text TEXT, level TEXT,
                    temperature REAL, power_on_hours INTEGER,
                    realloc INTEGER, pending INTEGER, crc INTEGER,
                    percentage_used INTEGER,
                    raw_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_serial_time
                    ON snapshots(serial, scanned_at);
                """
            )
            c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema', ?)",
                      (str(SCHEMA_VERSION),))

    # ---- tulis ----

    def record(self, report: DiskReport, *, store_raw: bool = False,
               scanned_at: datetime | None = None) -> bool:
        """Catat satu report. Return True kalau tercatat (False kalau tak ada serial).

        Drive tanpa serial dilewati — tak ada identitas untuk melacak trennya.
        """
        serial = serial_of(report)
        if serial is None:
            return False
        ts = (scanned_at or datetime.now(timezone.utc)).isoformat()
        m = _extract_metrics(report)
        raw = json.dumps(report.raw_json, ensure_ascii=False) if store_raw else None
        with self._conn() as c:
            c.execute(
                """INSERT INTO snapshots
                   (serial, scanned_at, device, model, health, health_text, level,
                    temperature, power_on_hours, realloc, pending, crc,
                    percentage_used, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (serial, ts, report.device, m["model"], m["health"], m["health_text"],
                 m["level"], m["temperature"], m["power_on_hours"], m["realloc"],
                 m["pending"], m["crc"], m["percentage_used"], raw),
            )
            # Batasi jumlah snapshot per drive (FIFO): buang yang terlama.
            c.execute(
                """DELETE FROM snapshots WHERE serial=? AND id NOT IN (
                       SELECT id FROM snapshots WHERE serial=?
                       ORDER BY scanned_at DESC, id DESC LIMIT ?)""",
                (serial, serial, MAX_SNAPSHOTS),
            )
        return True

    def record_all(self, reports: list[DiskReport], **kw: Any) -> int:
        """Catat banyak report sekaligus. Return jumlah yang tercatat."""
        return sum(1 for r in reports if self.record(r, **kw))

    # ---- baca ----

    def drives(self) -> list[dict[str, Any]]:
        """Daftar drive yang punya riwayat, dengan snapshot terbaru tiap drive."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT s.* FROM snapshots s
                   JOIN (SELECT serial, MAX(scanned_at) AS mx FROM snapshots
                         GROUP BY serial) t
                     ON s.serial=t.serial AND s.scanned_at=t.mx
                   ORDER BY s.model, s.serial"""
            ).fetchall()
        return [dict(r) for r in rows]

    def history_for(self, serial: str, limit: int = MAX_SNAPSHOTS) -> list[Snapshot]:
        """Riwayat satu drive, terbaru dulu."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT * FROM snapshots WHERE serial=?
                   ORDER BY scanned_at DESC, id DESC LIMIT ?""",
                (serial, limit),
            ).fetchall()
        return [_row_to_snapshot(r) for r in rows]

    def trend(self, serial: str, field: str) -> list[tuple[str, Any]]:
        """Deret (waktu, nilai) satu metrik untuk grafik/analisis tren."""
        allowed = {"health", "temperature", "power_on_hours", "realloc",
                   "pending", "crc", "percentage_used"}
        if field not in allowed:
            raise ValueError(f"field '{field}' tak dikenal")
        with self._conn() as c:
            rows = c.execute(
                f"""SELECT scanned_at, {field} FROM snapshots
                    WHERE serial=? AND {field} IS NOT NULL
                    ORDER BY scanned_at ASC""",
                (serial,),
            ).fetchall()
        return [(r["scanned_at"], r[field]) for r in rows]

    def delta(self, serial: str, field: str) -> Any | None:
        """Selisih nilai terbaru vs terlama untuk satu metrik. None kalau <2 titik.

        Positif = naik (mis. realloc bertambah = memburuk). Ini inti nilai riwayat:
        menunjukkan PERGERAKAN, bukan angka mati.
        """
        series = self.trend(serial, field)
        if len(series) < 2:
            return None
        first, last = series[0][1], series[-1][1]
        try:
            return last - first
        except TypeError:
            return None

    def purge(self, serial: str) -> int:
        """Hapus seluruh riwayat satu drive. Return jumlah baris terhapus."""
        with self._conn() as c:
            cur = c.execute("DELETE FROM snapshots WHERE serial=?", (serial,))
            return cur.rowcount


def _row_to_snapshot(r: sqlite3.Row) -> Snapshot:
    return Snapshot(
        scanned_at=r["scanned_at"], device=r["device"] or "", model=r["model"] or "",
        health=r["health"], health_text=r["health_text"] or "", level=r["level"] or "NA",
        temperature=r["temperature"], power_on_hours=r["power_on_hours"],
        realloc=r["realloc"], pending=r["pending"], crc=r["crc"],
        percentage_used=r["percentage_used"],
    )


def level_from_name(name: str) -> Level:
    return {"OK": Level.OK, "WARN": Level.WARN, "CRIT": Level.CRIT}.get(name, Level.NA)
