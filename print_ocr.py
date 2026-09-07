import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))
from src.ocr_engine import extract_text_from_image

image_path = 'data/scans_cache/back_IMG_2444.jpg'
res = extract_text_from_image(image_path)
for l in res.lines:
    print(f"[{l.confidence:.2f}] {l.text}")
