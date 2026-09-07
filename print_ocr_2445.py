import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))
from src.ocr_engine import extract_text_from_image
from src.field_parser import parse_ocr_lines
import json

image_path = 'data/scans_cache/back_IMG_2445.jpg'
res = extract_text_from_image(image_path)
print("Lines extracted:", res.total_lines)
parsed = parse_ocr_lines(res.lines)
out_fields = {}
for k, v in parsed.fields.items():
    out_fields[k] = v.extracted_value
print(json.dumps(out_fields, indent=2))
