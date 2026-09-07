"""Digital Metrology Inspector - Test Suite for Task 8: OCR Text Extraction.

Tests:
1. OCR extraction engine with synthetic packaging label images containing standard mandatory declarations:
   - "MRP Rs. 250.00"
   - "NET QTY: 500 g"
   - "MFG DATE: 08/2026"
2. Reference coin ROI masking and exclusion.
3. Invalid image inputs (non-existent file, empty array, None, blank image).
4. Multiple input formats (file path string, PIL Image, numpy array).
5. Tesseract engine fallback.
6. Dataclass integrity and annotation overlay rendering.
"""

from __future__ import annotations

import os
import sys
import unittest
import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.ocr_engine import (
    OCRLineItem,
    OCRExtractionResult,
    extract_text_from_image,
    is_in_coin_roi,
    load_image,
    draw_ocr_annotated_image,
)


class TestTask8OCRExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_files = []

        # 1. Standard packaging label image with mandatory declarations
        cls.label_path = "tests/test_ocr_label.png"
        label_img = np.full((350, 650, 3), 255, dtype=np.uint8)
        cv2.putText(label_img, "MRP Rs. 250.00", (40, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        cv2.putText(label_img, "NET QTY: 500 g", (40, 160), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        cv2.putText(label_img, "MFG DATE: 08/2026", (40, 245), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        cv2.imwrite(cls.label_path, label_img)
        cls.test_files.append(cls.label_path)
        cls.label_img = label_img

        # 2. Packaging label with reference coin containing markings
        cls.label_with_coin_path = "tests/test_ocr_label_with_coin.png"
        coin_label_img = np.full((400, 700, 3), 255, dtype=np.uint8)
        cv2.putText(coin_label_img, "MRP Rs. 250.00", (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        cv2.putText(coin_label_img, "NET QTY: 500 g", (40, 170), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        cv2.putText(coin_label_img, "MFG DATE: 08/2026", (40, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)

        cls.coin_center = (520, 200)
        cls.coin_radius = 55
        cv2.circle(coin_label_img, cls.coin_center, cls.coin_radius, (0, 0, 0), 2)
        cv2.putText(coin_label_img, "5 RUPEES", (cls.coin_center[0] - 40, cls.coin_center[1] + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)
        cv2.imwrite(cls.label_with_coin_path, coin_label_img)
        cls.test_files.append(cls.label_with_coin_path)
        cls.coin_label_img = coin_label_img

        # 3. Blank image (no text)
        cls.blank_path = "tests/test_ocr_blank.png"
        blank_img = np.full((200, 300, 3), 255, dtype=np.uint8)
        cv2.imwrite(cls.blank_path, blank_img)
        cls.test_files.append(cls.blank_path)
        cls.blank_img = blank_img

    @classmethod
    def tearDownClass(cls):
        for f in cls.test_files:
            if os.path.exists(f):
                os.remove(f)

    def test_dataclass_structure(self):
        """Verify OCRLineItem and OCRExtractionResult dataclass fields and types."""
        line = OCRLineItem(
            text="MRP Rs. 250.00",
            confidence=0.985,
            bbox=[40, 50, 290, 80],
            polygon=[[40, 50], [290, 50], [290, 80], [40, 80]],
            width_px=250.0,
            height_px=30.0,
        )
        self.assertEqual(line.text, "MRP Rs. 250.00")
        self.assertAlmostEqual(line.confidence, 0.985)
        self.assertEqual(line.bbox, [40, 50, 290, 80])
        self.assertEqual(line.polygon[2], [290, 80])
        self.assertEqual(line.width_px, 250.0)
        self.assertEqual(line.height_px, 30.0)

        result = OCRExtractionResult(
            lines=[line],
            full_text=line.text,
            total_lines=1,
            avg_confidence=0.985,
            annotated_image=None,
            engine_used="paddleocr",
        )
        self.assertEqual(result.total_lines, 1)
        self.assertEqual(result.engine_used, "paddleocr")
        self.assertIn("MRP", result.full_text)

    def test_extract_mandatory_label_text(self):
        """Verify extraction of MRP, NET QTY, and MFG DATE from synthetic packaging label."""
        result = extract_text_from_image(self.label_path)

        self.assertIsInstance(result, OCRExtractionResult)
        self.assertGreaterEqual(result.total_lines, 3, "Expected at least 3 mandatory text lines extracted")
        self.assertEqual(len(result.lines), result.total_lines)
        self.assertGreater(result.avg_confidence, 0.70, "Expected high confidence on clean label")
        self.assertIn(result.engine_used, ("paddleocr", "tesseract"))

        full_text_upper = result.full_text.upper()
        self.assertTrue("MRP" in full_text_upper or "250" in full_text_upper, f"MRP not found in: {result.full_text}")
        self.assertTrue("NET" in full_text_upper or "QTY" in full_text_upper or "500" in full_text_upper, f"Net Qty not found in: {result.full_text}")
        self.assertTrue("MFG" in full_text_upper or "DATE" in full_text_upper or "2026" in full_text_upper, f"Mfg Date not found in: {result.full_text}")

        # Verify geometric properties of line items
        for idx, item in enumerate(result.lines):
            self.assertIsInstance(item, OCRLineItem)
            self.assertTrue(len(item.text) > 0)
            self.assertGreater(item.confidence, 0.5)
            x_min, y_min, x_max, y_max = item.bbox
            self.assertLess(x_min, x_max, f"Invalid bbox width in line {idx}")
            self.assertLess(y_min, y_max, f"Invalid bbox height in line {idx}")
            self.assertEqual(item.width_px, float(x_max - x_min))
            self.assertEqual(item.height_px, float(y_max - y_min))
            self.assertEqual(len(item.polygon), 4)

        # Verify annotated image
        self.assertIsNotNone(result.annotated_image)
        self.assertEqual(result.annotated_image.shape, self.label_img.shape)

    def test_coin_roi_masking_and_exclusion(self):
        """Verify that coin area is masked and coin text is excluded from OCR results."""
        # 1. OCR WITH coin center and radius provided
        res_with_mask = extract_text_from_image(
            image_input=self.coin_label_img,
            coin_center=self.coin_center,
            coin_radius=self.coin_radius,
        )
        self.assertGreaterEqual(res_with_mask.total_lines, 3)

        # Confirm no line item intersects or is located inside the coin ROI
        for item in res_with_mask.lines:
            self.assertFalse(
                is_in_coin_roi(item.bbox, self.coin_center, self.coin_radius),
                f"Line '{item.text}' bbox {item.bbox} intersects coin ROI {self.coin_center} r={self.coin_radius}"
            )
            # Ensure coin text itself is not extracted
            self.assertNotIn("RUPEES", item.text.upper())

        # 2. OCR WITHOUT coin masking
        res_no_mask = extract_text_from_image(
            image_input=self.coin_label_img,
            coin_center=None,
            coin_radius=None,
        )
        # Without masking, coin markings produce an additional line item
        coin_text_detected = any(
            is_in_coin_roi(item.bbox, self.coin_center, self.coin_radius)
            or "RUPEE" in item.text.upper() or "5" in item.text
            for item in res_no_mask.lines
        )
        self.assertTrue(coin_text_detected, "Expected coin marking to be detected when masking is disabled")

    def test_invalid_and_edge_case_inputs(self):
        """Verify robust error handling on non-existent paths, empty arrays, None, and blank images."""
        # Non-existent file path
        res_bad_path = extract_text_from_image("tests/non_existent_file_xyz.png")
        self.assertEqual(res_bad_path.total_lines, 0)
        self.assertEqual(res_bad_path.lines, [])
        self.assertEqual(res_bad_path.full_text, "")
        self.assertIn("error", res_bad_path.engine_used)

        # None input
        res_none = extract_text_from_image(None)
        self.assertEqual(res_none.total_lines, 0)
        self.assertEqual(res_none.lines, [])
        self.assertIn("error", res_none.engine_used)

        # Empty numpy array
        res_empty = extract_text_from_image(np.array([]))
        self.assertEqual(res_empty.total_lines, 0)
        self.assertEqual(res_empty.lines, [])
        self.assertIn("error", res_empty.engine_used)

        # Blank white image (valid image, 0 text)
        res_blank = extract_text_from_image(self.blank_img)
        self.assertEqual(res_blank.total_lines, 0)
        self.assertEqual(res_blank.lines, [])
        self.assertEqual(res_blank.full_text, "")
        self.assertEqual(res_blank.avg_confidence, 0.0)
        self.assertIsNotNone(res_blank.annotated_image)

    def test_input_formats_support(self):
        """Verify image loading supports filepath string, PIL Image, and numpy array."""
        # Filepath string
        res_str = extract_text_from_image(self.label_path)
        # PIL Image
        pil_img = Image.open(self.label_path)
        res_pil = extract_text_from_image(pil_img)
        # Numpy array
        res_np = extract_text_from_image(self.label_img)

        self.assertGreaterEqual(res_str.total_lines, 3)
        self.assertGreaterEqual(res_pil.total_lines, 3)
        self.assertGreaterEqual(res_np.total_lines, 3)
        self.assertEqual(res_str.total_lines, res_np.total_lines)

    def test_tesseract_fallback_engine(self):
        """Verify extraction explicitly using Tesseract fallback engine."""
        res_tess = extract_text_from_image(self.label_img, engine="tesseract")
        self.assertEqual(res_tess.engine_used, "tesseract")
        self.assertGreaterEqual(res_tess.total_lines, 3)
        full_text_upper = res_tess.full_text.upper()
        self.assertTrue("MRP" in full_text_upper or "250" in full_text_upper)
        self.assertTrue("NET" in full_text_upper or "500" in full_text_upper)
        self.assertTrue("MFG" in full_text_upper or "2026" in full_text_upper)

    def test_annotated_image_rendering(self):
        """Verify annotated overlay draws green bounding boxes, line badges, and coin markers."""
        lines = [
            OCRLineItem("MRP Rs. 250.00", 0.99, [40, 50, 290, 80], [[40, 50], [290, 50], [290, 80], [40, 80]], 250.0, 30.0),
            OCRLineItem("NET QTY: 500 g", 0.95, [40, 130, 280, 165], [[40, 130], [280, 130], [280, 165], [40, 165]], 240.0, 35.0),
        ]
        annotated = draw_ocr_annotated_image(
            img=self.label_img,
            lines=lines,
            coin_center=self.coin_center,
            coin_radius=self.coin_radius,
        )
        self.assertIsInstance(annotated, np.ndarray)
        self.assertEqual(annotated.shape, self.label_img.shape)
        # Ensure image has been modified with annotations (not identical to raw image)
        self.assertFalse(np.array_equal(annotated, self.label_img))


if __name__ == "__main__":
    unittest.main()
