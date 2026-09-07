"""Test suite for Task 11: Store Extraction Results in Supabase.

Verifies:
1. save_scan_extraction_results function:
   - Persisting ParsedFieldsResult object with multiple fields.
   - Merging font measurement values (font_height_mm, is_rule7_compliant).
   - Calling db.save_extracted_fields(scan_id, fields_data) and inserting into extracted_fields table.
   - Updating scan status in scans table to 'processed'.
   - Returning SaveExtractionResult with status, saved_count, scan_id, and fields.
   - Tuple unpacking (status, count = save_scan_extraction_results(...)).
2. Database retrieval via db.get_extracted_fields(scan_id):
   - Asserting field_name, raw_text, parsed_value, bounding_box, font_height_px, font_height_mm,
     confidence, and is_rule7_compliant.
   - Filtering by side ('front', 'back').
3. Polymorphic input support:
   - Dictionary of fields representation.
   - Uncalibrated / None font measurement report fallback.
   - Upsert / deduplication when re-persisting fields for the same scan & side.
4. Streamlit App Integration:
   - AppTest execution verifying automated persistence invocation and rendering of the
     persistence confirmation badge (e.g. '💾 Saved 8 fields to Supabase').
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from typing import Any, Dict, List

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import db
from src.field_parser import ExtractedField, ParsedFieldsResult
from src.font_measurement import FontMeasurement, FontMeasurementReport
from src.scan_service import (
    SaveExtractionResult,
    save_scan_extraction_results,
)


class TestTask11Persistence(unittest.TestCase):
    """Automated test cases for Task 11 extraction persistence and retrieval."""

    def setUp(self):
        """Prepare sample parsed fields and font measurements."""
        self.sample_fields = {
            "mrp": ExtractedField(
                field_name="mrp",
                raw_text="M.R.P. Rs. 150.00 (Incl. of all taxes)",
                extracted_value="150.00",
                unit=None,
                confidence=0.98,
                line_number=0,
                bbox=[20, 30, 180, 70],
                height_px=40.0,
                is_mandatory=True,
            ),
            "net_quantity": ExtractedField(
                field_name="net_quantity",
                raw_text="Net Qty: 400 g",
                extracted_value="400",
                unit="g",
                confidence=0.99,
                line_number=1,
                bbox=[20, 80, 160, 120],
                height_px=40.0,
                is_mandatory=True,
            ),
            "mfg_date": ExtractedField(
                field_name="mfg_date",
                raw_text="MFG DATE: 08/2026",
                extracted_value="08/2026",
                unit=None,
                confidence=0.95,
                line_number=2,
                bbox=[20, 130, 150, 160],
                height_px=30.0,
                is_mandatory=True,
            ),
            "batch_number": ExtractedField(
                field_name="batch_number",
                raw_text="BATCH NO: ONH-26-0812",
                extracted_value="ONH-26-0812",
                unit=None,
                confidence=0.96,
                line_number=3,
                bbox=[20, 170, 190, 195],
                height_px=25.0,
                is_mandatory=True,
            ),
            "consumer_care": ExtractedField(
                field_name="consumer_care",
                raw_text="Consumer Care: 1800-425-9000",
                extracted_value="1800-425-9000",
                unit=None,
                confidence=0.94,
                line_number=4,
                bbox=[20, 205, 220, 230],
                height_px=25.0,
                is_mandatory=True,
            ),
            "country_of_origin": ExtractedField(
                field_name="country_of_origin",
                raw_text="Country of Origin: India",
                extracted_value="India",
                unit=None,
                confidence=0.97,
                line_number=5,
                bbox=[20, 240, 170, 265],
                height_px=25.0,
                is_mandatory=True,
            ),
            "unit_sale_price": ExtractedField(
                field_name="unit_sale_price",
                raw_text="USP: Rs. 0.375 / g",
                extracted_value="0.375 / g",
                unit=None,
                confidence=0.93,
                line_number=6,
                bbox=[20, 275, 160, 300],
                height_px=25.0,
                is_mandatory=True,
            ),
            "manufacturer_details": ExtractedField(
                field_name="manufacturer_details",
                raw_text="Mfd by: Nature Pure Foods Ltd, Vadodara, Gujarat",
                extracted_value="Nature Pure Foods Ltd, Vadodara, Gujarat",
                unit=None,
                confidence=0.92,
                line_number=7,
                bbox=[20, 310, 350, 340],
                height_px=30.0,
                is_mandatory=True,
            ),
        }

        self.parsed_result = ParsedFieldsResult(
            fields=self.sample_fields,
            missing_mandatory_fields=["expiry_date"],
            total_fields_found=8,
            overall_confidence=0.955,
        )

        # Corresponding font measurements with calibration (e.g. 10.0 px/mm)
        self.font_measurements = {
            "mrp": FontMeasurement(
                field_name="mrp",
                raw_text=self.sample_fields["mrp"].raw_text,
                bbox_height_px=40.0,
                cap_height_px=32.0,
                font_height_mm=3.20,
                calibration_px_per_mm=10.0,
                is_calibrated=True,
                measurement_method="hough_circle_calibration",
                rule7_min_height_mm=1.0,
                is_rule7_compliant=True,
                status="PASS",
            ),
            "net_quantity": FontMeasurement(
                field_name="net_quantity",
                raw_text=self.sample_fields["net_quantity"].raw_text,
                bbox_height_px=40.0,
                cap_height_px=32.0,
                font_height_mm=3.20,
                calibration_px_per_mm=10.0,
                is_calibrated=True,
                measurement_method="hough_circle_calibration",
                rule7_min_height_mm=4.0,  # 400g requires 4.0mm
                is_rule7_compliant=False,  # 3.20 < 4.0 -> Non-compliant
                status="DEFICIT",
            ),
            "mfg_date": FontMeasurement(
                field_name="mfg_date",
                raw_text=self.sample_fields["mfg_date"].raw_text,
                bbox_height_px=30.0,
                cap_height_px=24.0,
                font_height_mm=2.40,
                calibration_px_per_mm=10.0,
                is_calibrated=True,
                measurement_method="hough_circle_calibration",
                rule7_min_height_mm=1.0,
                is_rule7_compliant=True,
                status="PASS",
            ),
            "batch_number": FontMeasurement(
                field_name="batch_number",
                raw_text=self.sample_fields["batch_number"].raw_text,
                bbox_height_px=25.0,
                cap_height_px=20.0,
                font_height_mm=2.00,
                calibration_px_per_mm=10.0,
                is_calibrated=True,
                measurement_method="hough_circle_calibration",
                rule7_min_height_mm=1.0,
                is_rule7_compliant=True,
                status="PASS",
            ),
            "consumer_care": FontMeasurement(
                field_name="consumer_care",
                raw_text=self.sample_fields["consumer_care"].raw_text,
                bbox_height_px=25.0,
                cap_height_px=20.0,
                font_height_mm=2.00,
                calibration_px_per_mm=10.0,
                is_calibrated=True,
                measurement_method="hough_circle_calibration",
                rule7_min_height_mm=1.0,
                is_rule7_compliant=True,
                status="PASS",
            ),
            "country_of_origin": FontMeasurement(
                field_name="country_of_origin",
                raw_text=self.sample_fields["country_of_origin"].raw_text,
                bbox_height_px=25.0,
                cap_height_px=20.0,
                font_height_mm=2.00,
                calibration_px_per_mm=10.0,
                is_calibrated=True,
                measurement_method="hough_circle_calibration",
                rule7_min_height_mm=1.0,
                is_rule7_compliant=True,
                status="PASS",
            ),
            "unit_sale_price": FontMeasurement(
                field_name="unit_sale_price",
                raw_text=self.sample_fields["unit_sale_price"].raw_text,
                bbox_height_px=25.0,
                cap_height_px=20.0,
                font_height_mm=2.00,
                calibration_px_per_mm=10.0,
                is_calibrated=True,
                measurement_method="hough_circle_calibration",
                rule7_min_height_mm=1.0,
                is_rule7_compliant=True,
                status="PASS",
            ),
            "manufacturer_details": FontMeasurement(
                field_name="manufacturer_details",
                raw_text=self.sample_fields["manufacturer_details"].raw_text,
                bbox_height_px=30.0,
                cap_height_px=24.0,
                font_height_mm=2.40,
                calibration_px_per_mm=10.0,
                is_calibrated=True,
                measurement_method="hough_circle_calibration",
                rule7_min_height_mm=1.0,
                is_rule7_compliant=True,
                status="PASS",
            ),
        }

        self.font_report = FontMeasurementReport(
            measurements=self.font_measurements,
            calibrated_fields_count=8,
            calibration_ratio_used=10.0,
            summary="8/8 declarations calibrated",
            compliant_fields_count=7,
            non_compliant_fields_count=1,
        )

    def test_save_scan_extraction_results_success(self):
        """Test full save_scan_extraction_results workflow with ParsedFieldsResult and FontMeasurementReport."""
        scan_id = str(uuid.uuid4())
        # Create scan record in DB
        db.create_scan({"id": scan_id, "scan_id": scan_id, "status": "uploaded"})

        # Persist results
        res = save_scan_extraction_results(
            scan_id=scan_id,
            parsed_fields_result=self.parsed_result,
            font_measurement_report=self.font_report,
            side="front",
        )

        # 1. Assert result object properties
        self.assertIsInstance(res, SaveExtractionResult)
        self.assertEqual(res.status, "success")
        self.assertEqual(res.saved_count, 8)
        self.assertEqual(res.scan_id, scan_id)
        self.assertEqual(res.side, "front")
        self.assertTrue(res.success)
        self.assertIn("Saved 8 fields", res.message)

        # 2. Assert tuple unpacking behavior
        status, count = res
        self.assertEqual(status, "success")
        self.assertEqual(count, 8)

        # 3. Assert scan record status updated to 'processed'
        updated_scan = db.get_scan(scan_id)
        self.assertIsNotNone(updated_scan)
        self.assertEqual(updated_scan.get("status"), "processed")

        # 4. Query extracted fields from database
        stored_fields = db.get_extracted_fields(scan_id, side="front")
        self.assertEqual(len(stored_fields), 8)

        fields_by_name = {f["field_name"]: f for f in stored_fields}

        # Check MRP field
        mrp_rec = fields_by_name["mrp"]
        self.assertEqual(mrp_rec["scan_id"], scan_id)
        self.assertEqual(mrp_rec["side"], "front")
        self.assertEqual(mrp_rec["raw_text"], "M.R.P. Rs. 150.00 (Incl. of all taxes)")
        self.assertEqual(mrp_rec["parsed_value"], "150.00")
        self.assertEqual(mrp_rec["bounding_box"], [20, 30, 180, 70])
        self.assertEqual(mrp_rec["font_height_px"], 40.0)
        self.assertEqual(mrp_rec["font_height_mm"], 3.20)
        self.assertEqual(mrp_rec["confidence"], 0.98)
        self.assertTrue(mrp_rec["is_rule7_compliant"])
        self.assertFalse(mrp_rec["is_corrected"])

        # Check Net Quantity field with unit and deficit rule 7 status
        net_qty_rec = fields_by_name["net_quantity"]
        self.assertEqual(net_qty_rec["parsed_value"], "400 g")
        self.assertEqual(net_qty_rec["font_height_mm"], 3.20)
        self.assertFalse(net_qty_rec["is_rule7_compliant"])
        self.assertEqual(net_qty_rec["confidence"], 0.99)
        self.assertEqual(net_qty_rec["bounding_box"], [20, 80, 160, 120])

        # Check all mandatory fields exist
        expected_fields = [
            "mrp", "net_quantity", "mfg_date", "batch_number",
            "consumer_care", "country_of_origin", "unit_sale_price", "manufacturer_details",
        ]
        for ef in expected_fields:
            self.assertIn(ef, fields_by_name)
            f = fields_by_name[ef]
            self.assertIsNotNone(f["bounding_box"])
            self.assertGreater(f["confidence"], 0.90)
            self.assertGreater(f["font_height_mm"], 0.0)

    def test_persistence_with_dictionary_input(self):
        """Test save_scan_extraction_results when parsed_fields_result is a plain dictionary."""
        scan_id = str(uuid.uuid4())
        dict_fields = {
            "mrp": {
                "raw_text": "MRP: Rs. 99.00",
                "extracted_value": "99.00",
                "confidence": 0.95,
                "bbox": [10, 10, 100, 35],
                "height_px": 25.0,
            },
            "net_quantity": {
                "raw_text": "Net Wt: 200g",
                "extracted_value": "200",
                "unit": "g",
                "confidence": 0.97,
                "bbox": [10, 40, 100, 70],
                "height_px": 30.0,
            },
        }
        dict_measurements = {
            "mrp": {"font_height_mm": 2.50, "is_rule7_compliant": True, "bbox_height_px": 25.0},
            "net_quantity": {"font_height_mm": 3.00, "is_rule7_compliant": True, "bbox_height_px": 30.0},
        }

        res = save_scan_extraction_results(
            scan_id=scan_id,
            parsed_fields_result=dict_fields,
            font_measurement_report=dict_measurements,
            side="back",
        )

        self.assertEqual(res.status, "success")
        self.assertEqual(res.saved_count, 2)
        self.assertEqual(res.side, "back")

        # Verify DB records
        records = db.get_extracted_fields(scan_id, side="back")
        self.assertEqual(len(records), 2)
        rec_dict = {r["field_name"]: r for r in records}
        self.assertEqual(rec_dict["mrp"]["parsed_value"], "99.00")
        self.assertEqual(rec_dict["mrp"]["font_height_mm"], 2.50)
        self.assertEqual(rec_dict["net_quantity"]["parsed_value"], "200 g")
        self.assertEqual(rec_dict["net_quantity"]["font_height_mm"], 3.00)

    def test_side_filtering(self):
        """Test saving fields for both 'front' and 'back' and querying with side filter."""
        scan_id = str(uuid.uuid4())
        front_fields = {
            "mrp": {"raw_text": "MRP Rs 50", "extracted_value": "50", "bbox": [0, 0, 50, 20]}
        }
        back_fields = {
            "net_quantity": {"raw_text": "Net: 100ml", "extracted_value": "100", "unit": "ml", "bbox": [0, 0, 50, 20]},
            "manufacturer_details": {"raw_text": "ABC Ltd", "extracted_value": "ABC Ltd", "bbox": [0, 0, 50, 20]},
        }

        save_scan_extraction_results(scan_id, front_fields, side="front")
        save_scan_extraction_results(scan_id, back_fields, side="back")

        front_stored = db.get_extracted_fields(scan_id, side="front")
        back_stored = db.get_extracted_fields(scan_id, side="back")
        all_stored = db.get_extracted_fields(scan_id)

        self.assertEqual(len(front_stored), 1)
        self.assertEqual(front_stored[0]["field_name"], "mrp")
        self.assertEqual(len(back_stored), 2)
        self.assertEqual(set(f["field_name"] for f in back_stored), {"net_quantity", "manufacturer_details"})
        self.assertEqual(len(all_stored), 3)

    def test_uncalibrated_or_missing_font_report(self):
        """Test persistence when font_measurement_report is None (uncalibrated scan)."""
        scan_id = str(uuid.uuid4())
        fields = {
            "mrp": ExtractedField(
                field_name="mrp",
                raw_text="M.R.P. Rs. 200",
                extracted_value="200",
                unit=None,
                confidence=0.91,
                line_number=0,
                bbox=[10, 10, 80, 40],
                height_px=30.0,
                is_mandatory=True,
            )
        }
        res = save_scan_extraction_results(
            scan_id=scan_id,
            parsed_fields_result={"fields": fields},
            font_measurement_report=None,
            side="front",
        )
        self.assertEqual(res.status, "success")
        self.assertEqual(res.saved_count, 1)

        stored = db.get_extracted_fields(scan_id, side="front")
        self.assertEqual(len(stored), 1)
        self.assertIsNone(stored[0]["font_height_mm"])
        self.assertIsNone(stored[0]["is_rule7_compliant"])
        self.assertEqual(stored[0]["font_height_px"], 30.0)

    def test_upsert_deduplication(self):
        """Test that re-persisting the same scan and side updates existing records without duplication."""
        scan_id = str(uuid.uuid4())
        fields_initial = {
            "mrp": {"raw_text": "MRP 100", "extracted_value": "100", "confidence": 0.85, "bbox": [0, 0, 10, 10]}
        }
        res1 = save_scan_extraction_results(scan_id, fields_initial, side="front")
        self.assertEqual(res1.saved_count, 1)

        stored1 = db.get_extracted_fields(scan_id, side="front")
        self.assertEqual(len(stored1), 1)
        self.assertEqual(stored1[0]["parsed_value"], "100")
        initial_id = stored1[0]["id"]

        # Re-save with updated parsed value & higher confidence
        fields_updated = {
            "mrp": {"raw_text": "MRP 100.00", "extracted_value": "100.00", "confidence": 0.99, "bbox": [0, 0, 10, 10]}
        }
        res2 = save_scan_extraction_results(scan_id, fields_updated, side="front")
        self.assertEqual(res2.saved_count, 1)

        stored2 = db.get_extracted_fields(scan_id, side="front")
        self.assertEqual(len(stored2), 1, "Duplicate record created instead of upserting")
        self.assertEqual(stored2[0]["id"], initial_id)
        self.assertEqual(stored2[0]["parsed_value"], "100.00")
        self.assertEqual(stored2[0]["confidence"], 0.99)

    def test_empty_or_invalid_scan_id_raises_error(self):
        """Test ValueError is raised when scan_id is missing or empty."""
        with self.assertRaises(ValueError):
            save_scan_extraction_results("", self.parsed_result)
        with self.assertRaises(ValueError):
            save_scan_extraction_results("   ", self.parsed_result)

    def test_polymorphic_db_save_extracted_fields(self):
        """Verify db.save_extracted_fields supports both (scan_id, fields) and (fields) calling conventions."""
        scan_id = str(uuid.uuid4())

        # Convention 1: (scan_id, fields)
        fields1 = [{"field_name": "f1", "parsed_value": "v1", "side": "front"}]
        saved1 = db.save_extracted_fields(scan_id, fields1)
        self.assertEqual(len(saved1), 1)
        self.assertEqual(saved1[0]["scan_id"], scan_id)

        # Convention 2: (fields) where field has scan_id
        scan_id_2 = str(uuid.uuid4())
        fields2 = [{"scan_id": scan_id_2, "field_name": "f2", "parsed_value": "v2", "side": "back"}]
        saved2 = db.save_extracted_fields(fields2)
        self.assertEqual(len(saved2), 1)
        self.assertEqual(saved2[0]["scan_id"], scan_id_2)


def test_streamlit_app_persistence_integration():
    """Verify Streamlit app displays persistence confirmation badge via headless AppTest."""
    print("\n--- Testing Streamlit App Persistence Badge Rendering (AppTest) ---")
    try:
        from streamlit.testing.v1 import AppTest

        app_path = os.path.join(PROJECT_ROOT, "app.py")
        at = AppTest.from_file(app_path, default_timeout=30)
        at.run()

        # Simulate inspection scan result and parsed fields in session_state
        test_scan_id = str(uuid.uuid4())
        at.session_state["current_scan"] = {
            "scan_id": test_scan_id,
            "timestamp": "2026-09-07T12:00:00Z",
            "status": "processed",
            "storage_status": "Offline Mock",
            "is_offline": True,
            "front_image_url": f"mock://product-images/scans/{test_scan_id}/front.png",
            "back_image_url": f"mock://product-images/scans/{test_scan_id}/back.png",
            "dimensions": {"summary": "Front: 800x600 px | Back: 800x600 px"},
        }
        at.session_state["front_persistence"] = SaveExtractionResult(
            status="success",
            saved_count=8,
            scan_id=test_scan_id,
            side="front",
            is_offline=True,
            message="Saved 8 fields to Supabase",
        )

        at.run()
        assert not at.exception, f"Streamlit encountered exception: {at.exception}"

        # Verify persistence badge exists in rendered success alerts or markdown
        success_texts = [s.value for s in at.success]
        markdown_texts = [m.value for m in at.markdown]
        badge_found = any("Saved" in text and "fields to Supabase" in text for text in success_texts) or any(
            "Saved" in text and "fields to Supabase" in text for text in markdown_texts
        )
        assert badge_found, f"Persistence confirmation badge missing from at.success: {success_texts}"
        matched_text = [t for t in success_texts if "Saved" in t and "fields to Supabase" in t]
        print(f"✓ Streamlit persistence confirmation badge rendered: '{matched_text[0]}'")

    except ImportError:
        print("ℹ️ streamlit.testing.v1 not available; skipping AppTest")


if __name__ == "__main__":
    print("============================================================")
    print("STARTING TASK 11 VERIFICATION SUITE")
    print("============================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestTask11Persistence)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    assert result.wasSuccessful(), f"Task 11 unit tests failed: {result.failures or result.errors}"

    test_streamlit_app_persistence_integration()

    print("\n============================================================")
    print("ALL TASK 11 VERIFICATIONS PASSED SUCCESSFULLY!")
    print("============================================================")
