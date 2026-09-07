"""Font measurement and Legal Metrology Rule 7 compliance module.

Calculates real-world font height (in millimeters) of parsed mandatory package declarations
using the reference coin calibration ratio (pixels-per-mm). Excludes ascenders/descenders
by applying an empirical cap-height estimation factor (~0.80).
Evaluates statutory minimum font height compliance according to Legal Metrology
(Packaged Commodities) Rules, 2011 (Rule 7, Table 1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

try:
    from src.field_parser import ExtractedField, ParsedFieldsResult
except ImportError:  # pragma: no cover
    ExtractedField = Any  # type: ignore
    ParsedFieldsResult = Any  # type: ignore

try:
    from src.calibration import CalibrationResult
except ImportError:  # pragma: no cover
    CalibrationResult = Any  # type: ignore

# Standard cap-height to total bounding box height factor (typically ~70-80% for printed typography)
DEFAULT_CAP_HEIGHT_FACTOR: float = 0.80

# Baseline statutory minimum font height under Rule 7 (in mm)
RULE_7_BASELINE_MIN_HEIGHT_MM: float = 1.0


@dataclass
class FontMeasurement:
    """Measurement record for an individual extracted label field."""

    field_name: str
    raw_text: str
    bbox_height_px: float
    cap_height_px: float
    font_height_mm: float
    calibration_px_per_mm: float
    is_calibrated: bool
    measurement_method: str
    rule7_min_height_mm: float = RULE_7_BASELINE_MIN_HEIGHT_MM
    is_rule7_compliant: bool = False
    status: str = "PENDING"

    @property
    def formatted_display(self) -> str:
        """Formatted string for UI tables, e.g. '3.42 mm (28.1 px)'."""
        if self.is_calibrated and self.calibration_px_per_mm > 0:
            return f"{self.font_height_mm:.2f} mm ({self.bbox_height_px:.1f} px)"
        return f"{self.bbox_height_px:.1f} px (Uncalibrated)"

    @property
    def compliance_badge(self) -> str:
        """Visual status badge string for Legal Metrology Rule 7."""
        if not self.is_calibrated:
            return "⚪ Uncalibrated"
        if self.is_rule7_compliant:
            return f"🟢 PASS (≥{self.rule7_min_height_mm:.1f} mm)"
        return f"🔴 DEFICIT ({self.font_height_mm:.2f} < {self.rule7_min_height_mm:.1f} mm)"


@dataclass
class FontMeasurementReport:
    """Aggregated measurement report across all parsed fields for a label scan."""

    measurements: Dict[str, FontMeasurement]
    calibrated_fields_count: int
    calibration_ratio_used: float
    summary: str
    compliant_fields_count: int = 0
    non_compliant_fields_count: int = 0


def get_rule7_minimum_height_mm(
    field_name: str,
    net_quantity_val: Optional[float] = None,
    unit: Optional[str] = None,
) -> float:
    """Get statutory minimum font height in mm under Rule 7 of Legal Metrology Rules, 2011.

    Under Rule 7 Table 1:
    - For Net Quantity:
        - Qty <= 50 g / ml: 1.0 mm
        - 50 < Qty <= 200 g / ml: 2.0 mm
        - 200 < Qty <= 1000 g / ml (or <= 1 kg / l): 4.0 mm
        - Qty > 1000 g / ml (or > 1 kg / l): 6.0 mm
    - For other general mandatory declarations:
        - Baseline statutory minimum is 1.0 mm (Rule 7 general provision).
    """
    if field_name == "net_quantity" and net_quantity_val is not None:
        unit_str = (unit or "").lower().strip()
        try:
            qty = float(net_quantity_val)
        except (ValueError, TypeError):
            m = re.search(r"[\d\.]+", str(net_quantity_val))
            qty = float(m.group(0)) if m else 0.0
        if unit_str in ["kg", "l", "liter", "litre", "kilogram"]:
            qty = qty * 1000.0

        if qty <= 50:
            return 1.0
        elif qty <= 200:
            return 2.0
        elif qty <= 1000:
            return 4.0
        else:
            return 6.0
    elif field_name == "net_quantity":
        # Default minimum when amount is not parsed but field exists
        return 2.0

    return RULE_7_BASELINE_MIN_HEIGHT_MM


def _extract_single_line_height(field_val: Any) -> float:
    """Safely extract bounding box height in pixels, adjusting for multi-line or wrapped text."""
    if field_val is None:
        return 0.0

    raw_text = _extract_raw_text(field_val)
    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
    num_lines = max(1, len(lines))

    h_px = 0.0
    w_px = 0.0

    # 1. Direct height_px or bbox_height_px attribute
    for attr in ("height_px", "bbox_height_px"):
        val = getattr(field_val, attr, None)
        if val is not None:
            try:
                h = float(val)
                if h > 0:
                    h_px = h
                    break
            except (ValueError, TypeError):
                pass

    # 2. Dictionary lookups
    if h_px == 0.0 and isinstance(field_val, dict):
        for key in ("height_px", "bbox_height_px"):
            if key in field_val and field_val[key] is not None:
                try:
                    h = float(field_val[key])
                    if h > 0:
                        h_px = h
                        break
                except (ValueError, TypeError):
                    pass

    # 3. From bbox geometry [x1, y1, x2, y2] or [ymin, xmin, ymax, xmax]
    bbox = getattr(field_val, "bbox", None)
    if bbox is None and isinstance(field_val, dict):
        bbox = field_val.get("bbox")

    if bbox and isinstance(bbox, (list, tuple)):
        if len(bbox) == 4 and all(isinstance(x, (int, float)) for x in bbox):
            h_calc = float(abs(bbox[3] - bbox[1]))
            w_calc = float(abs(bbox[2] - bbox[0]))
            if h_px == 0.0:
                h_px = h_calc
            w_px = w_calc
        elif len(bbox) == 4 and all(isinstance(pt, (list, tuple)) for pt in bbox):
            ys = [pt[1] for pt in bbox]
            xs = [pt[0] for pt in bbox]
            h_calc = float(max(ys) - min(ys))
            w_calc = float(max(xs) - min(xs))
            if h_px == 0.0:
                h_px = h_calc
            w_px = w_calc

    # 4. Numeric primitive
    if h_px == 0.0 and isinstance(field_val, (int, float)):
        h_px = float(field_val)

    if h_px <= 0:
        return 0.0

    # Adjust for multi-line text (explicit newlines)
    if num_lines > 1:
        return h_px / num_lines

    # Adjust for wrapped text using aspect ratio estimation
    if w_px > 0 and len(raw_text) > 0:
        # Assume an average character aspect ratio of ~0.5 (width/height)
        expected_w = len(raw_text) * h_px * 0.5
        if w_px < expected_w * 0.6:  # Actual width is much smaller -> wrapped
            estimated_lines = max(1, round(expected_w / w_px))
            if estimated_lines > 1:
                return h_px / estimated_lines

    return h_px


def _extract_raw_text(field_val: Any) -> str:
    """Safely extract raw text representation from a field value."""
    if field_val is None:
        return ""
    if hasattr(field_val, "raw_text") and field_val.raw_text is not None:
        return str(field_val.raw_text)
    if isinstance(field_val, dict):
        if "raw_text" in field_val and field_val["raw_text"] is not None:
            return str(field_val["raw_text"])
        if "text" in field_val and field_val["text"] is not None:
            return str(field_val["text"])
        if "extracted_value" in field_val and field_val["extracted_value"] is not None:
            return str(field_val["extracted_value"])
    if hasattr(field_val, "extracted_value") and field_val.extracted_value is not None:
        return str(field_val.extracted_value)
    return str(field_val)


def measure_font_heights(
    parsed_fields: Union[ParsedFieldsResult, Dict[str, Any], Any],
    calibration_result: Union[CalibrationResult, Dict[str, Any], float, None] = None,
    cap_height_factor: float = DEFAULT_CAP_HEIGHT_FACTOR,
) -> FontMeasurementReport:
    """Measure font heights in mm for parsed fields using coin calibration.

    Args:
        parsed_fields: ParsedFieldsResult object or dictionary of extracted fields.
        calibration_result: CalibrationResult, dict with pixels_per_mm, float ratio, or None.
        cap_height_factor: Multiplier to estimate cap-height from total bounding box (default ~0.80).

    Returns:
        FontMeasurementReport with per-field FontMeasurement objects and compliance statistics.
    """
    # 1. Normalize calibration parameters
    pixels_per_mm: float = 0.0
    is_calibrated: bool = False

    if calibration_result is not None:
        if isinstance(calibration_result, (int, float)):
            if calibration_result > 0:
                pixels_per_mm = float(calibration_result)
                is_calibrated = True
        elif isinstance(calibration_result, dict):
            pixels_per_mm = float(calibration_result.get("pixels_per_mm", 0.0))
            is_calibrated = bool(calibration_result.get("is_calibrated", pixels_per_mm > 0)) and (pixels_per_mm > 0)
        else:
            try:
                pixels_per_mm = float(getattr(calibration_result, "pixels_per_mm", 0.0))
                is_calibrated = bool(getattr(calibration_result, "is_calibrated", pixels_per_mm > 0)) and (pixels_per_mm > 0)
            except Exception:
                pixels_per_mm = 0.0
                is_calibrated = False

    # 2. Extract fields dictionary
    fields_dict: Dict[str, Any] = {}
    if hasattr(parsed_fields, "fields") and isinstance(parsed_fields.fields, dict):
        fields_dict = parsed_fields.fields
    elif isinstance(parsed_fields, dict):
        if "fields" in parsed_fields and isinstance(parsed_fields["fields"], dict):
            fields_dict = parsed_fields["fields"]
        else:
            fields_dict = parsed_fields
    elif parsed_fields is None:
        fields_dict = {}

    # 3. Detect Net Quantity amount if present (for Rule 7 Table 1 minimum calculation)
    net_qty_num: Optional[float] = None
    net_qty_unit: Optional[str] = None
    if "net_quantity" in fields_dict:
        nq_obj = fields_dict["net_quantity"]
        nq_val_str = getattr(nq_obj, "extracted_value", None)
        if nq_val_str is None and isinstance(nq_obj, dict):
            nq_val_str = nq_obj.get("extracted_value") or nq_obj.get("raw_text")
        nq_unit = getattr(nq_obj, "unit", None)
        if nq_unit is None and isinstance(nq_obj, dict):
            nq_unit = nq_obj.get("unit")
        net_qty_unit = str(nq_unit) if nq_unit else None

        if nq_val_str:
            num_match = re.search(r"[\d\.]+", str(nq_val_str))
            if num_match:
                try:
                    net_qty_num = float(num_match.group(0))
                except (ValueError, TypeError):
                    net_qty_num = None

    # 4. Measure each field
    measurements: Dict[str, FontMeasurement] = {}
    calibrated_count: int = 0
    compliant_count: int = 0
    non_compliant_count: int = 0

    for fname, fobj in fields_dict.items():
        raw_text = _extract_raw_text(fobj)
        bbox_height_px = _extract_single_line_height(fobj)
        cap_height_px = round(bbox_height_px * cap_height_factor, 2)

        if is_calibrated and pixels_per_mm > 0:
            font_height_mm = round(cap_height_px / pixels_per_mm, 2)
            method = f"coin_calibrated_cap_height_{int(cap_height_factor * 100)}"
            rule7_min = get_rule7_minimum_height_mm(fname, net_qty_num, net_qty_unit)
            is_compliant = font_height_mm >= rule7_min
            status = "PASS" if is_compliant else "NON_COMPLIANT"

            calibrated_count += 1
            if is_compliant:
                compliant_count += 1
            else:
                non_compliant_count += 1
        else:
            font_height_mm = 0.0
            method = "uncalibrated"
            rule7_min = get_rule7_minimum_height_mm(fname, net_qty_num, net_qty_unit)
            is_compliant = False
            status = "UNCALIBRATED"

        measurements[fname] = FontMeasurement(
            field_name=fname,
            raw_text=raw_text,
            bbox_height_px=bbox_height_px,
            cap_height_px=cap_height_px,
            font_height_mm=font_height_mm,
            calibration_px_per_mm=pixels_per_mm if is_calibrated else 0.0,
            is_calibrated=is_calibrated,
            measurement_method=method,
            rule7_min_height_mm=rule7_min,
            is_rule7_compliant=is_compliant,
            status=status,
        )

    # 5. Build summary narrative
    total_fields = len(measurements)
    if total_fields == 0:
        summary = "No fields evaluated for font measurement."
    elif is_calibrated:
        summary = (
            f"Measured {total_fields} field(s) with calibration {pixels_per_mm:.2f} px/mm "
            f"(Cap-height factor: {cap_height_factor:.2f}): "
            f"{compliant_count}/{total_fields} compliant with Rule 7, "
            f"{non_compliant_count} deficit."
        )
    else:
        summary = (
            f"Evaluated {total_fields} field(s) in uncalibrated mode. "
            f"Pixel heights recorded; real-world mm font heights and Rule 7 compliance require coin calibration."
        )

    return FontMeasurementReport(
        measurements=measurements,
        calibrated_fields_count=calibrated_count,
        calibration_ratio_used=pixels_per_mm if is_calibrated else 0.0,
        summary=summary,
        compliant_fields_count=compliant_count,
        non_compliant_fields_count=non_compliant_count,
    )
