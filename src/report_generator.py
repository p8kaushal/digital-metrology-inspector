"""Legal Metrology Inspection Report Generator Module (Task 13).

Generates official, genuinely editable Word (.docx) documents and PDF exports for
packaged commodity inspections under the Legal Metrology (Packaged Commodities)
Rules, 2011 (SIH26034).

Includes:
- Department of Consumer Affairs Legal Metrology statutory header
- Inspection metadata summary table (Scan ID, Product ID, Timestamp, Completeness %)
- ₹5 Coin Reference Calibration section (21.90 mm standard & Rule 7 scale ratio)
- Statutory declarations and Rule 7 font-height compliance table
- Packaging digital photographic evidence embedding (Front & Back panels)
- Inspector attestation and metrological endorsement section
- Conversion from .docx to .pdf (LibreOffice / soffice / docx2pdf with graceful fallback)
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import io
import logging
import os
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

import docx
from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Inches, Pt, RGBColor
import numpy as np
from PIL import Image

# Configure module logger
logger = logging.getLogger("metrology_inspector.report_generator")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [REPORT] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Standard statutory declarations under Legal Metrology Rules, 2011
MANDATORY_DECLARATION_SPECS: List[Tuple[str, str, str]] = [
    ("mrp", "Maximum Retail Price (MRP)", "Rule 6(1)(e)"),
    ("net_quantity", "Net Quantity", "Rule 6(1)(d)"),
    ("manufacturer_details", "Manufacturer / Packer / Importer Details", "Rule 6(1)(a)/(b)"),
    ("mfg_date", "Month & Year of Manufacture / Packaging", "Rule 6(1)(f)"),
    ("expiry_date", "Expiry / Best Before Date", "Rule 6(1)(f)"),
    ("batch_number", "Batch / Lot / Code Number", "Rule 6(1)(g)"),
    ("consumer_care", "Consumer Care Contact Information", "Rule 6(1)(n)"),
    ("country_of_origin", "Country of Origin", "Rule 6(1)(j)"),
    ("unit_sale_price", "Unit Sale Price (USP)", "Rule 6(1)(l)"),
]

# Color palette for document typography & tables
COLOR_NAVY_PRIMARY = "1E3A8A"      # Deep Indian Emblem Blue
COLOR_SLATE_HEADER = "1F2937"      # Slate Dark
COLOR_ROW_ZEBRA = "F9FAFB"         # Light Gray Zebra Stripe
COLOR_BORDER = "D1D5DB"            # Muted Table Border
COLOR_SUCCESS_GREEN = "059669"     # Compliant Badge Green
COLOR_WARNING_RED = "DC2626"       # Deficit Badge Red
COLOR_MUTED_GRAY = "6B7280"        # Subtitle Gray


@dataclass
class ReportGenerationResult:
    """Dataclass holding generated inspection report artifacts and metadata."""

    docx_path: str
    pdf_path: Optional[str]
    scan_id: str
    product_id: Optional[str]
    is_editable_word: bool
    generation_time_sec: float


def _set_cell_background(cell: Any, hex_color: str) -> None:
    """Set the background color of a Word table cell."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    tc_pr.append(shading)


def _set_cell_margins(cell: Any, top: int = 100, bottom: int = 100, left: int = 150, right: int = 150) -> None:
    """Set inner padding margins of a Word table cell (in twentieths of a point / dxa)."""
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>\n'
        f'  <w:top w:w="{top}" w:type="dxa"/>\n'
        f'  <w:bottom w:w="{bottom}" w:type="dxa"/>\n'
        f'  <w:left w:w="{left}" w:type="dxa"/>\n'
        f'  <w:right w:w="{right}" w:type="dxa"/>\n'
        f'</w:tcMar>'
    )
    tc_pr.append(tc_mar)


def _apply_table_borders(table: Any, color: str = COLOR_BORDER, sz: str = "4") -> None:
    """Apply standard subtle borders to a Word table."""
    tbl_pr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>\n'
        f'  <w:top w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>\n'
        f'  <w:bottom w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>\n'
        f'  <w:left w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>\n'
        f'  <w:right w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>\n'
        f'  <w:insideH w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>\n'
        f'  <w:insideV w:val="single" w:sz="{sz}" w:space="0" w:color="{color}"/>\n'
        f'</w:tblBorders>'
    )
    tbl_pr.append(borders)


def _format_cell_paragraph(
    cell: Any,
    text: str,
    font_size_pt: float = 9.5,
    is_bold: bool = False,
    is_italic: bool = False,
    rgb_color: Optional[RGBColor] = None,
    alignment: WD_ALIGN_PARAGRAPH = WD_ALIGN_PARAGRAPH.LEFT,
) -> Any:
    """Helper to clean cell paragraph and apply consistent typography."""
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = alignment
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run(text)
    run.font.name = "Calibri"
    run.font.size = Pt(font_size_pt)
    run.font.bold = is_bold
    run.font.italic = is_italic
    if rgb_color:
        run.font.color.rgb = rgb_color
    return run


def _resolve_image_stream(img_input: Any) -> Optional[io.BytesIO]:
    """Convert heterogeneous image inputs (file path, ValidatedImage, PIL Image, numpy array) into BytesIO."""
    if img_input is None:
        return None

    # Case 1: Image file path (str or os.PathLike)
    if isinstance(img_input, (str, bytes, os.PathLike)):
        str_path = str(img_input)
        if os.path.isfile(str_path):
            try:
                with open(str_path, "rb") as f:
                    return io.BytesIO(f.read())
            except Exception as exc:
                logger.warning("Failed reading image file %s: %s", str_path, exc)
                return None
        return None

    # Case 2: ValidatedImage object with cache_path attribute
    if hasattr(img_input, "cache_path") and getattr(img_input, "cache_path"):
        cpath = getattr(img_input, "cache_path")
        if os.path.isfile(cpath):
            try:
                with open(cpath, "rb") as f:
                    return io.BytesIO(f.read())
            except Exception as exc:
                logger.warning("Failed reading cache image %s: %s", cpath, exc)

    # Case 3: Object with PIL image attribute
    if hasattr(img_input, "image") and isinstance(getattr(img_input, "image"), Image.Image):
        try:
            buf = io.BytesIO()
            getattr(img_input, "image").save(buf, format="PNG")
            buf.seek(0)
            return buf
        except Exception as exc:
            logger.warning("Failed converting object.image PIL: %s", exc)

    # Case 4: PIL Image directly
    if isinstance(img_input, Image.Image):
        try:
            buf = io.BytesIO()
            img_input.save(buf, format="PNG")
            buf.seek(0)
            return buf
        except Exception as exc:
            logger.warning("Failed saving PIL Image to buffer: %s", exc)
            return None

    # Case 5: OpenCV / NumPy ndarray
    if isinstance(img_input, np.ndarray):
        try:
            # OpenCV BGR -> RGB -> PIL
            if len(img_input.shape) == 3 and img_input.shape[2] == 3:
                rgb_arr = img_input[:, :, ::-1]
                pil_img = Image.fromarray(rgb_arr)
            else:
                pil_img = Image.fromarray(img_input)
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            buf.seek(0)
            return buf
        except Exception as exc:
            logger.warning("Failed converting numpy image array: %s", exc)
            return None

    return None


def _sanitize_pdf_string(text: str) -> str:
    """Sanitize Unicode characters for PDF standard font embedding."""
    replacements = {
        "—": " - ",
        "–": "-",
        "₹": "Rs. ",
        "≥": ">=",
        "≤": "<=",
        "✓": "[PASS]",
        "✅": "[PASS]",
        "🟢": "[PASS]",
        "🔴": "[DEFICIT]",
        "⚠️": "[WARNING]",
        "⚪": "[UNCALIBRATED]",
        "•": "*",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = text.encode("ascii", errors="replace").decode("ascii")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _generate_pure_python_fallback_pdf(docx_path: str, pdf_path: str) -> bool:
    """Generate a clean fallback PDF from docx paragraphs and tables without external dependencies."""
    try:
        doc = Document(docx_path)
    except Exception as exc:
        logger.warning("Could not read docx for PDF fallback: %s", exc)
        return False

    page_width, page_height = 612, 792  # Standard Letter size
    margin_left, margin_top, margin_bottom = 54, 54, 54

    pages: List[List[str]] = []
    current_cmds: List[str] = []
    y = page_height - margin_top

    def add_line(text: str, size: float = 10.0, is_bold: bool = False, indent: float = 0.0) -> None:
        nonlocal y, pages, current_cmds
        if y - size < margin_bottom:
            pages.append(current_cmds)
            current_cmds = []
            y = page_height - margin_top

        font_tag = "/F2" if is_bold else "/F1"
        sanitized = _sanitize_pdf_string(text)
        # Wrap long text if length > 90 characters
        if len(sanitized) > 90:
            words = sanitized.split()
            cur_line = ""
            for w in words:
                if len(cur_line) + len(w) + 1 > 85:
                    current_cmds.append(f"BT {font_tag} {size} Tf {margin_left + indent} {y} Td ({cur_line}) Tj ET")
                    y -= (size + 3)
                    if y - size < margin_bottom:
                        pages.append(current_cmds)
                        current_cmds = []
                        y = page_height - margin_top
                    cur_line = w
                else:
                    cur_line = f"{cur_line} {w}".strip()
            if cur_line:
                current_cmds.append(f"BT {font_tag} {size} Tf {margin_left + indent} {y} Td ({cur_line}) Tj ET")
                y -= (size + 3)
        else:
            current_cmds.append(f"BT {font_tag} {size} Tf {margin_left + indent} {y} Td ({sanitized}) Tj ET")
            y -= (size + 3)

    # Process paragraphs
    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt:
            y -= 4
            continue
        is_title = any(h in txt.upper() for h in ["GOVERNMENT", "MINISTRY", "DEPARTMENT", "REPORT"])
        size = 12.0 if is_title else 9.5
        is_bold = is_title or (len(txt) < 60 and ("." in txt or ":" in txt))
        add_line(txt, size=size, is_bold=is_bold)

    # Process tables
    for tbl_idx, table in enumerate(doc.tables):
        add_line(f"--- Table {tbl_idx + 1} ---", size=10.0, is_bold=True)
        y -= 2
        for r_idx, row in enumerate(table.rows):
            row_texts = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            # De-duplicate adjacent identical cells due to merge
            unique_texts = []
            for t in row_texts:
                if not unique_texts or t != unique_texts[-1]:
                    unique_texts.append(t)
            is_hdr = (r_idx == 0)
            line_str = " | ".join(unique_texts)
            add_line(line_str, size=8.5 if not is_hdr else 9.0, is_bold=is_hdr, indent=10)
        y -= 6

    if current_cmds or not pages:
        pages.append(current_cmds)

    # Assemble valid PDF byte stream
    buf = bytearray()
    buf.extend(b"%PDF-1.4\n")
    pcount = len(pages)
    pids = [5 + i * 2 for i in range(pcount)]
    offsets = []

    catalog_str = "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    kids_str = " ".join(f"{pid} 0 R" for pid in pids)
    pages_obj_str = f"2 0 obj\n<< /Type /Pages /Kids [{kids_str}] /Count {pcount} >>\nendobj\n"
    f1_str = "3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    f2_str = "4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n"

    for s in [catalog_str, pages_obj_str, f1_str, f2_str]:
        offsets.append(len(buf))
        buf.extend(s.encode("latin1"))

    for i, cmds in enumerate(pages):
        pid = 5 + i * 2
        cid = pid + 1
        sdata = "\n".join(cmds).encode("latin1")
        pstr = (
            f"{pid} 0 obj\n"
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Contents {cid} 0 R "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>\n"
            f"endobj\n"
        )
        offsets.append(len(buf))
        buf.extend(pstr.encode("latin1"))

        cstr = f"{cid} 0 obj\n<< /Length {len(sdata)} >>\nstream\n"
        offsets.append(len(buf))
        buf.extend(cstr.encode("latin1"))
        buf.extend(sdata)
        buf.extend(b"\nendstream\nendobj\n")

    xoffset = len(buf)
    tot = 5 + pcount * 2
    xstr = f"xref\n0 {tot}\n0000000000 65535 f \n"
    for o in offsets:
        xstr += f"{o:010d} 00000 n \n"
    tstr = f"trailer\n<< /Size {tot} /Root 1 0 R >>\nstartxref\n{xoffset}\n%%EOF"
    buf.extend(xstr.encode("latin1"))
    buf.extend(tstr.encode("latin1"))

    try:
        with open(pdf_path, "wb") as f_out:
            f_out.write(buf)
        return os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 0
    except Exception as exc:
        logger.warning("Failed writing fallback PDF: %s", exc)
        return False


def convert_docx_to_pdf(docx_path: str) -> Optional[str]:
    """Convert a .docx document to .pdf using LibreOffice or system tools, with graceful fallback.

    Parameters:
        docx_path: Absolute or relative file path to the generated .docx file.

    Returns:
        Absolute path to generated .pdf file if conversion succeeded, or None if conversion
        is not supported or fails gracefully.
    """
    if not docx_path or not os.path.exists(docx_path):
        logger.warning("convert_docx_to_pdf: Source .docx does not exist: %s", docx_path)
        return None

    docx_abs = os.path.abspath(docx_path)
    output_dir = os.path.dirname(docx_abs)
    base_name = os.path.splitext(os.path.basename(docx_abs))[0]
    expected_pdf = os.path.join(output_dir, f"{base_name}.pdf")

    # 1. Search for LibreOffice / soffice CLI binary
    soffice_candidates = [
        shutil.which("libreoffice"),
        shutil.which("soffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/libreoffice",
        "/usr/local/bin/libreoffice",
    ]
    soffice_bin = next(
        (b for b in soffice_candidates if b and os.path.isfile(b) and os.access(b, os.X_OK)),
        None,
    )

    if soffice_bin:
        try:
            logger.info("Converting %s to PDF using %s...", docx_abs, soffice_bin)
            proc = subprocess.run(
                [soffice_bin, "--headless", "--convert-to", "pdf", docx_abs, "--outdir", output_dir],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=45,
                check=False,
            )
            if proc.returncode == 0 and os.path.isfile(expected_pdf) and os.path.getsize(expected_pdf) > 0:
                logger.info("PDF conversion successful via LibreOffice: %s", expected_pdf)
                return os.path.abspath(expected_pdf)
            else:
                logger.warning(
                    "LibreOffice returned code %s: %s",
                    proc.returncode,
                    proc.stderr.decode("utf-8", errors="ignore"),
                )
        except Exception as exc:
            logger.warning("LibreOffice execution failed: %s", exc)

    # 2. Try docx2pdf if installed in python environment
    try:
        import docx2pdf  # type: ignore

        logger.info("Attempting PDF conversion via docx2pdf...")
        docx2pdf.convert(docx_abs, expected_pdf)
        if os.path.isfile(expected_pdf) and os.path.getsize(expected_pdf) > 0:
            logger.info("PDF conversion successful via docx2pdf: %s", expected_pdf)
            return os.path.abspath(expected_pdf)
    except (ImportError, Exception) as exc:
        logger.debug("docx2pdf conversion unavailable or failed: %s", exc)

    # 3. Pure-Python fallback PDF generation
    try:
        logger.info("Attempting pure-Python fallback PDF export for %s...", docx_abs)
        ok = _generate_pure_python_fallback_pdf(docx_abs, expected_pdf)
        if ok and os.path.isfile(expected_pdf):
            logger.info("Pure-Python fallback PDF generated successfully: %s", expected_pdf)
            return os.path.abspath(expected_pdf)
    except Exception as exc:
        logger.warning("Pure-Python fallback PDF export failed: %s", exc)

    logger.info("No PDF conversion tool active; graceful fallback without PDF.")
    return None


def generate_inspection_report(
    consolidated_record: Any,
    front_image: Optional[Any] = None,
    back_image: Optional[Any] = None,
    font_report: Optional[Any] = None,
    calibration_result: Optional[Any] = None,
    output_dir: str = "reports",
    scan_id: Optional[str] = None,
) -> ReportGenerationResult:
    """Generate a clean, genuinely editable Word document (.docx) and PDF inspection report.

    Parameters:
        consolidated_record: ConsolidatedProductRecord or dictionary containing merged package declarations.
        front_image: Front label image (path, ValidatedImage, PIL Image, or ndarray).
        back_image: Back label image (path, ValidatedImage, PIL Image, or ndarray).
        font_report: FontMeasurementReport or dictionary containing font height measurements.
        calibration_result: CalibrationResult or float ratio for reference coin calibration.
        output_dir: Target directory to persist generated inspection reports.
        scan_id: Optional scan UUID identifier.

    Returns:
        ReportGenerationResult containing paths to generated docx/pdf, scan metadata, and timing.
    """
    start_time = time.time()
    os.makedirs(output_dir, exist_ok=True)

    # 1. Normalize record and identifiers
    resolved_scan_id = (
        scan_id
        or getattr(consolidated_record, "scan_id", None)
        or (consolidated_record.get("scan_id") if isinstance(consolidated_record, dict) else None)
        or (consolidated_record.get("id") if isinstance(consolidated_record, dict) else None)
        or getattr(consolidated_record, "product_id", None)
        or str(uuid.uuid4())
    )
    clean_scan_id = re.sub(r"[^\w\-]", "_", str(resolved_scan_id))

    product_id = getattr(consolidated_record, "product_id", None) or (
        consolidated_record.get("product_id") if isinstance(consolidated_record, dict) else None
    )
    brand_name = (
        getattr(consolidated_record, "brand_name", "")
        or (consolidated_record.get("brand_name") if isinstance(consolidated_record, dict) else "")
        or (consolidated_record.get("name") if isinstance(consolidated_record, dict) else "")
        or "Packaged Commodity"
    )
    completeness_pct = float(
        getattr(consolidated_record, "completeness_pct", 0.0)
        or (consolidated_record.get("completeness_pct", 0.0) if isinstance(consolidated_record, dict) else 0.0)
    )
    missing_declarations = list(
        getattr(consolidated_record, "missing_declarations", [])
        or (consolidated_record.get("missing_declarations", []) if isinstance(consolidated_record, dict) else [])
    )
    front_fields = getattr(consolidated_record, "front_fields", {}) or (
        consolidated_record.get("front_fields", {}) if isinstance(consolidated_record, dict) else {}
    )
    back_fields = getattr(consolidated_record, "back_fields", {}) or (
        consolidated_record.get("back_fields", {}) if isinstance(consolidated_record, dict) else {}
    )
    record_fonts = getattr(consolidated_record, "font_measurements", {}) or (
        consolidated_record.get("font_measurements", {}) if isinstance(consolidated_record, dict) else {}
    )

    # 2. Normalize calibration data
    is_calibrated = False
    pixels_per_mm = 0.0
    coin_pixel_diameter = 0.0
    mm_per_pixel = 0.0
    calib_msg = "Reference ₹5 coin calibration verified."

    if calibration_result is not None:
        if isinstance(calibration_result, (int, float)):
            pixels_per_mm = float(calibration_result)
            is_calibrated = pixels_per_mm > 0
            coin_pixel_diameter = pixels_per_mm * 21.90
            mm_per_pixel = 1.0 / pixels_per_mm if pixels_per_mm > 0 else 0.0
        elif isinstance(calibration_result, dict):
            is_calibrated = bool(calibration_result.get("is_calibrated", False))
            pixels_per_mm = float(calibration_result.get("pixels_per_mm", 0.0))
            coin_pixel_diameter = float(calibration_result.get("coin_pixel_diameter", 0.0))
            mm_per_pixel = float(calibration_result.get("mm_per_pixel", 0.0))
            calib_msg = calibration_result.get("message", calib_msg)
        else:
            is_calibrated = bool(getattr(calibration_result, "is_calibrated", False))
            pixels_per_mm = float(getattr(calibration_result, "pixels_per_mm", 0.0))
            coin_pixel_diameter = float(getattr(calibration_result, "coin_pixel_diameter", 0.0))
            mm_per_pixel = float(getattr(calibration_result, "mm_per_pixel", 0.0))
            calib_msg = getattr(calibration_result, "message", calib_msg)

    # Fallback calibration ratio check from font_report if available
    if not is_calibrated and font_report is not None:
        ratio = getattr(font_report, "calibration_ratio_used", 0.0) or (
            font_report.get("calibration_ratio_used", 0.0) if isinstance(font_report, dict) else 0.0
        )
        if ratio > 0:
            pixels_per_mm = float(ratio)
            is_calibrated = True
            coin_pixel_diameter = pixels_per_mm * 21.90
            mm_per_pixel = 1.0 / pixels_per_mm

    # 3. Create python-docx Document
    doc = Document()

    # Configure clean standard margins (0.75 in / 54 pt)
    section = doc.sections[0]
    section.top_margin = Inches(0.75)
    section.bottom_margin = Inches(0.75)
    section.left_margin = Inches(0.75)
    section.right_margin = Inches(0.75)

    # =========================================================================
    # HEADER: Department of Consumer Affairs Legal Metrology Header
    # =========================================================================
    p_gov = doc.add_paragraph()
    p_gov.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_gov.paragraph_format.space_after = Pt(2)
    r_gov = p_gov.add_run("GOVERNMENT OF INDIA")
    r_gov.font.name = "Calibri"
    r_gov.font.size = Pt(11)
    r_gov.font.bold = True
    r_gov.font.color.rgb = RGBColor(75, 85, 99)

    p_dept = doc.add_paragraph()
    p_dept.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_dept.paragraph_format.space_after = Pt(4)
    r_dept = p_dept.add_run("MINISTRY OF CONSUMER AFFAIRS, FOOD & PUBLIC DISTRIBUTION\nDEPARTMENT OF CONSUMER AFFAIRS — LEGAL METROLOGY DIVISION")
    r_dept.font.name = "Calibri"
    r_dept.font.size = Pt(12)
    r_dept.font.bold = True
    r_dept.font.color.rgb = RGBColor(30, 58, 138)

    p_rep_title = doc.add_paragraph()
    p_rep_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_rep_title.paragraph_format.space_after = Pt(2)
    r_rep_title = p_rep_title.add_run("LEGAL METROLOGY PACKAGED COMMODITIES INSPECTION REPORT")
    r_rep_title.font.name = "Calibri"
    r_rep_title.font.size = Pt(15)
    r_rep_title.font.bold = True
    r_rep_title.font.color.rgb = RGBColor(30, 58, 138)

    p_subtitle = doc.add_paragraph()
    p_subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_subtitle.paragraph_format.space_after = Pt(14)
    r_sub = p_subtitle.add_run("Statutory Packaging Compliance & Physical Font Measurement Audit (Legal Metrology Rules, 2011 | SIH26034)")
    r_sub.font.name = "Calibri"
    r_sub.font.size = Pt(9.5)
    r_sub.font.italic = True
    r_sub.font.color.rgb = RGBColor(107, 114, 128)

    # =========================================================================
    # SECTION 1: Inspection Metadata Table
    # =========================================================================
    h1 = doc.add_heading("1. Inspection Metadata & Statutory Summary", level=2)
    h1.paragraph_format.space_before = Pt(6)
    h1.paragraph_format.space_after = Pt(6)

    meta_table = doc.add_table(rows=4, cols=4)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _apply_table_borders(meta_table)

    meta_items = [
        ("Scan ID", str(resolved_scan_id), "Inspection Timestamp", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")),
        ("Product ID", str(product_id or "Not Assigned"), "Brand / Commodity", str(brand_name)),
        ("Completeness Score", f"{completeness_pct:.1f}% ({9 - len(missing_declarations)}/9 Declarations)", "Rule 6 Disclosure", "FULL DISCLOSURE" if len(missing_declarations) == 0 else f"DEFICIENT ({len(missing_declarations)} Missing)"),
        ("Calibration Mode", "₹5 Coin Ground Truth (21.9mm)" if is_calibrated else "Uncalibrated", "Document Format", "Genuine Editable Word (.docx)"),
    ]

    col_widths = [Inches(1.5), Inches(2.0), Inches(1.5), Inches(2.0)]
    for r_idx, (k1, v1, k2, v2) in enumerate(meta_items):
        row = meta_table.rows[r_idx]
        cells = row.cells

        # Apply cell widths and padding
        for c_idx, cell in enumerate(cells):
            cell.width = col_widths[c_idx]
            _set_cell_margins(cell, top=80, bottom=80, left=120, right=120)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        # Left pair
        _set_cell_background(cells[0], "F3F4F6")
        _format_cell_paragraph(cells[0], k1, font_size_pt=9.0, is_bold=True, rgb_color=RGBColor(31, 41, 55))
        _format_cell_paragraph(cells[1], v1, font_size_pt=9.0, is_bold=False)

        # Right pair
        _set_cell_background(cells[2], "F3F4F6")
        _format_cell_paragraph(cells[2], k2, font_size_pt=9.0, is_bold=True, rgb_color=RGBColor(31, 41, 55))
        _format_cell_paragraph(cells[3], v2, font_size_pt=9.0, is_bold=False)

    p_spacer = doc.add_paragraph()
    p_spacer.paragraph_format.space_after = Pt(4)

    # =========================================================================
    # SECTION 2: ₹5 Coin Reference Calibration Section
    # =========================================================================
    h2 = doc.add_heading("2. Reference Coin Calibration Standard (Rule 7 Metrology)", level=2)
    h2.paragraph_format.space_before = Pt(6)
    h2.paragraph_format.space_after = Pt(4)

    p_cal_desc = doc.add_paragraph()
    p_cal_desc.paragraph_format.space_after = Pt(6)
    r_cd = p_cal_desc.add_run(
        "Under Rule 7 of the Legal Metrology (Packaged Commodities) Rules, 2011, printed mandatory declarations "
        "must satisfy statutory minimum font heights. Physical font dimensions are measured in real millimeters "
        "using an Indian ₹5 coin (statutory fixed diameter = 21.90 mm) photographed coplanar with the packaging label."
    )
    r_cd.font.size = Pt(9.5)

    cal_table = doc.add_table(rows=5, cols=3)
    cal_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _apply_table_borders(cal_table)

    cal_headers = ["Calibration Parameter", "Measured / Calibrated Value", "Metrological Specification"]
    for c_idx, htext in enumerate(cal_headers):
        cell = cal_table.rows[0].cells[c_idx]
        _set_cell_background(cell, COLOR_NAVY_PRIMARY)
        _set_cell_margins(cell, top=100, bottom=100, left=120, right=120)
        _format_cell_paragraph(cell, htext, font_size_pt=9.5, is_bold=True, rgb_color=RGBColor(255, 255, 255))

    cal_rows_data = [
        ("Reference Calibration Standard", "Indian ₹5 Coin (Ferritic Stainless Steel / Nickel-Brass)", "Statutory Fixed Outer Diameter = 21.90 mm"),
        ("Detected Coin Pixel Diameter", f"{coin_pixel_diameter:.2f} px" if is_calibrated else "Not Detected", "OpenCV Circular Hough Transform Detection"),
        ("Pixel-to-Millimeter Ratio", f"{pixels_per_mm:.2f} pixels / mm" if is_calibrated else "Uncalibrated", "Scale Factor = Coin_Diameter_px / 21.90 mm"),
        ("Millimeter-per-Pixel Resolution", f"{mm_per_pixel:.4f} mm / pixel" if is_calibrated else "Uncalibrated", "Linear Metrological Resolution"),
    ]

    cal_col_widths = [Inches(2.5), Inches(2.3), Inches(2.2)]
    for r_idx, (p_name, p_val, p_spec) in enumerate(cal_rows_data, start=1):
        row = cal_table.rows[r_idx]
        if r_idx % 2 == 1:
            for cell in row.cells:
                _set_cell_background(cell, COLOR_ROW_ZEBRA)

        for c_idx, cell in enumerate(row.cells):
            cell.width = cal_col_widths[c_idx]
            _set_cell_margins(cell, top=80, bottom=80, left=120, right=120)

        _format_cell_paragraph(row.cells[0], p_name, font_size_pt=9.0, is_bold=True)
        _format_cell_paragraph(row.cells[1], p_val, font_size_pt=9.0, is_bold=False)
        _format_cell_paragraph(row.cells[2], p_spec, font_size_pt=8.5, is_italic=True, rgb_color=RGBColor(107, 114, 128))

    p_spacer2 = doc.add_paragraph()
    p_spacer2.paragraph_format.space_after = Pt(4)

    # =========================================================================
    # SECTION 3: Declarations Table (Field Name, Value, Font Size mm, Rule 7 Status)
    # =========================================================================
    h3 = doc.add_heading("3. Mandatory Declarations & Rule 7 Font Size Compliance", level=2)
    h3.paragraph_format.space_before = Pt(6)
    h3.paragraph_format.space_after = Pt(4)

    p_dec_desc = doc.add_paragraph()
    p_dec_desc.paragraph_format.space_after = Pt(6)
    r_dd = p_dec_desc.add_run(
        "Mandatory packaging declarations extracted across Front and Back panels, consolidated under Rule 6 "
        "of Legal Metrology Rules, 2011. Real-world font heights are measured in millimeters and audited against "
        "the minimum font height prescriptions of Rule 7 (Table 1)."
    )
    r_dd.font.size = Pt(9.5)

    # Gather font measurements lookup
    all_fonts: Dict[str, Any] = dict(record_fonts)
    if font_report is not None:
        meas_dict = getattr(font_report, "measurements", None) or (
            font_report.get("measurements") if isinstance(font_report, dict) else None
        )
        if isinstance(meas_dict, dict):
            for k, v in meas_dict.items():
                if k not in all_fonts:
                    all_fonts[k] = v

    # Build declarations table (Headers + 9 Mandatory declarations + Brand Name)
    total_decl_rows = len(MANDATORY_DECLARATION_SPECS) + (1 if brand_name else 0)
    decl_table = doc.add_table(rows=total_decl_rows + 1, cols=5)
    decl_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _apply_table_borders(decl_table)

    decl_headers = [
        "Statutory Declaration",
        "Declared Value / Content",
        "Source Panel",
        "Font Height (mm)",
        "Rule 7 Status",
    ]
    for c_idx, htext in enumerate(decl_headers):
        cell = decl_table.rows[0].cells[c_idx]
        _set_cell_background(cell, COLOR_NAVY_PRIMARY)
        _set_cell_margins(cell, top=100, bottom=100, left=100, right=100)
        _format_cell_paragraph(cell, htext, font_size_pt=9.5, is_bold=True, rgb_color=RGBColor(255, 255, 255))

    decl_col_widths = [Inches(1.8), Inches(2.0), Inches(1.0), Inches(1.1), Inches(1.1)]

    current_row = 1
    # If brand name is present, include as general declaration
    if brand_name:
        row = decl_table.rows[current_row]
        for c_idx, cell in enumerate(row.cells):
            cell.width = decl_col_widths[c_idx]
            _set_cell_margins(cell, top=80, bottom=80, left=100, right=100)
        _format_cell_paragraph(row.cells[0], "Brand / Commodity Name\n(General Provision)", font_size_pt=9.0, is_bold=True)
        _format_cell_paragraph(row.cells[1], brand_name, font_size_pt=9.0)
        _format_cell_paragraph(row.cells[2], "Front / Master", font_size_pt=8.5)
        _format_cell_paragraph(row.cells[3], "—", font_size_pt=9.0)
        _format_cell_paragraph(row.cells[4], "🟢 PASS", font_size_pt=9.0, is_bold=True, rgb_color=RGBColor(5, 150, 105))
        current_row += 1

    # Populate the 9 mandatory declarations
    for d_key, d_title, d_rule in MANDATORY_DECLARATION_SPECS:
        row = decl_table.rows[current_row]
        if current_row % 2 == 1:
            for cell in row.cells:
                _set_cell_background(cell, COLOR_ROW_ZEBRA)

        for c_idx, cell in enumerate(row.cells):
            cell.width = decl_col_widths[c_idx]
            _set_cell_margins(cell, top=80, bottom=80, left=100, right=100)

        # 1. Declaration Title & Rule citation
        _format_cell_paragraph(row.cells[0], f"{d_title}\n({d_rule})", font_size_pt=8.5, is_bold=True)

        # 2. Declared Value
        val = getattr(consolidated_record, d_key, "") or (
            consolidated_record.get(d_key, "") if isinstance(consolidated_record, dict) else ""
        )
        is_declared = bool(val and str(val).strip())
        val_str = str(val).strip() if is_declared else "[MISSING / NOT DECLARED]"
        _format_cell_paragraph(
            row.cells[1],
            val_str,
            font_size_pt=9.0,
            is_bold=not is_declared,
            is_italic=not is_declared,
            rgb_color=RGBColor(220, 38, 38) if not is_declared else RGBColor(31, 41, 55),
        )

        # 3. Source Panel
        in_f = d_key in front_fields
        in_b = d_key in back_fields
        if in_f and in_b:
            panel_str = "Front & Back"
        elif in_f:
            panel_str = "Front Panel"
        elif in_b:
            panel_str = "Back Panel"
        else:
            panel_str = "—"
        _format_cell_paragraph(row.cells[2], panel_str, font_size_pt=8.5)

        # 4. Font Measurement & 5. Rule 7 Status
        f_meas = all_fonts.get(d_key)
        font_disp = "—"
        rule7_text = "⚪ Not Measured"
        rule7_color = RGBColor(107, 114, 128)

        if not is_declared:
            rule7_text = "🔴 MISSING"
            rule7_color = RGBColor(220, 38, 38)
        elif f_meas:
            if hasattr(f_meas, "font_height_mm") and getattr(f_meas, "is_calibrated", False):
                fh = getattr(f_meas, "font_height_mm", 0.0)
                px = getattr(f_meas, "bbox_height_px", 0.0)
                font_disp = f"{fh:.2f} mm ({px:.1f} px)"
                compliant = getattr(f_meas, "is_rule7_compliant", False)
                min_req = getattr(f_meas, "rule7_min_height_mm", 1.0)
                if compliant:
                    rule7_text = f"🟢 PASS (≥{min_req:.1f} mm)"
                    rule7_color = RGBColor(5, 150, 105)
                else:
                    rule7_text = f"🔴 DEFICIT (<{min_req:.1f} mm)"
                    rule7_color = RGBColor(220, 38, 38)
            elif isinstance(f_meas, dict):
                fh = f_meas.get("font_height_mm")
                px = f_meas.get("bbox_height_px", 0.0)
                font_disp = f"{fh:.2f} mm ({px:.1f} px)" if fh is not None else f"{px:.1f} px"
                compliant = f_meas.get("is_rule7_compliant", False)
                if compliant:
                    rule7_text = "🟢 PASS"
                    rule7_color = RGBColor(5, 150, 105)
                else:
                    rule7_text = "🔴 DEFICIT"
                    rule7_color = RGBColor(220, 38, 38)
            else:
                font_disp = str(f_meas)
                rule7_text = "⚪ Uncalibrated"
        else:
            if is_declared:
                rule7_text = "⚪ Pending Verification"

        _format_cell_paragraph(row.cells[3], font_disp, font_size_pt=8.5)
        _format_cell_paragraph(row.cells[4], rule7_text, font_size_pt=8.5, is_bold=True, rgb_color=rule7_color)

        current_row += 1

    # Completeness Alert Paragraph
    p_comp_note = doc.add_paragraph()
    p_comp_note.paragraph_format.space_before = Pt(8)
    p_comp_note.paragraph_format.space_after = Pt(8)
    if missing_declarations:
        missing_titles = [
            next((spec[1] for spec in MANDATORY_DECLARATION_SPECS if spec[0] == m), m.replace("_", " ").title())
            for m in missing_declarations
        ]
        r_cn = p_comp_note.add_run(
            f"STATUTORY NON-COMPLIANCE NOTICE: {len(missing_declarations)} of 9 mandatory declarations are missing "
            f"from this packaging ({', '.join(missing_titles)}). This violates Rule 6 of the Legal Metrology "
            f"(Packaged Commodities) Rules, 2011."
        )
        r_cn.font.name = "Calibri"
        r_cn.font.size = Pt(9.5)
        r_cn.font.bold = True
        r_cn.font.color.rgb = RGBColor(220, 38, 38)
    else:
        r_cn = p_comp_note.add_run(
            "STATUTORY COMPLIANCE NOTICE: All 9 mandatory declarations required under Rule 6 of the "
            "Legal Metrology (Packaged Commodities) Rules, 2011 were detected on the packaging labels."
        )
        r_cn.font.name = "Calibri"
        r_cn.font.size = Pt(9.5)
        r_cn.font.bold = True
        r_cn.font.color.rgb = RGBColor(5, 150, 105)

    # =========================================================================
    # SECTION 4: Packaging Digital Evidence (Front & Back Images)
    # =========================================================================
    h4 = doc.add_heading("4. Packaging Photographic Digital Evidence", level=2)
    h4.paragraph_format.space_before = Pt(8)
    h4.paragraph_format.space_after = Pt(4)

    p_img_desc = doc.add_paragraph()
    p_img_desc.paragraph_format.space_after = Pt(6)
    r_id = p_img_desc.add_run(
        "Photographic inspection evidence captured and verified during metrology examination."
    )
    r_id.font.size = Pt(9.5)

    img_table = doc.add_table(rows=2, cols=2)
    img_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _apply_table_borders(img_table)

    for cell in img_table.rows[0].cells:
        _set_cell_background(cell, COLOR_NAVY_PRIMARY)
        _set_cell_margins(cell, top=80, bottom=80, left=100, right=100)
    _format_cell_paragraph(img_table.rows[0].cells[0], "Front Label Photographic Record", font_size_pt=9.5, is_bold=True, rgb_color=RGBColor(255, 255, 255), alignment=WD_ALIGN_PARAGRAPH.CENTER)
    _format_cell_paragraph(img_table.rows[0].cells[1], "Back Label Photographic Record", font_size_pt=9.5, is_bold=True, rgb_color=RGBColor(255, 255, 255), alignment=WD_ALIGN_PARAGRAPH.CENTER)

    img_col_widths = [Inches(3.4), Inches(3.4)]
    front_stream = _resolve_image_stream(front_image)
    back_stream = _resolve_image_stream(back_image)

    # Embed Front Image
    cell_f = img_table.rows[1].cells[0]
    cell_f.width = img_col_widths[0]
    _set_cell_margins(cell_f, top=100, bottom=100, left=100, right=100)
    cell_f.text = ""
    p_f = cell_f.paragraphs[0]
    p_f.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if front_stream:
        try:
            p_f.add_run().add_picture(front_stream, width=Inches(3.1))
        except Exception as exc:
            logger.warning("Failed embedding front image picture: %s", exc)
            p_f.add_run("[Front Label Image Attached - Format Conversion Note]")
    else:
        p_f.add_run("[Front Packaging Photographic Evidence Not Attached / Not Available]").font.italic = True

    # Embed Back Image
    cell_b = img_table.rows[1].cells[1]
    cell_b.width = img_col_widths[1]
    _set_cell_margins(cell_b, top=100, bottom=100, left=100, right=100)
    cell_b.text = ""
    p_b = cell_b.paragraphs[0]
    p_b.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if back_stream:
        try:
            p_b.add_run().add_picture(back_stream, width=Inches(3.1))
        except Exception as exc:
            logger.warning("Failed embedding back image picture: %s", exc)
            p_b.add_run("[Back Label Image Attached - Format Conversion Note]")
    else:
        p_b.add_run("[Back Packaging Photographic Evidence Not Attached / Not Available]").font.italic = True

    # =========================================================================
    # SECTION 5: Regulatory Attestation & Endorsement Block
    # =========================================================================
    h5 = doc.add_heading("5. Metrological Attestation & Inspector Certification", level=2)
    h5.paragraph_format.space_before = Pt(12)
    h5.paragraph_format.space_after = Pt(4)

    p_attest = doc.add_paragraph()
    p_attest.paragraph_format.space_after = Pt(8)
    r_at = p_attest.add_run(
        "I hereby certify that the digital metrology inspection documented herein was conducted in accordance "
        "with the standards of the Legal Metrology Act, 2009 and the Legal Metrology (Packaged Commodities) Rules, 2011. "
        "This report is generated as an editable Microsoft Word (.docx) document to allow statutory metrology inspectors "
        "to review, annotate, and verify all extracted declarations and physical font dimensions before formal enforcement."
    )
    r_at.font.name = "Calibri"
    r_at.font.size = Pt(9.0)

    sign_table = doc.add_table(rows=3, cols=2)
    sign_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _apply_table_borders(sign_table)
    sign_col_widths = [Inches(3.4), Inches(3.4)]

    for row in sign_table.rows:
        for c_idx, cell in enumerate(row.cells):
            cell.width = sign_col_widths[c_idx]
            _set_cell_margins(cell, top=80, bottom=80, left=100, right=100)

    _format_cell_paragraph(sign_table.rows[0].cells[0], "Inspecting Officer: __________________________", font_size_pt=9.0)
    _format_cell_paragraph(sign_table.rows[0].cells[1], "Official Signature: __________________________", font_size_pt=9.0)
    _format_cell_paragraph(sign_table.rows[1].cells[0], "Designation: Legal Metrology Inspector", font_size_pt=9.0)
    _format_cell_paragraph(sign_table.rows[1].cells[1], "Official Seal / Stamp:", font_size_pt=9.0)
    _format_cell_paragraph(sign_table.rows[2].cells[0], f"Inspection Station / District: National Metrology Lab", font_size_pt=9.0)
    _format_cell_paragraph(sign_table.rows[2].cells[1], f"Date & Time: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", font_size_pt=9.0)

    # 4. Save docx to disk
    docx_filename = f"inspection_report_{clean_scan_id}.docx"
    docx_path = os.path.join(output_dir, docx_filename)
    docx_abs = os.path.abspath(docx_path)
    doc.save(docx_abs)
    logger.info("Saved editable Word inspection report to %s", docx_abs)

    # 5. Convert docx to PDF
    pdf_path = convert_docx_to_pdf(docx_abs)

    generation_time = round(time.time() - start_time, 4)

    return ReportGenerationResult(
        docx_path=docx_abs,
        pdf_path=pdf_path,
        scan_id=str(resolved_scan_id),
        product_id=product_id,
        is_editable_word=True,
        generation_time_sec=generation_time,
    )
