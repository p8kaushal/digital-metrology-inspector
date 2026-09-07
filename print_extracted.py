import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))
from src.field_parser import parse_ocr_lines

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
    {"text": "UNIT SALE PRICE Rs. 0.30/g", "confidence": 0.95, "bbox": [10, 210, 100, 220]}
]

result = parse_ocr_lines(ocr_lines)
print(result.fields.get('unit_sale_price'))
