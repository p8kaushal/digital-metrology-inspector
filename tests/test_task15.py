"""Automated Test Suite for Task 15: Inspector Manual Verification & Field Corrections.

Verifies:
1. DDL & Database Mock in src/db.py:
   - correction_logs table schema and mock store support.
   - log_field_correction(scan_id, field_name, original_value, corrected_value, inspector_id, reason).
   - get_correction_logs(scan_id) retrieval and sorting.
2. Manual Correction Service in src/scan_service.py:
   - apply_manual_corrections(scan_id, corrections_dict, inspector_id, reason).
   - Updates extracted_fields in DB with is_corrected=True and new value.
   - Logs audit entries to correction_logs table.
   - Re-consolidates product record (updates master attributes, completeness, missing declarations).
   - Synchronizes product table in DB and scan foreign keys.
   - ManualCorrectionResult container polymorphism (attributes, dict indexing, and ConsolidatedProductRecord inheritance).
3. Streamlit UI Integration in app.py:
   - Headless AppTest verifying the Inspector Manual Verification & Correction Panel.
   - Form inputs for mandatory fields.
   - Form submission via "Save Manual Corrections & Update Master Record".
   - Displays success alert '✏️ Saved X field correction(s) to Supabase audit log'.
   - Audit trail display and session state synchronization.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import db
from src.consolidation import ConsolidatedProductRecord, MANDATORY_DECLARATIONS
from src.scan_service import (
    ManualCorrectionResult,
    apply_manual_corrections,
)


class TestTask15DatabaseAuditLog(unittest.TestCase):
    """Unit tests for correction_logs database operations."""

    def setUp(self):
        """Reset mock database correction logs for clean testing."""
        self.scan_id = str(uuid.uuid4())

    def test_01_log_field_correction_record_schema(self):
        """Verify log_field_correction creates an audit entry with all required schema fields."""
        log = db.log_field_correction(
            scan_id=self.scan_id,
            field_name="mrp",
            original_value="28.00",
            corrected_value="35.00",
            inspector_id="INS-007",
            reason="OCR misread 35 as 28 due to specular glare",
        )

        self.assertIsInstance(log, dict)
        self.assertTrue(log.get("id"))
        self.assertEqual(log.get("scan_id"), self.scan_id)
        self.assertEqual(log.get("field_name"), "mrp")
        self.assertEqual(log.get("original_value"), "28.00")
        self.assertEqual(log.get("corrected_value"), "35.00")
        self.assertEqual(log.get("inspector_id"), "INS-007")
        self.assertEqual(log.get("reason"), "OCR misread 35 as 28 due to specular glare")
        self.assertTrue(log.get("created_at"))

    def test_02_log_field_correction_defaults(self):
        """Verify default values for inspector_id and nullable fields."""
        log = db.log_field_correction(
            scan_id=self.scan_id,
            field_name="net_quantity",
            original_value=None,
            corrected_value="500 g",
        )

        self.assertEqual(log.get("inspector_id"), "INS-001")
        self.assertIsNone(log.get("original_value"))
        self.assertIsNone(log.get("reason"))
        self.assertEqual(log.get("corrected_value"), "500 g")

    def test_03_get_correction_logs_filtering(self):
        """Verify get_correction_logs returns logs filtered by scan_id."""
        other_scan_id = str(uuid.uuid4())
        db.log_field_correction(self.scan_id, "batch_number", "B1", "B2")
        db.log_field_correction(other_scan_id, "mfg_date", "01/25", "02/25")

        logs_this_scan = db.get_correction_logs(self.scan_id)
        self.assertTrue(any(l["field_name"] == "batch_number" for l in logs_this_scan))
        self.assertFalse(any(l["scan_id"] == other_scan_id for l in logs_this_scan))


class TestTask15ApplyManualCorrections(unittest.TestCase):
    """Unit and integration tests for apply_manual_corrections in scan_service.py."""

    def setUp(self):
        """Set up test scan and sample initial extracted fields."""
        self.scan_id = str(uuid.uuid4())
        self.product_id = str(uuid.uuid4())

        # Create base scan in DB
        db.create_scan({
            "id": self.scan_id,
            "scan_id": self.scan_id,
            "product_id": self.product_id,
            "status": "processed",
        })

        # Pre-seed extracted_fields with uncorrected values
        self.initial_fields = [
            {
                "scan_id": self.scan_id,
                "side": "front",
                "field_name": "mrp",
                "raw_text": "MRP Rs 28.00",
                "parsed_value": "28.00",
                "confidence": 0.85,
                "is_corrected": False,
            },
            {
                "scan_id": self.scan_id,
                "side": "front",
                "field_name": "net_quantity",
                "raw_text": "Net Qty: 1 kg",
                "parsed_value": "1 kg",
                "confidence": 0.95,
                "is_corrected": False,
            },
            {
                "scan_id": self.scan_id,
                "side": "back",
                "field_name": "brand_name",
                "raw_text": "Tata Salt",
                "parsed_value": "Tata Salt",
                "confidence": 0.90,
                "is_corrected": False,
            },
        ]
        db.save_extracted_fields(self.scan_id, self.initial_fields)

        # Create initial product record
        self.initial_record = ConsolidatedProductRecord(
            product_id=self.product_id,
            brand_name="Tata Salt",
            mrp="28.00",
            net_quantity="1 kg",
            mfg_date="01/2026",
            expiry_date="",  # Missing
            batch_number="",  # Missing
            manufacturer_details="Tata Chemicals Ltd",
            consumer_care="",  # Missing
            country_of_origin="India",
            unit_sale_price="",  # Missing
            missing_declarations=["expiry_date", "batch_number", "consumer_care", "unit_sale_price"],
            completeness_pct=55.56,
        )
        db.create_product(self.initial_record.to_db_payload())

    def test_01_updates_extracted_fields_is_corrected_and_value(self):
        """Verify extracted_fields table has is_corrected=True and the updated parsed_value."""
        corrections = {
            "mrp": "32.00",
        }
        res = apply_manual_corrections(
            scan_id=self.scan_id,
            corrections_dict=corrections,
            inspector_id="INS-002",
            reason="Verified from barcode database",
            current_record=self.initial_record,
        )

        # Check DB extracted_fields
        db_fields = db.get_extracted_fields(self.scan_id)
        mrp_fields = [f for f in db_fields if f.get("field_name") == "mrp"]
        self.assertTrue(mrp_fields, "MRP field must exist in extracted_fields")
        for f in mrp_fields:
            self.assertEqual(f.get("parsed_value"), "32.00")
            self.assertTrue(f.get("is_corrected"))

        # Verify untouched field remains uncorrected
        net_qty_fields = [f for f in db_fields if f.get("field_name") == "net_quantity"]
        self.assertFalse(net_qty_fields[0].get("is_corrected"))

    def test_02_logs_audit_entries_in_correction_logs(self):
        """Verify entries are logged into correction_logs with original and corrected values."""
        corrections = {
            "mrp": "35.50",
            "net_quantity": "1.2 kg",
        }
        res = apply_manual_corrections(
            scan_id=self.scan_id,
            corrections_dict=corrections,
            inspector_id="INS-003",
            reason="Label text blurred",
            current_record=self.initial_record,
        )

        logs = db.get_correction_logs(self.scan_id)
        self.assertGreaterEqual(len(logs), 2)

        mrp_log = next((l for l in logs if l.get("field_name") == "mrp"), None)
        self.assertIsNotNone(mrp_log)
        self.assertEqual(mrp_log.get("original_value"), "28.00")
        self.assertEqual(mrp_log.get("corrected_value"), "35.50")
        self.assertEqual(mrp_log.get("inspector_id"), "INS-003")
        self.assertEqual(mrp_log.get("reason"), "Label text blurred")

    def test_03_completes_missing_declarations_and_recomputes_completeness(self):
        """Verify completing previously missing fields removes them from missing list and increases completeness."""
        corrections = {
            "expiry_date": "12/2027",
            "batch_number": "BATCH-XYZ",
            "consumer_care": "care@tata.com",
            "unit_sale_price": "Rs 0.032/g",
        }

        res = apply_manual_corrections(
            scan_id=self.scan_id,
            corrections_dict=corrections,
            inspector_id="INS-001",
            current_record=self.initial_record,
        )

        # All 9 mandatory declarations are now provided
        self.assertEqual(len(res.missing_declarations), 0)
        self.assertEqual(res.completeness_pct, 100.0)
        self.assertTrue(res.is_complete)
        self.assertEqual(res.expiry_date, "12/2027")
        self.assertEqual(res.batch_number, "BATCH-XYZ")
        self.assertEqual(res.consumer_care, "care@tata.com")
        self.assertEqual(res.unit_sale_price, "Rs 0.032/g")

        # Check that DB products table was synchronized
        db_prod = db.get_product(self.product_id)
        self.assertIsNotNone(db_prod)
        self.assertEqual(db_prod.get("consumer_care"), "care@tata.com")
        self.assertEqual(db_prod.get("completeness_pct"), 100.0)

    def test_04_manual_correction_result_container_polymorphism(self):
        """Verify ManualCorrectionResult supports both attribute and dictionary access."""
        corrections = {"mrp": "40.00"}
        res = apply_manual_corrections(
            scan_id=self.scan_id,
            corrections_dict=corrections,
            current_record=self.initial_record,
        )

        self.assertIsInstance(res, ManualCorrectionResult)
        self.assertIsInstance(res, ConsolidatedProductRecord)

        # Attribute access
        self.assertEqual(res.mrp, "40.00")
        self.assertEqual(res.corrections_count, 1)
        self.assertTrue(res.logged_corrections)

        # Dict access
        self.assertEqual(res["mrp"], "40.00")
        self.assertEqual(res.get("mrp"), "40.00")
        self.assertTrue("mrp" in res)
        self.assertEqual(res["corrections_count"], 1)

        # Record property
        self.assertIs(res.record, res)

    def test_05_error_handling_empty_scan_id(self):
        """Verify ValueError is raised on missing scan_id."""
        with self.assertRaises(ValueError):
            apply_manual_corrections("", {"mrp": "20.00"})
        with self.assertRaises(ValueError):
            apply_manual_corrections("   ", {"mrp": "20.00"})


def test_streamlit_app_manual_correction_panel():
    """Headless Streamlit AppTest verifying inspector manual correction form submission and UI alerts."""
    try:
        from streamlit.testing.v1 import AppTest
        print("\n--- Testing Streamlit App Manual Correction Panel (AppTest) ---")

        app_path = os.path.join(PROJECT_ROOT, "app.py")
        at = AppTest.from_file(app_path, default_timeout=35)
        at.run()
        assert not at.exception, f"AppTest exception on startup: {at.exception}"

        # Initialize mock scan and consolidated record in session state
        test_scan_id = str(uuid.uuid4())
        test_product_id = str(uuid.uuid4())
        sample_rec = ConsolidatedProductRecord(
            product_id=test_product_id,
            brand_name="Dabur Honey 100% Pure",
            mrp="125.00",
            net_quantity="250 g",
            mfg_date="03/2026",
            expiry_date="",  # Missing declaration
            batch_number="DH-987",
            manufacturer_details="Dabur India Ltd, New Delhi",
            consumer_care="",  # Missing declaration
            country_of_origin="India",
            unit_sale_price="Rs 0.50/g",
            completeness_pct=77.78,
            missing_declarations=["expiry_date", "consumer_care"],
        )

        at.session_state["active_scan_id"] = test_scan_id
        at.session_state["consolidated_record"] = sample_rec
        at.session_state["current_scan"] = {
            "scan_id": test_scan_id,
            "status": "processed",
            "storage_status": "Offline Mock",
            "timestamp": "2026-09-07T12:00:00Z",
            "front_image_url": "mock://img_front.png",
            "back_image_url": "mock://img_back.png",
        }

        # Run to render the Inspector Manual Verification & Correction Panel
        at.run()
        assert not at.exception, f"AppTest exception on rendering panel: {at.exception}"

        # 1. Locate the form submit button: "Save Manual Corrections & Update Master Record"
        save_buttons = [b for b in at.button if "Save Manual Corrections & Update Master Record" in b.label]
        assert save_buttons, f"Button 'Save Manual Corrections & Update Master Record' not found: {[b.label for b in at.button]}"
        print("✓ Streamlit form submit button 'Save Manual Corrections & Update Master Record' located")

        # 2. Modify form inputs: update mrp from 125.00 to 130.00 and complete consumer_care
        mrp_inputs = [ti for ti in at.text_input if ti.key == "form_field_mrp"]
        care_inputs = [ti for ti in at.text_input if ti.key == "form_field_consumer_care"]
        inspector_inputs = [ti for ti in at.text_input if ti.key == "input_inspector_id"]
        reason_inputs = [ti for ti in at.text_input if ti.key == "input_correction_reason"]

        assert mrp_inputs, "MRP text_input 'form_field_mrp' not found"
        assert care_inputs, "Consumer care text_input 'form_field_consumer_care' not found"

        mrp_inputs[0].set_value("130.00")
        care_inputs[0].set_value("customercare@dabur.com")
        if inspector_inputs:
            inspector_inputs[0].set_value("INS-GOLD-01")
        if reason_inputs:
            reason_inputs[0].set_value("Price revised on PDP; customer care confirmed")

        # 3. Submit form
        save_buttons[0].click().run()
        assert not at.exception, f"AppTest exception after form submission: {at.exception}"

        # 4. Verify success alert: "✏️ Saved 2 field correction(s) to Supabase audit log"
        success_messages = [s.value for s in at.success]
        expected_substr = "Saved 2 field correction(s) to Supabase audit log"
        assert any(expected_substr in s for s in success_messages), (
            f"Expected '{expected_substr}' not found in success alerts: {success_messages}"
        )
        print(f"✓ Success alert confirmed: {[s for s in success_messages if expected_substr in s][0]}")

        # 5. Verify session_state['consolidated_record'] was updated
        assert "consolidated_record" in at.session_state, "consolidated_record not in session_state"
        updated_rec = at.session_state["consolidated_record"]
        assert updated_rec is not None, "session_state['consolidated_record'] is None"
        assert updated_rec.mrp == "130.00", f"Expected mrp='130.00', got {updated_rec.mrp}"
        assert updated_rec.consumer_care == "customercare@dabur.com", (
            f"Expected consumer_care='customercare@dabur.com', got {updated_rec.consumer_care}"
        )
        assert "consumer_care" not in updated_rec.missing_declarations, (
            "consumer_care should no longer be missing"
        )
        print("✓ Session state consolidated_record successfully updated with manual corrections")

        # 6. Verify audit logs in database
        logs = db.get_correction_logs(test_scan_id)
        assert len(logs) >= 2, f"Expected at least 2 logs in DB, got {len(logs)}"
        mrp_entry = next((l for l in logs if l.get("field_name") == "mrp"), None)
        care_entry = next((l for l in logs if l.get("field_name") == "consumer_care"), None)

        assert mrp_entry is not None, "MRP correction entry missing from DB"
        assert mrp_entry.get("original_value") == "125.00"
        assert mrp_entry.get("corrected_value") == "130.00"
        assert mrp_entry.get("inspector_id") == "INS-GOLD-01"

        assert care_entry is not None, "Consumer care correction entry missing from DB"
        assert care_entry.get("corrected_value") == "customercare@dabur.com"
        print("✓ Database audit log entries verified in Supabase correction_logs mock store")

    except ImportError:
        print("ℹ️ streamlit.testing.v1 not available; skipping AppTest")


if __name__ == "__main__":
    print("============================================================")
    print("STARTING TASK 15 VERIFICATION SUITE")
    print("============================================================")

    suite = unittest.TestSuite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestTask15DatabaseAuditLog))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestTask15ApplyManualCorrections))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    assert result.wasSuccessful(), f"Task 15 unit tests failed: {result.failures or result.errors}"

    # Run Streamlit App headless integration test
    test_streamlit_app_manual_correction_panel()

    print("\n============================================================")
    print("ALL TASK 15 TESTS PASSED SUCCESSFULLY (0 FAILURES)")
    print("============================================================")
