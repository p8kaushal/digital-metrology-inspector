import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from src.ocr_engine import extract_text_from_image
from src.field_parser import parse_ocr_lines
from src.font_measurement import measure_font_heights
from src.calibration import compute_calibration

def run_verification():
    image_path = "data/scans_cache/back_cache_p1_food_snacks_back.png"
    print(f"Running verification on {image_path}")
    
    calib_result = compute_calibration(422.6)
    print(f"Calibrated: {calib_result.pixels_per_mm:.2f} px/mm")

    print("Running OCR...")
    ocr_results = extract_text_from_image(image_path)
    
    print("Parsing fields...")
    parsed_fields = parse_ocr_lines(ocr_results)
    print(f"Parsed fields: {list(parsed_fields.fields.keys())}")
    
    print("Measuring font heights...")
    report = measure_font_heights(parsed_fields, calib_result)
    
    print("\n--- Font Height Measurements ---")
    for field, m in report.measurements.items():
        print(f"{field}: {m.font_height_mm:.2f} mm (bbox: {m.bbox_height_px:.1f} px, status: {m.status}, text: '{m.raw_text}')")
        if m.font_height_mm > 0:
            if not (1.0 <= m.font_height_mm <= 4.0):
                print(f"  --> WARNING: {field} height {m.font_height_mm} mm is out of expected 1.0 - 4.0 mm range")
            else:
                print(f"  --> PASS expected range")
                
if __name__ == "__main__":
    run_verification()
