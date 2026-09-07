import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.field_parser import parse_ocr_lines, MANDATORY_FIELDS, ParsedFieldsResult


class TestTask9FieldParser(unittest.TestCase):
    def test_parse_ocr_lines_food_packaging(self):
        ocr_lines = [
            {"text": "M.R.P. Rs. 150.00 (Incl. of all taxes)", "confidence": 0.98, "bbox": [10, 10, 100, 20]},
            {"text": "NET QTY: 500 g", "confidence": 0.99, "bbox": [10, 30, 100, 40]},
            {"text": "MFG DATE: 08/2026", "confidence": 0.95, "bbox": [10, 50, 100, 60]},
            {"text": "EXPIRY DATE: 08/2027", "confidence": 0.95, "bbox": [10, 70, 100, 80]},
            {"text": "BATCH NO: B-1234", "confidence": 0.97, "bbox": [10, 90, 100, 100]},
            {"text": "MADE IN INDIA", "confidence": 0.99, "bbox": [10, 110, 100, 120]},
            {"text": "MANUFACTURED BY:", "confidence": 0.9, "bbox": [10, 130, 100, 140]},
            {"text": "Acme Corp, Industrial Area", "confidence": 0.9, "bbox": [10, 150, 100, 160]},
            {"text": "New Delhi - 110001", "confidence": 0.9, "bbox": [10, 170, 100, 180]},
            {"text": "CUSTOMER CARE: 1800-111-222", "confidence": 0.99, "bbox": [10, 190, 100, 200]},
            {"text": "UNIT SALE PRICE Rs. 0.30/g", "confidence": 0.95, "bbox": [10, 210, 100, 220]},
        ]

        result = parse_ocr_lines(ocr_lines)

        self.assertIsInstance(result, ParsedFieldsResult)
        self.assertEqual(result.total_fields_found, 9)
        self.assertEqual(len(result.missing_mandatory_fields), 0)
        self.assertEqual(result.fields['mrp'].extracted_value, "150.00")
        self.assertIn(result.fields['net_quantity'].extracted_value, ("500 g", "500", "500g"))
        self.assertEqual(result.fields['net_quantity'].unit.lower(), "g")
        self.assertEqual(result.fields['mfg_date'].extracted_value, "08/2026")
        self.assertEqual(result.fields['batch_number'].extracted_value, "B-1234")
        self.assertEqual(result.fields['country_of_origin'].extracted_value, "INDIA")
        self.assertIn("Acme Corp", result.fields['manufacturer_details'].extracted_value)
        self.assertIn("1800-111-222", result.fields['consumer_care'].extracted_value)
        self.assertTrue("0.30/g" in result.fields['unit_sale_price'].extracted_value.lower() or "0.30/g" in result.fields['unit_sale_price'].raw_text.lower())

    def test_parse_ocr_lines_missing_fields(self):
        ocr_lines = [
            {"text": "Some random text on package", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
            {"text": "NET QTY: 1 kg", "confidence": 0.9, "bbox": [0, 20, 10, 30]},
        ]

        result = parse_ocr_lines(ocr_lines)
        self.assertEqual(result.total_fields_found, 1)
        self.assertEqual(len(result.missing_mandatory_fields), 8)
        self.assertIn("mrp", result.missing_mandatory_fields)
        self.assertNotIn("net_quantity", result.missing_mandatory_fields)

    def test_parse_ocr_lines_stacked_fields(self):
        ocr_lines = [
            {"text": "Net Quantity", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
            {"text": "200 g", "confidence": 0.9, "bbox": [0, 20, 10, 30]},
            {"text": "MRP", "confidence": 0.9, "bbox": [0, 40, 10, 50]},
            {"text": "Inclusive of all taxes", "confidence": 0.9, "bbox": [0, 60, 10, 70]},
            {"text": "70.00", "confidence": 0.9, "bbox": [0, 80, 10, 90]},
            {"text": "Date of Packaging", "confidence": 0.9, "bbox": [0, 100, 10, 110]},
            {"text": "14/05/25", "confidence": 0.9, "bbox": [0, 120, 10, 130]},
            {"text": "Use By", "confidence": 0.9, "bbox": [0, 140, 10, 150]},
            {"text": "13/05/27", "confidence": 0.9, "bbox": [0, 160, 10, 170]},
        ]
        result = parse_ocr_lines(ocr_lines)
        self.assertIn(result.fields['net_quantity'].extracted_value, ("200 g", "200", "200g"))
        self.assertEqual(result.fields['mrp'].extracted_value, "70.00")
        self.assertEqual(result.fields['mfg_date'].extracted_value, "14/05/25")
        self.assertEqual(result.fields['expiry_date'].extracted_value, "13/05/27")

    def test_parse_ocr_lines_adjacent_back_panel(self):
        """Verify parsing adjacent and stacked fields as found on back label panels (e.g. Tamarind Date Chutney)."""
        ocr_lines = [
            {"text": "Net Quantity :", "confidence": 0.99, "bbox": [1269, 2221, 1565, 2299]},
            {"text": "200 g", "confidence": 1.0, "bbox": [1622, 2234, 1781, 2312]},
            {"text": "MRP:", "confidence": 0.89, "bbox": [1275, 2313, 1425, 2375]},
            {"text": "(Inclusive of all taxes)", "confidence": 0.99, "bbox": [1280, 2363, 1483, 2403]},
            {"text": "70.00", "confidence": 1.0, "bbox": [1745, 2372, 1911, 2423]},
            {"text": "Batch No :", "confidence": 0.96, "bbox": [1281, 2403, 1476, 2460]},
            {"text": "B2605 14", "confidence": 0.94, "bbox": [1734, 2452, 2029, 2511]},
            {"text": "Date of Packaging :", "confidence": 1.0, "bbox": [1279, 2452, 1639, 2522]},
            {"text": "14/05/25", "confidence": 1.0, "bbox": [1743, 2493, 2026, 2554]},
            {"text": "A Quality Product of Desai Foods Pvt. Ltd., 2-A, Atur", "confidence": 0.98, "bbox": [512, 2506, 1262, 2551]},
            {"text": "Use By:", "confidence": 1.0, "bbox": [1280, 2503, 1440, 2574]},
            {"text": "13/05/27", "confidence": 1.0, "bbox": [1745, 2532, 2024, 2594]},
            {"text": "Chambers, Camp, Pune, Maharashtra- 411001, India.", "confidence": 0.99, "bbox": [516, 2543, 1155, 2588]},
        ]
        result = parse_ocr_lines(ocr_lines)
        self.assertEqual(result.fields['mrp'].extracted_value, "70.00")
        self.assertIn(result.fields['net_quantity'].extracted_value, ("200 g", "200", "200g"))
        self.assertEqual(result.fields['mfg_date'].extracted_value, "14/05/25")
        self.assertEqual(result.fields['expiry_date'].extracted_value, "13/05/27")
        self.assertIn("Desai Foods Pvt. Ltd.", result.fields['manufacturer_details'].extracted_value)


if __name__ == "__main__":
    unittest.main()
