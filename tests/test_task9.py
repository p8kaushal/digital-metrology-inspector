import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.field_parser import parse_ocr_lines, MANDATORY_FIELDS, ParsedFieldsResult

def test_parse_ocr_lines_food_packaging():
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
    
    assert isinstance(result, ParsedFieldsResult), "Result is not a ParsedFieldsResult"
    assert result.total_fields_found == 9, f"Expected 9, got {result.total_fields_found}"
    assert len(result.missing_mandatory_fields) == 0, f"Expected 0 missing, got {result.missing_mandatory_fields}"
    assert result.fields['mrp'].extracted_value == "150.00"
    assert result.fields['net_quantity'].extracted_value == "500"
    assert result.fields['net_quantity'].unit.lower() == "g"
    assert result.fields['mfg_date'].extracted_value == "08/2026"
    assert result.fields['batch_number'].extracted_value == "B-1234"
    assert result.fields['country_of_origin'].extracted_value == "INDIA"
    assert "Acme Corp" in result.fields['manufacturer_details'].extracted_value
    assert "1800-111-222" in result.fields['consumer_care'].extracted_value
    assert "0.30/g" in result.fields['unit_sale_price'].extracted_value.lower() or "0.30/g" in result.fields['unit_sale_price'].raw_text.lower()

def test_parse_ocr_lines_missing_fields():
    ocr_lines = [
        {"text": "Some random text on package", "confidence": 0.9, "bbox": [0,0,10,10]},
        {"text": "NET QTY: 1 kg", "confidence": 0.9, "bbox": [0,20,10,30]}
    ]
    
    result = parse_ocr_lines(ocr_lines)
    assert result.total_fields_found == 1
    assert len(result.missing_mandatory_fields) == 8
    assert "mrp" in result.missing_mandatory_fields
    assert "net_quantity" not in result.missing_mandatory_fields

if __name__ == "__main__":
    test_parse_ocr_lines_food_packaging()
    test_parse_ocr_lines_missing_fields()
    print("All tests passed successfully.")
