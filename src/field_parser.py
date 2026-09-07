import re
from dataclasses import dataclass, field
from typing import List, Dict, Union, Any

@dataclass
class ExtractedField:
    field_name: str
    raw_text: str
    extracted_value: str
    unit: Union[str, None]
    confidence: float
    line_number: int
    bbox: List[int]
    height_px: float
    is_mandatory: bool

@dataclass
class ParsedFieldsResult:
    fields: Dict[str, ExtractedField]
    missing_mandatory_fields: List[str]
    total_fields_found: int
    overall_confidence: float

MANDATORY_FIELDS = [
    'mrp',
    'net_quantity',
    'manufacturer_details',
    'mfg_date',
    'expiry_date',
    'batch_number',
    'consumer_care',
    'country_of_origin',
    'unit_sale_price'
]

def _extract_height(bbox: List[int]) -> float:
    if not bbox or len(bbox) != 4:
        return 0.0
    return float(bbox[3] - bbox[1])

def parse_ocr_lines(ocr_lines: Any) -> ParsedFieldsResult:
    """
    Parse OCR lines to extract mandatory legal metrology fields.
    """
    
    # Normalize input
    lines = []
    
    # Attempt to extract lines from OCRExtractionResult
    if hasattr(ocr_lines, 'lines'):
        lines_data = getattr(ocr_lines, 'lines')
    else:
        lines_data = ocr_lines
        
    for i, item in enumerate(lines_data):
        if hasattr(item, 'text'):
            text = getattr(item, 'text')
            conf = getattr(item, 'confidence', 1.0)
            bbox = getattr(item, 'bbox', [0, 0, 0, 0])
        elif isinstance(item, dict):
            text = item.get('text', '')
            conf = item.get('confidence', 1.0)
            bbox = item.get('bbox', [0, 0, 0, 0])
        else:
            continue
            
        lines.append({
            'text': text,
            'confidence': conf,
            'bbox': bbox,
            'line_number': i
        })
        
    extracted_fields: Dict[str, ExtractedField] = {}
    
    patterns = {
        'mrp': r"(?:M\.?R\.?P\.?|MAXIMUM\s*RETAIL\s*PRICE|MRP)\s*(?:RS\.?|INR|₹)?\s*[:\-\.]?\s*(?:RS\.?|INR|₹)?\s*([\d\.,]+)",
        'net_quantity': r"(?:NET\s*(?:QTY|QUANTITY|WT|WEIGHT|VOL|VOLUME)|(?:NET\s*)?WEIGHT|CONTENT(?:S)?)\s*[:\-]?\s*([\d\.]+)\s*(g|kg|ml|l|liter|litre|pieces|pcs|n)",
        'mfg_date': r"(?:MFG\.?\s*(?:DATE)?|PKD\.?\s*(?:DATE)?|MANUFACTURED|PACKED)\s*(?:ON|DATE)?\s*[:\-]?\s*([\d]{2,4}[/\-][\d]{2,4}|[A-Za-z]+\s*[\d]{2,4})",
        'expiry_date': r"(?:EXP(?:IRY)?\.?\s*(?:DATE)?|USE\s*(?:BY|BEFORE)|BEST\s*BEFORE)\s*[:\-]?\s*([\d]{2,4}[/\-][\d]{2,4}|[A-Za-z]+\s*[\d]{2,4}|[\d]+\s*(?:MONTHS|YEARS)\s*FROM\s*(?:MFG|PACKAGING|DATE))",
        'batch_number': r"(?:BATCH|LOT)\s*(?:NO\.?|NUMBER)?\s*[:\-]?\s*([A-Za-z0-9\-\/]+)",
        'country_of_origin': r"(?:MADE\s*IN|COUNTRY\s*OF\s*ORIGIN|PRODUCT\s*OF)\s*[:\-]?\s*([A-Za-z\s]+)",
        'unit_sale_price': r"(?:USP|UNIT\s*SALE\s*PRICE|RS\.?\s*[\d\.]+\s*(?:PER|\/)\s*(?:G|ML|KG|L|PC|N))",
    }
    
    # Simple single-line parsing first
    for i, line_dict in enumerate(lines):
        text_line = line_dict['text']
        
        for field_name, pattern in patterns.items():
            if field_name in extracted_fields:
                continue
                
            match = re.search(pattern, text_line, re.IGNORECASE)
            if match:
                try:
                    val = match.group(1).strip()
                except IndexError:
                    val = match.group(0).strip()
                
                unit = None
                try:
                    if len(match.groups()) > 1:
                        unit = match.group(2).strip()
                except IndexError:
                    pass
                    
                if field_name == 'unit_sale_price':
                    val = match.group(0).strip()
                    
                extracted_fields[field_name] = ExtractedField(
                    field_name=field_name,
                    raw_text=line_dict['text'],
                    extracted_value=val,
                    unit=unit,
                    confidence=line_dict['confidence'],
                    line_number=line_dict['line_number'],
                    bbox=line_dict['bbox'],
                    height_px=_extract_height(line_dict['bbox']),
                    is_mandatory=True
                )
    
    # Contextual parsing for multiline (Manufacturer, Consumer Care)
    manufacturer_markers = [r"MFG\.?\s*BY", r"MANUFACTURED\s*BY", r"PACKED\s*BY", r"MKTD\.?\s*BY", r"MARKETED\s*BY", r"IMPORTED\s*BY"]
    care_markers = [r"CONSUMER\s*CARE", r"CUSTOMER\s*CARE", r"TOLL\s*FREE", r"FEEDBACK", r"COMPLAINTS?"]
    
    def extract_multiline(markers, field_name, max_lines=4):
        if field_name in extracted_fields:
            return
        for i, line_dict in enumerate(lines):
            text_line = line_dict['text']
            if any(re.search(marker, text_line, re.IGNORECASE) for marker in markers):
                combined_text = [line_dict['text']]
                bbox = line_dict['bbox'].copy() if line_dict['bbox'] else [0,0,0,0]
                conf_sum = line_dict['confidence']
                count = 1
                
                for j in range(i + 1, min(i + max_lines, len(lines))):
                    next_text = lines[j]['text']
                    # Stop if we hit another key field pattern
                    hit_other = False
                    for pat in patterns.values():
                        if re.search(pat, next_text, re.IGNORECASE):
                            hit_other = True
                            break
                    if any(re.search(m, next_text, re.IGNORECASE) for m in (manufacturer_markers + care_markers)):
                        hit_other = True
                        
                    if hit_other:
                        break
                        
                    combined_text.append(next_text)
                    conf_sum += lines[j]['confidence']
                    count += 1
                    
                    if lines[j]['bbox']:
                        bbox[2] = max(bbox[2], lines[j]['bbox'][2])
                        bbox[3] = max(bbox[3], lines[j]['bbox'][3])
                        
                extracted_fields[field_name] = ExtractedField(
                    field_name=field_name,
                    raw_text=" ".join(combined_text),
                    extracted_value=" ".join(combined_text),
                    unit=None,
                    confidence=conf_sum / count,
                    line_number=line_dict['line_number'],
                    bbox=bbox,
                    height_px=_extract_height(bbox),
                    is_mandatory=True
                )
                break
                
    extract_multiline(manufacturer_markers, 'manufacturer_details')
    extract_multiline(care_markers, 'consumer_care')
    
    missing = [f for f in MANDATORY_FIELDS if f not in extracted_fields]
    avg_conf = sum(f.confidence for f in extracted_fields.values()) / len(extracted_fields) if extracted_fields else 0.0
    
    return ParsedFieldsResult(
        fields=extracted_fields,
        missing_mandatory_fields=missing,
        total_fields_found=len(extracted_fields),
        overall_confidence=avg_conf
    )
