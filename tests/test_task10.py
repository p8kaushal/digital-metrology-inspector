"""Test suite for Task 10: Font-Height Measurement & Rule 7 Compliance.

Verifies:
1. Font size measurement calculations across various pixel heights and calibration ratios.
2. Cap-height factor adjustments (default ~0.80 and custom factors).
3. Uncalibrated fallback handling (None, zero, negative, uncalibrated objects).
4. Rule 7 statutory minimum font height evaluation across size tiers.
5. Report aggregation, counts, and formatted display outputs.
"""

import os
import sys
import unittest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.calibration import CalibrationResult
from src.field_parser import ExtractedField, ParsedFieldsResult
from src.font_measurement import (
    DEFAULT_CAP_HEIGHT_FACTOR,
    FontMeasurement,
    FontMeasurementReport,
    get_rule7_minimum_height_mm,
    measure_font_heights,
)


class TestTask10FontMeasurement(unittest.TestCase):
    """Automated test cases for Task 10 font-height measurement module."""

    def setUp(self):
        """Create sample extracted fields for testing."""
        self.sample_fields = {
            "mrp": ExtractedField(
                field_name="mrp",
                raw_text="M.R.P. Rs. 150.00",
                extracted_value="150.00",
                unit=None,
                confidence=0.98,
                line_number=0,
                bbox=[10, 20, 110, 55],  # height = 35 px
                height_px=35.0,
                is_mandatory=True,
            ),
            "net_quantity": ExtractedField(
                field_name="net_quantity",
                raw_text="NET QTY: 500 g",
                extracted_value="500",
                unit="g",
                confidence=0.99,
                line_number=1,
                bbox=[10, 60, 110, 110],  # height = 50 px
                height_px=50.0,
                is_mandatory=True,
            ),
            "mfg_date": ExtractedField(
                field_name="mfg_date",
                raw_text="MFG DATE: 08/2026",
                extracted_value="08/2026",
                unit=None,
                confidence=0.95,
                line_number=2,
                bbox=[10, 120, 110, 140],  # height = 20 px
                height_px=20.0,
                is_mandatory=True,
            ),
        }
        self.parsed_result = ParsedFieldsResult(
            fields=self.sample_fields,
            missing_mandatory_fields=["expiry_date", "batch_number"],
            total_fields_found=3,
            overall_confidence=0.973,
        )

    def test_font_size_calculations_various_pixel_heights_and_ratios(self):
        """Test font height in mm across various pixel heights and calibration ratios."""
        test_cases = [
            # (bbox_height_px, calibration_ratio, expected_cap_px, expected_font_mm)
            (20.0, 10.0, 16.0, 1.60),
            (30.0, 10.0, 24.0, 2.40),
            (50.0, 10.0, 40.0, 4.00),
            (28.1, 8.2164, 22.48, 2.74),
            (35.125, 8.2164, 28.1, 3.42),
            (45.0, 15.0, 36.0, 2.40),
            (100.0, 20.0, 80.0, 4.00),
        ]

        for bbox_h, ratio, exp_cap, exp_mm in test_cases:
            with self.subTest(bbox_h=bbox_h, ratio=ratio):
                fields = {
                    "test_field": {
                        "raw_text": "Sample Text",
                        "height_px": bbox_h,
                        "bbox": [0, 0, 100, int(bbox_h)],
                    }
                }
                report = measure_font_heights(fields, calibration_result=ratio)
                self.assertIn("test_field", report.measurements)
                m = report.measurements["test_field"]

                self.assertTrue(m.is_calibrated)
                self.assertAlmostEqual(m.bbox_height_px, bbox_h, places=1)
                self.assertAlmostEqual(m.cap_height_px, exp_cap, places=1)
                self.assertAlmostEqual(m.font_height_mm, exp_mm, places=2)
                self.assertAlmostEqual(m.calibration_px_per_mm, ratio, places=2)
                self.assertTrue(m.measurement_method.startswith("coin_calibrated_cap_height"))

    def test_font_measurement_dataclass_fields(self):
        """Test FontMeasurement dataclass contains all required fields and properties."""
        calib = CalibrationResult(
            pixels_per_mm=10.0,
            mm_per_pixel=0.1,
            coin_pixel_diameter=219.0,
            is_calibrated=True,
            message="Calibration successful.",
        )
        report = measure_font_heights(self.parsed_result, calib)

        self.assertIsInstance(report, FontMeasurementReport)
        self.assertEqual(len(report.measurements), 3)
        self.assertEqual(report.calibrated_fields_count, 3)
        self.assertAlmostEqual(report.calibration_ratio_used, 10.0, places=2)

        mrp_m = report.measurements["mrp"]
        # Required attributes check
        self.assertEqual(mrp_m.field_name, "mrp")
        self.assertEqual(mrp_m.raw_text, "M.R.P. Rs. 150.00")
        self.assertEqual(mrp_m.bbox_height_px, 35.0)
        self.assertEqual(mrp_m.cap_height_px, 28.0)  # 35 * 0.8
        self.assertEqual(mrp_m.font_height_mm, 2.80)  # 28.0 / 10.0
        self.assertEqual(mrp_m.calibration_px_per_mm, 10.0)
        self.assertTrue(mrp_m.is_calibrated)
        self.assertTrue(len(mrp_m.measurement_method) > 0)

        # Formatted string check (e.g. '2.80 mm (35.0 px)')
        self.assertIn("2.80 mm (35.0 px)", mrp_m.formatted_display)

    def test_cap_height_factor_adjustment(self):
        """Test cap-height estimation factor variations (0.70, 0.80, 0.85, 1.00)."""
        field_input = {"mrp": {"raw_text": "MRP 100", "height_px": 40.0}}
        ratio = 10.0

        factors = [0.70, 0.75, 0.80, 0.85, 1.00]
        for factor in factors:
            with self.subTest(factor=factor):
                report = measure_font_heights(field_input, ratio, cap_height_factor=factor)
                m = report.measurements["mrp"]
                expected_cap = round(40.0 * factor, 2)
                expected_mm = round(expected_cap / ratio, 2)

                self.assertAlmostEqual(m.cap_height_px, expected_cap, places=2)
                self.assertAlmostEqual(m.font_height_mm, expected_mm, places=2)

    def test_uncalibrated_fallback_handling(self):
        """Test graceful fallback behavior when calibration is missing or invalid."""
        uncalibrated_inputs = [
            None,
            0.0,
            -5.0,
            {},
            {"is_calibrated": False, "pixels_per_mm": 0.0},
            CalibrationResult(0.0, 0.0, 0.0, False, "Coin not detected."),
        ]

        for uncalib in uncalibrated_inputs:
            with self.subTest(uncalib=uncalib):
                report = measure_font_heights(self.parsed_result, uncalib)

                self.assertIsInstance(report, FontMeasurementReport)
                self.assertEqual(report.calibrated_fields_count, 0)
                self.assertEqual(report.calibration_ratio_used, 0.0)
                self.assertIn("uncalibrated", report.summary.lower())

                for fname, m in report.measurements.items():
                    self.assertFalse(m.is_calibrated)
                    self.assertEqual(m.font_height_mm, 0.0)
                    self.assertEqual(m.calibration_px_per_mm, 0.0)
                    self.assertEqual(m.measurement_method, "uncalibrated")
                    self.assertEqual(m.status, "UNCALIBRATED")
                    self.assertIn("Uncalibrated", m.formatted_display)
                    self.assertIn("Uncalibrated", m.compliance_badge)

    def test_rule7_minimum_font_height_tiers(self):
        """Test Rule 7 statutory minimum font height calculations for Net Qty & general fields."""
        # 1. Net Quantity tiers
        self.assertEqual(get_rule7_minimum_height_mm("net_quantity", 30, "g"), 1.0)
        self.assertEqual(get_rule7_minimum_height_mm("net_quantity", 50, "ml"), 1.0)
        self.assertEqual(get_rule7_minimum_height_mm("net_quantity", 150, "g"), 2.0)
        self.assertEqual(get_rule7_minimum_height_mm("net_quantity", 200, "ml"), 2.0)
        self.assertEqual(get_rule7_minimum_height_mm("net_quantity", 500, "g"), 4.0)
        self.assertEqual(get_rule7_minimum_height_mm("net_quantity", 1.0, "kg"), 4.0)
        self.assertEqual(get_rule7_minimum_height_mm("net_quantity", 1.5, "kg"), 6.0)
        self.assertEqual(get_rule7_minimum_height_mm("net_quantity", 2000, "ml"), 6.0)

        # 2. General mandatory declarations (MRP, Mfg Date, Expiry, etc.)
        self.assertEqual(get_rule7_minimum_height_mm("mrp"), 1.0)
        self.assertEqual(get_rule7_minimum_height_mm("manufacturer_details"), 1.0)
        self.assertEqual(get_rule7_minimum_height_mm("mfg_date"), 1.0)
        self.assertEqual(get_rule7_minimum_height_mm("consumer_care"), 1.0)

    def test_rule7_compliance_pass_and_deficit(self):
        """Test Rule 7 compliance evaluation (PASS and DEFICIT)."""
        # Ratio = 10 px/mm
        # 500g net_quantity requires 4.0 mm
        # Box 60 px -> cap 48 px -> 4.8 mm (PASS >= 4.0mm)
        # Box 30 px -> cap 24 px -> 2.4 mm (DEFICIT < 4.0mm)
        fields_pass = {
            "net_quantity": {
                "raw_text": "NET QTY: 500 g",
                "extracted_value": "500",
                "unit": "g",
                "height_px": 60.0,
            },
            "mrp": {
                "raw_text": "MRP Rs 150",
                "height_px": 25.0,  # 25 * 0.8 / 10 = 2.0 mm (PASS >= 1.0 mm)
            },
        }
        report_pass = measure_font_heights(fields_pass, 10.0)
        self.assertTrue(report_pass.measurements["net_quantity"].is_rule7_compliant)
        self.assertTrue(report_pass.measurements["mrp"].is_rule7_compliant)
        self.assertEqual(report_pass.compliant_fields_count, 2)
        self.assertEqual(report_pass.non_compliant_fields_count, 0)
        self.assertIn("PASS", report_pass.measurements["net_quantity"].compliance_badge)

        fields_deficit = {
            "net_quantity": {
                "raw_text": "NET QTY: 500 g",
                "extracted_value": "500",
                "unit": "g",
                "height_px": 30.0,  # 30 * 0.8 / 10 = 2.4 mm (DEFICIT < 4.0 mm)
            },
            "mrp": {
                "raw_text": "MRP Rs 150",
                "height_px": 10.0,  # 10 * 0.8 / 10 = 0.8 mm (DEFICIT < 1.0 mm)
            },
        }
        report_deficit = measure_font_heights(fields_deficit, 10.0)
        self.assertFalse(report_deficit.measurements["net_quantity"].is_rule7_compliant)
        self.assertFalse(report_deficit.measurements["mrp"].is_rule7_compliant)
        self.assertEqual(report_deficit.compliant_fields_count, 0)
        self.assertEqual(report_deficit.non_compliant_fields_count, 2)
        self.assertIn("DEFICIT", report_deficit.measurements["net_quantity"].compliance_badge)

    def test_flexible_input_types_and_edge_cases(self):
        """Test various input formats: dict, ParsedFieldsResult, bbox formats, empty."""
        # Empty input
        empty_report = measure_font_heights({}, 10.0)
        self.assertEqual(len(empty_report.measurements), 0)
        self.assertEqual(empty_report.calibrated_fields_count, 0)

        # Polygon bbox points [[x, y], ...]
        poly_field = {
            "mrp": {
                "raw_text": "MRP Rs 50",
                "bbox": [[10, 20], [110, 20], [110, 60], [10, 60]],  # height = 40
            }
        }
        poly_report = measure_font_heights(poly_field, 10.0)
        self.assertAlmostEqual(poly_report.measurements["mrp"].bbox_height_px, 40.0)
        self.assertAlmostEqual(poly_report.measurements["mrp"].font_height_mm, 3.20)

        # Dict with 'fields' nested key
        nested_dict = {
            "fields": {
                "batch_no": {"raw_text": "B-999", "height_px": 25.0}
            }
        }
        nested_report = measure_font_heights(nested_dict, 10.0)
        self.assertIn("batch_no", nested_report.measurements)
        self.assertAlmostEqual(nested_report.measurements["batch_no"].cap_height_px, 20.0)


if __name__ == "__main__":
    unittest.main()
