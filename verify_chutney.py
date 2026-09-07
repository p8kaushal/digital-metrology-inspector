import os
import sys
import json
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))
from src.ocr_engine import extract_text_from_image
from src.field_parser import parse_ocr_lines

image_path = sys.argv[1] if len(sys.argv) > 1 else 'data/scans_cache/back_IMG_2445.jpg'
if not os.path.exists(image_path):
    print("Could not find image at", image_path)
    sys.exit(1)

res = extract_text_from_image(image_path)
print(f"Extracted {res.total_lines} lines using {res.engine_used}")

parsed = parse_ocr_lines(res.lines)
out_fields = {}
for k, v in parsed.fields.items():
    out_fields[k] = v.extracted_value

print("Extracted Data JSON:")
print(json.dumps(out_fields, indent=2))
