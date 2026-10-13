"""JSON skema 2 (`--full`) & `--push` ke hub (server HTTP lokal palsu)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from amubasmart import cli, privilege
from amubasmart.analysis import analyze


def _attr(id_, name, value, thresh, raw_value):
    return {"id": id_, "name": name, "value": value, "worst": value, "thresh": thresh,
            "when_failed": "", "flags": {"prefailure": thresh > 0},
            "raw": {"value": raw_value, "string": str(raw_value)}}


SATA = {
    "smartctl": {"exit_status": 0}, "model_name": "ST1000LM035", "serial_number": " WL1234 ",
    "firmware_version": "LCM2", "user_capacity": {"bytes": 1000204886016},
    "in_smartctl_database": True, "smart_status": {"passed": True},
    "temperature": {"current": 38}, "power_on_time": {"hours": 2234},
    "ata_smart_attributes": {"table": [
        _attr(5, "Reallocated_Sector_Ct", 100, 36, 8),
        _attr(197, "Current_Pending_Sector", 100, 0, 0),
        _attr(199, "UDMA_CRC_Error_Count", 200, 0, 1),
    ]},
}
NVME = {
    "smartctl": {"exit_status": 0}, "model_name": "NVME TEST", "serial_number": "NV99",
    "firmware_version": "1.0", "nvme_total_capacity": 512110190592,
    "smart_status": {"passed": True}, "temperature": {"current": 41},
    "nvme_smart_health_information_log": {
        "percentage_used": 7, "available_spare": 100, "available_spare_threshold": 10,
        "media_errors": 0, "unsafe_shutdowns": 12, "power_on_hours": 900, "critical_warning": 0},
}


def _reports():
    return [analyze("/dev/sdb", NVME, True), analyze("/dev/sda", SATA, True)]


def test_json_without_full_is_unchanged():
    out = json.loads(cli._to_json(_reports()))
    assert set(out) == {"tool", "version", "disks"}
    assert set(out["disks"][0]) == {"device", "read_ok", "protocol", "model", "temperature_c",
                                    "smart_status", "health_percent", "not_in_smartctl_db",
                                    "overall_level", "key_metric", "diagnosis"}


def test_full_schema2_fields():
    out = json.loads(cli._to_json(_reports(), full=True))
    assert out["schema"] == 2 and out["host"] and out["scanned_at"].endswith("+00:00")
    sda, sdb = out["disks"]  # diurut device
    assert sda["device"] == "/dev/sda" and sda["serial"] == "WL1234"
    assert sda["firmware"] == "LCM2" and sda["capacity_bytes"] == 1000204886016
    assert sda["power_on_hours"] == 2234
    assert sda["metrics"] == {"realloc": 8, "pending": 0, "crc": 1, "nvme_used_pct": None,
                              "media_errors": None, "unsafe_shutdowns": None}
    assert sda["overall_level"] in ("WARN", "CRIT")  # realloc 8 > ambang kuning
    assert sda["details"] and {"label", "value", "level"} <= set(sda["details"][0])
    assert sda["attributes"]["headers"] and sda["attributes"]["rows"][0]["level"] in (
        "NA", "OK", "WARN", "CRIT")
    assert sdb["capacity_bytes"] == 512110190592 and sdb["power_on_hours"] == 900
    assert sdb["metrics"]["nvme_used_pct"] == 7 and sdb["metrics"]["unsafe_shutdowns"] == 12
    assert sdb["metrics"]["realloc"] is None


def test_failed_read_has_no_serial():
    out = cli._payload([analyze("/dev/sdc", None, False, "Permission denied")], full=True)
    disk = out["disks"][0]
    assert disk["read_ok"] is False and disk["serial"] is None and disk["attributes"] is None


# ---------------------------------------------------------------- push

class _Hub:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.requests = []
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                hub.requests.append((self.path, dict(self.headers), json.loads(body)))
                code = hub.statuses.pop(0) if hub.statuses else 200
                self.send_response(code)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/infra/ingest/smart"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def token(tmp_path):
    p = tmp_path / "token"
    p.write_text("rahasia-123\n")
    return str(p)


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    monkeypatch.setattr(cli, "PUSH_RETRY_DELAY_S", 0)


def test_push_ok_sends_bearer_and_schema2(token):
    hub = _Hub([200])
    try:
        assert cli._push(hub.url, token, cli._payload(_reports(), full=True)) is None
        path, headers, body = hub.requests[0]
        assert path == "/api/infra/ingest/smart"
        assert headers["Authorization"] == "Bearer rahasia-123"
        assert body["schema"] == 2 and len(body["disks"]) == 2
    finally:
        hub.close()


def test_push_retries_5xx_then_succeeds(token):
    hub = _Hub([503, 500, 200])
    try:
        assert cli._push(hub.url, token, {"disks": []}) is None
        assert len(hub.requests) == 3
    finally:
        hub.close()


def test_push_4xx_fails_without_retry(token):
    hub = _Hub([401, 200])
    try:
        assert "401" in cli._push(hub.url, token, {"disks": []})
        assert len(hub.requests) == 1
    finally:
        hub.close()


def test_push_gives_up_after_3(token):
    hub = _Hub([500, 500, 500, 200])
    try:
        assert "3x" in cli._push(hub.url, token, {"disks": []})
        assert len(hub.requests) == 3
    finally:
        hub.close()


def test_push_rejects_bad_scheme_and_token(tmp_path, token):
    assert "http" in cli._push("file:///etc/passwd", token, {})
    assert "--token-file" in cli._push("http://127.0.0.1:1/x", None, {})
    empty = tmp_path / "kosong"
    empty.write_text("  \n")
    assert "kosong" in cli._push("http://127.0.0.1:1/x", str(empty), {})
    assert "gak kebaca" in cli._push("http://127.0.0.1:1/x", str(tmp_path / "nggak-ada"), {})


def test_run_cli_push_exit_codes(monkeypatch, token, capsys):
    monkeypatch.setattr(cli, "_collect", lambda devs, elevate=True: ([analyze("/dev/sdb", NVME, True)], None))
    hub = _Hub([200, 401])
    try:
        assert cli.run_cli(["--no-history", "--push", hub.url, "--token-file", token]) == 0
        assert "Terkirim ke hub: 1 disk" in capsys.readouterr().err
        assert cli.run_cli(["--no-history", "--push", hub.url, "--token-file", token]) == 4
    finally:
        hub.close()
    assert cli.run_cli(["--push", "http://127.0.0.1:1/x"]) == 3  # tanpa token-file


def test_no_elevate_runs_helper_directly(monkeypatch):
    monkeypatch.setattr(privilege, "is_admin", lambda: False)
    cmd = privilege.build_helper_command(["/dev/sda"], elevate=False)
    assert cmd.mode is privilege.PrivilegeMode.DIRECT and "pkexec" not in " ".join(cmd.argv)
    assert cmd.argv[-1] == "/dev/sda"


def test_helper_keeps_running_when_parent_is_pid1(monkeypatch):
    # Kontainer: `amubasmart` = PID 1, jadi parent helper memang 1 — jangan dikira parent mati.
    from amubasmart import smart_helper
    monkeypatch.setattr(smart_helper.os, "getppid", lambda: 1)
    smart_helper._set_parent_death_signal()  # dulu: SystemExit(0)
