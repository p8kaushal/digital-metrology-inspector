import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.calibration import (
    compute_calibration,
    pixels_to_mm,
    mm_to_pixels,
    INDIAN_5_RUPEE_COIN_DIAMETER_MM
)
from src.coin_detector import CoinDetectionResult

class TestTask6Calibration(unittest.TestCase):
    def test_compute_calibration_with_float(self):
        result = compute_calibration(219.0)
        self.assertTrue(result.is_calibrated)
        self.assertAlmostEqual(result.pixels_per_mm, 10.0, places=2)
        self.assertAlmostEqual(result.mm_per_pixel, 0.1, places=2)
        
        result2 = compute_calibration(438.0)
        self.assertTrue(result2.is_calibrated)
        self.assertAlmostEqual(result2.pixels_per_mm, 20.0, places=2)
        
    def test_compute_calibration_with_dict(self):
        result = compute_calibration({'detected': True, 'pixel_diameter': 219.0})
        self.assertTrue(result.is_calibrated)
        self.assertAlmostEqual(result.pixels_per_mm, 10.0, places=2)
        
        failed = compute_calibration({'detected': False, 'pixel_diameter': 0.0})
        self.assertFalse(failed.is_calibrated)
        
    def test_compute_calibration_with_dataclass(self):
        coin = CoinDetectionResult(
            detected=True,
            center=(100, 100),
            radius=109.5,
            pixel_diameter=219.0,
            confidence=0.9,
            annotated_image=None,
            message="OK"
        )
        result = compute_calibration(coin)
        self.assertTrue(result.is_calibrated)
        self.assertAlmostEqual(result.pixels_per_mm, 10.0, places=2)
        
        coin_fail = CoinDetectionResult(
            detected=False,
            center=None,
            radius=0,
            pixel_diameter=0,
            confidence=0.0,
            annotated_image=None,
            message="Fail"
        )
        result_fail = compute_calibration(coin_fail)
        self.assertFalse(result_fail.is_calibrated)

    def test_pixels_to_mm(self):
        self.assertAlmostEqual(pixels_to_mm(100.0, 10.0), 10.0, places=2)
        self.assertAlmostEqual(pixels_to_mm(25.0, 10.0), 2.5, places=2)
        
    def test_mm_to_pixels(self):
        self.assertAlmostEqual(mm_to_pixels(10.0, 10.0), 100.0, places=2)
        self.assertAlmostEqual(mm_to_pixels(2.5, 10.0), 25.0, places=2)

if __name__ == '__main__':
    unittest.main()
