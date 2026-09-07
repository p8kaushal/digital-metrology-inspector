"""Data Consolidation Module for Digital Metrology Inspector (Task 12).

Consolidates extracted packaging declarations and font measurements across Front and Back
panels into a unified ConsolidatedProductRecord. Resolves field conflicts using confidence
scores and domain-aware panel priority weighting, calculates Legal Metrology mandatory
declaration completeness across statutory fields, and persists records to the Supabase
products table.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from src import db

# Configure module logger
logger = logging.getLogger("metrology_inspector.consolidation")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [CONSOLIDATION] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# The 9 mandatory packaging declarations under Legal Metrology (Packaged Commodities) Rules, 2011
MANDATORY_DECLARATIONS: List[str] = [
    "mrp",
    "net_quantity",
    "manufacturer_details",
    "mfg_date",
    "expiry_date",
    "batch_number",
    "consumer_care",
    "country_of_origin",
    "unit_sale_price",
]

# Domain-informed panel priority weighting:
# - Front panel (Principal Display Panel) typically emphasizes Brand Name, Net Quantity, and MRP.
# - Back panel (Information Panel) typically contains statutory disclosures such as Manufacturer Details,
#   Batch Number, Consumer Care, Mfg/Expiry Dates, and Unit Sale Price.
DEFAULT_PANEL_WEIGHTS: Dict[str, Dict[str, float]] = {
    "brand_name": {"front": 1.25, "back": 1.0},
    "brand": {"front": 1.25, "back": 1.0},
    "net_quantity": {"front": 1.15, "back": 1.0},
    "mrp": {"front": 1.10, "back": 1.0},
    "manufacturer_details": {"front": 1.0, "back": 1.25},
    "consumer_care": {"front": 1.0, "back": 1.25},
    "batch_number": {"front": 1.0, "back": 1.20},
    "mfg_date": {"front": 1.0, "back": 1.15},
    "expiry_date": {"front": 1.0, "back": 1.15},
    "country_of_origin": {"front": 1.0, "back": 1.15},
    "unit_sale_price": {"front": 1.0, "back": 1.15},
}


@dataclass
class ConsolidatedProductRecord:
    """Consolidated product master record combining front and back label declarations."""

    product_id: str = ""
    brand_name: str = ""
    mrp: str = ""
    net_quantity: str = ""
    mfg_date: str = ""
    expiry_date: str = ""
    batch_number: str = ""
    manufacturer_details: str = ""
    consumer_care: str = ""
    country_of_origin: str = ""
    unit_sale_price: str = ""
    front_fields: dict = field(default_factory=dict)
    back_fields: dict = field(default_factory=dict)
    font_measurements: dict = field(default_factory=dict)
    completeness_pct: float = 0.0
    missing_declarations: list[str] = field(default_factory=list)
    resolved_conflicts: list = field(default_factory=list)

    @property
    def total_declarations_present(self) -> int:
        """Count of mandatory declarations with non-empty values."""
        return len(MANDATORY_DECLARATIONS) - len(self.missing_declarations)

    @property
    def is_complete(self) -> bool:
        """True if all 9 mandatory declarations are declared."""
        return len(self.missing_declarations) == 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary representation."""
        return asdict(self)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_db_payload(self) -> Dict[str, Any]:
        """Convert record to a schema-compatible dictionary for the Supabase products table."""
        mrp_numeric = None
        if self.mrp:
            cleaned = re.sub(r"[^\d\.]", "", self.mrp)
            try:
                if cleaned:
                    mrp_numeric = float(cleaned)
            except (ValueError, TypeError):
                mrp_numeric = None

        return {
            "id": self.product_id,
            "name": self.brand_name or "Packaged Commodity",
            "brand": self.brand_name or "",
            "net_quantity_declared": self.net_quantity,
            "mrp_declared": mrp_numeric,
            "manufacturer_name": self.manufacturer_details,
            "consumer_care": self.consumer_care,
            "country_of_origin": self.country_of_origin,
            # Additional convenience fields preserved in mock database store
            "mrp": self.mrp,
            "net_quantity": self.net_quantity,
            "mfg_date": self.mfg_date,
            "expiry_date": self.expiry_date,
            "batch_number": self.batch_number,
            "unit_sale_price": self.unit_sale_price,
            "completeness_pct": self.completeness_pct,
            "missing_declarations": list(self.missing_declarations),
        }


def _extract_field_details(f_obj: Any, field_name: str) -> Dict[str, Any]:
    """Normalize extracted field object, dictionary, or primitive into a standard dictionary."""
    if f_obj is None:
        return {
            "value": "",
            "raw_text": "",
            "confidence": 0.0,
            "unit": None,
            "bbox": None,
            "height_px": 0.0,
            "raw_obj": None,
        }

    raw_text = ""
    val = ""
    unit = None
    confidence = 1.0
    bbox = None
    height_px = 0.0

    # Case 1: ExtractedField or class with attributes
    if hasattr(f_obj, "extracted_value"):
        val = getattr(f_obj, "extracted_value", "")
        raw_text = getattr(f_obj, "raw_text", "")
        unit = getattr(f_obj, "unit", None)
        confidence = float(getattr(f_obj, "confidence", 1.0))
        bbox = getattr(f_obj, "bbox", None)
        height_px = float(getattr(f_obj, "height_px", 0.0))
    elif isinstance(f_obj, dict):
        val = f_obj.get("extracted_value") or f_obj.get("value") or f_obj.get("parsed_value", "")
        raw_text = f_obj.get("raw_text") or f_obj.get("text", "")
        unit = f_obj.get("unit")
        confidence = float(f_obj.get("confidence", 1.0))
        bbox = f_obj.get("bbox") or f_obj.get("bounding_box")
        height_px = float(f_obj.get("height_px") or f_obj.get("font_height_px", 0.0))
    else:
        # String or primitive
        val = str(f_obj)
        raw_text = str(f_obj)
        confidence = 1.0

    val_str = str(val).strip() if val is not None else ""

    # Unit formatting for net quantity if unit not already included
    if field_name == "net_quantity" and unit and unit.lower() not in val_str.lower():
        val_str = f"{val_str} {unit}".strip()

    return {
        "value": val_str,
        "raw_text": raw_text,
        "confidence": confidence,
        "unit": unit,
        "bbox": bbox,
        "height_px": height_px,
        "raw_obj": f_obj,
    }


def _normalize_panel_input(panel_input: Any) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Normalize input from either ParsedFieldsResult or dictionary into structured mappings.

    Returns:
        Tuple of (normalized_fields_dict, raw_fields_dict)
    """
    if panel_input is None:
        return {}, {}

    raw_items: Dict[str, Any] = {}
    if hasattr(panel_input, "fields"):
        raw_items = getattr(panel_input, "fields", {})
    elif isinstance(panel_input, dict):
        raw_items = panel_input
    else:
        return {}, {}

    normalized: Dict[str, Dict[str, Any]] = {}
    raw_dict: Dict[str, Any] = {}

    for k, v in raw_items.items():
        k_norm = str(k).lower().strip()
        details = _extract_field_details(v, k_norm)
        normalized[k_norm] = details
        raw_dict[k_norm] = v

    return normalized, raw_dict


def _normalize_fonts_input(fonts_input: Any) -> Dict[str, Any]:
    """Normalize FontMeasurementReport or dictionary of FontMeasurements into a mapping."""
    if fonts_input is None:
        return {}

    if hasattr(fonts_input, "measurements"):
        return dict(getattr(fonts_input, "measurements", {}))
    elif isinstance(fonts_input, dict):
        return dict(fonts_input)
    return {}


def consolidate_scan_records(
    front_parsed: Any = None,
    back_parsed: Any = None,
    front_fonts: Any = None,
    back_fonts: Any = None,
    scan_id: Optional[str] = None,
    panel_weights: Optional[Dict[str, Dict[str, float]]] = None,
) -> ConsolidatedProductRecord:
    """Consolidate extractions from front and back packaging panels into a unified product record.

    Performs:
    1. Normalization of polymorphic front and back parsed fields.
    2. Conflict resolution using confidence scores and panel priority weighting.
    3. Font measurement assignment for unified declarations.
    4. Mandatory Legal Metrology declaration completeness computation.
    5. Persistence of the consolidated product record to the Supabase products table via db.create_product.

    Args:
        front_parsed: Parsed fields from front label (ParsedFieldsResult or dict).
        back_parsed: Parsed fields from back label (ParsedFieldsResult or dict).
        front_fonts: Font measurement report or dict for front label.
        back_fonts: Font measurement report or dict for back label.
        scan_id: Optional scan UUID string to link the product record.
        panel_weights: Optional custom dictionary of panel weights per field name.

    Returns:
        ConsolidatedProductRecord containing unified fields, completeness metrics, and persistence ID.
    """
    weights = panel_weights or DEFAULT_PANEL_WEIGHTS

    # 1. Normalize front and back parsed fields
    norm_front, raw_front = _normalize_panel_input(front_parsed)
    norm_back, raw_back = _normalize_panel_input(back_parsed)

    # Normalize font measurements
    norm_front_fonts = _normalize_fonts_input(front_fonts)
    norm_back_fonts = _normalize_fonts_input(back_fonts)

    # 2. Collect all candidate field names
    all_keys = set(norm_front.keys()) | set(norm_back.keys())
    # Ensure brand name aliases are resolved
    if "brand" in all_keys and "brand_name" not in all_keys:
        all_keys.add("brand_name")

    consolidated_values: Dict[str, str] = {}
    consolidated_fonts: Dict[str, Any] = {}
    resolved_conflicts: List[Dict[str, Any]] = []
    field_sources: Dict[str, str] = {}

    # 3. Resolve each field
    for field_key in all_keys:
        # Check aliases for brand_name
        front_entry = norm_front.get(field_key)
        if not front_entry and field_key == "brand_name":
            front_entry = norm_front.get("brand")

        back_entry = norm_back.get(field_key)
        if not back_entry and field_key == "brand_name":
            back_entry = norm_back.get("brand")

        selected_side = ""
        selected_val = ""
        selected_entry = None

        if front_entry and not back_entry:
            selected_side = "front"
            selected_entry = front_entry
            selected_val = front_entry["value"]
        elif back_entry and not front_entry:
            selected_side = "back"
            selected_entry = back_entry
            selected_val = back_entry["value"]
        elif front_entry and back_entry:
            val_f = front_entry["value"]
            val_b = back_entry["value"]
            has_val_f = bool(str(val_f).strip())
            has_val_b = bool(str(val_b).strip())

            # If only one panel produced a non-empty string, prioritize the non-empty declaration
            if has_val_f and not has_val_b:
                selected_side = "front"
                selected_entry = front_entry
                selected_val = val_f
            elif has_val_b and not has_val_f:
                selected_side = "back"
                selected_entry = back_entry
                selected_val = val_b
            else:
                # Both panels have values (or both empty). Compute weighted confidence scores.
                conf_f = float(front_entry.get("confidence", 1.0))
                conf_b = float(back_entry.get("confidence", 1.0))

                field_weight_dict = weights.get(field_key, {"front": 1.0, "back": 1.0})
                weight_f = field_weight_dict.get("front", 1.0)
                weight_b = field_weight_dict.get("back", 1.0)

                score_f = conf_f * weight_f
                score_b = conf_b * weight_b

                if score_f >= score_b:
                    selected_side = "front"
                    selected_entry = front_entry
                    selected_val = val_f
                else:
                    selected_side = "back"
                    selected_entry = back_entry
                    selected_val = val_b

                # Detect and log field conflict if values differ
                if val_f.strip() != val_b.strip() and has_val_f and has_val_b:
                    conflict_info = {
                        "field_name": field_key,
                        "front_value": val_f,
                        "front_confidence": conf_f,
                        "front_score": round(score_f, 4),
                        "back_value": val_b,
                        "back_confidence": conf_b,
                        "back_score": round(score_b, 4),
                        "selected_side": selected_side,
                        "selected_value": selected_val,
                        "reason": f"Higher weighted confidence ({score_f:.3f} vs {score_b:.3f})"
                        if score_f != score_b
                        else "Front preference tie-breaker",
                    }
                    resolved_conflicts.append(conflict_info)
                    logger.info(
                        "Resolved conflict on '%s': Selected %s panel value '%s' (score %.3f vs %.3f)",
                        field_key,
                        selected_side,
                        selected_val,
                        score_f if selected_side == "front" else score_b,
                        score_b if selected_side == "front" else score_f,
                    )

        consolidated_values[field_key] = selected_val
        field_sources[field_key] = selected_side

        # 4. Map font measurement for selected field
        winning_fonts = norm_front_fonts if selected_side == "front" else norm_back_fonts
        fallback_fonts = norm_back_fonts if selected_side == "front" else norm_front_fonts

        font_meas = winning_fonts.get(field_key) or fallback_fonts.get(field_key)
        if font_meas:
            consolidated_fonts[field_key] = font_meas

    # Also capture any remaining font measurements present in either report
    for k, v in norm_front_fonts.items():
        if k not in consolidated_fonts:
            consolidated_fonts[k] = v
    for k, v in norm_back_fonts.items():
        if k not in consolidated_fonts:
            consolidated_fonts[k] = v

    # 5. Compute completeness across the 9 Legal Metrology mandatory declarations
    missing_declarations: List[str] = []
    present_declarations: List[str] = []

    for decl in MANDATORY_DECLARATIONS:
        val = consolidated_values.get(decl, "")
        if val and str(val).strip():
            present_declarations.append(decl)
        else:
            missing_declarations.append(decl)

    completeness_pct = round((len(present_declarations) / float(len(MANDATORY_DECLARATIONS))) * 100.0, 2)

    # 6. Generate or retrieve product UUID
    existing_product_id: Optional[str] = None
    if scan_id:
        scan_record = db.get_scan(str(scan_id))
        if scan_record and scan_record.get("product_id"):
            existing_product_id = scan_record.get("product_id")

    product_id = existing_product_id or str(uuid.uuid4())
    brand_name = consolidated_values.get("brand_name") or consolidated_values.get("brand", "")

    # 7. Instantiate ConsolidatedProductRecord
    record = ConsolidatedProductRecord(
        product_id=product_id,
        brand_name=brand_name,
        mrp=consolidated_values.get("mrp", ""),
        net_quantity=consolidated_values.get("net_quantity", ""),
        mfg_date=consolidated_values.get("mfg_date", ""),
        expiry_date=consolidated_values.get("expiry_date", ""),
        batch_number=consolidated_values.get("batch_number", ""),
        manufacturer_details=consolidated_values.get("manufacturer_details", ""),
        consumer_care=consolidated_values.get("consumer_care", ""),
        country_of_origin=consolidated_values.get("country_of_origin", ""),
        unit_sale_price=consolidated_values.get("unit_sale_price", ""),
        front_fields=raw_front,
        back_fields=raw_back,
        font_measurements=consolidated_fonts,
        completeness_pct=completeness_pct,
        missing_declarations=missing_declarations,
        resolved_conflicts=resolved_conflicts,
    )

    # 8. Persist/update consolidated product record in Supabase products table via db.create_product()
    db_payload = record.to_db_payload()
    saved_product = db.create_product(db_payload)
    if saved_product and saved_product.get("id"):
        record.product_id = saved_product["id"]

    # If scan_id provided, link product_id in scans table
    if scan_id:
        try:
            db.update_scan(str(scan_id), {"product_id": record.product_id})
            logger.info("Linked scan %s to consolidated product %s", scan_id, record.product_id)
        except Exception as exc:
            logger.warning("Could not link product %s to scan %s: %s", record.product_id, scan_id, exc)

    logger.info(
        "Consolidated product %s: Completeness %.1f%% (%d/%d fields). Conflicts resolved: %d.",
        record.product_id,
        record.completeness_pct,
        record.total_declarations_present,
        len(MANDATORY_DECLARATIONS),
        len(resolved_conflicts),
    )

    return record
