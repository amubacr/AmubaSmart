"""
cli.py — frontend CLI untuk server headless / SSH / cron.

Prinsip kunci: TIDAK meng-import PyQt6 sama sekali. Modul ini cuma butuh
subprocess (via helper) + analysis.py yang memang sudah murni Python. Dengan
begitu `amubasmart --cli` jalan di server tanpa X11/Wayland dan tanpa paket Qt.

Alur eksekusi disederhanakan dibanding GUI: di CLI kita gak butuh QThread —
proses memang blocking dari atas ke bawah, jadi helper dijalankan langsung dan
outputnya dibaca sampai selesai. Warna pakai ANSI (dimatikan otomatis kalau
output bukan terminal, mis. di-pipe atau di-redirect ke file).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import TextIO

from . import __version__
from .analysis import DEFAULT_THRESHOLDS, DiskReport, Level, analyze
from .privilege import PrivilegeError, build_helper_command

# Kode warna ANSI, dipetakan dari Level. Sengaja sama semangатnya dgn badge() bash.
_ANSI = {Level.OK: "\033[32m", Level.WARN: "\033[33m", Level.CRIT: "\033[31m", Level.NA: "\033[2m"}
_RESET = "\033[0m"
_BOLD = "\033[1m"

# Lebar kolom tabel ringkasan (mirip scan_all() di bash).
_COLS = (("DEVICE", 13), ("MODEL", 22), ("PROTO", 6), ("SUHU", 7),
         ("STATUS", 8), ("HEALTH", 8), ("KEY METRIC", 0))  # 0 = sisa baris


def _use_color(stream: TextIO, force: str) -> bool:
    if force == "always":
        return True
    if force == "never":
        return False
    # auto: warna hanya kalau output ke terminal betulan (bukan pipe/file) dan
    # NO_COLOR tidak diset (konvensi https://no-color.org).
    return stream.isatty() and os.environ.get("NO_COLOR") is None


def _paint(text: str, level: Level, color: bool) -> str:
    if not color or level not in _ANSI:
        return text
    return f"{_ANSI[level]}{text}{_RESET}"


# ---------------------------------------------------------------- akuisisi

def _collect(devices: list[str]) -> tuple[list[DiskReport], str | None]:
    """Jalankan helper, kumpulkan DiskReport. Return (reports, fatal_error).

    Beda dari worker GUI: sinkron & sederhana. Helper mengeluarkan NDJSON;
    kita baca baris per baris sampai proses selesai.
    """
    try:
        cmd = build_helper_command(devices)
    except PrivilegeError as exc:
        return [], str(exc)

    reports: list[DiskReport] = []
    fatal: str | None = None
    proc = subprocess.Popen(cmd.argv, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    for raw in proc.stdout:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = msg.get("type")
        if kind == "result":
            reports.append(analyze(str(msg.get("device", "?")), msg.get("data"),
                                   bool(msg.get("ok")), msg.get("error"), DEFAULT_THRESHOLDS,
                                   flashdrive=bool(msg.get("flashdrive")), meta=msg.get("meta")))
        elif kind == "fatal":
            fatal = str(msg.get("error", "helper error"))
    proc.wait()
    if fatal is None and proc.returncode not in (0, None) and not reports:
        stderr = (proc.stderr.read().decode("utf-8", "replace").strip()
                  if proc.stderr else "")
        fatal = f"Helper keluar dengan kode {proc.returncode}." + (f"\n{stderr}" if stderr else "")
    return reports, fatal


# ---------------------------------------------------------------- output

def _print_table(reports: list[DiskReport], color: bool, out: TextIO) -> None:
    header = "  ".join(f"{name:<{w}}" if w else name for name, w in _COLS)
    print(f"{_BOLD}{header}{_RESET}" if color else header, file=out)
    print("-" * min(len(header) + 20, 100), file=out)
    for r in sorted(reports, key=lambda x: x.device):
        # Warnai STATUS & HEALTH sesuai levelnya; padding SEBELUM diwarnai supaya
        # kode ANSI tidak ikut terhitung sebagai lebar kolom (bug klasik di bash).
        # FD: read_ok=False tapi punya model/kapasitas -> tetap tampilkan.
        has_info = r.read_ok or r.dtype == "flashdrive"
        status = f"{r.status:<8}"
        health = f"{(r.health_text if has_info else '-'):<8}"
        cells = [
            f"{r.device:<13}",
            f"{(r.model[:22] if has_info else '-'):<22}",
            f"{(r.protocol_label if has_info else '-'):<6}",
            f"{(r.temperature_text if r.read_ok else '-'):<7}",
            _paint(status, r.status_level, color),
            _paint(health, r.health_level, color),
            r.key_metric,
        ]
        print("  ".join(cells), file=out)


def _print_detail(report: DiskReport, color: bool, out: TextIO) -> None:
    print(f"{_BOLD}Detail SMART: {report.device}{_RESET}" if color
          else f"Detail SMART: {report.device}", file=out)
    print("-" * 60, file=out)
    for row in report.details:
        value = _paint(row.value, row.level, color)
        print(f"  {row.label:<20}: {value}", file=out)
    if report.attributes and report.attributes.rows:
        print(f"\n  {_BOLD}Atribut SMART{_RESET}" if color else "\n  Atribut SMART", file=out)
        headers = report.attributes.headers
        print("  " + "  ".join(f"{h:<14}" for h in headers), file=out)
        for cells, level in report.attributes.rows:
            line = "  ".join(f"{c:<14}" for c in cells)
            print("  " + _paint(line, level, color), file=out)


def _to_json(reports: list[DiskReport]) -> str:
    """Output mesin-terbaca untuk cron/monitoring (Zabbix, Nagios, dsb)."""
    payload = [
        {
            "device": r.device, "read_ok": r.read_ok, "protocol": r.dtype,
            "model": r.model if r.read_ok else None,
            "temperature_c": r.temperature, "smart_status": r.status,
            "health_percent": r.health, "not_in_smartctl_db": r.not_in_db,
            "overall_level": r.overall_level.name,  # OK / WARN / CRIT / NA
            "key_metric": r.key_metric,
            "diagnosis": r.diagnosis if not r.read_ok else None,
        }
        for r in sorted(reports, key=lambda x: x.device)
    ]
    return json.dumps({"tool": "AmubaSMART", "version": __version__, "disks": payload},
                      indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- entry

def run_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="amubasmart", description="AmubaSMART — analisa kesehatan SMART (mode CLI).")
    parser.add_argument("devices", nargs="*",
                        help="device spesifik (mis. /dev/sda). Kosong = scan semua.")
    parser.add_argument("--cli", action="store_true",
                        help="paksa mode CLI (default kalau tanpa display)")
    parser.add_argument("--json", action="store_true",
                        help="output JSON (buat scripting/monitoring)")
    parser.add_argument("--detail", action="store_true", help="tampilkan detail lengkap tiap disk")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("-V", "--version", action="version", version=f"AmubaSMART {__version__}")
    args = parser.parse_args(argv)

    reports, fatal = _collect(args.devices)
    if fatal:
        print(f"Error: {fatal}", file=sys.stderr)
        return 3
    if not reports:
        print("Gak ada disk yang kebaca.", file=sys.stderr)
        return 1

    if args.json:
        print(_to_json(reports))
    else:
        color = _use_color(sys.stdout, args.color)
        if args.detail or args.devices:
            for i, report in enumerate(reports):
                if i:
                    print()
                _print_detail(report, color, sys.stdout)
        else:
            _print_table(reports, color, sys.stdout)

    # Exit code bermakna buat monitoring: 0 sehat semua, 2 ada yang CRIT,
    # 1 ada WARN. Script cron bisa `if amubasmart --cli --json; then ...`.
    worst = max((r.overall_level for r in reports), default=Level.OK)
    return {Level.CRIT: 2, Level.WARN: 1}.get(worst, 0)
