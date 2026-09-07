"""Automated Test Suite for Task 13: Report Generation.

Verifies:
1. ReportGenerationResult dataclass:
   - Fields: docx_path (str), pdf_path (str | None), scan_id (str), product_id (str | None),
     is_editable_word (bool), generation_time_sec (float).
2. generate_inspection_report function:
   - Uses python-docx to generate genuine editable Word (.docx) documents.
   - Official Department of Consumer Affairs Legal Metrology statutory headers.
   - Inspection metadata table (Scan ID, Product ID, Timestamp, Completeness %).
   - ₹5 Coin Reference Calibration section (21.90 mm standard & Rule 7 scale ratio).
   - Mandatory packaging declarations table (Rule 6 fields, values, font size mm, Rule 7 status).
   - Digital photographic evidence embedding (Front & Back packaging labels).
   - Packaging digital attestation and regulatory endorsement block.
   - Polymorphic input handling (ConsolidatedProductRecord, dict, partial extractions).
   - Graceful fallback for missing images and uncalibrated scans.
3. convert_docx_to_pdf function:
   - Converts .docx to .pdf if LibreOffice / soffice / docx2pdf is available.
   - Provides graceful fallback (including self-contained pure-Python PDF export).
   - Handles missing files and error cases gracefully without raising uncaught exceptions.
4. Streamlit App Integration:
   - Headless AppTest verification of the '📄 Generate Inspection Report' workflow.
   - Streamlit st.download_button download triggers for editable Word doc (.docx) and PDF (.pdf).
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import sys
import time
import unittest
import uuid
from PIL import Image
import docx
import pypdfium2 as pdfium

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.calibration import CalibrationResult
from src.consolidation import ConsolidatedProductRecord
from src.field_parser import ExtractedField, ParsedFieldsResult
from src.font_measurement import FontMeasurement, FontMeasurementReport
from src.report_generator import (
    ReportGenerationResult,
    convert_docx_to_pdf,
    generate_inspection_report,
)

TEST_REPORTS_DIR = os.path.join(PROJECT_ROOT, "tests", "temp_reports_task13")


class TestTask13ReportGenerator(unittest.TestCase):
    """Unit and integration test cases for Task 13 Report Generator."""

    def setUp(self):
        """Set up test directories and sample records."""
        os.makedirs(TEST_REPORTS_DIR, exist_ok=True)
        self.test_scan_id = str(uuid.uuid4())
        self.test_product_id = str(uuid.uuid4())

        # Create dummy sample front and back images for embedding tests
        self.front_img_path = os.path.join(TEST_REPORTS_DIR, "test_front.png")
        self.back_img_path = os.path.join(TEST_REPORTS_DIR, "test_back.png")

        img_front = Image.new("RGB", (300, 200), color=(54, 162, 235))
        img_front.save(self.front_img_path)

        img_back = Image.new("RGB", (300, 200), color=(255, 99, 132))
        img_back.save(self.back_img_path)

        # Create sample ConsolidatedProductRecord with all 9 mandatory fields
        self.sample_record = ConsolidatedProductRecord(
            product_id=self.test_product_id,
            brand_name="Britannia Good Day",
            mrp="40.00",
            net_quantity="200 g",
            mfg_date="09/2026",
            expiry_date="06/2027",
            batch_number="LOT-GD-404",
            manufacturer_details="Britannia Industries Ltd, Kolkata, WB - 700017",
            consumer_care="feedback@britannia.co.in | 1800-425-4444",
            country_of_origin="India",
            unit_sale_price="Rs 0.20 / g",
            front_fields={"brand_name": {}, "mrp": {}, "net_quantity": {}},
            back_fields={
                "manufacturer_details": {},
                "mfg_date": {},
                "expiry_date": {},
                "batch_number": {},
                "consumer_care": {},
                "country_of_origin": {},
                "unit_sale_price": {},
            },
            completeness_pct=100.0,
            missing_declarations=[],
        )

        # Sample coin calibration
        self.sample_calibration = CalibrationResult(
            pixels_per_mm=8.20,
            mm_per_pixel=0.1220,
            coin_pixel_diameter=179.58,
            is_calibrated=True,
            message="Calibration successful via Indian ₹5 coin (21.9mm).",
        )

        # Sample font measurement report
        self.sample_font_report = FontMeasurementReport(
            measurements={
                "mrp": FontMeasurement(
                    field_name="mrp",
                    raw_text="MRP Rs 40.00",
                    bbox_height_px=28.7,
                    cap_height_px=22.96,
                    font_height_mm=2.80,
                    calibration_px_per_mm=8.20,
                    is_calibrated=True,
                    measurement_method="coin_calibrated_bbox_cap_height",
                    rule7_min_height_mm=1.0,
                    is_rule7_compliant=True,
                    status="COMPLIANT",
                ),
                "net_quantity": FontMeasurement(
                    field_name="net_quantity",
                    raw_text="Net Weight: 200 g",
                    bbox_height_px=32.8,
                    cap_height_px=26.24,
                    font_height_mm=3.20,
                    calibration_px_per_mm=8.20,
                    is_calibrated=True,
                    measurement_method="coin_calibrated_bbox_cap_height",
                    rule7_min_height_mm=2.0,
                    is_rule7_compliant=True,
                    status="COMPLIANT",
                ),
            },
            calibrated_fields_count=2,
            calibration_ratio_used=8.20,
            summary="All measured declarations meet Rule 7 requirements.",
            compliant_fields_count=2,
            non_compliant_fields_count=0,
        )

    def tearDown(self):
        """Clean up test artifacts."""
        if os.path.exists(TEST_REPORTS_DIR):
            try:
                shutil.rmtree(TEST_REPORTS_DIR)
            except Exception:
                pass

    def test_01_dataclass_fields_and_types(self):
        """Verify ReportGenerationResult dataclass structure and field annotations."""
        result = ReportGenerationResult(
            docx_path="/path/to/report.docx",
            pdf_path="/path/to/report.pdf",
            scan_id="test-scan-123",
            product_id="test-prod-456",
            is_editable_word=True,
            generation_time_sec=0.1234,
        )

        self.assertEqual(result.docx_path, "/path/to/report.docx")
        self.assertEqual(result.pdf_path, "/path/to/report.pdf")
        self.assertEqual(result.scan_id, "test-scan-123")
        self.assertEqual(result.product_id, "test-prod-456")
        self.assertTrue(result.is_editable_word)
        self.assertEqual(result.generation_time_sec, 0.1234)

        # Verify dataclass fields inspection
        field_names = [f.name for f in dataclasses.fields(ReportGenerationResult)]
        expected_fields = [
            "docx_path",
            "pdf_path",
            "scan_id",
            "product_id",
            "is_editable_word",
            "generation_time_sec",
        ]
        for ef in expected_fields:
            self.assertIn(ef, field_names, f"Expected field {ef} missing from ReportGenerationResult")

    def test_02_generate_inspection_report_file_creation(self):
        """Verify generate_inspection_report produces a valid .docx file on disk."""
        res = generate_inspection_report(
            consolidated_record=self.sample_record,
            front_image=self.front_img_path,
            back_image=self.back_img_path,
            font_report=self.sample_font_report,
            calibration_result=self.sample_calibration,
            output_dir=TEST_REPORTS_DIR,
            scan_id=self.test_scan_id,
        )

        self.assertIsInstance(res, ReportGenerationResult)
        self.assertTrue(res.is_editable_word)
        self.assertEqual(res.scan_id, self.test_scan_id)
        self.assertEqual(res.product_id, self.test_product_id)
        self.assertGreater(res.generation_time_sec, 0.0)

        # Verify file existence and properties
        self.assertTrue(os.path.isfile(res.docx_path), f"Word docx file does not exist at {res.docx_path}")
        self.assertTrue(res.docx_path.endswith(".docx"))
        self.assertIn(f"inspection_report_{self.test_scan_id}.docx", res.docx_path)
        self.assertGreater(os.path.getsize(res.docx_path), 5000, "Docx file size unexpectedly small")

    def test_03_verify_docx_content_paragraphs_and_headers(self):
        """Open generated .docx and assert Department of Consumer Affairs Legal Metrology headers."""
        res = generate_inspection_report(
            consolidated_record=self.sample_record,
            front_image=self.front_img_path,
            back_image=self.back_img_path,
            font_report=self.sample_font_report,
            calibration_result=self.sample_calibration,
            output_dir=TEST_REPORTS_DIR,
            scan_id=self.test_scan_id,
        )

        doc = docx.Document(res.docx_path)
        all_para_text = " ".join(p.text for p in doc.paragraphs)

        # Department of Consumer Affairs Legal Metrology Header assertions
        self.assertIn("GOVERNMENT OF INDIA", all_para_text)
        self.assertIn("MINISTRY OF CONSUMER AFFAIRS, FOOD & PUBLIC DISTRIBUTION", all_para_text)
        self.assertIn("DEPARTMENT OF CONSUMER AFFAIRS", all_para_text)
        self.assertIn("LEGAL METROLOGY DIVISION", all_para_text)
        self.assertIn("LEGAL METROLOGY PACKAGED COMMODITIES INSPECTION REPORT", all_para_text)
        self.assertIn("Legal Metrology Rules, 2011", all_para_text)

        # Section Headings assertions
        self.assertIn("1. Inspection Metadata & Statutory Summary", all_para_text)
        self.assertIn("2. Reference Coin Calibration Standard (Rule 7 Metrology)", all_para_text)
        self.assertIn("3. Mandatory Declarations & Rule 7 Font Size Compliance", all_para_text)
        self.assertIn("4. Packaging Photographic Digital Evidence", all_para_text)
        self.assertIn("5. Metrological Attestation & Inspector Certification", all_para_text)

    def test_04_verify_docx_tables_cell_content_and_structure(self):
        """Assert exact table contents for metadata, calibration, and declarations."""
        res = generate_inspection_report(
            consolidated_record=self.sample_record,
            front_image=self.front_img_path,
            back_image=self.back_img_path,
            font_report=self.sample_font_report,
            calibration_result=self.sample_calibration,
            output_dir=TEST_REPORTS_DIR,
            scan_id=self.test_scan_id,
        )

        doc = docx.Document(res.docx_path)
        self.assertGreaterEqual(len(doc.tables), 4, "Expected at least 4 tables in the inspection report")

        # Table 0: Metadata Table
        tbl_meta = doc.tables[0]
        meta_text = " ".join(cell.text for row in tbl_meta.rows for cell in row.cells)
        self.assertIn("Scan ID", meta_text)
        self.assertIn(self.test_scan_id, meta_text)
        self.assertIn("Product ID", meta_text)
        self.assertIn(self.test_product_id, meta_text)
        self.assertIn("Completeness Score", meta_text)
        self.assertIn("100.0%", meta_text)
        self.assertIn("Britannia Good Day", meta_text)

        # Table 1: ₹5 Coin Calibration Table
        tbl_cal = doc.tables[1]
        cal_text = " ".join(cell.text for row in tbl_cal.rows for cell in row.cells)
        self.assertIn("Indian ₹5 Coin", cal_text)
        self.assertIn("21.90 mm", cal_text)
        self.assertIn("8.20 pixels / mm", cal_text)
        self.assertIn("179.58 px", cal_text)

        # Table 2: Mandatory Declarations Table
        tbl_decl = doc.tables[2]
        decl_headers = [c.text.strip() for c in tbl_decl.rows[0].cells]
        self.assertIn("Statutory Declaration", decl_headers[0])
        self.assertIn("Declared Value / Content", decl_headers[1])
        self.assertIn("Source Panel", decl_headers[2])
        self.assertIn("Font Height (mm)", decl_headers[3])
        self.assertIn("Rule 7 Status", decl_headers[4])

        decl_text = " ".join(cell.text for row in tbl_decl.rows for cell in row.cells)
        self.assertIn("Maximum Retail Price (MRP)", decl_text)
        self.assertIn("40.00", decl_text)
        self.assertIn("Net Quantity", decl_text)
        self.assertIn("200 g", decl_text)
        self.assertIn("Manufacturer / Packer / Importer Details", decl_text)
        self.assertIn("Britannia Industries Ltd", decl_text)
        self.assertIn("Month & Year of Manufacture / Packaging", decl_text)
        self.assertIn("09/2026", decl_text)
        self.assertIn("Expiry / Best Before Date", decl_text)
        self.assertIn("06/2027", decl_text)
        self.assertIn("Batch / Lot / Code Number", decl_text)
        self.assertIn("LOT-GD-404", decl_text)
        self.assertIn("Consumer Care Contact Information", decl_text)
        self.assertIn("feedback@britannia.co.in", decl_text)
        self.assertIn("Country of Origin", decl_text)
        self.assertIn("India", decl_text)
        self.assertIn("Unit Sale Price (USP)", decl_text)
        self.assertIn("Rs 0.20 / g", decl_text)

        # Font measurements & Rule 7 status check
        self.assertIn("2.80 mm", decl_text)
        self.assertIn("3.20 mm", decl_text)

    def test_05_docx_structure_genuinely_editable(self):
        """Verify that the generated docx document is genuinely editable."""
        res = generate_inspection_report(
            consolidated_record=self.sample_record,
            output_dir=TEST_REPORTS_DIR,
            scan_id=self.test_scan_id,
        )

        doc = docx.Document(res.docx_path)

        # Edit paragraph text directly in python-docx
        original_para_count = len(doc.paragraphs)
        new_note = "INSPECTOR ANNOTATION: Packaging label verified compliant on-site."
        doc.add_paragraph(new_note)

        # Edit table cell text directly
        table = doc.tables[2]
        original_cell_text = table.rows[1].cells[1].text
        edited_cell_text = f"{original_cell_text} [VERIFIED BY INSPECTOR]"
        table.rows[1].cells[1].text = edited_cell_text

        # Save modifications and reopen
        modified_path = os.path.join(TEST_REPORTS_DIR, "modified_report.docx")
        doc.save(modified_path)

        doc_modified = docx.Document(modified_path)
        self.assertEqual(len(doc_modified.paragraphs), original_para_count + 1)
        self.assertEqual(doc_modified.paragraphs[-1].text, new_note)
        self.assertEqual(doc_modified.tables[2].rows[1].cells[1].text, edited_cell_text)

    def test_06_image_embedding_front_and_back(self):
        """Verify front and back panel images are embedded into the document."""
        res = generate_inspection_report(
            consolidated_record=self.sample_record,
            front_image=self.front_img_path,
            back_image=self.back_img_path,
            output_dir=TEST_REPORTS_DIR,
            scan_id=self.test_scan_id,
        )

        doc = docx.Document(res.docx_path)

        # Check for image parts in the document package relationships
        image_parts = [
            part for part in doc.part.related_parts.values()
            if "image" in getattr(part, "content_type", "")
        ]
        self.assertGreaterEqual(len(image_parts), 2, "Expected at least 2 embedded images in document parts")

    def test_07_graceful_fallback_without_images_and_uncalibrated(self):
        """Verify graceful fallback when images are omitted and coin is uncalibrated."""
        res = generate_inspection_report(
            consolidated_record=self.sample_record,
            front_image=None,
            back_image=None,
            calibration_result=None,
            font_report=None,
            output_dir=TEST_REPORTS_DIR,
            scan_id=self.test_scan_id,
        )

        doc = docx.Document(res.docx_path)
        all_text = " ".join(p.text for p in doc.paragraphs)
        for tbl in doc.tables:
            all_text += " " + " ".join(c.text for r in tbl.rows for c in r.cells)

        self.assertIn("Uncalibrated", all_text)
        self.assertIn("Photographic Evidence Not Attached", all_text)

    def test_08_convert_docx_to_pdf_and_fallback(self):
        """Verify convert_docx_to_pdf creates a valid PDF via LibreOffice or pure-Python fallback."""
        res = generate_inspection_report(
            consolidated_record=self.sample_record,
            output_dir=TEST_REPORTS_DIR,
            scan_id=self.test_scan_id,
        )

        # PDF should be generated
        pdf_path = convert_docx_to_pdf(res.docx_path)
        self.assertIsNotNone(pdf_path, "PDF export should return valid path (LibreOffice or pure-Python fallback)")
        self.assertTrue(os.path.isfile(pdf_path), f"PDF file not found at {pdf_path}")
        self.assertGreater(os.path.getsize(pdf_path), 500, "PDF file size unexpectedly small")

        # Validate with pypdfium2
        pdf_doc = pdfium.PdfDocument(pdf_path)
        self.assertGreaterEqual(len(pdf_doc), 1, "PDF document should have at least 1 page")
        first_page_text = pdf_doc[0].get_textpage().get_text_range()
        self.assertIn("LEGAL METROLOGY", first_page_text)

        # Non-existent file should gracefully return None
        none_res = convert_docx_to_pdf("/non_existent/path/report.docx")
        self.assertIsNone(none_res)

    def test_09_polymorphic_dict_record_and_missing_fields_warning(self):
        """Verify support for raw dictionary records with missing declarations."""
        partial_dict = {
            "scan_id": str(uuid.uuid4()),
            "product_id": str(uuid.uuid4()),
            "brand_name": "Deficient Brand",
            "mrp": "99.00",
            # net_quantity, manufacturer, mfg_date, etc. are missing
            "completeness_pct": 11.1,
            "missing_declarations": [
                "net_quantity",
                "manufacturer_details",
                "mfg_date",
                "expiry_date",
                "batch_number",
                "consumer_care",
                "country_of_origin",
                "unit_sale_price",
            ],
        }

        res = generate_inspection_report(
            consolidated_record=partial_dict,
            output_dir=TEST_REPORTS_DIR,
            scan_id=partial_dict["scan_id"],
        )

        doc = docx.Document(res.docx_path)
        all_text = " ".join(p.text for p in doc.paragraphs)
        for tbl in doc.tables:
            all_text += " " + " ".join(c.text for r in tbl.rows for c in r.cells)

        self.assertIn("STATUTORY NON-COMPLIANCE NOTICE", all_text)
        self.assertIn("[MISSING / NOT DECLARED]", all_text)
        self.assertIn("11.1%", all_text)


def test_streamlit_app_report_generation_integration():
    """Verify Streamlit app report generation workflow and download buttons via headless AppTest."""
    print("\n--- Testing Streamlit App Report Generation Workflow (AppTest) ---")
    try:
        from streamlit.testing.v1 import AppTest

        app_path = os.path.join(PROJECT_ROOT, "app.py")
        at = AppTest.from_file(app_path, default_timeout=35)
        at.run()

        test_scan_id = str(uuid.uuid4())
        at.session_state["active_scan_id"] = test_scan_id
        at.session_state["current_scan"] = {
            "scan_id": test_scan_id,
            "timestamp": "2026-09-07T13:30:00Z",
            "status": "processed",
            "storage_status": "Offline Mock",
            "is_offline": True,
            "front_image_url": f"mock://product-images/scans/{test_scan_id}/front.png",
            "back_image_url": f"mock://product-images/scans/{test_scan_id}/back.png",
            "dimensions": {"summary": "Front: 600x400 px | Back: 600x400 px"},
        }

        # Inject consolidated record
        sample_rec = ConsolidatedProductRecord(
            product_id=str(uuid.uuid4()),
            brand_name="Tata Tea Gold",
            mrp="150.00",
            net_quantity="500 g",
            mfg_date="07/2026",
            expiry_date="07/2027",
            batch_number="TT-101",
            manufacturer_details="Tata Consumer Products Ltd, Bengaluru",
            consumer_care="care@tataconsumer.com",
            country_of_origin="India",
            unit_sale_price="Rs 0.30/g",
            completeness_pct=100.0,
            missing_declarations=[],
        )
        at.session_state["consolidated_record"] = sample_rec

        # Run app to render the Consolidated Product Master Record and report button
        at.run()
        assert not at.exception, f"AppTest exception on render: {at.exception}"

        # Locate the 'Generate Inspection Report' button
        gen_buttons = [b for b in at.button if "Generate Inspection Report" in b.label]
        assert gen_buttons, f"Button '📄 Generate Inspection Report' not found in buttons: {[b.label for b in at.button]}"
        print("✓ Streamlit '📄 Generate Inspection Report' button located")

        # Click the Generate Inspection Report button
        gen_buttons[0].click().run()
        assert not at.exception, f"AppTest exception after button click: {at.exception}"

        # Verify success notification is rendered
        success_texts = [s.value for s in at.success]
        assert any("Inspection report generated" in t for t in success_texts), (
            f"Success notification missing from: {success_texts}"
        )
        print("✓ Streamlit report generation success notification verified")

        # Verify session state report_result
        assert "report_result" in at.session_state, "report_result not found in session_state"
        rep_result = at.session_state["report_result"]
        assert rep_result is not None, "session_state['report_result'] is None"
        assert rep_result.is_editable_word, "report_result.is_editable_word is False"
        assert os.path.isfile(rep_result.docx_path), f"Report file missing: {rep_result.docx_path}"
        print(f"✓ Generated docx artifact confirmed: {os.path.basename(rep_result.docx_path)}")

        # Verify download buttons are rendered
        dl_labels = [d.label for d in at.download_button]
        assert any("Download Editable Word (.docx)" in lbl for lbl in dl_labels), (
            f"Word download button missing from: {dl_labels}"
        )
        print("✓ Streamlit '📥 Download Editable Word (.docx)' download button verified")

        if rep_result.pdf_path and os.path.isfile(rep_result.pdf_path):
            assert any("Download Inspection PDF (.pdf)" in lbl for lbl in dl_labels), (
                f"PDF download button missing from: {dl_labels}"
            )
            print("✓ Streamlit '📥 Download Inspection PDF (.pdf)' download button verified")

    except ImportError:
        print("ℹ️ streamlit.testing.v1 not available; skipping AppTest")


if __name__ == "__main__":
    print("============================================================")
    print("STARTING TASK 13 VERIFICATION SUITE")
    print("============================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestTask13ReportGenerator)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    assert result.wasSuccessful(), f"Task 13 unit tests failed: {result.failures or result.errors}"

    # Run Streamlit App headless integration test
    test_streamlit_app_report_generation_integration()
    print("\n============================================================")
    print("ALL TASK 13 TESTS PASSED SUCCESSFULLY (0 FAILURES)")
    print("============================================================")
