"""
report.py — ekspor laporan teknis (PDF-A) dari hasil scan.

Murni transformasi: list[DiskReport] -> file PDF. Tidak menyentuh Qt maupun
subprocess, jadi bisa dipakai dari GUI maupun CLI. reportlab di-import lazy di
dalam fungsi supaya paket yang tak butuh PDF tak menariknya saat start.

Data diambil dari DiskReport (hasil analyze()) + raw_json untuk detail yang tak
masuk ringkasan (serial, kapasitas). Level -> warna konsisten dengan GUI.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .analysis import DiskReport, Level

def _asset_dir() -> Path:
    """Folder aset — di source di samping modul; di bundle PyInstaller di _MEIPASS."""
    import sys
    base = getattr(sys, "_MEIPASS", None)
    if base:  # build PyInstaller (onefile/onedir)
        return Path(base) / "amubasmart" / "assets"
    return Path(__file__).resolve().parent / "assets"


_LOGO = _asset_dir() / "logo.png"

# Warna selaras dengan ui_common (tema terang) — badge & status atribut.
_HEX = {
    Level.OK: "#1a7f37", Level.WARN: "#9a6700",
    Level.CRIT: "#cf222e", Level.NA: "#6b7280",
}
_LEVEL_LABEL = {
    Level.OK: "SEHAT", Level.WARN: "PERLU PERHATIAN",
    Level.CRIT: "KRITIS", Level.NA: "—",
}
_ACCENT = "#ADD0FD"   # biru brand (dari logo)
_DARK = "#131418"


class ReportError(RuntimeError):
    """Gagal membuat PDF — pesan siap tampil ke user."""


# --------------------------------------------------------------- ekstraksi data

def _raw(report: DiskReport, *path: str, default: Any = None) -> Any:
    """Akses aman ke raw_json (mis. serial, kapasitas yang tak ada di DiskReport)."""
    cur: Any = report.raw_json
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _serial(report: DiskReport) -> str:
    return str(_raw(report, "serial_number", default="—"))


def _capacity(report: DiskReport) -> str:
    """Kapasitas dari user_capacity.bytes (NVMe pakai nvme_total_capacity)."""
    b = _raw(report, "user_capacity", "bytes") or _raw(report, "nvme_total_capacity")
    if not isinstance(b, (int, float)) or b <= 0:
        return "—"
    tb = b / 1e12
    return f"{tb:.2f} TB" if tb >= 1 else f"{b / 1e9:.0f} GB"


def _poh_pcc(report: DiskReport) -> tuple[str, str]:
    """Ambil Power On Hours & Power Cycles dari details (sudah diformat analyze)."""
    poh = pcc = "—"
    for d in report.details:
        if d.label == "Power On Hours":
            poh = d.value
        elif d.label == "Power Cycles":
            pcc = d.value
    return poh, pcc


# --------------------------------------------------------------- bangun PDF

def build_report(reports: list[DiskReport], out_path: str,
                 scanned_at: datetime | None = None) -> str:
    """Bangun PDF laporan teknis. Return path file. Raise ReportError kalau gagal."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ImportError as exc:
        raise ReportError(
            "Modul 'reportlab' belum terpasang. Install: pip install reportlab "
            "(atau paket sistem python3-reportlab)."
        ) from exc

    scanned_at = scanned_at or datetime.now()
    dark = colors.HexColor(_DARK)
    accent = colors.HexColor(_ACCENT)
    na = colors.HexColor(_HEX[Level.NA])

    styles = getSampleStyleSheet()
    h_style = ParagraphStyle("h", parent=styles["Normal"], fontName="Helvetica-Bold",
                             fontSize=11, textColor=dark)
    norm = ParagraphStyle("n", parent=styles["Normal"], fontSize=8.5, textColor=dark)

    def draw_header(canvas, doc):
        canvas.saveState()
        w, hh = A4
        if _LOGO.is_file():
            canvas.drawImage(str(_LOGO), 1.9 * cm, hh - 3.0 * cm, width=3.0 * cm,
                             height=3.0 * cm, mask="auto", preserveAspectRatio=True)
        canvas.setFont("Helvetica-Bold", 17)
        canvas.setFillColor(dark)
        canvas.drawString(5.2 * cm, hh - 1.7 * cm, "AmubaSMART")
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(na)
        canvas.drawString(5.2 * cm, hh - 2.2 * cm, "Laporan Teknis Kesehatan Disk")
        canvas.setStrokeColor(accent)
        canvas.setLineWidth(2.5)
        canvas.line(2 * cm, hh - 2.9 * cm, w - 2 * cm, hh - 2.9 * cm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(na)
        canvas.drawString(2 * cm, 1.2 * cm,
                          "Dihasilkan oleh AmubaSMART — analisa kesehatan SMART")
        canvas.drawRightString(w - 2 * cm, 1.2 * cm, f"Halaman {doc.page}")
        canvas.restoreState()

    def badge(level: Level) -> Table:
        t = Table([[_LEVEL_LABEL[level]]], colWidths=[3.2 * cm], rowHeights=[0.65 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(_HEX[level])),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return t

    story: list[Any] = []

    # Meta scan
    meta = Table([[
        Paragraph(f"<b>Tanggal scan:</b> {scanned_at:%d %B %Y, %H:%M}", norm),
        Paragraph(f"<b>Jumlah disk:</b> {len(reports)}", norm),
    ]], colWidths=[9 * cm, 5.7 * cm])
    meta.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story.append(meta)
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e0e0e0")))
    story.append(Spacer(1, 8))

    for report in reports:
        _disk_section(report, story, h_style, norm, badge, colors, cm, dark, na,
                      Paragraph, Table, TableStyle, Spacer, ParagraphStyle)

    try:
        doc = SimpleDocTemplate(out_path, pagesize=A4, topMargin=3.4 * cm,
                                bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm)
        doc.build(story, onFirstPage=draw_header, onLaterPages=draw_header)
    except OSError as exc:
        raise ReportError(f"Gagal menulis PDF ke '{out_path}': {exc}") from exc
    return out_path


def _disk_section(report, story, h_style, norm, badge, colors, cm, dark, na,
                  Paragraph, Table, TableStyle, Spacer, ParagraphStyle) -> None:
    # Header disk + badge
    head = Table([[
        Paragraph(f"<b>{report.device}</b> &nbsp;&nbsp; {report.model}", h_style),
        badge(report.overall_level),
    ]], colWidths=[11.5 * cm, 3.2 * cm])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0f4fa")),
        ("LINEBELOW", (0, 0), (-1, -1), 1.5, colors.HexColor(_ACCENT)),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (0, 0), 8),
        ("RIGHTPADDING", (1, 0), (1, 0), 8),
    ]))
    story.append(head)
    story.append(Spacer(1, 4))

    poh, pcc = _poh_pcc(report)
    health = report.health_text if report.read_ok or report.dtype == "flashdrive" else "—"
    info_rows = [
        ["Protokol", report.protocol_label, "Kapasitas", _capacity(report)],
        ["Serial Number", _serial(report), "Suhu", report.temperature_text],
        ["Status SMART", report.status, "Kesehatan", health],
        ["Power On Hours", poh, "Power Cycles", pcc],
    ]
    it = Table(info_rows, colWidths=[3 * cm, 4.3 * cm, 3 * cm, 4.3 * cm])
    it.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), na),
        ("TEXTCOLOR", (2, 0), (2, -1), na),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    story.append(it)
    story.append(Spacer(1, 5))

    # Diagnosa untuk drive gagal baca / flashdisk
    if not report.read_ok and report.diagnosis:
        story.append(Paragraph(f"<i>{report.diagnosis}</i>",
                               ParagraphStyle("d", parent=norm, textColor=na)))
        story.append(Spacer(1, 6))

    # Tabel atribut lengkap
    attrs = report.attributes
    if attrs and attrs.rows:
        story.append(Paragraph(
            f"Atribut SMART ({len(attrs.rows)})",
            ParagraphStyle("ah", parent=norm, fontName="Helvetica-Bold", fontSize=9,
                           spaceBefore=3)))
        _append_attr_table(attrs, story, colors, cm, dark, Table, TableStyle)

    story.append(Spacer(1, 10))


def _append_attr_table(attrs, story, colors, cm, dark, Table, TableStyle) -> None:
    from .analysis import Level as _L

    headers = attrs.headers
    ncol = len(headers)
    rows = [headers] + [cells for cells, _lvl in attrs.rows]

    # Lebar kolom: kolom "nama atribut" (yang mengandung 'Atribut') dapat porsi
    # terbesar, sisanya dibagi rata. Total muat di lebar konten A4 (~14.7cm).
    TOTAL = 14.7
    name_idx = next((i for i, hdr in enumerate(headers) if "Atribut" in hdr), 1)
    if ncol == 1:
        widths = [TOTAL]
    else:
        # nama atribut porsi besar; kolom lain rata.
        name_w = min(5.0, TOTAL * 0.35)
        rest_w = (TOTAL - name_w) / (ncol - 1)
        widths = [name_w if i == name_idx else rest_w for i in range(ncol)]
    col_widths = [w * cm for w in widths]

    t = Table(rows, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), dark),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d0d0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # Nama atribut rata kiri; kolom angka rata tengah.
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (name_idx, 0), (name_idx, -1), "LEFT"),
    ]
    for i, (_cells, level) in enumerate(attrs.rows, start=1):
        if level in (_L.WARN, _L.CRIT):
            style.append(("TEXTCOLOR", (0, i), (-1, i), colors.HexColor(_HEX[level])))
            style.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    story.append(t)
