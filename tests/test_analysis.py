"""Regression test untuk kasus lapangan nyata yang pernah bikin script bash salah."""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from amubasmart import smart_helper
from amubasmart.analysis import (
    Level, analyze, ata_raw_clean, detect_type, sata_health_score, vendor_wear_pct,
)


def _attr(id_, name, value, thresh, raw_value, raw_string=None, when_failed=""):
    return {"id": id_, "name": name, "value": value, "worst": value, "thresh": thresh,
            "when_failed": when_failed, "flags": {"prefailure": thresh > 0},
            "raw": {"value": raw_value, "string": raw_string or str(raw_value)}}


def _ata(attrs, *, in_db=True, passed=True):
    return {"smartctl": {"exit_status": 0}, "model_name": "TEST DRIVE",
            "in_smartctl_database": in_db, "smart_status": {"passed": passed},
            "temperature": {"current": 35}, "ata_smart_attributes": {"table": attrs}}


def test_seagate_packed_raw_uses_string_prefix():
    # ST1000LM035: raw.value 6-byte packed = 27 miliar tahun, raw.string yang benar.
    attr = _attr(9, "Power_On_Hours", 98, 0, 236708532600720, "2234 (105 2 0)")
    assert ata_raw_clean(attr) == 2234


def test_vendor_wear_gated_by_drivedb():
    # N-Tech: model gak dikenal tapi ID 177 tetap dinamai Wear_Leveling_Count.
    attrs = [_attr(177, "Wear_Leveling_Count", 85, 0, 123)]
    assert vendor_wear_pct(_ata(attrs, in_db=True)) == (85, "Wear_Leveling_Count")
    assert vendor_wear_pct(_ata(attrs, in_db=False)) == (None, None)


def test_inverted_wear_name():
    attrs = [_attr(202, "Perc_Rated_Life_Used", 20, 0, 20)]
    assert vendor_wear_pct(_ata(attrs)) == (80, "Perc_Rated_Life_Used")


def test_margin_score_picks_tightest_attribute():
    # Dua attribute KEAUSAN asli; yang lebih mepet ke threshold-nya yang menang.
    # ID 5 (Reallocated) tetap dipakai; ID 169 Bad_Block juga indikator keausan.
    attrs = [_attr(5, "Reallocated_Sector_Ct", 100, 10, 0),
             _attr(169, "Bad_Block_Count", 60, 20, 0)]   # (60-20)/80 = 50%
    assert sata_health_score(_ata(attrs)) == 50.0


def test_non_wear_attributes_excluded_from_score():
    """Suhu & error-rate TIDAK boleh menyeret skor (kasus nyata ADATA SU650).

    Temperature value=66 thresh=30 -> margin 51.4% KALAU salah dihitung.
    Dengan pengecualian, attribute keausan sehat (100/50) yang menentukan.
    """
    attrs = [_attr(5, "Reallocated_Sector_Ct", 100, 50, 0),
             _attr(194, "Temperature_Celsius", 66, 30, 34),      # suhu -> diabaikan
             _attr(1, "Raw_Read_Error_Rate", 77, 44, 0)]         # error-rate -> diabaikan
    score = sata_health_score(_ata(attrs))
    assert score == 100.0, f"suhu/error-rate ikut terhitung, skor jadi {score}"


def test_thresh_zero_attributes_ignored():
    assert sata_health_score(_ata([_attr(5, "Reallocated_Sector_Ct", 100, 0, 0)])) is None


def test_smart_failed_overrides_health():
    r = analyze("/dev/sdz", _ata([_attr(5, "Reallocated_Sector_Ct", 100, 10, 0)],
                                 passed=False), True)
    assert (r.health, r.health_level, r.overall_level) == (0, Level.CRIT, Level.CRIT)


def test_not_in_db_marked_with_asterisk():
    r = analyze("/dev/sdz", _ata([_attr(5, "Reallocated_Sector_Ct", 100, 50, 0)],
                                 in_db=False), True)
    assert r.health_text == "100%*" and r.not_in_db


def test_realloc_escalates_row_even_if_health_green():
    r = analyze("/dev/sdz", _ata([_attr(5, "Reallocated_Sector_Ct", 100, 10, 3)]), True)
    assert r.health_level is Level.OK
    assert r.overall_level is Level.WARN
    assert r.key_metric == "Realloc:3 Pending:N/A"


def test_crc_uses_own_thresholds():
    r = analyze("/dev/sdz", _ata([_attr(199, "UDMA_CRC_Error_Count", 200, 0, 20)]), True)
    row = next(d for d in r.details if d.label.startswith("ID 199"))
    assert row.level is Level.WARN   # 20 < CRC_CRIT(50), padahal > ATA_RAW_CRIT(10)


def test_nvme_used_crit():
    data = {"smart_status": {"passed": True}, "model_name": "NVME",
            "nvme_smart_health_information_log": {
                "percentage_used": 95, "available_spare": 100,
                "available_spare_threshold": 10, "critical_warning": 0,
                "data_units_written": 2_000_000}}
    r = analyze("/dev/nvme0n1", data, True)
    assert r.dtype == "nvme" and r.health == 5 and r.health_level is Level.CRIT
    assert any(d.value == "1024 GB" for d in r.details)


def test_sas_detected_with_error_counter_only():
    # Bug fix vs bash: jq -e '.a, .b' cuma menilai .b
    assert detect_type({"scsi_error_counter_log": {"read": {}}}) == "sas"


def test_read_failure_decodes_bit1():
    r = analyze("/dev/sdz", {"smartctl": {"exit_status": 2}, "device": {}}, False)
    assert not r.read_ok and r.status == "GAGAL" and "reseat" in r.diagnosis


@pytest.mark.skipif(sys.platform == "win32", reason="fake smartctl pakai shell script")
def test_helper_retries_once(tmp_path: Path, monkeypatch):
    # Simulasi N-Tech: attempt 1 cuma .device kosong, attempt 2 normal.
    fake = tmp_path / "smartctl"
    fake.write_text(
        '#!/bin/sh\nf="$(dirname "$0")/count"\nn=$(cat "$f" 2>/dev/null || echo 0)\n'
        'n=$((n+1)); echo $n > "$f"\n'
        'if [ $n -eq 1 ]; then echo \'{"smartctl":{"exit_status":2},"device":{}}\'; exit 2; fi\n'
        'echo \'{"smartctl":{"exit_status":0},"nvme_smart_health_information_log":'
        '{"percentage_used":1}}\'\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(smart_helper, "RETRY_DELAY_S", 0)
    result = smart_helper.read_smart(os.fspath(fake), "/dev/fake")
    assert result["ok"] and result["attempts"] == 2


def test_helper_rejects_non_block_device():
    assert not smart_helper.validate_device("/dev/../etc/passwd")
    assert not smart_helper.validate_device("/dev/-a")
    assert not smart_helper.validate_device("/dev/null")   # char device, bukan block


def test_bundled_smartctl_priority(tmp_path, monkeypatch):
    """Windows onedir: smartctl di samping exe harus menang atas PATH sistem."""
    monkeypatch.setattr(smart_helper, "_IS_WINDOWS", True)
    monkeypatch.setattr(smart_helper.sys, "frozen", True, raising=False)
    monkeypatch.setattr(smart_helper.sys, "executable",
                        str(tmp_path / "AmubaSMART.exe"), raising=False)

    # Belum ada bundle -> None (nanti jatuh ke which()/kandidat sistem).
    assert smart_helper._bundled_smartctl() is None

    # Layout root: exe & smartctl.exe sefolder.
    (tmp_path / "smartctl.exe").write_bytes(b"")
    assert smart_helper._bundled_smartctl() == str(tmp_path / "smartctl.exe")

    # Layout subfolder smartmontools\ juga dikenali.
    (tmp_path / "smartctl.exe").unlink()
    sub = tmp_path / "smartmontools"
    sub.mkdir()
    (sub / "smartctl.exe").write_bytes(b"")
    assert smart_helper._bundled_smartctl() == str(sub / "smartctl.exe")


# ---- CLI (mode teks, tanpa Qt) ----

def test_cli_json_output(capsys, monkeypatch):
    """run_cli --json harus keluarkan JSON valid tanpa menyentuh PyQt6."""
    from amubasmart import cli

    fake = analyze("/dev/sda", _ata([_attr(5, "Reallocated_Sector_Ct", 100, 10, 0)]), True)
    monkeypatch.setattr(cli, "_collect", lambda devices: ([fake], None))
    rc = cli.run_cli(["--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["tool"] == "AmubaSMART"
    assert payload["disks"][0]["device"] == "/dev/sda"
    assert payload["disks"][0]["health_percent"] == 100.0


def test_cli_exit_code_reflects_worst(capsys, monkeypatch):
    """Exit code: CRIT->2, WARN->1, OK->0 (buat cron/monitoring)."""
    from amubasmart import cli

    crit = analyze("/dev/sdz", _ata([_attr(5, "Reallocated_Sector_Ct", 100, 10, 0)],
                                    passed=False), True)
    monkeypatch.setattr(cli, "_collect", lambda devices: ([crit], None))
    assert cli.run_cli(["--json"]) == 2


def test_cli_no_qt_import():
    """amubasmart.cli TIDAK boleh menarik PyQt6 (harus jalan di server headless)."""
    import importlib
    import sys as _sys

    for mod in [m for m in _sys.modules if m.startswith("PyQt6")]:
        del _sys.modules[mod]
    importlib.import_module("amubasmart.cli")
    assert not any(m.startswith("PyQt6") for m in _sys.modules), \
        "cli.py menarik PyQt6 — akan gagal di server tanpa Qt"


# ---- USB bridge auto-retry (kasus SSK DK201) ----

def test_usb_bridge_detection():
    """Output 'Unknown USB bridge' harus terdeteksi supaya helper coba flag -d."""
    from amubasmart.smart_helper import _looks_like_usb_bridge
    bridge = {"smartctl": {"messages": [
        {"string": "/dev/sdb: Unknown USB bridge [0x152d:0xa586 (0x114)]"}]}}
    assert _looks_like_usb_bridge(bridge)
    assert not _looks_like_usb_bridge({"smartctl": {"messages": [{"string": "all good"}]}})
    assert not _looks_like_usb_bridge({"nvme_smart_health_information_log": {}})


def test_usb_bridge_dtype_shown_in_report():
    """Marker usb_bridge_dtype dari helper harus muncul sebagai detail 'Koneksi'."""
    data = {
        "model_name": "WDC SN530", "smart_status": {"passed": True},
        "temperature": {"current": 57},
        "nvme_smart_health_information_log": {
            "percentage_used": 0, "available_spare": 100,
            "available_spare_threshold": 10, "critical_warning": 0},
        "amubasmart": {"usb_bridge_dtype": "sntjmicron"},
    }
    r = analyze("/dev/sdb", data, True)
    koneksi = [d for d in r.details if d.label == "Koneksi"]
    assert koneksi and "sntjmicron" in koneksi[0].value


# ---- Flashdisk / USB removable (kasus Cruzer Blade) ----

def test_flashdrive_detection():
    """TRAN=usb + RM=1 -> flashdisk. SSD internal & SSD-di-dock TIDAK."""
    from amubasmart.smart_helper import is_flashdrive
    assert is_flashdrive({"tran": "usb", "removable": True})           # Cruzer Blade
    assert not is_flashdrive({"tran": "sata", "removable": False})     # SSD internal
    assert not is_flashdrive({"tran": "usb", "removable": False})      # SSD di dock DK201
    assert not is_flashdrive({"tran": "nvme", "removable": False})


def test_flashdrive_report_is_neutral_not_alarm():
    """FD dilabeli netral (NA), bukan alarm GAGAL merah, + info kapasitas/model."""
    meta = {"tran": "usb", "removable": True, "readonly": False,
            "size": "57,3G", "model": "Cruzer Blade"}
    r = analyze("/dev/sdd", None, False, flashdrive=True, meta=meta)
    assert r.dtype == "flashdrive"
    assert r.overall_level is Level.NA          # netral, bukan WARN/CRIT
    assert "Cruzer Blade" in r.model
    assert any("57,3G" in d.value for d in r.details)


def test_flashdrive_readonly_flagged():
    """FD read-only (gejala controller sekarat) -> WARN, bukan netral."""
    meta = {"tran": "usb", "removable": True, "readonly": True, "model": "FD"}
    r = analyze("/dev/sdd", None, False, flashdrive=True, meta=meta)
    assert r.overall_level is Level.WARN
    assert "READ-ONLY" in r.key_metric


# ---- Ekspor PDF (report.py) ----

def test_pdf_report_generated(tmp_path):
    """build_report menghasilkan file PDF valid dari DiskReport."""
    from amubasmart.report import build_report

    r = analyze("/dev/sda", _ata([_attr(5, "Reallocated_Sector_Ct", 100, 50, 0)]), True)
    out = tmp_path / "test.pdf"
    build_report([r], str(out))
    assert out.is_file()
    assert out.read_bytes()[:4] == b"%PDF"    # header PDF valid


def test_pdf_report_multiple_disks(tmp_path):
    """PDF dengan beberapa disk (termasuk flashdrive) tidak crash."""
    from amubasmart.report import build_report

    sata = analyze("/dev/sda", _ata([_attr(5, "Reallocated_Sector_Ct", 100, 50, 0)]), True)
    fd = analyze("/dev/sdd", None, False, flashdrive=True,
                 meta={"tran": "usb", "removable": True, "model": "Cruzer Blade",
                       "size": "57,3G", "readonly": False})
    out = tmp_path / "multi.pdf"
    build_report([sata, fd], str(out))
    assert out.is_file() and out.read_bytes()[:4] == b"%PDF"


# ---- CRC error di-cap WARN (kasus Samsung 850 EVO) ----

def test_crc_error_capped_at_warn():
    """CRC tinggi (ID 199) -> WARN, TIDAK pernah CRIT (masalah kabel, bukan disk).

    Kasus nyata Samsung 850 EVO: CRC=161, 0 realloc, health 97% -> harus WARN.
    Sebelum fix, CRC>=50 memicu CRIT (badge KRITIS keliru).
    """
    attrs = [_attr(5, "Reallocated_Sector_Ct", 100, 10, 0),      # 0 bad sector
             _attr(199, "UDMA_CRC_Error_Count", 99, 0, 161)]      # CRC tinggi
    r = analyze("/dev/sdc", _ata(attrs), True)
    assert Level.CRIT not in r.indicator_levels, "CRC seharusnya tak memicu CRIT"
    assert r.overall_level is Level.WARN


def test_real_bad_sector_still_crit():
    """Bad sector nyata (realloc >= crit) tetap CRIT — jangan sampai ikut ter-cap."""
    attrs = [_attr(5, "Reallocated_Sector_Ct", 99, 36, 48)]       # 48 bad sector
    r = analyze("/dev/sdd", _ata(attrs), True)
    assert r.overall_level is Level.CRIT


def test_attribute_table_no_scientific_notation_column():
    """Kolom 'Raw Value' (notasi ilmiah) dibuang; 'Raw' pakai string akurat."""
    attrs = [_attr(9, "Power_On_Hours", 82, 0, 16272)]
    r = analyze("/dev/sdd", _ata(attrs), True)
    assert r.attributes.headers == ["ID", "Atribut", "Normalized", "Worst",
                                     "Thresh", "Raw", "Tipe"]


# ---- Riwayat scan (history.py) ----

def test_history_records_and_tracks_trend(tmp_path):
    """Riwayat mencatat & melacak pergerakan metrik per serial."""
    from datetime import datetime, timedelta, timezone
    from amubasmart.history import History

    h = History(tmp_path / "h.db")
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for i, rc in enumerate([0, 5, 12]):
        data = _ata([_attr(5, "Reallocated_Sector_Ct", 100 - rc, 36, rc)])
        data["serial_number"] = "SN-TEST"
        h.record(analyze("/dev/sda", data, True), scanned_at=base + timedelta(days=i))
    assert len(h.drives()) == 1
    assert h.delta("SN-TEST", "realloc") == 12       # naik = memburuk
    assert len(h.history_for("SN-TEST")) == 3


def test_history_skips_no_serial(tmp_path):
    """Drive tanpa serial tak dicatat (tak ada identitas untuk melacak)."""
    from amubasmart.history import History

    h = History(tmp_path / "h.db")
    r = analyze("/dev/sdz", _ata([_attr(5, "Reallocated_Sector_Ct", 100, 36, 0)]), True)
    assert h.record(r) is False
    assert h.drives() == []


def test_history_fifo_limit(tmp_path, monkeypatch):
    """Snapshot dibatasi MAX_SNAPSHOTS per drive (FIFO)."""
    from datetime import datetime, timedelta, timezone
    from amubasmart import history as hist

    monkeypatch.setattr(hist, "MAX_SNAPSHOTS", 3)
    h = hist.History(tmp_path / "h.db")
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(6):
        data = _ata([_attr(5, "Reallocated_Sector_Ct", 100, 36, i)])
        data["serial_number"] = "SN-X"
        h.record(analyze("/dev/sda", data, True), scanned_at=base + timedelta(days=i))
    snaps = h.history_for("SN-X")
    assert len(snaps) == 3                            # cuma 3 terbaru
    assert snaps[0].realloc == 5                      # terbaru (i=5)


# ---- Opsi A: Unknown_Attribute dikecualikan dari health (kasus HUH728080) ----

def test_unknown_attribute_excluded_from_health():
    """Attribute vendor tak dikenal (Unknown_Attribute) tak menyeret skor.

    HGST HUH728080: ID 45 Unknown_Attribute value=50/thresh=1 -> margin 49.5%.
    Setelah fix, attribute keausan ASLI (semua sehat) yang menentukan -> ~100%.
    """
    attrs = [
        _attr(5, "Reallocated_Sector_Ct", 100, 5, 0),
        _attr(45, "Unknown_Attribute", 50, 1, 4311679231),   # tak dikenal -> abaikan
        _attr(22, "Helium_Level", 100, 25, 100),
    ]
    r = analyze("/dev/sda", _ata(attrs), True)
    assert r.health == 100.0
    assert r.overall_level is Level.OK


def test_known_wear_attribute_still_counts():
    """Attribute keausan yang DIKENAL (mis. Helium_Level) tetap dihitung."""
    attrs = [
        _attr(5, "Reallocated_Sector_Ct", 100, 5, 0),
        _attr(22, "Helium_Level", 30, 25, 0),                # He bocor - masalah nyata
    ]
    r = analyze("/dev/sda", _ata(attrs), True)
    assert r.health is not None and r.health < 20    # margin (30-25)/(100-25) = 6.7%
