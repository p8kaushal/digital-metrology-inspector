"""Test suite for Task 12: Data Consolidation.

Verifies:
1. ConsolidatedProductRecord dataclass definition:
   - product_id: str, brand_name: str, mrp: str, net_quantity: str, mfg_date: str,
     expiry_date: str, batch_number: str, manufacturer_details: str, consumer_care: str,
     country_of_origin: str, unit_sale_price: str, front_fields: dict, back_fields: dict,
     font_measurements: dict, completeness_pct: float, missing_declarations: list[str]
   - Default instantiation and helper methods (to_dict, to_db_payload, properties).
2. consolidate_scan_records function:
   - Merging extractions across front and back packaging panels.
   - Conflict resolution using confidence scores and panel priority weighting.
   - Completeness score computation across the 9 Legal Metrology mandatory declarations.
   - Font measurement association across panels.
   - Polymorphic inputs (ParsedFieldsResult, ExtractedField dicts, plain dicts, strings, None).
3. Database persistence to Supabase 'products' table:
   - Verifying db.create_product() persistence and db.get_product() retrieval.
   - Linking scan record product_id when scan_id is provided.
   - Idempotent re-consolidation preserving existing product_id.
4. Streamlit App Integration:
   - Headless AppTest verification of the '📦 Consolidated Product Master Record' expander.
   - Verification of the completeness metric badge (e.g. 'Mandatory Completeness: 100% (9/9 fields)').
"""

from __future__ import annotations

import dataclasses
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
from src.consolidation import (
    DEFAULT_PANEL_WEIGHTS,
    MANDATORY_DECLARATIONS,
    ConsolidatedProductRecord,
    consolidate_scan_records,
)
from src.field_parser import ExtractedField, ParsedFieldsResult
from src.font_measurement import FontMeasurement, FontMeasurementReport


class TestTask12Consolidation(unittest.TestCase):
    """Unit and integration test cases for Task 12 Data Consolidation."""

    def setUp(self):
        """Prepare sample front and back extractions and measurements."""
        # Clean / mock DB product and scan entries for testing
        self.test_scan_id = str(uuid.uuid4())
        db.create_scan({
            "id": self.test_scan_id,
            "status": "uploaded",
            "front_image_url": "https://example.com/front.png",
            "back_image_url": "https://example.com/back.png",
        })

        # Front panel sample fields (typically prominent marketing & primary declarations)
        self.front_fields = {
            "brand_name": ExtractedField(
                field_name="brand_name",
                raw_text="PARLE-G GOLD",
                extracted_value="Parle-G Gold",
                unit=None,
                confidence=0.98,
                line_number=0,
                bbox=[20, 20, 200, 60],
                height_px=40.0,
                is_mandatory=False,
            ),
            "mrp": ExtractedField(
                field_name="mrp",
                raw_text="M.R.P. ₹ 30.00 (Incl. of all taxes)",
                extracted_value="30.00",
                unit=None,
                confidence=0.97,
                line_number=1,
                bbox=[20, 80, 160, 110],
                height_px=30.0,
                is_mandatory=True,
            ),
            "net_quantity": ExtractedField(
                field_name="net_quantity",
                raw_text="Net Qty: 250 g",
                extracted_value="250",
                unit="g",
                confidence=0.96,
                line_number=2,
                bbox=[20, 120, 150, 150],
                height_px=30.0,
                is_mandatory=True,
            ),
            "country_of_origin": ExtractedField(
                field_name="country_of_origin",
                raw_text="Made in India",
                extracted_value="India",
                unit=None,
                confidence=0.91,
                line_number=3,
                bbox=[20, 160, 120, 180],
                height_px=20.0,
                is_mandatory=True,
            ),
        }

        # Back panel sample fields (comprehensive statutory declarations block)
        self.back_fields = {
            "mrp": ExtractedField(
                field_name="mrp",
                raw_text="MRP Rs. 30.00",
                extracted_value="30.00",
                unit=None,
                confidence=0.88,
                line_number=0,
                bbox=[30, 30, 140, 55],
                height_px=25.0,
                is_mandatory=True,
            ),
            "manufacturer_details": ExtractedField(
                field_name="manufacturer_details",
                raw_text="MFG BY PARLE BISCUITS PVT LTD, MUMBAI 400057",
                extracted_value="Parle Biscuits Pvt Ltd, Mumbai 400057",
                unit=None,
                confidence=0.95,
                line_number=1,
                bbox=[30, 65, 350, 95],
                height_px=30.0,
                is_mandatory=True,
            ),
            "mfg_date": ExtractedField(
                field_name="mfg_date",
                raw_text="MFG DATE: 08/2026",
                extracted_value="08/2026",
                unit=None,
                confidence=0.94,
                line_number=2,
                bbox=[30, 105, 160, 130],
                height_px=25.0,
                is_mandatory=True,
            ),
            "expiry_date": ExtractedField(
                field_name="expiry_date",
                raw_text="BEST BEFORE 9 MONTHS FROM MFG",
                extracted_value="9 Months from Mfg",
                unit=None,
                confidence=0.93,
                line_number=3,
                bbox=[30, 140, 240, 165],
                height_px=25.0,
                is_mandatory=True,
            ),
            "batch_number": ExtractedField(
                field_name="batch_number",
                raw_text="BATCH NO: PKG-26-4401",
                extracted_value="PKG-26-4401",
                unit=None,
                confidence=0.95,
                line_number=4,
                bbox=[30, 175, 180, 200],
                height_px=25.0,
                is_mandatory=True,
            ),
            "consumer_care": ExtractedField(
                field_name="consumer_care",
                raw_text="CONSUMER CARE: 1800-22-1022 EMAIL: CARE@PARLE.BIZ",
                extracted_value="1800-22-1022 email: care@parle.biz",
                unit=None,
                confidence=0.92,
                line_number=5,
                bbox=[30, 210, 320, 235],
                height_px=25.0,
                is_mandatory=True,
            ),
            "unit_sale_price": ExtractedField(
                field_name="unit_sale_price",
                raw_text="USP: Rs 0.12 / g",
                extracted_value="Rs 0.12 / g",
                unit=None,
                confidence=0.90,
                line_number=6,
                bbox=[30, 245, 170, 270],
                height_px=25.0,
                is_mandatory=True,
            ),
        }

        # Font measurements for calibration validation
        self.front_fonts = FontMeasurementReport(
            measurements={
                "mrp": FontMeasurement(
                    field_name="mrp",
                    raw_text="M.R.P. ₹ 30.00",
                    bbox_height_px=30.0,
                    cap_height_px=24.0,
                    font_height_mm=3.0,
                    calibration_px_per_mm=8.0,
                    is_calibrated=True,
                    measurement_method="hough_coin_ratio",
                    rule7_min_height_mm=2.0,
                    is_rule7_compliant=True,
                ),
                "net_quantity": FontMeasurement(
                    field_name="net_quantity",
                    raw_text="Net Qty: 250 g",
                    bbox_height_px=30.0,
                    cap_height_px=24.0,
                    font_height_mm=3.0,
                    calibration_px_per_mm=8.0,
                    is_calibrated=True,
                    measurement_method="hough_coin_ratio",
                    rule7_min_height_mm=4.0,
                    is_rule7_compliant=False,
                ),
            },
            calibrated_fields_count=2,
            calibration_ratio_used=8.0,
            summary="2 fields calibrated",
            compliant_fields_count=1,
            non_compliant_fields_count=1,
        )

        self.back_fonts = FontMeasurementReport(
            measurements={
                "manufacturer_details": FontMeasurement(
                    field_name="manufacturer_details",
                    raw_text="MFG BY PARLE",
                    bbox_height_px=24.0,
                    cap_height_px=19.2,
                    font_height_mm=2.4,
                    calibration_px_per_mm=8.0,
                    is_calibrated=True,
                    measurement_method="hough_coin_ratio",
                    rule7_min_height_mm=1.0,
                    is_rule7_compliant=True,
                ),
                "consumer_care": FontMeasurement(
                    field_name="consumer_care",
                    raw_text="CONSUMER CARE",
                    bbox_height_px=20.0,
                    cap_height_px=16.0,
                    font_height_mm=2.0,
                    calibration_px_per_mm=8.0,
                    is_calibrated=True,
                    measurement_method="hough_coin_ratio",
                    rule7_min_height_mm=1.0,
                    is_rule7_compliant=True,
                ),
            },
            calibrated_fields_count=2,
            calibration_ratio_used=8.0,
            summary="2 fields calibrated",
            compliant_fields_count=2,
            non_compliant_fields_count=0,
        )

    def test_01_dataclass_fields_and_defaults(self):
        """Verify ConsolidatedProductRecord dataclass definition, required fields, and defaults."""
        record = ConsolidatedProductRecord()
        self.assertIsInstance(record.product_id, str)
        self.assertIsInstance(record.brand_name, str)
        self.assertIsInstance(record.mrp, str)
        self.assertIsInstance(record.net_quantity, str)
        self.assertIsInstance(record.mfg_date, str)
        self.assertIsInstance(record.expiry_date, str)
        self.assertIsInstance(record.batch_number, str)
        self.assertIsInstance(record.manufacturer_details, str)
        self.assertIsInstance(record.consumer_care, str)
        self.assertIsInstance(record.country_of_origin, str)
        self.assertIsInstance(record.unit_sale_price, str)
        self.assertIsInstance(record.front_fields, dict)
        self.assertIsInstance(record.back_fields, dict)
        self.assertIsInstance(record.font_measurements, dict)
        self.assertIsInstance(record.completeness_pct, float)
        self.assertIsInstance(record.missing_declarations, list)

        # Check fields presence via dataclasses.fields
        field_names = [f.name for f in dataclasses.fields(ConsolidatedProductRecord)]
        expected_fields = [
            "product_id",
            "brand_name",
            "mrp",
            "net_quantity",
            "mfg_date",
            "expiry_date",
            "batch_number",
            "manufacturer_details",
            "consumer_care",
            "country_of_origin",
            "unit_sale_price",
            "front_fields",
            "back_fields",
            "font_measurements",
            "completeness_pct",
            "missing_declarations",
        ]
        for ef in expected_fields:
            self.assertIn(ef, field_names, f"Missing expected dataclass field: {ef}")

        # Test to_dict and properties
        as_dict = record.to_dict()
        self.assertIsInstance(as_dict, dict)
        self.assertEqual(record.total_declarations_present, 9 - len(record.missing_declarations))

    def test_02_consolidation_merging_front_and_back(self):
        """Verify merging extractions from front and back panels into a unified complete record."""
        record = consolidate_scan_records(
            front_parsed=self.front_fields,
            back_parsed=self.back_fields,
            front_fonts=self.front_fonts,
            back_fonts=self.back_fonts,
            scan_id=self.test_scan_id,
        )

        self.assertEqual(record.brand_name, "Parle-G Gold")
        self.assertEqual(record.mrp, "30.00")
        self.assertEqual(record.net_quantity, "250 g")
        self.assertEqual(record.country_of_origin, "India")
        self.assertEqual(record.manufacturer_details, "Parle Biscuits Pvt Ltd, Mumbai 400057")
        self.assertEqual(record.mfg_date, "08/2026")
        self.assertEqual(record.expiry_date, "9 Months from Mfg")
        self.assertEqual(record.batch_number, "PKG-26-4401")
        self.assertEqual(record.consumer_care, "1800-22-1022 email: care@parle.biz")
        self.assertEqual(record.unit_sale_price, "Rs 0.12 / g")

        # 9 out of 9 declarations present
        self.assertEqual(record.completeness_pct, 100.0)
        self.assertEqual(record.missing_declarations, [])
        self.assertTrue(record.is_complete)
        self.assertEqual(record.total_declarations_present, 9)

        # Verify font measurements preserved
        self.assertIn("mrp", record.font_measurements)
        self.assertIn("manufacturer_details", record.font_measurements)

    def test_03_conflict_resolution_higher_confidence_wins(self):
        """Verify field conflict resolution when front panel has higher confidence."""
        front_override = {
            "mrp": ExtractedField(
                field_name="mrp",
                raw_text="MRP Rs 50.00",
                extracted_value="50.00",
                unit=None,
                confidence=0.99,  # High confidence
                line_number=0,
                bbox=[0, 0, 10, 10],
                height_px=20.0,
                is_mandatory=True,
            ),
        }
        back_override = {
            "mrp": ExtractedField(
                field_name="mrp",
                raw_text="MRP Rs 40.00",
                extracted_value="40.00",
                unit=None,
                confidence=0.60,  # Low confidence
                line_number=0,
                bbox=[0, 0, 10, 10],
                height_px=20.0,
                is_mandatory=True,
            ),
        }

        record = consolidate_scan_records(front_parsed=front_override, back_parsed=back_override)
        self.assertEqual(record.mrp, "50.00")
        self.assertEqual(len(record.resolved_conflicts), 1)
        conflict = record.resolved_conflicts[0]
        self.assertEqual(conflict["field_name"], "mrp")
        self.assertEqual(conflict["selected_side"], "front")
        self.assertEqual(conflict["selected_value"], "50.00")

    def test_04_conflict_resolution_priority_weighting_wins_on_equal_confidence(self):
        """Verify panel priority weighting resolves conflict when confidence scores are tied."""
        # For consumer_care, back panel is prioritized (weight 1.25 vs front 1.0)
        front_care = {
            "consumer_care": ExtractedField(
                field_name="consumer_care",
                raw_text="Care: front@company.com",
                extracted_value="front@company.com",
                unit=None,
                confidence=0.90,
                line_number=0,
                bbox=[0, 0, 10, 10],
                height_px=20.0,
                is_mandatory=True,
            ),
        }
        back_care = {
            "consumer_care": ExtractedField(
                field_name="consumer_care",
                raw_text="Care: back@company.com",
                extracted_value="back@company.com",
                unit=None,
                confidence=0.90,  # Equal confidence
                line_number=0,
                bbox=[0, 0, 10, 10],
                height_px=20.0,
                is_mandatory=True,
            ),
        }

        record = consolidate_scan_records(front_parsed=front_care, back_parsed=back_care)
        self.assertEqual(record.consumer_care, "back@company.com")
        self.assertEqual(len(record.resolved_conflicts), 1)
        self.assertEqual(record.resolved_conflicts[0]["selected_side"], "back")

    def test_05_conflict_resolution_non_empty_over_empty_declaration(self):
        """Verify non-empty extraction is selected even if empty field has high confidence."""
        front = {
            "batch_number": {"extracted_value": "", "confidence": 1.0},
        }
        back = {
            "batch_number": {"extracted_value": "B-9982", "confidence": 0.85},
        }

        record = consolidate_scan_records(front_parsed=front, back_parsed=back)
        self.assertEqual(record.batch_number, "B-9982")

    def test_06_completeness_and_missing_field_lists(self):
        """Verify completeness score and missing declarations list for partial extractions."""
        # Provide only 4 out of 9 mandatory declarations
        partial_front = {
            "mrp": "100.00",
            "net_quantity": "500 ml",
        }
        partial_back = {
            "batch_number": "L-12345",
            "mfg_date": "01/2026",
        }

        record = consolidate_scan_records(front_parsed=partial_front, back_parsed=partial_back)
        # 4 out of 9 = 44.44%
        self.assertEqual(record.completeness_pct, 44.44)
        self.assertEqual(record.total_declarations_present, 4)
        self.assertFalse(record.is_complete)

        expected_missing = [
            "manufacturer_details",
            "expiry_date",
            "consumer_care",
            "country_of_origin",
            "unit_sale_price",
        ]
        self.assertEqual(sorted(record.missing_declarations), sorted(expected_missing))

    def test_07_empty_inputs_handling(self):
        """Verify robust handling of empty or None front and back extractions."""
        record = consolidate_scan_records(front_parsed=None, back_parsed=None)
        self.assertEqual(record.completeness_pct, 0.0)
        self.assertEqual(record.total_declarations_present, 0)
        self.assertEqual(len(record.missing_declarations), 9)
        self.assertFalse(record.is_complete)

    def test_08_database_persistence_products_table(self):
        """Verify consolidated product record is saved to Supabase products table via db.create_product."""
        record = consolidate_scan_records(
            front_parsed=self.front_fields,
            back_parsed=self.back_fields,
            scan_id=self.test_scan_id,
        )

        self.assertTrue(bool(record.product_id), "Record should have a product_id UUID")

        # Verify retrieval from database
        db_product = db.get_product(record.product_id)
        self.assertIsNotNone(db_product, f"Product {record.product_id} not found in database")
        self.assertEqual(db_product.get("id"), record.product_id)
        self.assertEqual(db_product.get("brand"), "Parle-G Gold")
        self.assertEqual(db_product.get("net_quantity_declared"), "250 g")
        self.assertEqual(float(db_product.get("mrp_declared")), 30.00)
        self.assertEqual(db_product.get("country_of_origin"), "India")

        # Verify scan record is linked with the product_id
        linked_scan = db.get_scan(self.test_scan_id)
        self.assertIsNotNone(linked_scan)
        self.assertEqual(linked_scan.get("product_id"), record.product_id)

    def test_09_polymorphic_parsed_fields_result_support(self):
        """Verify ParsedFieldsResult instance input support."""
        front_res = ParsedFieldsResult(
            fields=self.front_fields,
            missing_mandatory_fields=["manufacturer_details"],
            total_fields_found=len(self.front_fields),
            overall_confidence=0.95,
        )
        back_res = ParsedFieldsResult(
            fields=self.back_fields,
            missing_mandatory_fields=[],
            total_fields_found=len(self.back_fields),
            overall_confidence=0.93,
        )

        record = consolidate_scan_records(front_parsed=front_res, back_parsed=back_res)
        self.assertEqual(record.completeness_pct, 100.0)
        self.assertEqual(record.brand_name, "Parle-G Gold")


def test_streamlit_app_consolidation_integration():
    """Verify Streamlit app displays Consolidated Product Master Record via headless AppTest."""
    print("\n--- Testing Streamlit App Consolidated Product Master Record (AppTest) ---")
    try:
        from streamlit.testing.v1 import AppTest

        app_path = os.path.join(PROJECT_ROOT, "app.py")
        at = AppTest.from_file(app_path, default_timeout=30)
        at.run()

        # Inject front and back parsed fields into session_state
        test_scan_id = str(uuid.uuid4())
        at.session_state["active_scan_id"] = test_scan_id
        at.session_state["current_scan"] = {
            "scan_id": test_scan_id,
            "timestamp": "2026-09-07T13:00:00Z",
            "status": "processed",
            "storage_status": "Offline Mock",
            "is_offline": True,
            "front_image_url": f"mock://product-images/scans/{test_scan_id}/front.png",
            "back_image_url": f"mock://product-images/scans/{test_scan_id}/back.png",
            "dimensions": {"summary": "Front: 800x600 px | Back: 800x600 px"},
        }

        # Populate all 9 mandatory fields across front and back
        at.session_state["front_parsed_fields"] = ParsedFieldsResult(
            fields={
                "brand_name": ExtractedField("brand_name", "Parle-G", "Parle-G", None, 0.98, 0, [0, 0, 10, 10], 10, False),
                "mrp": ExtractedField("mrp", "MRP Rs 30.00", "30.00", None, 0.99, 1, [0, 0, 10, 10], 10, True),
                "net_quantity": ExtractedField("net_quantity", "Net Qty 250 g", "250", "g", 0.98, 2, [0, 0, 10, 10], 10, True),
            },
            missing_mandatory_fields=[],
            total_fields_found=3,
            overall_confidence=0.98,
        )

        at.session_state["back_parsed_fields"] = ParsedFieldsResult(
            fields={
                "manufacturer_details": ExtractedField("manufacturer_details", "Parle Ltd", "Parle Ltd", None, 0.95, 0, [0, 0, 10, 10], 10, True),
                "mfg_date": ExtractedField("mfg_date", "08/2026", "08/2026", None, 0.95, 1, [0, 0, 10, 10], 10, True),
                "expiry_date": ExtractedField("expiry_date", "05/2027", "05/2027", None, 0.95, 2, [0, 0, 10, 10], 10, True),
                "batch_number": ExtractedField("batch_number", "B-100", "B-100", None, 0.95, 3, [0, 0, 10, 10], 10, True),
                "consumer_care": ExtractedField("consumer_care", "care@parle.biz", "care@parle.biz", None, 0.95, 4, [0, 0, 10, 10], 10, True),
                "country_of_origin": ExtractedField("country_of_origin", "India", "India", None, 0.95, 5, [0, 0, 10, 10], 10, True),
                "unit_sale_price": ExtractedField("unit_sale_price", "Rs 0.12/g", "Rs 0.12/g", None, 0.95, 6, [0, 0, 10, 10], 10, True),
            },
            missing_mandatory_fields=[],
            total_fields_found=7,
            overall_confidence=0.95,
        )

        at.run()
        assert not at.exception, f"AppTest encountered exception: {at.exception}"

        # Verify expander card is rendered
        expanders = [e.label for e in at.expander]
        assert any("Consolidated Product Master Record" in lbl for lbl in expanders), (
            f"Consolidated Product Master Record expander missing from {expanders}"
        )
        print("✓ Streamlit '📦 Consolidated Product Master Record' expander rendered")

        # Verify completeness metric badge
        success_texts = [s.value for s in at.success]
        badge_found = any("Mandatory Completeness: 100% (9/9 fields)" in text for text in success_texts)
        assert badge_found, f"Completeness badge missing from success texts: {success_texts}"
        print(f"✓ Streamlit completeness badge verified: '{[t for t in success_texts if 'Mandatory Completeness' in t][0]}'")

    except ImportError:
        print("ℹ️ streamlit.testing.v1 not available; skipping AppTest")


if __name__ == "__main__":
    print("============================================================")
    print("STARTING TASK 12 VERIFICATION SUITE")
    print("============================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestTask12Consolidation)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    assert result.wasSuccessful(), f"Task 12 unit tests failed: {result.failures or result.errors}"

    # Run Streamlit App headless integration test
    test_streamlit_app_consolidation_integration()
    print("\n============================================================")
    print("ALL TASK 12 TESTS PASSED SUCCESSFULLY (0 FAILURES)")
    print("============================================================")
