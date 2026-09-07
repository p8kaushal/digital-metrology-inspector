import unittest
import cv2
import numpy as np
import os
from src.coin_detector import detect_coin

class TestTask5(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = []
        cls.paths.append(cls.create_synthetic_coin_image("test_coin_120.jpg", 120, False))
        cls.paths.append(cls.create_synthetic_coin_image("test_coin_180.jpg", 180, True))
        cls.paths.append(cls.create_non_coin_image("test_no_coin.jpg"))

    @classmethod
    def tearDownClass(cls):
        for p in cls.paths:
            if os.path.exists(p):
                os.remove(p)

    @staticmethod
    def create_synthetic_coin_image(filename: str, diameter: int, bg_noise: bool = False):
        img_size = 500
        img = np.ones((img_size, img_size, 3), dtype=np.uint8) * 255
        
        if bg_noise:
            noise = np.random.randint(0, 50, (img_size, img_size, 3), dtype=np.uint8)
            img = cv2.add(img, noise)
            
        center = (img_size // 2, img_size // 2)
        radius = diameter // 2
        
        # Draw a coin-like circle
        cv2.circle(img, center, radius, (50, 50, 50), -1)
        
        cv2.imwrite(filename, img)
        return filename

    @staticmethod
    def create_non_coin_image(filename: str):
        img_size = 500
        img = np.ones((img_size, img_size, 3), dtype=np.uint8) * 255
        
        # Draw a square instead of a circle
        cv2.rectangle(img, (100, 100), (400, 400), (100, 100, 100), -1)
        
        cv2.imwrite(filename, img)
        return filename

    def test_detect_coin_120px(self):
        res = detect_coin(self.paths[0], minRadius=50, maxRadius=100)
        self.assertTrue(res.detected)
        self.assertIsNotNone(res.center)
        
        expected_diameter = 120
        tolerance = expected_diameter * 0.03
        self.assertTrue(abs(res.pixel_diameter - expected_diameter) <= tolerance)

    def test_detect_coin_180px_with_noise(self):
        res = detect_coin(self.paths[1], minRadius=70, maxRadius=120)
        self.assertTrue(res.detected)
        self.assertIsNotNone(res.center)
        
        expected_diameter = 180
        tolerance = expected_diameter * 0.03
        self.assertTrue(abs(res.pixel_diameter - expected_diameter) <= tolerance)

    def test_detect_non_coin(self):
        res = detect_coin(self.paths[2])
        self.assertFalse(res.detected)
        self.assertIsNone(res.center)
        self.assertEqual(res.pixel_diameter, 0.0)

    def test_invalid_image_path(self):
        res = detect_coin("invalid_path_to_image.xyz")
        self.assertFalse(res.detected)

if __name__ == '__main__':
    unittest.main()
