"""
analysis.py — logika analisa SMART, terjemahan dari disk-health.sh.

Murni Python: TANPA Qt, TANPA subprocess. Input = dict hasil json.loads()
output `smartctl -a -j`. Dengan begitu modul ini:
  - bisa di-unit-test pakai fixture JSON drive nyata (Seagate, N-Tech, VISPRO...),
  - bisa dipakai ulang di frontend lain (CLI, web) tanpa bawa dependensi GUI.

Pemetaan fungsi bash -> Python ada di komentar tiap fungsi.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

JsonDict = dict[str, Any]


class Level(IntEnum):
    """Severity. Nilai numerik dipakai max(): level terburuk yang menang."""

    NA = 0     # info netral, tanpa warna
    OK = 1     # hijau
    WARN = 2   # kuning
    CRIT = 3   # merah


@dataclass(frozen=True)
class Thresholds:
    """Blok threshold dari script bash (silakan di-tuning sesuai lapangan)."""

    nvme_used_warn: int = 50
    nvme_used_crit: int = 90
    nvme_spare_margin_warn: int = 15
    nvme_spare_margin_crit: int = 5
    ata_raw_warn: int = 1        # raw ID 5/187/197/198
    ata_raw_crit: int = 10
    crc_warn: int = 1            # ID 199 (UDMA CRC) -> sering kabel/konektor
    crc_crit: int = 50
    sas_defect_warn: int = 1
    sas_defect_crit: int = 100
    health_ok: float = 70
    health_warn: float = 30


DEFAULT_THRESHOLDS = Thresholds()

CRITICAL_ATA_IDS: tuple[int, ...] = (5, 187, 197, 198, 199)
CRC_ATTR_ID = 199
WEAR_NAMES: tuple[str, ...] = (
    "Wear_Leveling_Count", "Media_Wearout_Indicator", "SSD_Life_Left",
    "Percent_Lifetime_Remain", "Remaining_Lifetime_Perc",
)
INVERTED_WEAR_NAMES: tuple[str, ...] = ("Perc_Rated_Life_Used",)  # VALUE naik = makin aus

PROTOCOL_LABELS = {"nvme": "NVMe", "sata": "SATA/ATA", "sas": "SAS/SCSI", "unknown": "?"}

_RAW_LEADING_INT = re.compile(r"^([0-9]+)")


# =============================================================================
# Util akses JSON (pengganti operator `//` di jq)
# =============================================================================

def _get(obj: Any, *path: str, default: Any = None) -> Any:
    """Akses nested aman, setara `.a.b // default` di jq untuk kasus null/missing."""
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _num(value: Any) -> int | float | None:
    """Angka beneran atau None. bool dikecualikan (di Python bool subclass int)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _fmt(value: int | float | None, suffix: str = "") -> str:
    return "N/A" if value is None else f"{value:g}{suffix}"


def _round1(x: float) -> float:
    # jq `round` = half away from zero; round() Python = banker's rounding.
    # x di sini selalu >= 0 (sudah di-clamp), jadi floor(x*10 + .5) cukup.
    return math.floor(x * 10 + 0.5) / 10


# =============================================================================
# Validasi & diagnosa pembacaan
# =============================================================================

def has_smart_data(data: Any) -> bool:
    """bash: validasi jq -e di get_smart_json()."""
    if not isinstance(data, dict):
        return False
    return (
        _get(data, "ata_smart_attributes", "table") is not None
        or data.get("nvme_smart_health_information_log") is not None
        or data.get("scsi_error_counter_log") is not None
        or data.get("scsi_grown_defect_list") is not None
    )


_EXIT_BITS: tuple[tuple[int, str], ...] = (
    (1, "command-line smartctl gak valid"),
    (2, "device gak kebuka / gak respon IDENTIFY — coba URUTAN INI: (1) reseat kabel "
        "data & power fisik dulu; (2) paksa protokol: smartctl -a -d sat / -d scsi / "
        "-d sntjmicron <drive>; (3) cek device lagi sleep/low-power"),
    (4, "command SMART/ATA gagal atau checksum error"),
    (8, "SMART overall status bilang DISK FAILING"),
    (16, "ada attribute prefail yang <= threshold"),
    (32, "pernah ada attribute yang nembus threshold"),
    (64, "error log drive ada isinya"),
    (128, "self-test log drive ada isinya"),
)


def decode_smartctl_exit(bits: int) -> list[str]:
    """bash: decode_smartctl_exit() — lihat `man smartctl`, RETURN VALUES."""
    out = [msg for mask, msg in _EXIT_BITS if bits & mask]
    return out or [f"exit_status={bits}, bit gak dikenal"]


def smart_read_diagnosis(data: Any, error: str | None = None) -> str:
    """bash: smart_read_diagnosis(), plus pesan error dari helper (timeout, dll)."""
    exit_status = _num(_get(data, "smartctl", "exit_status"))
    if exit_status:
        bits = int(exit_status)
        return f"smartctl exit_status={bits} → " + "; ".join(decode_smartctl_exit(bits))
    if error:
        return error
    return ("gak ada data SMART yang kebaca — kemungkinan device gak dukung SMART, "
            "atau protokol USB bridge butuh flag -d eksplisit")


def detect_type(data: JsonDict) -> str:
    """bash: detect_type() — berbasis KEBERADAAN key, bukan .device.protocol."""
    if data.get("nvme_smart_health_information_log") is not None:
        return "nvme"
    if _get(data, "ata_smart_attributes", "table") is not None:
        return "sata"
    # BUG FIX vs bash: `jq -e '.a, .b'` cuma menilai output TERAKHIR (.b), jadi
    # drive yang cuma punya scsi_error_counter_log jatuh ke "unknown". Di sini OR beneran.
    if (data.get("scsi_error_counter_log") is not None
            or data.get("scsi_grown_defect_list") is not None):
        return "sas"
    return "unknown"


def smart_status_text(data: JsonDict) -> str:
    passed = _get(data, "smart_status", "passed")  # False tetap False (bukan default)
    if passed is True:
        return "PASSED"
    if passed is False:
        return "FAILED"
    return "N/A"


def in_smartctl_db(data: JsonDict) -> bool:
    """bash: in_smartctl_db() — model BENERAN ketemu di drivedb smartctl?

    Beda dari "attribute punya nama": smartctl tetap kasih nama default untuk ID
    umum walau model gak dikenal (kasus N-Tech: ID 177 dinamai Wear_Leveling_Count
    dengan raw absurd). Field INI yang jadi pagar vendor_wear_pct().
    """
    return data.get("in_smartctl_database") is True


# =============================================================================
# ATA helpers
# =============================================================================

def ata_table(data: JsonDict) -> list[JsonDict]:
    table = _get(data, "ata_smart_attributes", "table", default=[])
    return [a for a in table if isinstance(a, dict)] if isinstance(table, list) else []


def find_ata_attr(data: JsonDict, attr_id: int) -> JsonDict | None:
    return next((a for a in ata_table(data) if a.get("id") == attr_id), None)


def ata_raw_clean(attr: JsonDict | None) -> int | None:
    """bash: ata_attr_raw_clean() — raw value integer "bersih".

    Kasus nyata Seagate ST1000LM035: ID 9 .raw.value = 236.708.532.600.720
    (6 byte packed), sedangkan .raw.string = "2234 (105 2 0)". Ambil angka
    di depan .raw.string (parsing resmi smartctl), fallback ke .raw.value.
    """
    if attr is None:
        return None
    raw_str = _get(attr, "raw", "string")
    if isinstance(raw_str, str):
        match = _RAW_LEADING_INT.match(raw_str.strip())
        if match:
            return int(match.group(1))
    raw_val = _num(_get(attr, "raw", "value"))
    return int(raw_val) if raw_val is not None else None


# =============================================================================
# Skor kesehatan — TRANSPARAN (lihat catatan panjang di script bash)
# =============================================================================

def nvme_health_score(data: JsonDict) -> float | None:
    """bash: nvme_health_score() — 100 - percentage_used (field wajib NVMe spec)."""
    used = _num(_get(data, "nvme_smart_health_information_log", "percentage_used"))
    if used is None:
        return None
    return max(0, 100 - used)  # percentage_used boleh > 100 (spec: sampai 255)


def sata_health_score(data: JsonDict) -> float | None:
    """bash: sata_health_score() — margin attribute paling mepet ke threshold-nya.

    (value - thresh) / (100 - thresh) * 100, hanya attribute 0 < thresh < 100.
    """
    margins: list[float] = []
    for attr in ata_table(data):
        value, thresh = _num(attr.get("value")), _num(attr.get("thresh"))
        if value is None or thresh is None or not 0 < thresh < 100:
            continue
        margins.append((value - thresh) / (100 - thresh) * 100)
    if not margins:
        return None
    return _round1(min(max(min(margins), 0.0), 100.0))


def vendor_wear_pct(data: JsonDict) -> tuple[float | None, str | None]:
    """bash: vendor_wear_pct() — return (persen, nama attribute sumber).

    Dipagar in_smartctl_db(): model gak dikenal -> JANGAN percaya nama attribute.
    Dicocokkan via NAMA (bukan ID) karena ruang ID vendor-spesifik gampang tabrakan.
    """
    if not in_smartctl_db(data):
        return None, None
    for attr in ata_table(data):  # urutan tabel, sama kayak $matches[0] di jq
        name = attr.get("name")
        if name in WEAR_NAMES or name in INVERTED_WEAR_NAMES:
            value = _num(attr.get("value"))
            if value is None:
                return None, name
            return (100 - value if name in INVERTED_WEAR_NAMES else value), name
    return None, None


def combine_min(a: float | None, b: float | None) -> float | None:
    """bash: combine_min() — kesehatan cuma sebagus dimensi paling lemahnya.

    Bash membandingkan bagian integer saja (keterbatasan `-le`); di sini float penuh.
    """
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


_NVME_WARN_BITS = (
    (1, "Spare Rendah"), (2, "Suhu Diluar Batas"), (4, "Reliabilitas NVM Turun"),
    (8, "Media Read-Only"), (16, "Backup Volatile Memory Gagal"),
)


def decode_nvme_warning(bits: int) -> list[str]:
    out = [msg for mask, msg in _NVME_WARN_BITS if bits & mask]
    return out or ["Bit tidak dikenal"]


def level_for_score(score: float, th: Thresholds = DEFAULT_THRESHOLDS) -> Level:
    if score >= th.health_ok:
        return Level.OK
    if score >= th.health_warn:
        return Level.WARN
    return Level.CRIT


def level_for_count(value: float, warn: float, crit: float) -> Level:
    """Pola `>= crit -> merah, >= warn -> kuning, else hijau` yang berulang di bash."""
    if value >= crit:
        return Level.CRIT
    if value >= warn:
        return Level.WARN
    return Level.OK


# =============================================================================
# Model hasil untuk UI
# =============================================================================

@dataclass
class DetailRow:
    label: str
    value: str
    level: Level = Level.NA


@dataclass
class AttributeTable:
    headers: list[str]
    rows: list[tuple[list[str], Level]] = field(default_factory=list)


@dataclass
class DiskReport:
    device: str
    read_ok: bool
    dtype: str = "unknown"
    model: str = "-"
    temperature: float | None = None
    status: str = "N/A"
    status_level: Level = Level.WARN
    health: float | None = None
    health_text: str = "N/A"
    health_level: Level = Level.WARN
    not_in_db: bool = False
    key_metric: str = ""
    diagnosis: str = ""
    details: list[DetailRow] = field(default_factory=list)
    attributes: AttributeTable | None = None
    # Level indikator "bukti nyata" (raw count kritis, spare, defect...) untuk
    # warna BARIS. Kolom Kesehatan tetap setia ke logika health_field() bash.
    indicator_levels: list[Level] = field(default_factory=list)
    overall_level: Level = Level.WARN
    raw_json: JsonDict | None = None

    @property
    def protocol_label(self) -> str:
        return PROTOCOL_LABELS.get(self.dtype, "?")

    @property
    def temperature_text(self) -> str:
        # Fix yang sama kayak bash: jangan jadi "N/AC" kalau suhu gak kebaca.
        return _fmt(self.temperature, " °C")


# =============================================================================
# Entry point analisa
# =============================================================================

def analyze(device: str, data: JsonDict | None, read_ok: bool, error: str | None = None,
            th: Thresholds = DEFAULT_THRESHOLDS) -> DiskReport:
    """Satu disk: JSON smartctl -> DiskReport siap tampil."""
    if not read_ok or not isinstance(data, dict):
        diag = smart_read_diagnosis(data, error)
        return DiskReport(
            device=device, read_ok=False, status="GAGAL", status_level=Level.WARN,
            health_text="-", health_level=Level.NA, key_metric=diag, diagnosis=diag,
            details=[DetailRow("Diagnosis", diag, Level.WARN)],
            overall_level=Level.WARN, raw_json=data if isinstance(data, dict) else None,
        )

    dtype = detect_type(data)
    status = smart_status_text(data)
    report = DiskReport(
        device=device, read_ok=True, dtype=dtype,
        model=str(data.get("model_name") or _get(data, "device", "name") or "Unknown"),
        temperature=_num(_get(data, "temperature", "current")),
        status=status,
        # Deviasi sadar dari bash: N/A = kuning (bash: merah). "Drive gak lapor
        # status" != "drive dinyatakan gagal".
        status_level={"PASSED": Level.OK, "FAILED": Level.CRIT}.get(status, Level.WARN),
        not_in_db=(dtype == "sata" and not in_smartctl_db(data)),
        raw_json=data,
    )
    _fill_summary_health(report, data, th)
    builder = {"nvme": _analyze_nvme, "sata": _analyze_sata, "sas": _analyze_sas}.get(
        dtype, _analyze_unknown)
    builder(report, data, th)
    report.overall_level = _overall_level(report)
    return report


def _overall_level(r: DiskReport) -> Level:
    levels = [r.status_level, *r.indicator_levels]
    if r.health is not None:
        levels.append(r.health_level)
    elif not r.indicator_levels:
        levels.append(Level.WARN)  # gak ada skor & gak ada indikator = gak bisa dinilai
    return max(levels)


def _fill_summary_health(r: DiskReport, data: JsonDict, th: Thresholds) -> None:
    """bash: health_field() — kolom HEALTH tabel ringkasan."""
    if r.status == "FAILED":
        r.health, r.health_text, r.health_level = 0, "0%", Level.CRIT
        return
    if r.dtype == "nvme":
        score = nvme_health_score(data)
    elif r.dtype == "sata":
        score = combine_min(sata_health_score(data), vendor_wear_pct(data)[0])
    else:
        score = None

    if score is None:
        r.health, r.health_text, r.health_level = None, "N/A", Level.WARN
        return
    r.health = score
    r.health_text = _fmt(score, "%") + ("*" if r.not_in_db else "")
    r.health_level = level_for_score(score, th)


def _head_rows(r: DiskReport) -> list[DetailRow]:
    return [
        DetailRow("Model", r.model),
        DetailRow("Protokol", r.protocol_label),
        DetailRow("SMART Status", r.status, r.status_level),
    ]


def _health_row(status: str, score: float | None, basis: str, th: Thresholds,
                na_text: str = "N/A", caveat: str = "") -> DetailRow:
    label = "Perkiraan Kesehatan"
    if status == "FAILED":
        return DetailRow(label, "0% (SMART overall status FAILED, override)", Level.CRIT)
    if score is None:
        return DetailRow(label, na_text, Level.WARN)
    return DetailRow(label, f"{_fmt(score, '%')} ({basis}){caveat}", level_for_score(score, th))


# ---------------------------- NVMe ----------------------------------------

_NVME_FMT = {
    "data_units_read": lambda v: f"{v * 512000 / 1e9:.2f} GB",
    "data_units_written": lambda v: f"{v * 512000 / 1e9:.2f} GB",
    "percentage_used": lambda v: f"{v}%",
    "available_spare": lambda v: f"{v}%",
    "available_spare_threshold": lambda v: f"{v}%",
    "temperature": lambda v: f"{v} °C",
    "critical_warning": lambda v: f"0x{v:02x}",
}


def _analyze_nvme(r: DiskReport, data: JsonDict, th: Thresholds) -> None:
    """bash: analyze_nvme()."""
    log: JsonDict = data.get("nvme_smart_health_information_log") or {}
    used = _num(log.get("percentage_used"))
    spare = _num(log.get("available_spare"))
    spare_th = _num(log.get("available_spare_threshold"))
    crit_warn = _num(log.get("critical_warning"))
    poh = _num(_get(data, "power_on_time", "hours"))
    if poh is None:
        poh = _num(log.get("power_on_hours"))
    pcc = _num(data.get("power_cycle_count"))

    rows = _head_rows(r)
    rows.append(_health_row(r.status, nvme_health_score(data),
                            "dari 100 − percentage_used, standar NVMe", th))
    rows += [
        DetailRow("Suhu", r.temperature_text),
        DetailRow("Power On Hours", _fmt(poh, " jam")),
        DetailRow("Power Cycles", _fmt(pcc, "x")),
    ]

    # Level per-field dihitung SEKALI, dipakai detail + tabel atribut.
    field_levels: dict[str, Level] = {}

    if used is None:
        rows.append(DetailRow("Percentage Used", "N/A", Level.WARN))
    else:
        lvl = level_for_count(used, th.nvme_used_warn, th.nvme_used_crit)
        note = {Level.CRIT: " (mendekati/lewat rated endurance)",
                Level.WARN: " (sudah lewat separuh umur pakai)"}.get(lvl, "")
        rows.append(DetailRow("Percentage Used", f"{used}%{note}", lvl))
        field_levels["percentage_used"] = lvl

    if spare is None or spare_th is None:
        rows.append(DetailRow("Available Spare", "N/A", Level.WARN))
    else:
        margin = spare - spare_th
        if margin <= th.nvme_spare_margin_crit:
            lvl, note = Level.CRIT, ", mepet!"
        elif margin <= th.nvme_spare_margin_warn:
            lvl, note = Level.WARN, ""
        else:
            lvl, note = Level.OK, ""
        rows.append(DetailRow("Available Spare", f"{spare}% (ambang {spare_th}%{note})", lvl))
        field_levels["available_spare"] = lvl

    if crit_warn is None:
        rows.append(DetailRow("Critical Warning", "N/A", Level.WARN))
    elif crit_warn == 0:
        rows.append(DetailRow("Critical Warning", "0x00 (tidak ada warning aktif)", Level.OK))
        field_levels["critical_warning"] = Level.OK
    else:
        bits = int(crit_warn)
        rows.append(DetailRow("Critical Warning",
                              f"0x{bits:02x} → {', '.join(decode_nvme_warning(bits))}", Level.CRIT))
        field_levels["critical_warning"] = Level.CRIT

    for key, label in (("data_units_read", "Data Units Read"),
                       ("data_units_written", "Data Units Written")):
        units = _num(log.get(key)) or 0
        rows.append(DetailRow(label, f"{round(units * 512000 / 1e9, 2):g} GB"))

    r.details = rows
    r.indicator_levels = list(field_levels.values())
    r.key_metric = f"Used:{used}%" if used is not None else "N/A"

    table = AttributeTable(["Atribut", "Raw Value", "Normalized"])
    for key, value in log.items():
        raw = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
        fmt = _NVME_FMT.get(key)
        norm = fmt(value) if fmt and _num(value) is not None else "-"
        table.rows.append(([key, raw, norm], field_levels.get(key, Level.NA)))
    r.attributes = table


# ---------------------------- SATA ----------------------------------------

def _analyze_sata(r: DiskReport, data: JsonDict, th: Thresholds) -> None:
    """bash: analyze_sata()."""
    score = sata_health_score(data)
    vwear, wname = vendor_wear_pct(data)
    caveat = (" — WASPADA: model gak ketemu di drivedb smartctl, VALUE/THRESH bisa aja "
              "gak pernah di-update firmware, cek raw count manual") if r.not_in_db else ""

    rows = _head_rows(r)
    rows.append(_health_row(
        r.status, score, "margin attribute paling mepet ke threshold-nya sendiri", th,
        na_text=("N/A (drive gak expose attribute dengan threshold > 0 — umum di consumer "
                 "SSD, cek attribute mentah manual)"),
        caveat=caveat,
    ))
    if vwear is not None:
        rows.append(DetailRow("Wear NAND (vendor)",
                              f"{_fmt(vwear, '%')} (dari attribute '{wname}', konvensi vendor)",
                              level_for_score(vwear, th)))
    rows += [
        DetailRow("Suhu", r.temperature_text),
        DetailRow("Power On Hours", _fmt(ata_raw_clean(find_ata_attr(data, 9)), " jam")),
        DetailRow("Power Cycles", _fmt(ata_raw_clean(find_ata_attr(data, 12)), "x")),
    ]

    for attr_id in CRITICAL_ATA_IDS:
        attr = find_ata_attr(data, attr_id)
        if attr is None:
            # Gak masuk indicator_levels: banyak SSD memang gak punya ID 187/198.
            rows.append(DetailRow(f"ID {attr_id}", "tidak ada di drive ini", Level.WARN))
            continue
        raw = ata_raw_clean(attr) or 0
        warn, crit = ((th.crc_warn, th.crc_crit) if attr_id == CRC_ATTR_ID
                      else (th.ata_raw_warn, th.ata_raw_crit))
        lvl = level_for_count(raw, warn, crit)
        r.indicator_levels.append(lvl)
        rows.append(DetailRow(
            f"ID {attr_id} {attr.get('name', 'Unknown')}",
            f"raw={raw}  (normalized {_fmt(_num(attr.get('value')))}/"
            f"{_fmt(_num(attr.get('thresh')))})",
            lvl,
        ))

    r.details = rows
    r.key_metric = (f"Realloc:{_fmt(ata_raw_clean(find_ata_attr(data, 5)))} "
                    f"Pending:{_fmt(ata_raw_clean(find_ata_attr(data, 197)))}")
    r.attributes = _ata_attribute_table(data, th, r)


def _ata_attribute_table(data: JsonDict, th: Thresholds, r: DiskReport) -> AttributeTable:
    table = AttributeTable(["ID", "Atribut", "Normalized", "Worst", "Thresh",
                            "Raw Value", "Raw (smartctl)", "Tipe"])
    for attr in ata_table(data):
        attr_id = attr.get("id")
        raw = ata_raw_clean(attr)
        lvl = Level.NA
        # Tambahan vs bash: `when_failed` adalah vonis smartctl SENDIRI
        # (value <= thresh sekarang / dulu) -> bukan heuristik baru.
        when_failed = attr.get("when_failed")
        if when_failed == "now":
            lvl = Level.CRIT
        elif when_failed == "past":
            lvl = Level.WARN
        if lvl is not Level.NA:
            r.indicator_levels.append(lvl)
        if attr_id in CRITICAL_ATA_IDS and raw is not None:
            warn, crit = ((th.crc_warn, th.crc_crit) if attr_id == CRC_ATTR_ID
                          else (th.ata_raw_warn, th.ata_raw_crit))
            lvl = max(lvl, level_for_count(raw, warn, crit))
        prefail = _get(attr, "flags", "prefailure")
        kind = "Pre-fail" if prefail is True else "Old_age" if prefail is False else "-"
        table.rows.append(([
            str(attr_id), str(attr.get("name", "Unknown")),
            _fmt(_num(attr.get("value"))), _fmt(_num(attr.get("worst"))),
            _fmt(_num(attr.get("thresh"))), _fmt(raw),
            str(_get(attr, "raw", "string", default="-")), kind,
        ], lvl))
    return table


# ---------------------------- SAS -----------------------------------------

def _analyze_sas(r: DiskReport, data: JsonDict, th: Thresholds) -> None:
    """bash: analyze_sas() — best-effort, skema scsi_* bervariasi antar vendor."""
    log: JsonDict = data.get("scsi_error_counter_log") or {}
    defect = _num(data.get("scsi_grown_defect_list"))

    def _sum(key: str) -> int:
        return sum(int(_num(_get(log, op, key)) or 0) for op in ("read", "write"))

    corrected, uncorrected = _sum("total_errors_corrected"), _sum("total_uncorrected_errors")

    rows = _head_rows(r)
    rows.append(DetailRow("Perkiraan Kesehatan",
                          "N/A (standar SCSI gak punya mekanisme value/threshold kayak ATA)",
                          Level.WARN))
    rows.append(DetailRow("Suhu", r.temperature_text))

    if defect is None:
        rows.append(DetailRow("Grown Defect List", "N/A", Level.WARN))
    else:
        lvl = level_for_count(defect, th.sas_defect_warn, th.sas_defect_crit)
        r.indicator_levels.append(lvl)
        rows.append(DetailRow("Grown Defect List", _fmt(defect), lvl))

    unc_lvl = Level.CRIT if uncorrected > 0 else Level.OK
    r.indicator_levels.append(unc_lvl)
    rows += [
        DetailRow("Uncorrected Errors", str(uncorrected), unc_lvl),
        DetailRow("Errors Corrected", str(corrected)),
        DetailRow("Catatan",
                  "Dukungan SAS best-effort — cross-check manual untuk keputusan kritis"),
    ]
    r.details = rows
    r.key_metric = f"GrownDefect:{_fmt(defect)}"

    table = AttributeTable(["Atribut", "Raw Value", "Normalized"])
    table.rows.append((["grown_defect_list", _fmt(defect), "-"], Level.NA))
    for op in ("read", "write", "verify"):
        for key, value in (log.get(op) or {}).items():
            table.rows.append(([f"{op}.{key}", str(value), "-"], Level.NA))
    r.attributes = table


def _analyze_unknown(r: DiskReport, data: JsonDict, th: Thresholds) -> None:
    r.details = [*_head_rows(r),
                 DetailRow("Catatan", "Protokol gak kekenali otomatis — cek tab Raw JSON",
                           Level.WARN)]
    r.indicator_levels.append(Level.WARN)
    r.key_metric = "protokol gak dikenali (cek detail)"
