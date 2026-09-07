import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))
print("Importing detect_coin")
from src.coin_detector import detect_coin
import cv2
print("Loading image")
img = cv2.imread("data/scans_cache/back_IMG_2444.jpg")
print("Detecting coin")
res = detect_coin(img)
print(f"Coin diameter: {res.pixel_diameter}")
