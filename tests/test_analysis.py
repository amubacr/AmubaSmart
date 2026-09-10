"""Regression test untuk kasus lapangan nyata yang pernah bikin script bash salah."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from diskhealth import smart_helper
from diskhealth.analysis import (
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
    attrs = [_attr(5, "Reallocated_Sector_Ct", 100, 10, 0),
             _attr(1, "Raw_Read_Error_Rate", 60, 20, 0)]   # (60-20)/80 = 50%
    assert sata_health_score(_ata(attrs)) == 50.0


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
