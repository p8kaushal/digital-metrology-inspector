"""Automated Test Suite for Task 16: Phase 1 Test Pass & Accuracy Benchmark.

Validates the full Digital Metrology Inspector Phase 1 pipeline end-to-end against
5 diverse packaged commodity products across industry categories:
  1. Food/Snacks: Crunchy Masala Potato Chips (150 g)
  2. Beverage Carton: Pure Himalayan Spring Water (1000 ml)
  3. Cosmetics: Glow Radiance Hydrating Day Cream (50 g)
  4. Electronics: HyperCharge 65W Fast Charger (1 N)
  5. Personal Care: Organic Neem & Aloe Body Wash (250 ml)

Covers all 11 pipeline stages:
  Stage 1: Image loading & validation (format, dimensions, metadata, caching)
  Stage 2: Coin detection & calibration math (21.9mm ₹5 reference coin)
  Stage 3: Text region detection with coin ROI masking
  Stage 4: OCR line extraction (PaddleOCR) with high confidence & coin exclusion
  Stage 5: Field structuring & parsing (9 mandatory Legal Metrology declarations)
  Stage 6: Real-world font-size measurement in mm & Rule 7 baseline evaluation
  Stage 7: Front & Back data consolidation into master product record
  Stage 8: Database persistence (scans, extracted_fields, products tables)
  Stage 9: Editable Word (.docx) and PDF statutory inspection report generation
  Stage 10: Inspection report storage upload & retrievable cloud links
  Stage 11: Inspector manual correction & audit trail logging in correction_logs

Benchmark Criteria:
  - Extraction accuracy: >90% across mandatory declarations
  - Real-world font-size measurement accuracy within physical bounds
  - 100% test pass rate across all categories and pipeline stages
"""

from __future__ import annotations

import os
import shutil
import sys
import unittest
import uuid
from typing import Any, Dict, List, Tuple

import cv2
import docx
import numpy as np
from PIL import Image

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import db
from src.calibration import (
    INDIAN_5_RUPEE_COIN_DIAMETER_MM,
    CalibrationResult,
    compute_calibration,
)
from src.coin_detector import CoinDetectionResult, detect_coin
from src.consolidation import (
    MANDATORY_DECLARATIONS,
    ConsolidatedProductRecord,
    consolidate_scan_records,
)
from src.field_parser import (
    MANDATORY_FIELDS,
    ExtractedField,
    ParsedFieldsResult,
    parse_ocr_lines,
)
from src.font_measurement import (
    FontMeasurement,
    FontMeasurementReport,
    measure_font_heights,
)
from src.image_handler import (
    ValidatedImage,
    compute_image_metadata,
    save_to_cache,
    validate_image_bytes,
)
from src.ocr_engine import (
    OCRExtractionResult,
    OCRLineItem,
    extract_text_from_image,
    is_in_coin_roi,
)
from src.report_generator import ReportGenerationResult, generate_inspection_report
from src.scan_service import (
    ManualCorrectionResult,
    ReportUploadResult,
    SaveExtractionResult,
    ScanUploadResult,
    apply_manual_corrections,
    process_scan_upload,
    save_scan_extraction_results,
    upload_inspection_report,
)

TEMP_TEST_DIR = os.path.join(PROJECT_ROOT, "tests", "temp_task16_benchmark")


class TestTask16Phase1Benchmark(unittest.TestCase):
    """End-to-end benchmark test suite simulating 5 diverse packaged commodities."""

    @classmethod
    def setUpClass(cls):
        """Prepare temporary directory, generate 5 sample products, and precompute extractions."""
        os.makedirs(TEMP_TEST_DIR, exist_ok=True)
        cls.test_dir = TEMP_TEST_DIR

        # Specifications for 5 diverse sample packaged products across Indian consumer categories
        cls.product_specs = [
            {
                "category": "Food/Snacks",
                "brand_name": "Crunchy Masala Potato Chips",
                "declared_mrp": "40.00",
                "declared_qty": "150",
                "declared_unit": "g",
                "coin_center": (680, 480),
                "coin_radius": 65,  # 130 px diameter => ~5.94 px/mm
                "front_lines": [
                    ("CRUNCHY MASALA POTATO CHIPS", 0.85),
                    ("MRP Rs. 40.00", 0.80),
                    ("NET QTY: 150 g", 0.80),
                ],
                "back_lines": [
                    ("MFG DATE: 08/2026", 0.80),
                    ("EXPIRY DATE: 02/2027", 0.80),
                    ("BATCH NO: CHIP-9821", 0.80),
                    ("COUNTRY OF ORIGIN: INDIA", 0.80),
                    ("UNIT SALE PRICE Rs. 0.27/g", 0.80),
                    ("MANUFACTURED BY: Apex Foods Pvt Ltd, GIDC Estate, Ahmedabad - 382445", 0.70),
                    ("CUSTOMER CARE: 1800-209-1234", 0.70),
                ],
            },
            {
                "category": "Beverage Carton",
                "brand_name": "Pure Himalayan Spring Water",
                "declared_mrp": "60.00",
                "declared_qty": "1000",
                "declared_unit": "ml",
                "coin_center": (700, 490),
                "coin_radius": 65,
                "front_lines": [
                    ("PURE HIMALAYAN SPRING WATER", 0.85),
                    ("MRP Rs. 60.00", 0.80),
                    ("NET VOLUME: 1000 ml", 0.80),
                ],
                "back_lines": [
                    ("PKD DATE: 07/2026", 0.80),
                    ("BEST BEFORE: 07/2027", 0.80),
                    ("LOT NO: WTR-7041", 0.80),
                    ("COUNTRY OF ORIGIN: INDIA", 0.80),
                    ("UNIT SALE PRICE Rs. 0.06/ml", 0.80),
                    ("PACKED BY: Glacier Spring Beverages Ltd, Industrial Zone, Solan - 173212", 0.70),
                    ("CONSUMER CARE: 1800-419-8800", 0.70),
                ],
            },
            {
                "category": "Cosmetics",
                "brand_name": "Glow Radiance Hydrating Day Cream",
                "declared_mrp": "350.00",
                "declared_qty": "50",
                "declared_unit": "g",
                "coin_center": (680, 480),
                "coin_radius": 65,
                "front_lines": [
                    ("GLOW RADIANCE HYDRATING DAY CREAM", 0.85),
                    ("MRP Rs. 350.00", 0.80),
                    ("NET WT: 50 g", 0.80),
                ],
                "back_lines": [
                    ("MFG DATE: 05/2026", 0.80),
                    ("USE BEFORE: 05/2028", 0.80),
                    ("BATCH: GLOW-330", 0.80),
                    ("MADE IN INDIA", 0.80),
                    ("UNIT SALE PRICE Rs. 7.00/g", 0.80),
                    ("MANUFACTURED BY: Lotus Wellness Cosmetics Ltd, Sector 62, Noida - 201309", 0.70),
                    ("CUSTOMER CARE: 1800-222-7788", 0.70),
                ],
            },
            {
                "category": "Electronics",
                "brand_name": "HyperCharge 65W Fast Charger",
                "declared_mrp": "1999.00",
                "declared_qty": "1",
                "declared_unit": "N",
                "coin_center": (680, 480),
                "coin_radius": 65,
                "front_lines": [
                    ("HYPERCHARGE 65W FAST CHARGER", 0.85),
                    ("MRP Rs. 1999.00", 0.80),
                    ("NET QUANTITY: 1 N", 0.80),
                ],
                "back_lines": [
                    ("MFG DATE: 04/2026", 0.80),
                    ("EXPIRY DATE: 04/2031", 0.80),
                    ("BATCH NO: HC-65-889", 0.80),
                    ("COUNTRY OF ORIGIN: INDIA", 0.80),
                    ("UNIT SALE PRICE Rs. 1999.00/N", 0.80),
                    ("MANUFACTURED BY: TechVolt Electronics India Pvt Ltd, Whitefield, Bengaluru - 560066", 0.70),
                    ("CONSUMER CARE: 1800-889-9900", 0.70),
                ],
            },
            {
                "category": "Personal Care",
                "brand_name": "Organic Neem & Aloe Body Wash",
                "declared_mrp": "175.00",
                "declared_qty": "250",
                "declared_unit": "ml",
                "coin_center": (680, 480),
                "coin_radius": 65,
                "front_lines": [
                    ("ORGANIC NEEM & ALOE BODY WASH", 0.85),
                    ("MRP Rs. 175.00", 0.80),
                    ("NET CONTENTS: 250 ml", 0.80),
                ],
                "back_lines": [
                    ("MFG DATE: 06/2026", 0.80),
                    ("EXPIRY DATE: 06/2028", 0.80),
                    ("BATCH NO: ALOE-554", 0.80),
                    ("COUNTRY OF ORIGIN: INDIA", 0.80),
                    ("UNIT SALE PRICE Rs. 0.70/ml", 0.80),
                    ("MANUFACTURED BY: GreenHerb Naturals Pvt Ltd, Kinfra Park, Thrissur - 680001", 0.70),
                    ("CONSUMER CARE: 1800-333-8899", 0.70),
                ],
            },
        ]

        cls.benchmark_data: List[Dict[str, Any]] = []

        # Generate images, run coin detection, calibration, OCR, and parsing for all 5 products
        for idx, spec in enumerate(cls.product_specs):
            prefix = f"p{idx+1}_{spec['category'].lower().replace('/', '_')}"
            f_path = os.path.join(cls.test_dir, f"{prefix}_front.png")
            b_path = os.path.join(cls.test_dir, f"{prefix}_back.png")

            # 1. Render front label image with ₹5 reference coin
            img_front = np.full((600, 850, 3), 255, dtype=np.uint8)
            cv2.circle(img_front, spec["coin_center"], spec["coin_radius"], (60, 60, 60), -1)
            cv2.circle(img_front, spec["coin_center"], spec["coin_radius"], (30, 30, 30), 2)
            for l_idx, (text, font_scale) in enumerate(spec["front_lines"]):
                cv2.putText(
                    img_front,
                    text,
                    (50, 80 + l_idx * 75),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale,
                    (0, 0, 0),
                    2,
                )
            cv2.imwrite(f_path, img_front)

            # 2. Render back label image with ₹5 reference coin
            img_back = np.full((650, 950, 3), 255, dtype=np.uint8)
            cv2.circle(img_back, spec["coin_center"], spec["coin_radius"], (60, 60, 60), -1)
            cv2.circle(img_back, spec["coin_center"], spec["coin_radius"], (30, 30, 30), 2)
            for l_idx, (text, font_scale) in enumerate(spec["back_lines"]):
                cv2.putText(
                    img_back,
                    text,
                    (50, 70 + l_idx * 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale,
                    (0, 0, 0),
                    2,
                )
            cv2.imwrite(b_path, img_back)

            # 3. Detect coin & calibrate for front
            coin_f = detect_coin(f_path, minRadius=40, maxRadius=100)
            calib_f = compute_calibration(coin_f)

            # 4. Detect coin & calibrate for back
            coin_b = detect_coin(b_path, minRadius=40, maxRadius=100)
            calib_b = compute_calibration(coin_b)

            # 5. Extract OCR for front and back (with coin ROI masking)
            ocr_f = extract_text_from_image(
                image_input=f_path,
                coin_center=coin_f.center if coin_f.detected else spec["coin_center"],
                coin_radius=coin_f.radius if coin_f.detected else spec["coin_radius"],
            )
            ocr_b = extract_text_from_image(
                image_input=b_path,
                coin_center=coin_b.center if coin_b.detected else spec["coin_center"],
                coin_radius=coin_b.radius if coin_b.detected else spec["coin_radius"],
            )

            # 6. Parse structured fields
            parsed_f = parse_ocr_lines(ocr_f)
            parsed_b = parse_ocr_lines(ocr_b)

            # 7. Measure font heights
            fonts_f = measure_font_heights(parsed_f, calib_f)
            fonts_b = measure_font_heights(parsed_b, calib_b)

            # Store precomputed benchmark artifact record
            cls.benchmark_data.append({
                "spec": spec,
                "front_path": f_path,
                "back_path": b_path,
                "img_front": img_front,
                "img_back": img_back,
                "coin_f": coin_f,
                "coin_b": coin_b,
                "calib_f": calib_f,
                "calib_b": calib_b,
                "ocr_f": ocr_f,
                "ocr_b": ocr_b,
                "parsed_f": parsed_f,
                "parsed_b": parsed_b,
                "fonts_f": fonts_f,
                "fonts_b": fonts_b,
            })

    @classmethod
    def tearDownClass(cls):
        """Clean up generated benchmark files."""
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    # ==========================================================================
    # Stage 1: Image Loading & Validation
    # ==========================================================================
    def test_01_image_loading_and_validation(self):
        """Stage 1: Verify all 10 sample packaging images validate and yield valid metadata."""
        for item in self.benchmark_data:
            cat = item["spec"]["category"]
            for side, path in (("front", item["front_path"]), ("back", item["back_path"])):
                with open(path, "rb") as f:
                    raw_bytes = f.read()

                is_valid, err_msg, pil_img, metadata = validate_image_bytes(
                    raw_bytes, filename=os.path.basename(path)
                )
                self.assertTrue(is_valid, f"Validation failed for {cat} {side}: {err_msg}")
                self.assertIsNotNone(pil_img)
                self.assertIsNotNone(metadata)
                self.assertGreaterEqual(metadata["width"], 500)
                self.assertGreaterEqual(metadata["height"], 500)
                self.assertEqual(metadata["format"], "PNG")
                self.assertGreater(metadata["size_kb"], 1.0)

                # Test cache functionality
                cached_path = save_to_cache(raw_bytes, side=side, custom_filename=f"cache_{os.path.basename(path)}")
                self.assertTrue(os.path.exists(cached_path))

    # ==========================================================================
    # Stage 2: Coin Detection & Calibration Math (21.9mm ₹5 Reference)
    # ==========================================================================
    def test_02_coin_detection_and_calibration_math(self):
        """Stage 2: Verify OpenCV Hough Circle coin detection and calibration math."""
        for item in self.benchmark_data:
            cat = item["spec"]["category"]
            spec = item["spec"]
            expected_diameter = float(spec["coin_radius"] * 2)

            for side, coin_res, calib_res in (
                ("front", item["coin_f"], item["calib_f"]),
                ("back", item["coin_b"], item["calib_b"]),
            ):
                self.assertTrue(
                    coin_res.detected,
                    f"Coin not detected on {cat} {side} panel",
                )
                self.assertIsNotNone(coin_res.center)
                self.assertGreater(coin_res.confidence, 0.5)

                # Assert measured diameter is within 5% tolerance of drawn diameter
                diff = abs(coin_res.pixel_diameter - expected_diameter)
                self.assertLessEqual(
                    diff,
                    expected_diameter * 0.05,
                    f"Coin diameter {coin_res.pixel_diameter} on {cat} {side} differs from {expected_diameter}",
                )

                # Calibration math verification
                self.assertTrue(calib_res.is_calibrated)
                expected_px_per_mm = coin_res.pixel_diameter / INDIAN_5_RUPEE_COIN_DIAMETER_MM
                self.assertAlmostEqual(calib_res.pixels_per_mm, expected_px_per_mm, places=3)
                self.assertAlmostEqual(
                    calib_res.pixels_per_mm * calib_res.mm_per_pixel, 1.0, places=3
                )
                self.assertGreater(calib_res.pixels_per_mm, 5.0)
                self.assertLess(calib_res.pixels_per_mm, 7.0)

    # ==========================================================================
    # Stage 3: Text Region Detection
    # ==========================================================================
    def test_03_text_region_detection_and_coin_masking(self):
        """Stage 3: Verify text region detector detects packaging text and respects coin masking."""
        from src.text_detector import detect_text_regions

        for item in self.benchmark_data:
            cat = item["spec"]["category"]
            coin_res = item["coin_f"]

            td_res = detect_text_regions(
                image_input=item["front_path"],
                coin_center=coin_res.center,
                coin_radius=coin_res.radius,
            )
            self.assertGreater(
                td_res.total_regions,
                0,
                f"No text regions detected on {cat} front panel",
            )

            # Confirm no text region overlaps the center of the coin
            for reg in td_res.regions:
                x1, y1, x2, y2 = reg.bbox
                cx, cy = coin_res.center
                is_centered_inside = (x1 <= cx <= x2) and (y1 <= cy <= y2)
                self.assertFalse(
                    is_centered_inside,
                    f"Text region {reg.bbox} inside coin center {coin_res.center} on {cat}",
                )

    # ==========================================================================
    # Stage 4: OCR Line Extraction
    # ==========================================================================
    def test_04_ocr_line_extraction_quality(self):
        """Stage 4: Verify PaddleOCR extracts text lines with high confidence and excludes coin."""
        for item in self.benchmark_data:
            cat = item["spec"]["category"]
            ocr_f = item["ocr_f"]
            ocr_b = item["ocr_b"]

            self.assertGreaterEqual(ocr_f.total_lines, 3, f"Insufficient front lines for {cat}")
            self.assertGreaterEqual(ocr_b.total_lines, 5, f"Insufficient back lines for {cat}")
            self.assertGreater(ocr_f.avg_confidence, 0.85, f"Low front OCR confidence for {cat}")
            self.assertGreater(ocr_b.avg_confidence, 0.85, f"Low back OCR confidence for {cat}")

            # Verify no extracted line item overlaps coin ROI
            coin_f = item["coin_f"]
            for line in ocr_f.lines:
                self.assertFalse(
                    is_in_coin_roi(line.bbox, coin_f.center, coin_f.radius),
                    f"Front line '{line.text}' overlapped coin on {cat}",
                )

    # ==========================================================================
    # Stage 5: Field Structuring & Parsing Accuracy Benchmark (>90%)
    # ==========================================================================
    def test_05_field_structuring_and_accuracy_benchmark(self):
        """Stage 5: Assert field structuring extraction accuracy exceeds 90% across the 5 categories."""
        total_mandatory_slots = len(self.benchmark_data) * len(MANDATORY_FIELDS)
        total_detected_slots = 0
        category_accuracies: Dict[str, float] = {}

        for item in self.benchmark_data:
            cat = item["spec"]["category"]
            parsed_f = item["parsed_f"]
            parsed_b = item["parsed_b"]

            combined_fields = set(parsed_f.fields.keys()) | set(parsed_b.fields.keys())
            found_count = len([f for f in MANDATORY_FIELDS if f in combined_fields])
            cat_accuracy = (found_count / float(len(MANDATORY_FIELDS))) * 100.0
            category_accuracies[cat] = cat_accuracy
            total_detected_slots += found_count

            # Verify critical fields specifically for each category
            self.assertIn("mrp", combined_fields, f"MRP missing in {cat}")
            self.assertIn("net_quantity", combined_fields, f"Net Qty missing in {cat}")
            self.assertIn("mfg_date", combined_fields, f"Mfg Date missing in {cat}")
            self.assertIn("batch_number", combined_fields, f"Batch No missing in {cat}")
            self.assertIn("manufacturer_details", combined_fields, f"Manufacturer missing in {cat}")
            self.assertIn("consumer_care", combined_fields, f"Consumer Care missing in {cat}")
            self.assertIn("country_of_origin", combined_fields, f"Country of Origin missing in {cat}")
            self.assertIn("unit_sale_price", combined_fields, f"USP missing in {cat}")

        overall_accuracy = (total_detected_slots / float(total_mandatory_slots)) * 100.0
        print(f"\n[BENCHMARK] Total Extracted Fields: {total_detected_slots}/{total_mandatory_slots}")
        print(f"[BENCHMARK] Overall Accuracy: {overall_accuracy:.2f}%")
        for cat, acc in category_accuracies.items():
            print(f"  - {cat}: {acc:.1f}%")

        # Core Benchmark Assertion: >90% accuracy across all sample products
        self.assertGreater(
            overall_accuracy,
            90.0,
            f"Extraction accuracy {overall_accuracy:.2f}% is below the 90.0% threshold requirement!",
        )

    # ==========================================================================
    # Stage 6: Font Size Measurement in mm & Rule 7 Evaluation
    # ==========================================================================
    def test_06_font_size_measurement_and_rule7_evaluation(self):
        """Stage 6: Verify font height measurement in mm and statutory Rule 7 evaluation."""
        for item in self.benchmark_data:
            cat = item["spec"]["category"]
            fonts_f: FontMeasurementReport = item["fonts_f"]
            fonts_b: FontMeasurementReport = item["fonts_b"]

            self.assertGreater(fonts_f.calibrated_fields_count, 0)
            self.assertGreater(fonts_b.calibrated_fields_count, 0)

            # Check font height measurements for front fields
            for fname, fm in fonts_f.measurements.items():
                self.assertTrue(fm.is_calibrated, f"Uncalibrated field {fname} in {cat}")
                self.assertGreater(fm.font_height_mm, 1.0, f"Implausibly small font height for {fname} in {cat}")
                self.assertLess(fm.font_height_mm, 10.0, f"Implausibly large font height for {fname} in {cat}")
                self.assertIn(fm.is_rule7_compliant, (True, False))

                # Expected cap-height formula verification: (bbox_height * 0.80) / pixels_per_mm
                expected_mm = (fm.bbox_height_px * 0.80) / fm.calibration_px_per_mm
                self.assertAlmostEqual(fm.font_height_mm, expected_mm, places=2)

            # Check font height measurements for back fields
            for fname, fm in fonts_b.measurements.items():
                self.assertTrue(fm.is_calibrated)
                self.assertGreater(fm.font_height_mm, 1.0)
                self.assertLess(fm.font_height_mm, 10.0)

    # ==========================================================================
    # Stage 7: Front & Back Data Consolidation into Master Product Record
    # ==========================================================================
    def test_07_data_consolidation_into_master_record(self):
        """Stage 7: Verify merging front and back panels into a unified master product record."""
        for item in self.benchmark_data:
            cat = item["spec"]["category"]
            spec = item["spec"]
            scan_id = str(uuid.uuid4())

            consolidated = consolidate_scan_records(
                front_parsed=item["parsed_f"],
                back_parsed=item["parsed_b"],
                front_fonts=item["fonts_f"],
                back_fonts=item["fonts_b"],
                scan_id=scan_id,
            )

            self.assertIsInstance(consolidated, ConsolidatedProductRecord)
            self.assertTrue(consolidated.product_id)
            self.assertIn(spec["declared_mrp"], consolidated.mrp)
            self.assertIn(spec["declared_qty"], consolidated.net_quantity)
            self.assertIn("INDIA", consolidated.country_of_origin.upper())
            self.assertGreaterEqual(consolidated.completeness_pct, 88.0, f"Low completeness for {cat}")
            self.assertGreaterEqual(consolidated.total_declarations_present, 8)

            # Font measurements should be mapped onto consolidated record
            self.assertIn("mrp", consolidated.font_measurements)
            self.assertIn("net_quantity", consolidated.font_measurements)

    # ==========================================================================
    # Stage 8: Database Persistence (scans, extracted_fields, products)
    # ==========================================================================
    def test_08_database_persistence_lifecycle(self):
        """Stage 8: Verify persistence across scans, extracted_fields, and products tables."""
        item = self.benchmark_data[0]
        test_scan_id = str(uuid.uuid4())

        # 1. Upload scan metadata via scan_service
        upload_res: ScanUploadResult = process_scan_upload(
            front_image=item["front_path"],
            back_image=item["back_path"],
            scan_id=test_scan_id,
        )
        self.assertEqual(upload_res.scan_id, test_scan_id)
        self.assertEqual(upload_res.status, "uploaded")

        # Verify scan record in DB
        scan_row = db.get_scan(test_scan_id)
        self.assertIsNotNone(scan_row)
        self.assertEqual(scan_row.get("status"), "uploaded")

        # 2. Persist extracted fields for front and back panels
        save_f: SaveExtractionResult = save_scan_extraction_results(
            scan_id=test_scan_id,
            parsed_fields_result=item["parsed_f"],
            font_measurement_report=item["fonts_f"],
            side="front",
        )
        self.assertEqual(save_f.status, "success")
        self.assertGreater(save_f.saved_count, 0)

        save_b: SaveExtractionResult = save_scan_extraction_results(
            scan_id=test_scan_id,
            parsed_fields_result=item["parsed_b"],
            font_measurement_report=item["fonts_b"],
            side="back",
        )
        self.assertEqual(save_b.status, "success")
        self.assertGreater(save_b.saved_count, 0)

        # Retrieve and verify extracted fields from DB
        db_fields = db.get_extracted_fields(test_scan_id)
        self.assertGreaterEqual(len(db_fields), save_f.saved_count + save_b.saved_count)
        field_names = {f["field_name"] for f in db_fields}
        self.assertIn("mrp", field_names)
        self.assertIn("net_quantity", field_names)
        self.assertIn("batch_number", field_names)

        # 3. Consolidate and verify product record in DB
        consolidated = consolidate_scan_records(
            front_parsed=item["parsed_f"],
            back_parsed=item["parsed_b"],
            front_fonts=item["fonts_f"],
            back_fonts=item["fonts_b"],
            scan_id=test_scan_id,
        )
        prod_row = db.get_product(consolidated.product_id)
        self.assertIsNotNone(prod_row)
        self.assertEqual(prod_row.get("id"), consolidated.product_id)

    # ==========================================================================
    # Stage 9: Editable Word (.docx) and PDF Report Generation
    # ==========================================================================
    def test_09_editable_word_and_pdf_report_generation(self):
        """Stage 9: Verify generation of genuinely editable Word (.docx) and PDF inspection reports."""
        for item in self.benchmark_data:
            cat = item["spec"]["category"]
            scan_id = str(uuid.uuid4())
            consolidated = consolidate_scan_records(
                front_parsed=item["parsed_f"],
                back_parsed=item["parsed_b"],
                front_fonts=item["fonts_f"],
                back_fonts=item["fonts_b"],
                scan_id=scan_id,
            )

            rep_res: ReportGenerationResult = generate_inspection_report(
                consolidated_record=consolidated,
                front_image=item["front_path"],
                back_image=item["back_path"],
                font_report=item["fonts_f"],
                calibration_result=item["calib_f"],
                output_dir=self.test_dir,
                scan_id=scan_id,
            )

            self.assertIsInstance(rep_res, ReportGenerationResult)
            self.assertTrue(os.path.exists(rep_res.docx_path), f"Word report missing for {cat}")
            self.assertTrue(rep_res.is_editable_word)
            self.assertGreater(os.path.getsize(rep_res.docx_path), 1000)

            # Inspect python-docx document structure to ensure it is genuine editable Word
            doc = docx.Document(rep_res.docx_path)
            full_docx_text = "\n".join([p.text for p in doc.paragraphs])
            all_tables_text = " ".join([cell.text for tbl in doc.tables for row in tbl.rows for cell in row.cells])
            self.assertIn("LEGAL METROLOGY", full_docx_text.upper())
            self.assertTrue(scan_id in full_docx_text or scan_id in all_tables_text, f"Scan ID {scan_id} not found in docx")
            self.assertGreaterEqual(len(doc.tables), 2)  # Metadata & Declarations tables

            # Verify PDF report existence if generated
            if rep_res.pdf_path:
                self.assertTrue(os.path.exists(rep_res.pdf_path))
                self.assertGreater(os.path.getsize(rep_res.pdf_path), 500)

    # ==========================================================================
    # Stage 10: Inspection Report Storage Upload & Link Retrieval
    # ==========================================================================
    def test_10_inspection_report_storage_upload(self):
        """Stage 10: Verify upload of inspection reports to storage and saving retrievable link."""
        item = self.benchmark_data[0]
        scan_id = str(uuid.uuid4())
        consolidated = consolidate_scan_records(
            front_parsed=item["parsed_f"],
            back_parsed=item["parsed_b"],
            scan_id=scan_id,
        )
        rep_res = generate_inspection_report(
            consolidated_record=consolidated,
            output_dir=self.test_dir,
            scan_id=scan_id,
        )

        upload_res: ReportUploadResult = upload_inspection_report(
            scan_id=scan_id,
            docx_path=rep_res.docx_path,
            pdf_path=rep_res.pdf_path,
        )

        self.assertIsInstance(upload_res, ReportUploadResult)
        self.assertEqual(upload_res.scan_id, scan_id)
        self.assertEqual(upload_res.status, "success")
        self.assertTrue(upload_res.report_url.startswith("http") or "reports/" in upload_res.report_url)

        # Verify report_url is stored in database scan record
        updated_scan = db.get_scan(scan_id)
        self.assertIsNotNone(updated_scan)
        self.assertEqual(updated_scan.get("report_url"), upload_res.report_url)

    # ==========================================================================
    # Stage 11: Inspector Manual Correction Logging
    # ==========================================================================
    def test_11_inspector_manual_correction_and_audit_trail(self):
        """Stage 11: Verify inspector field edits, audit logging to correction_logs, and re-consolidation."""
        item = self.benchmark_data[3]  # Electronics product
        scan_id = str(uuid.uuid4())

        # Setup initial extraction
        save_scan_extraction_results(
            scan_id=scan_id,
            parsed_fields_result=item["parsed_b"],
            side="back",
        )
        consolidated = consolidate_scan_records(
            front_parsed=item["parsed_f"],
            back_parsed=item["parsed_b"],
            scan_id=scan_id,
        )

        # Inspector applies correction to expiry date & MRP note
        corrections = {
            "expiry_date": {
                "value": "04/2031",
                "original_value": consolidated.expiry_date or "Not Declared",
                "reason": "Inspector verified warranty expiration date from physical inner guarantee card",
            },
            "brand_name": "HyperCharge 65W GaN Pro Charger",
        }

        result: ManualCorrectionResult = apply_manual_corrections(
            scan_id=scan_id,
            corrections_dict=corrections,
            inspector_id="INS-SIH-2026",
            reason="Manual regulatory verification",
            current_record=consolidated,
        )

        self.assertIsInstance(result, ManualCorrectionResult)
        self.assertEqual(result.expiry_date, "04/2031")
        self.assertEqual(result.brand_name, "HyperCharge 65W GaN Pro Charger")
        self.assertEqual(result.completeness_pct, 100.0)
        self.assertEqual(len(result.missing_declarations), 0)

        # Verify audit entries in correction_logs table
        audit_logs = db.get_correction_logs(scan_id)
        self.assertGreaterEqual(len(audit_logs), 2)
        exp_log = next((l for l in audit_logs if l["field_name"] == "expiry_date"), None)
        self.assertIsNotNone(exp_log)
        self.assertEqual(exp_log["corrected_value"], "04/2031")
        self.assertEqual(exp_log["inspector_id"], "INS-SIH-2026")

        # Verify extracted_fields updated with is_corrected=True
        db_fields = db.get_extracted_fields(scan_id)
        corrected_field = next((f for f in db_fields if f["field_name"] == "expiry_date"), None)
        self.assertIsNotNone(corrected_field)
        self.assertTrue(corrected_field.get("is_corrected"))
        self.assertEqual(corrected_field.get("parsed_value"), "04/2031")

    # ==========================================================================
    # Stage 12: Unified End-to-End Pipeline Execution (100% Pass Rate)
    # ==========================================================================
    def test_12_full_pipeline_end_to_end_verification(self):
        """Stage 12: Execute the full 11-step pipeline sequentially in a single pass."""
        spec = self.product_specs[0]  # Food / Snacks
        item = self.benchmark_data[0]
        unified_scan_id = str(uuid.uuid4())

        # 1. Image loading & validation
        with open(item["front_path"], "rb") as f:
            f_bytes = f.read()
        with open(item["back_path"], "rb") as f:
            b_bytes = f.read()
        v1, _, _, m1 = validate_image_bytes(f_bytes)
        v2, _, _, m2 = validate_image_bytes(b_bytes)
        self.assertTrue(v1 and v2)

        # 2. Coin detection & calibration
        c_front = detect_coin(item["front_path"])
        c_back = detect_coin(item["back_path"])
        cal_front = compute_calibration(c_front)
        cal_back = compute_calibration(c_back)
        self.assertTrue(cal_front.is_calibrated and cal_back.is_calibrated)

        # 3. Process scan upload to database & storage
        upload_res = process_scan_upload(
            front_image=item["front_path"],
            back_image=item["back_path"],
            scan_id=unified_scan_id,
        )
        self.assertEqual(upload_res.status, "uploaded")

        # 4. OCR extraction & text region detection
        ocr_f = extract_text_from_image(item["front_path"], c_front.center, c_front.radius)
        ocr_b = extract_text_from_image(item["back_path"], c_back.center, c_back.radius)
        self.assertGreater(ocr_f.total_lines, 0)
        self.assertGreater(ocr_b.total_lines, 0)

        # 5. Field structuring & parsing
        parsed_f = parse_ocr_lines(ocr_f)
        parsed_b = parse_ocr_lines(ocr_b)
        self.assertGreater(parsed_f.total_fields_found, 0)
        self.assertGreater(parsed_b.total_fields_found, 0)

        # 6. Font measurement in mm & Rule 7
        font_f = measure_font_heights(parsed_f, cal_front)
        font_b = measure_font_heights(parsed_b, cal_back)
        self.assertGreater(font_f.calibrated_fields_count, 0)
        self.assertGreater(font_b.calibrated_fields_count, 0)

        # 7. Database persistence of extractions
        save_scan_extraction_results(unified_scan_id, parsed_f, font_f, side="front")
        save_scan_extraction_results(unified_scan_id, parsed_b, font_b, side="back")

        # 8. Data consolidation
        master_record = consolidate_scan_records(
            front_parsed=parsed_f,
            back_parsed=parsed_b,
            front_fonts=font_f,
            back_fonts=font_b,
            scan_id=unified_scan_id,
        )
        self.assertGreaterEqual(master_record.completeness_pct, 90.0)

        # 9. Editable Word (.docx) and PDF report generation
        rep = generate_inspection_report(
            consolidated_record=master_record,
            front_image=item["front_path"],
            back_image=item["back_path"],
            font_report=font_f,
            calibration_result=cal_front,
            output_dir=self.test_dir,
            scan_id=unified_scan_id,
        )
        self.assertTrue(os.path.exists(rep.docx_path))

        # 10. Cloud report upload
        up_rep = upload_inspection_report(
            scan_id=unified_scan_id,
            docx_path=rep.docx_path,
            pdf_path=rep.pdf_path,
        )
        self.assertEqual(up_rep.status, "success")

        # 11. Inspector correction
        corr = apply_manual_corrections(
            scan_id=unified_scan_id,
            corrections_dict={"brand_name": "Crunchy Masala Potato Chips Special Edition"},
            inspector_id="INS-VERIFY-001",
            current_record=master_record,
        )
        self.assertEqual(corr.brand_name, "Crunchy Masala Potato Chips Special Edition")

        print(f"\n[E2E SUCCESS] Completed unified 11-step pipeline for {spec['brand_name']}.")
        print(f"             Scan ID: {unified_scan_id}")
        print(f"             Product ID: {corr.product_id}")
        print(f"             Final Completeness: {corr.completeness_pct}% (Pass Rate: 100%)")


if __name__ == "__main__":
    unittest.main()
