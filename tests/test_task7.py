import unittest
import os
import sys
import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.text_detector import (
    TextRegion,
    TextDetectionResult,
    detect_text_regions,
    is_in_coin_roi,
    load_image,
)

class TestTask7TextRegionDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_files = []

        # 1. Standard synthetic packaging label with text blocks and a coin
        cls.synthetic_label_path = "tests/test_label_with_coin.png"
        cls.coin_center = (600, 300)
        cls.coin_radius = 55

        img = np.ones((650, 800, 3), dtype=np.uint8) * 255
        # Text blocks
        cv2.putText(img, "MRP Rs. 100", (80, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 2)
        cv2.putText(img, "NET QTY: 500g", (80, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 2)
        cv2.putText(img, "Mfg Date: 01/2026", (80, 370), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        cv2.putText(img, "Batch No: B1042", (80, 480), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)

        # Draw a coin at (600, 300) with coin details
        cv2.circle(img, cls.coin_center, cls.coin_radius, (0, 0, 0), 3)
        cv2.putText(img, "5 RUPEES", (cls.coin_center[0] - 45, cls.coin_center[1] + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        cv2.imwrite(cls.synthetic_label_path, img)
        cls.test_files.append(cls.synthetic_label_path)
        cls.synthetic_img = img

        # 2. Blank white image
        cls.blank_path = "tests/test_blank.png"
        blank = np.ones((300, 300, 3), dtype=np.uint8) * 255
        cv2.imwrite(cls.blank_path, blank)
        cls.test_files.append(cls.blank_path)

    @classmethod
    def tearDownClass(cls):
        for f in cls.test_files:
            if os.path.exists(f):
                os.remove(f)

    def test_detect_text_regions_basic_count_and_dataclass(self):
        """Verify text region detection count, bounding box, dimensions, and dataclass fields."""
        result = detect_text_regions(
            image_input=self.synthetic_label_path,
            coin_center=self.coin_center,
            coin_radius=self.coin_radius,
            merge_lines=True,
        )

        self.assertIsInstance(result, TextDetectionResult)
        self.assertGreaterEqual(result.total_regions, 4, "Expected at least 4 text line regions detected")
        self.assertEqual(len(result.regions), result.total_regions)
        self.assertIsNotNone(result.annotated_image)
        self.assertIn("morphology", result.message)

        # Verify attributes of each TextRegion
        for idx, region in enumerate(result.regions):
            self.assertIsInstance(region, TextRegion)
            x_min, y_min, x_max, y_max = region.bbox
            self.assertLess(x_min, x_max, f"Invalid bbox width in region {idx}")
            self.assertLess(y_min, y_max, f"Invalid bbox height in region {idx}")

            self.assertEqual(region.width_px, float(x_max - x_min))
            self.assertEqual(region.height_px, float(y_max - y_min))

            self.assertGreaterEqual(region.confidence, 0.5)
            self.assertLessEqual(region.confidence, 1.0)

            # Check polygon has 4 corner vertices
            self.assertEqual(len(region.polygon), 4)
            self.assertEqual(region.polygon[0], [x_min, y_min])
            self.assertEqual(region.polygon[1], [x_max, y_min])
            self.assertEqual(region.polygon[2], [x_max, y_max])
            self.assertEqual(region.polygon[3], [x_min, y_max])

    def test_coin_roi_exclusion_logic(self):
        """Verify that coin markings are detected without exclusion, and excluded when coin ROI is passed."""
        # 1. Detection WITHOUT coin exclusion
        res_no_excl = detect_text_regions(
            image_input=self.synthetic_img,
            coin_center=None,
            coin_radius=None,
        )
        has_coin_region_without_excl = any(
            is_in_coin_roi(r.bbox, self.coin_center, self.coin_radius)
            for r in res_no_excl.regions
        )
        self.assertTrue(
            has_coin_region_without_excl,
            "Coin features should be detected when coin exclusion is disabled."
        )

        # 2. Detection WITH coin exclusion
        res_with_excl = detect_text_regions(
            image_input=self.synthetic_img,
            coin_center=self.coin_center,
            coin_radius=self.coin_radius,
        )
        for r in res_with_excl.regions:
            in_coin = is_in_coin_roi(r.bbox, self.coin_center, self.coin_radius)
            self.assertFalse(
                in_coin,
                f"Region at {r.bbox} should not be inside coin ROI {self.coin_center} with radius {self.coin_radius}"
            )

        # Confirm the label declarations were still detected
        self.assertGreaterEqual(res_with_excl.total_regions, 4)

    def test_bounding_box_dimensions(self):
        """Verify text region bounding box covers the synthetic text blocks accurately."""
        res = detect_text_regions(
            image_input=self.synthetic_img,
            coin_center=self.coin_center,
            coin_radius=self.coin_radius,
            merge_lines=True,
        )

        # Check that regions cover the text lines around y ~ 150, 260, 370, 480
        y_centers = [(r.bbox[1] + r.bbox[3]) / 2.0 for r in res.regions]

        # Expect text lines near y=138, 242, 342, 452 (baseline offsets)
        found_mrp = any(110 <= yc <= 170 for yc in y_centers)
        found_qty = any(220 <= yc <= 280 for yc in y_centers)
        found_mfg = any(330 <= yc <= 390 for yc in y_centers)
        found_batch = any(440 <= yc <= 500 for yc in y_centers)

        self.assertTrue(found_mrp, "MRP text line not captured within expected y-bounds")
        self.assertTrue(found_qty, "NET QTY text line not captured within expected y-bounds")
        self.assertTrue(found_mfg, "Mfg Date text line not captured within expected y-bounds")
        self.assertTrue(found_batch, "Batch No text line not captured within expected y-bounds")

    def test_annotated_image_cyan_boxes(self):
        """Verify annotated image contains cyan bounding boxes (BGR: [255, 255, 0])."""
        res = detect_text_regions(
            image_input=self.synthetic_img,
            coin_center=self.coin_center,
            coin_radius=self.coin_radius,
        )
        self.assertIsNotNone(res.annotated_image)
        ann = res.annotated_image
        self.assertEqual(ann.shape, self.synthetic_img.shape)

        # Cyan in OpenCV BGR: B=255, G=255, R=0
        cyan_mask = (ann[:, :, 0] == 255) & (ann[:, :, 1] == 255) & (ann[:, :, 2] == 0)
        cyan_count = np.count_nonzero(cyan_mask)
        self.assertGreater(cyan_count, 100, "Annotated image must contain cyan pixels for bounding boxes")

    def test_input_handling_types(self):
        """Verify filepath, PIL Image, and numpy array all work seamlessly."""
        # 1. Filepath string
        res_str = detect_text_regions(self.synthetic_label_path, self.coin_center, self.coin_radius)
        self.assertGreaterEqual(res_str.total_regions, 4)

        # 2. PIL Image
        pil_img = Image.open(self.synthetic_label_path)
        res_pil = detect_text_regions(pil_img, self.coin_center, self.coin_radius)
        self.assertEqual(res_pil.total_regions, res_str.total_regions)

        # 3. numpy ndarray
        np_img = cv2.imread(self.synthetic_label_path)
        res_np = detect_text_regions(np_img, self.coin_center, self.coin_radius)
        self.assertEqual(res_np.total_regions, res_str.total_regions)

    def test_empty_and_invalid_inputs(self):
        """Verify robust error handling for invalid paths and blank images."""
        # Nonexistent file
        res_invalid = detect_text_regions("nonexistent_path_123.jpg")
        self.assertEqual(res_invalid.total_regions, 0)
        self.assertEqual(len(res_invalid.regions), 0)
        self.assertIsNone(res_invalid.annotated_image)
        self.assertIn("error", res_invalid.message.lower())

        # Blank white image
        res_blank = detect_text_regions(self.blank_path)
        self.assertEqual(res_blank.total_regions, 0)
        self.assertEqual(len(res_blank.regions), 0)

        # Unsupported type
        res_type = detect_text_regions(12345)
        self.assertEqual(res_type.total_regions, 0)
        self.assertIn("error", res_type.message.lower())

    def test_word_vs_line_mode(self):
        """Verify both line merging and word-level modes work as expected."""
        res_lines = detect_text_regions(self.synthetic_img, self.coin_center, self.coin_radius, merge_lines=True)
        res_words = detect_text_regions(self.synthetic_img, self.coin_center, self.coin_radius, merge_lines=False)

        # Word mode should have more individual boxes than line mode
        self.assertGreater(res_words.total_regions, res_lines.total_regions)

if __name__ == '__main__':
    unittest.main()
