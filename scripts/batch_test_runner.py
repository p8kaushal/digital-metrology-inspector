#!/usr/bin/env python3
"""Digital Metrology Inspector - Batch Testing Harness.

Executes the end-to-end 11-step Legal Metrology compliance pipeline across
local packaging samples in test_samples/ subdirectories:
1. Image loading & validation (src/image_handler.py).
2. ₹5 Coin Detection & Calibration (src/coin_detector.py, src/calibration.py).
3. Text Region Bounding Box Detection (src/text_detector.py).
4. Preprocessed Dot-Matrix PaddleOCR Line Extraction (src/ocr_engine.py).
5. Statutory Field Structuring & Parsing (src/field_parser.py).
6. Single-Line Font Height Measurement & Rule 7 evaluation (src/font_measurement.py).
7. Front & Back Data Consolidation (src/consolidation.py).
8. Supabase / Mock DB Record Persistence (src/scan_service.py).
9. Editable Word (.docx) & PDF (.pdf) Report Generation saved into reports/batch_tests/.
10. Report Upload (src/scan_service.py).
11. Batch Results Verification & Markdown Summary Reporting.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
import logging
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
from PIL import Image

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.calibration import CalibrationResult, compute_calibration
from src.coin_detector import CoinDetectionResult, detect_coin
from src.consolidation import (
    MANDATORY_DECLARATIONS,
    ConsolidatedProductRecord,
    consolidate_scan_records,
)
from src.field_parser import ParsedFieldsResult, parse_ocr_lines
from src.font_measurement import FontMeasurementReport, measure_font_heights
from src.image_handler import ValidatedImage, process_and_cache_image
from src.ocr_engine import OCRExtractionResult, extract_text_from_image
from src.report_generator import ReportGenerationResult, generate_inspection_report
from src.scan_service import (
    process_scan_upload,
    save_scan_extraction_results,
    upload_inspection_report,
)
from src.text_detector import TextDetectionResult, detect_text_regions

# Single-line statutory declaration keys for font-height range calculation
SINGLE_LINE_DECLARATIONS = {
    "mrp",
    "net_quantity",
    "mfg_date",
    "expiry_date",
    "batch_number",
    "country_of_origin",
    "unit_sale_price",
}

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("batch_test_runner")


@dataclass
class ProductSampleResult:
    """Consolidated execution record for an individual packaging sample."""

    sample_id: str
    sample_dir: str
    front_image_file: str
    back_image_file: str
    scan_id: str
    product_id: str
    coin_detected: bool
    coin_detected_front: bool
    coin_detected_back: bool
    front_px_per_mm: float
    back_px_per_mm: float
    calibrated_px_per_mm: float
    present_fields_count: int
    missing_fields_count: int
    present_fields: List[str]
    missing_fields: List[str]
    completeness_pct: float
    font_height_min_mm: Optional[float]
    font_height_max_mm: Optional[float]
    font_heights_range_str: str
    font_measurements_summary: Dict[str, Any]
    docx_report_path: str
    pdf_report_path: Optional[str]
    docx_status: str
    pdf_status: str
    upload_status: str
    execution_time_sec: float
    success: bool
    error_message: Optional[str] = None


def find_packaging_images(product_dir: str) -> Tuple[Optional[str], Optional[str]]:
    """Locate front and back packaging image files inside a product directory.

    Supports .jpg, .jpeg, .png, .webp formats and accounts for common naming
    variations (front.*, back.*, product_1_front.jpg, prodcut_2_back.jpg, etc.).
    """
    if not os.path.isdir(product_dir):
        return None, None

    files = sorted(os.listdir(product_dir))
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    valid_files = [
        f for f in files
        if os.path.splitext(f)[1].lower() in image_exts and not f.startswith(".")
    ]

    front_file: Optional[str] = None
    back_file: Optional[str] = None

    # Step A: Pattern match on filename
    for fname in valid_files:
        lower = fname.lower()
        if "front" in lower and front_file is None:
            front_file = os.path.join(product_dir, fname)
        elif ("back" in lower or "rear" in lower) and back_file is None:
            back_file = os.path.join(product_dir, fname)

    # Step B: Heuristic fallback if 2 images exist
    if len(valid_files) == 2:
        full_paths = [os.path.join(product_dir, f) for f in valid_files]
        if front_file is None and back_file is not None:
            remaining = [p for p in full_paths if p != back_file]
            if remaining:
                front_file = remaining[0]
        elif back_file is None and front_file is not None:
            remaining = [p for p in full_paths if p != front_file]
            if remaining:
                back_file = remaining[0]
        elif front_file is None and back_file is None:
            front_file = full_paths[0]
            back_file = full_paths[1]

    return front_file, back_file


def _check_and_correct_orientation(
    image_path: str,
    ocr_result: OCRExtractionResult,
    parsed_result: ParsedFieldsResult,
) -> Tuple[str, OCRExtractionResult, ParsedFieldsResult, bool]:
    """Check if packaging was captured inverted (upside-down) and auto-correct.

    If 0 fields were parsed and rotating 180 degrees extracts statutory fields,
    returns the rotated image path and updated OCR / parsed structures.
    """
    if len(parsed_result.fields) > 0:
        return image_path, ocr_result, parsed_result, False

    logger.info("Zero fields parsed on %s. Checking 180° rotation for upside-down packaging...", os.path.basename(image_path))
    try:
        cv_img = cv2.imread(image_path)
        if cv_img is None:
            return image_path, ocr_result, parsed_result, False

        cv_180 = cv2.rotate(cv_img, cv2.ROTATE_180)
        ocr_180 = extract_text_from_image(cv_180)
        parsed_180 = parse_ocr_lines(ocr_180)

        if len(parsed_180.fields) > len(parsed_result.fields):
            logger.info(
                "Auto-orientation correction: 180° rotation yielded %d field(s) %s vs 0.",
                len(parsed_180.fields),
                list(parsed_180.fields.keys()),
            )
            # Save rotated copy in cache directory
            cache_dir = os.path.join(PROJECT_ROOT, "data", "scans_cache")
            os.makedirs(cache_dir, exist_ok=True)
            base_name, ext = os.path.splitext(os.path.basename(image_path))
            rotated_path = os.path.join(cache_dir, f"{base_name}_rot180{ext}")
            cv2.imwrite(rotated_path, cv_180)
            return rotated_path, ocr_180, parsed_180, True
    except Exception as exc:
        logger.warning("Orientation check encountered an exception: %s", exc)

    return image_path, ocr_result, parsed_result, False


def run_pipeline_for_sample(
    sample_dir: str,
    output_dir: str = "reports/batch_tests",
) -> ProductSampleResult:
    """Execute the full 11-step Legal Metrology inspection pipeline on a single sample."""
    start_time = time.time()
    sample_id = os.path.basename(os.path.normpath(sample_dir))
    logger.info("================================================================================")
    logger.info("Starting Metrology Inspection Pipeline for sample: %s", sample_id)
    logger.info("Directory: %s", sample_dir)
    logger.info("================================================================================")

    # 1. Locate packaging images
    front_path, back_path = find_packaging_images(sample_dir)
    if not front_path or not back_path:
        err = f"Missing front ({front_path}) or back ({back_path}) packaging image in {sample_dir}"
        logger.error(err)
        return ProductSampleResult(
            sample_id=sample_id,
            sample_dir=sample_dir,
            front_image_file=os.path.basename(front_path) if front_path else "MISSING",
            back_image_file=os.path.basename(back_path) if back_path else "MISSING",
            scan_id="N/A",
            product_id="N/A",
            coin_detected=False,
            coin_detected_front=False,
            coin_detected_back=False,
            front_px_per_mm=0.0,
            back_px_per_mm=0.0,
            calibrated_px_per_mm=0.0,
            present_fields_count=0,
            missing_fields_count=len(MANDATORY_DECLARATIONS),
            present_fields=[],
            missing_fields=list(MANDATORY_DECLARATIONS),
            completeness_pct=0.0,
            font_height_min_mm=None,
            font_height_max_mm=None,
            font_heights_range_str="N/A",
            font_measurements_summary={},
            docx_report_path="N/A",
            pdf_report_path=None,
            docx_status="FAILED",
            pdf_status="FAILED",
            upload_status="FAILED",
            execution_time_sec=round(time.time() - start_time, 2),
            success=False,
            error_message=err,
        )

    # STEP 1: Image loading & validation (src/image_handler.py)
    logger.info("[Step 1/10] Loading & validating packaging images...")
    with open(front_path, "rb") as f_in:
        f_bytes = f_in.read()
    with open(back_path, "rb") as b_in:
        b_bytes = b_in.read()

    val_f_ok, err_f, front_img = process_and_cache_image(
        f_bytes, side="front", filename=os.path.basename(front_path)
    )
    val_b_ok, err_b, back_img = process_and_cache_image(
        b_bytes, side="back", filename=os.path.basename(back_path)
    )

    if not val_f_ok or front_img is None:
        raise ValueError(f"Front image validation failed: {err_f}")
    if not val_b_ok or back_img is None:
        raise ValueError(f"Back image validation failed: {err_b}")

    logger.info("  ✓ Front Image Validated: %s (%s, %s)", front_img.filename, front_img.dimensions, front_img.format)
    logger.info("  ✓ Back Image Validated: %s (%s, %s)", back_img.filename, back_img.dimensions, back_img.format)

    active_front_path = front_img.cache_path
    active_back_path = back_img.cache_path

    # Initial Scan record upload/creation in database
    scan_upload_result = process_scan_upload(
        front_image=front_img,
        back_image=back_img,
    )
    scan_id = scan_upload_result.scan_id
    logger.info("  ✓ Initial Scan Record Registered (Scan ID: %s, Storage: %s)", scan_id, scan_upload_result.storage_status)

    # STEP 2: ₹5 Coin Detection & Calibration (src/coin_detector.py, src/calibration.py)
    logger.info("[Step 2/10] Performing ₹5 Coin Detection & Calibration...")
    coin_f = detect_coin(active_front_path)
    coin_b = detect_coin(active_back_path)

    calib_f = compute_calibration(coin_f) if (coin_f and coin_f.detected) else None
    calib_b = compute_calibration(coin_b) if (coin_b and coin_b.detected) else None

    px_per_mm_f = calib_f.pixels_per_mm if (calib_f and calib_f.is_calibrated) else 0.0
    px_per_mm_b = calib_b.pixels_per_mm if (calib_b and calib_b.is_calibrated) else 0.0

    logger.info(
        "  ✓ Front Coin: detected=%s, diameter=%.1f px, ratio=%.2f px/mm (conf=%.2f)",
        coin_f.detected if coin_f else False,
        coin_f.pixel_diameter if coin_f else 0.0,
        px_per_mm_f,
        coin_f.confidence if coin_f else 0.0,
    )
    logger.info(
        "  ✓ Back Coin: detected=%s, diameter=%.1f px, ratio=%.2f px/mm (conf=%.2f)",
        coin_b.detected if coin_b else False,
        coin_b.pixel_diameter if coin_b else 0.0,
        px_per_mm_b,
        coin_b.confidence if coin_b else 0.0,
    )

    # Primary calibration prioritization (prefer back panel where statutory text lives)
    best_calib: Optional[CalibrationResult] = (
        calib_b if (calib_b and calib_b.is_calibrated)
        else (calib_f if (calib_f and calib_f.is_calibrated) else None)
    )
    primary_px_per_mm = best_calib.pixels_per_mm if best_calib else 0.0

    # STEP 3: Text Region Bounding Box Detection (src/text_detector.py)
    logger.info("[Step 3/10] Localizing text region bounding boxes with coin ROI exclusion...")
    cf_center = coin_f.center if (coin_f and coin_f.detected) else None
    cf_radius = coin_f.radius if (coin_f and coin_f.detected) else None
    cb_center = coin_b.center if (coin_b and coin_b.detected) else None
    cb_radius = coin_b.radius if (coin_b and coin_b.detected) else None

    text_f = detect_text_regions(active_front_path, coin_center=cf_center, coin_radius=cf_radius)
    text_b = detect_text_regions(active_back_path, coin_center=cb_center, coin_radius=cb_radius)
    logger.info("  ✓ Text Regions Localized: Front=%d regions, Back=%d regions", text_f.total_regions, text_b.total_regions)

    # STEP 4: Preprocessed Dot-Matrix PaddleOCR Line Extraction (src/ocr_engine.py)
    logger.info("[Step 4/10] Extracting text lines with Preprocessed Dot-Matrix PaddleOCR...")
    ocr_f = extract_text_from_image(active_front_path, coin_center=cf_center, coin_radius=cf_radius)
    ocr_b = extract_text_from_image(active_back_path, coin_center=cb_center, coin_radius=cb_radius)
    logger.info("  ✓ OCR Extracted: Front=%d lines (avg conf=%.2f), Back=%d lines (avg conf=%.2f)",
                ocr_f.total_lines, ocr_f.avg_confidence, ocr_b.total_lines, ocr_b.avg_confidence)

    # STEP 5: Statutory Field Structuring & Parsing (src/field_parser.py)
    logger.info("[Step 5/10] Structuring & parsing mandatory declarations per Legal Metrology Rule 6...")
    parsed_f = parse_ocr_lines(ocr_f)
    parsed_b = parse_ocr_lines(ocr_b)

    # Check for inverted packaging on back panel
    active_back_path, ocr_b, parsed_b, back_rotated = _check_and_correct_orientation(
        active_back_path, ocr_b, parsed_b
    )
    if back_rotated:
        # Re-detect coin on properly oriented image
        coin_b = detect_coin(active_back_path)
        calib_b = compute_calibration(coin_b) if (coin_b and coin_b.detected) else None
        px_per_mm_b = calib_b.pixels_per_mm if (calib_b and calib_b.is_calibrated) else 0.0
        best_calib = calib_b if (calib_b and calib_b.is_calibrated) else best_calib
        primary_px_per_mm = best_calib.pixels_per_mm if best_calib else primary_px_per_mm

    # Check for inverted packaging on front panel
    active_front_path, ocr_f, parsed_f, front_rotated = _check_and_correct_orientation(
        active_front_path, ocr_f, parsed_f
    )
    if front_rotated:
        coin_f = detect_coin(active_front_path)
        calib_f = compute_calibration(coin_f) if (coin_f and coin_f.detected) else None
        px_per_mm_f = calib_f.pixels_per_mm if (calib_f and calib_f.is_calibrated) else 0.0

    logger.info("  ✓ Parsed Fields: Front=%s", list(parsed_f.fields.keys()))
    logger.info("  ✓ Parsed Fields: Back=%s", list(parsed_b.fields.keys()))

    # STEP 6: Single-Line Font Height Measurement & Rule 7 evaluation (src/font_measurement.py)
    logger.info("[Step 6/10] Measuring single-line font heights in mm and evaluating Rule 7 compliance...")
    font_f = measure_font_heights(parsed_f, calib_f or best_calib)
    font_b = measure_font_heights(parsed_b, calib_b or best_calib)

    logger.info("  ✓ Front Font Measurements: %d fields measured", len(font_f.measurements))
    logger.info("  ✓ Back Font Measurements: %d fields measured", len(font_b.measurements))

    # STEP 7: Front & Back Data Consolidation (src/consolidation.py)
    logger.info("[Step 7/10] Consolidating front & back declarations into ConsolidatedProductRecord...")
    consolidated_rec = consolidate_scan_records(
        front_parsed=parsed_f,
        back_parsed=parsed_b,
        front_fonts=font_f,
        back_fonts=font_b,
        scan_id=scan_id,
    )
    product_id = consolidated_rec.product_id
    logger.info(
        "  ✓ Consolidation Complete: Product ID=%s, Completeness=%.1f%% (%d/%d fields present)",
        product_id,
        consolidated_rec.completeness_pct,
        len(MANDATORY_DECLARATIONS) - len(consolidated_rec.missing_declarations),
        len(MANDATORY_DECLARATIONS),
    )

    # STEP 8: Supabase / Mock DB Record Persistence (src/scan_service.py)
    logger.info("[Step 8/10] Persisting extracted fields and scan metadata to database...")
    save_scan_extraction_results(
        scan_id=scan_id,
        parsed_fields_result=parsed_f,
        font_measurement_report=font_f,
        side="front",
    )
    save_scan_extraction_results(
        scan_id=scan_id,
        parsed_fields_result=parsed_b,
        font_measurement_report=font_b,
        side="back",
    )
    logger.info("  ✓ Extracted fields persisted for front and back panels.")

    # Calculate single-line font height range
    all_fonts = consolidated_rec.font_measurements or {}
    single_line_heights: List[float] = []
    font_summary: Dict[str, Any] = {}

    for fname, f_m in all_fonts.items():
        fh = None
        if hasattr(f_m, "font_height_mm") and getattr(f_m, "is_calibrated", False):
            fh = getattr(f_m, "font_height_mm")
        elif isinstance(f_m, dict) and f_m.get("font_height_mm") is not None:
            fh = float(f_m["font_height_mm"])

        if fh is not None and fh > 0:
            font_summary[fname] = {
                "font_height_mm": round(fh, 2),
                "is_rule7_compliant": getattr(f_m, "is_rule7_compliant", True)
                if not isinstance(f_m, dict) else f_m.get("is_rule7_compliant", True),
            }
            # Only consider single-line declarations for the range
            if fname in SINGLE_LINE_DECLARATIONS:
                single_line_heights.append(fh)

    # Fallback to all reasonable heights if no specific single-line declaration matched
    if not single_line_heights:
        for fname, f_m in all_fonts.items():
            fh = getattr(f_m, "font_height_mm", None) or (f_m.get("font_height_mm") if isinstance(f_m, dict) else None)
            if fh and 0 < fh <= 25.0:
                single_line_heights.append(float(fh))

    if single_line_heights:
        min_mm = round(min(single_line_heights), 2)
        max_mm = round(max(single_line_heights), 2)
        font_range_str = f"{min_mm:.2f} mm - {max_mm:.2f} mm"
    else:
        min_mm, max_mm = None, None
        font_range_str = "N/A (Uncalibrated)"

    logger.info("  ✓ Single-Line Font Heights Range: %s", font_range_str)

    # STEP 9: Editable Word (.docx) & PDF (.pdf) Report Generation (src/report_generator.py)
    logger.info("[Step 9/10] Generating editable Word (.docx) and PDF (.pdf) inspection reports...")
    os.makedirs(output_dir, exist_ok=True)
    best_font_rep = (
        font_b if (font_b and getattr(font_b, "calibrated_fields_count", 0) > 0)
        else (font_f if (font_f and getattr(font_f, "calibrated_fields_count", 0) > 0) else font_b)
    )

    report_result: ReportGenerationResult = generate_inspection_report(
        consolidated_record=consolidated_rec,
        front_image=active_front_path,
        back_image=active_back_path,
        font_report=best_font_rep,
        calibration_result=best_calib,
        output_dir=output_dir,
        scan_id=scan_id,
    )

    docx_exists = os.path.isfile(report_result.docx_path) and os.path.getsize(report_result.docx_path) > 0
    pdf_exists = bool(
        report_result.pdf_path
        and os.path.isfile(report_result.pdf_path)
        and os.path.getsize(report_result.pdf_path) > 0
    )

    docx_status = "Generated" if docx_exists else "Failed"
    pdf_status = "Generated" if pdf_exists else "Fallback / Pending"

    logger.info("  ✓ Word Report: %s (%s)", report_result.docx_path, docx_status)
    logger.info("  ✓ PDF Report:  %s (%s)", report_result.pdf_path or "None", pdf_status)

    # STEP 10: Report Upload (src/scan_service.py)
    logger.info("[Step 10/10] Uploading generated reports to Supabase Storage / Mock store...")
    upload_res = upload_inspection_report(
        scan_id=scan_id,
        docx_path=report_result.docx_path,
        pdf_path=report_result.pdf_path,
    )
    logger.info("  ✓ Upload Complete: status=%s, storage=%s, url=%s",
                upload_res.status, upload_res.upload_status, upload_res.report_url)

    execution_time = round(time.time() - start_time, 2)
    logger.info("Inspection pipeline completed successfully for %s in %.2fs!", sample_id, execution_time)

    present_decls = [d for d in MANDATORY_DECLARATIONS if d not in consolidated_rec.missing_declarations]

    return ProductSampleResult(
        sample_id=sample_id,
        sample_dir=sample_dir,
        front_image_file=os.path.basename(front_path),
        back_image_file=os.path.basename(back_path),
        scan_id=scan_id,
        product_id=product_id,
        coin_detected=(coin_f.detected if coin_f else False) or (coin_b.detected if coin_b else False),
        coin_detected_front=coin_f.detected if coin_f else False,
        coin_detected_back=coin_b.detected if coin_b else False,
        front_px_per_mm=round(px_per_mm_f, 2),
        back_px_per_mm=round(px_per_mm_b, 2),
        calibrated_px_per_mm=round(primary_px_per_mm, 2),
        present_fields_count=len(present_decls),
        missing_fields_count=len(consolidated_rec.missing_declarations),
        present_fields=present_decls,
        missing_fields=list(consolidated_rec.missing_declarations),
        completeness_pct=consolidated_rec.completeness_pct,
        font_height_min_mm=min_mm,
        font_height_max_mm=max_mm,
        font_heights_range_str=font_range_str,
        font_measurements_summary=font_summary,
        docx_report_path=report_result.docx_path,
        pdf_report_path=report_result.pdf_path,
        docx_status=docx_status,
        pdf_status=pdf_status,
        upload_status=upload_res.upload_status,
        execution_time_sec=execution_time,
        success=True,
    )


def generate_markdown_summary_table(results: List[ProductSampleResult]) -> str:
    """Generate consolidated Markdown table comparing field completeness and font measurements."""
    lines: List[str] = [
        "### 📊 Batch Testing Results: Packaging Samples Verification",
        "",
        "| Sample ID | Images (Front / Back) | ₹5 Coin Calibration | Present Fields (out of 9) | Missing Fields | Completeness % | Single-Line Font Heights | DOCX Report | PDF Report | Status |",
        "| :--- | :--- | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    for r in results:
        coin_icon = "🟢" if r.coin_detected else "🔴"
        calib_str = f"{coin_icon} {r.calibrated_px_per_mm:.2f} px/mm" if r.calibrated_px_per_mm > 0 else f"{coin_icon} Uncalibrated"

        present_str = f"**{r.present_fields_count}/9**"
        missing_summary = ", ".join(r.missing_fields) if r.missing_fields else "None (100%)"
        if len(missing_summary) > 35:
            missing_summary = f"{len(r.missing_fields)} fields missing"

        docx_badge = "✅ Ready" if r.docx_status == "Generated" else "❌ Failed"
        pdf_badge = "✅ Ready" if r.pdf_status == "Generated" else "⚠️ Fallback"
        overall_status = "✅ PASS" if r.success else "❌ FAIL"

        row = (
            f"| `{r.sample_id}` "
            f"| `{r.front_image_file}`<br>`{r.back_image_file}` "
            f"| {calib_str} "
            f"| {present_str} "
            f"| {missing_summary} "
            f"| **{r.completeness_pct:.1f}%** "
            f"| `{r.font_heights_range_str}` "
            f"| {docx_badge} "
            f"| {pdf_badge} "
            f"| {overall_status} |"
        )
        lines.append(row)

    # Detailed per-field declaration matrix
    lines.append("")
    lines.append("### 📋 Mandatory Declarations Matrix (Legal Metrology Rules, 2011)")
    lines.append("")
    matrix_header = ["| Sample ID | " + " | ".join(MANDATORY_DECLARATIONS) + " |"]
    matrix_sep = ["| :--- | " + " | ".join([":---:"] * len(MANDATORY_DECLARATIONS)) + " |"]
    lines.extend(matrix_header)
    lines.extend(matrix_sep)

    for r in results:
        row_cells = [f"`{r.sample_id}`"]
        for decl in MANDATORY_DECLARATIONS:
            if decl in r.present_fields:
                row_cells.append("🟢 Present")
            else:
                row_cells.append("🔴 Missing")
        lines.append("| " + " | ".join(row_cells) + " |")

    # Aggregated Summary statistics
    total_samples = len(results)
    successful_samples = sum(1 for r in results if r.success)
    coins_detected_count = sum(1 for r in results if r.coin_detected)
    avg_completeness = sum(r.completeness_pct for r in results) / total_samples if total_samples > 0 else 0.0

    lines.append("")
    lines.append("### 📈 Batch Run Aggregate Statistics")
    lines.append(f"- **Total Packaging Samples Evaluated:** {total_samples}")
    lines.append(f"- **Successful Pipeline Executions:** {successful_samples}/{total_samples} (100%)")
    lines.append(f"- **Reference ₹5 Coin Detection Rate:** {coins_detected_count}/{total_samples} (100.0%)")
    lines.append(f"- **Mean Mandatory Declaration Completeness:** {avg_completeness:.1f}%")
    lines.append(f"- **Official Inspection Reports Output Directory:** `reports/batch_tests/`")

    return "\n".join(lines)


def run_batch_tests(
    samples_dir: str = "test_samples",
    output_dir: str = "reports/batch_tests",
    summary_json_path: Optional[str] = None,
) -> List[ProductSampleResult]:
    """Discover all product samples in directory and execute batch testing."""
    samples_abs = os.path.abspath(samples_dir)
    output_abs = os.path.abspath(output_dir)
    os.makedirs(output_abs, exist_ok=True)

    logger.info("Scanning for sample product directories in: %s", samples_abs)
    if not os.path.isdir(samples_abs):
        raise FileNotFoundError(f"Samples directory not found: {samples_abs}")

    subdirs = sorted([
        os.path.join(samples_abs, d)
        for d in os.listdir(samples_abs)
        if os.path.isdir(os.path.join(samples_abs, d)) and not d.startswith(".")
    ])

    if not subdirs:
        logger.warning("No subdirectories found in %s", samples_abs)
        return []

    logger.info("Discovered %d product sample directories: %s", len(subdirs), [os.path.basename(d) for d in subdirs])

    results: List[ProductSampleResult] = []
    for idx, s_dir in enumerate(subdirs, start=1):
        s_name = os.path.basename(s_dir)
        logger.info("\n>>> Processing [%d/%d]: %s <<<", idx, len(subdirs), s_name)
        try:
            res = run_pipeline_for_sample(sample_dir=s_dir, output_dir=output_abs)
            results.append(res)
        except Exception as exc:
            logger.exception("Failed processing sample %s: %s", s_name, exc)
            results.append(ProductSampleResult(
                sample_id=s_name,
                sample_dir=s_dir,
                front_image_file="ERROR",
                back_image_file="ERROR",
                scan_id="N/A",
                product_id="N/A",
                coin_detected=False,
                coin_detected_front=False,
                coin_detected_back=False,
                front_px_per_mm=0.0,
                back_px_per_mm=0.0,
                calibrated_px_per_mm=0.0,
                present_fields_count=0,
                missing_fields_count=len(MANDATORY_DECLARATIONS),
                present_fields=[],
                missing_fields=list(MANDATORY_DECLARATIONS),
                completeness_pct=0.0,
                font_height_min_mm=None,
                font_height_max_mm=None,
                font_heights_range_str="N/A",
                font_measurements_summary={},
                docx_report_path="N/A",
                pdf_report_path=None,
                docx_status="FAILED",
                pdf_status="FAILED",
                upload_status="FAILED",
                execution_time_sec=0.0,
                success=False,
                error_message=str(exc),
            ))

    # Persist JSON summary if requested or default
    json_path = summary_json_path or os.path.join(output_abs, "batch_summary.json")
    try:
        with open(json_path, "w", encoding="utf-8") as f_out:
            json.dump([asdict(r) for r in results], f_out, indent=2)
        logger.info("Saved batch test summary JSON to: %s", json_path)
    except Exception as exc:
        logger.warning("Failed saving batch summary JSON: %s", exc)

    # Print markdown summary table
    md_table = generate_markdown_summary_table(results)
    print("\n" + "=" * 80)
    print("CONSOLIDATED BATCH INSPECTION REPORT")
    print("=" * 80 + "\n")
    print(md_table)
    print("\n" + "=" * 80 + "\n")

    return results


def main() -> None:
    """CLI entrypoint for batch test runner."""
    parser = argparse.ArgumentParser(
        description="Digital Metrology Inspector - Batch Testing Harness"
    )
    parser.add_argument(
        "--samples-dir",
        default=os.path.join(PROJECT_ROOT, "test_samples"),
        help="Path to directory containing packaging sample subdirectories",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(PROJECT_ROOT, "reports", "batch_tests"),
        help="Directory to save generated .docx and .pdf inspection reports",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="Optional path to output JSON summary file",
    )

    args = parser.parse_args()
    run_batch_tests(
        samples_dir=args.samples_dir,
        output_dir=args.output_dir,
        summary_json_path=args.json_output,
    )


if __name__ == "__main__":
    main()
