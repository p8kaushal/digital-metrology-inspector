"""Digital Metrology Inspector - Scan Service Module.

Coordinates raw packaging image uploads to Supabase Storage ('product-images' bucket
under 'scans/') and persists scan metadata (scan_id, timestamp, URLs, dimensions,
status='uploaded') to the 'scans' database table via src/db.py.
Handles live Supabase connections and graceful offline mock fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image

from src import db
from src.image_handler import (
    ValidatedImage,
    compute_image_metadata,
    validate_image_bytes,
)

# Configure logger
logger = logging.getLogger("metrology_inspector.scan_service")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [SCAN_SVC] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Storage constants
STORAGE_BUCKET = "product-images"
STORAGE_PREFIX = "scans"


def _get_utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _get_mime_and_extension(img_format: str) -> Tuple[str, str]:
    """Map image format to MIME content-type and canonical file extension."""
    fmt = (img_format or "PNG").upper().strip()
    if fmt in ("JPEG", "JPG"):
        return "image/jpeg", "jpg"
    elif fmt == "WEBP":
        return "image/webp", "webp"
    else:
        return "image/png", "png"


def _extract_image_payload(
    img_input: Any, side: str = "front"
) -> Tuple[bytes, Dict[str, Any], str, str]:
    """Extract raw bytes, metadata, filename, and content-type from various image inputs.

    Supports:
    - ValidatedImage instance
    - dict with 'bytes'/'raw_bytes' and 'metadata'
    - bytes / bytearray
    - PIL Image.Image
    - File-like objects with a .read() method

    Returns:
        Tuple of (raw_bytes, metadata_dict, filename, content_type)
    """
    if img_input is None:
        raise ValueError(f"Image for {side} label cannot be None.")

    raw_bytes: bytes = b""
    metadata: Dict[str, Any] = {}
    filename: str = f"{side}_label"
    content_type: str = "image/png"

    # Case 1: ValidatedImage instance or dictionary representation
    if isinstance(img_input, ValidatedImage) or (
        isinstance(img_input, dict) and ("bytes" in img_input or "raw_bytes" in img_input)
    ):
        raw_bytes = img_input.get("bytes") or img_input.get("raw_bytes")
        metadata = img_input.get("metadata", {})
        filename = img_input.get("filename") or f"{side}_label.png"
        img_format = metadata.get("format") or img_input.get("format", "PNG")
        content_type, ext = _get_mime_and_extension(img_format)
        if not filename.lower().endswith(f".{ext}"):
            filename = f"{os.path.splitext(filename)[0]}.{ext}"
        return raw_bytes, metadata, filename, content_type

    # Case 2: Raw bytes or bytearray
    elif isinstance(img_input, (bytes, bytearray)):
        raw_bytes = bytes(img_input)
        is_valid, err_msg, pil_img, meta = validate_image_bytes(raw_bytes)
        if not is_valid or pil_img is None:
            raise ValueError(f"Invalid {side} image data: {err_msg}")
        metadata = meta if meta is not None else compute_image_metadata(pil_img, raw_bytes, filename=f"{side}.png")
        content_type, ext = _get_mime_and_extension(metadata.get("format", "PNG"))
        filename = f"{side}.{ext}"
        return raw_bytes, metadata, filename, content_type

    # Case 3: PIL Image
    elif isinstance(img_input, Image.Image):
        pil_img = img_input
        img_format = pil_img.format or "PNG"
        content_type, ext = _get_mime_and_extension(img_format)
        buf = io.BytesIO()
        pil_img.save(buf, format=img_format if img_format in ("JPEG", "PNG", "WEBP") else "PNG")
        raw_bytes = buf.getvalue()
        metadata = compute_image_metadata(pil_img, raw_bytes, filename=f"{side}.{ext}")
        filename = f"{side}.{ext}"
        return raw_bytes, metadata, filename, content_type

    # Case 4: File-like object (e.g. Streamlit UploadedFile)
    elif hasattr(img_input, "read"):
        if hasattr(img_input, "seek"):
            img_input.seek(0)
        raw_bytes = img_input.read()
        filename = getattr(img_input, "name", f"{side}.png")
        is_valid, err_msg, pil_img, meta = validate_image_bytes(raw_bytes, filename=filename)
        if not is_valid or pil_img is None:
            raise ValueError(f"Invalid {side} file input: {err_msg}")
        metadata = meta if meta is not None else compute_image_metadata(pil_img, raw_bytes, filename=filename)
        content_type, ext = _get_mime_and_extension(metadata.get("format", "PNG"))
        return raw_bytes, metadata, filename, content_type

    else:
        raise TypeError(
            f"Unsupported image input type for {side}: {type(img_input).__name__}."
        )


class ScanUploadResult(dict):
    """Container for scan upload results and metadata.

    Supports both dictionary key access (result['scan_id']) and attribute
    access (result.scan_id) for developer convenience.
    """

    def __init__(
        self,
        scan_id: str,
        timestamp: str,
        front_image_url: str,
        back_image_url: str,
        dimensions: Dict[str, Any],
        status: str,
        storage_status: str,
        is_offline: bool,
        front_storage_path: str,
        back_storage_path: str,
        scan_record: Dict[str, Any],
        product_id: Optional[str] = None,
    ):
        super().__init__(
            scan_id=scan_id,
            id=scan_id,
            timestamp=timestamp,
            created_at=timestamp,
            front_image_url=front_image_url,
            back_image_url=back_image_url,
            dimensions=dimensions,
            status=status,
            storage_status=storage_status,
            is_offline=is_offline,
            front_storage_path=front_storage_path,
            back_storage_path=back_storage_path,
            scan_record=scan_record,
            product_id=product_id,
        )
        self.scan_id = scan_id
        self.id = scan_id
        self.timestamp = timestamp
        self.created_at = timestamp
        self.front_image_url = front_image_url
        self.back_image_url = back_image_url
        self.dimensions = dimensions
        self.status = status
        self.storage_status = storage_status
        self.is_offline = is_offline
        self.front_storage_path = front_storage_path
        self.back_storage_path = back_storage_path
        self.scan_record = scan_record
        self.product_id = product_id

    def __repr__(self) -> str:
        return (
            f"<ScanUploadResult scan_id='{self.scan_id}' status='{self.status}' "
            f"storage='{self.storage_status}'>"
        )


def process_scan_upload(
    front_image: Any,
    back_image: Any,
    product_id: Optional[str] = None,
    scan_id: Optional[str] = None,
    bucket_name: str = STORAGE_BUCKET,
    storage_prefix: str = STORAGE_PREFIX,
) -> ScanUploadResult:
    """Upload raw front & back images to Supabase Storage and log scan metadata to scans table.

    Args:
        front_image: ValidatedImage, dictionary, raw bytes, or PIL Image of front packaging.
        back_image: ValidatedImage, dictionary, raw bytes, or PIL Image of back packaging.
        product_id: Optional UUID string of associated product.
        scan_id: Optional UUID string for the scan (auto-generated if None).
        bucket_name: Storage bucket name (default 'product-images').
        storage_prefix: Folder prefix inside storage bucket (default 'scans').

    Returns:
        ScanUploadResult containing scan_id, timestamp, URLs, dimensions, status='uploaded',
        storage_status, and full scan record.

    Raises:
        ValueError: If either image is missing or invalid.
    """
    if front_image is None or back_image is None:
        raise ValueError("Both front and back images are required to process a scan upload.")

    assigned_scan_id = scan_id or str(uuid.uuid4())
    timestamp = _get_utc_now_iso()

    logger.info("Initiating scan upload (Scan ID: %s)...", assigned_scan_id)

    # 1. Extract payloads (bytes, metadata, filename, MIME)
    front_bytes, front_meta, front_fname, front_mime = _extract_image_payload(
        front_image, side="front"
    )
    back_bytes, back_meta, back_fname, back_mime = _extract_image_payload(
        back_image, side="back"
    )

    _, front_ext = _get_mime_and_extension(front_meta.get("format", "PNG"))
    _, back_ext = _get_mime_and_extension(back_meta.get("format", "PNG"))

    front_storage_path = f"{storage_prefix}/{assigned_scan_id}/front.{front_ext}"
    back_storage_path = f"{storage_prefix}/{assigned_scan_id}/back.{back_ext}"

    # 2. Upload front image to Supabase Storage (product-images bucket)
    logger.info("Uploading front image to %s:%s...", bucket_name, front_storage_path)
    front_upload = db.upload_file_to_storage(
        bucket_name=bucket_name,
        file_bytes=front_bytes,
        destination_path=front_storage_path,
        content_type=front_mime,
    )
    front_image_url = front_upload.get("url", "")
    front_offline = front_upload.get("offline", False)

    # 3. Upload back image to Supabase Storage (product-images bucket)
    logger.info("Uploading back image to %s:%s...", bucket_name, back_storage_path)
    back_upload = db.upload_file_to_storage(
        bucket_name=bucket_name,
        file_bytes=back_bytes,
        destination_path=back_storage_path,
        content_type=back_mime,
    )
    back_image_url = back_upload.get("url", "")
    back_offline = back_upload.get("offline", False)

    is_offline = front_offline or back_offline or db.is_offline_mode()
    storage_status = "Offline Mock" if is_offline else "Cloud (Supabase)"

    # 4. Construct dimensions structure
    front_w = front_meta.get("width", 0)
    front_h = front_meta.get("height", 0)
    back_w = back_meta.get("width", 0)
    back_h = back_meta.get("height", 0)

    dimensions = {
        "front": {
            "width": front_w,
            "height": front_h,
            "aspect_ratio": front_meta.get("aspect_ratio", 0.0),
            "size_kb": front_meta.get("size_kb", 0.0),
            "format": front_meta.get("format", "PNG"),
        },
        "back": {
            "width": back_w,
            "height": back_h,
            "aspect_ratio": back_meta.get("aspect_ratio", 0.0),
            "size_kb": back_meta.get("size_kb", 0.0),
            "format": back_meta.get("format", "PNG"),
        },
        "summary": f"Front: {front_w}×{front_h} px | Back: {back_w}×{back_h} px",
    }

    # 5. Log scan metadata into scans table via src/db.py
    scan_data = {
        "id": assigned_scan_id,
        "scan_id": assigned_scan_id,
        "product_id": product_id,
        "front_image_url": front_image_url,
        "back_image_url": back_image_url,
        "dimensions": dimensions,
        "status": "uploaded",
        "notes": (
            f"Raw packaging images uploaded. Storage status: {storage_status}. "
            f"Dimensions: {dimensions['summary']}."
        ),
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    logger.info("Logging scan record to database (status='uploaded')...")
    created_scan = db.create_scan(scan_data)

    result = ScanUploadResult(
        scan_id=assigned_scan_id,
        timestamp=timestamp,
        front_image_url=front_image_url,
        back_image_url=back_image_url,
        dimensions=dimensions,
        status="uploaded",
        storage_status=storage_status,
        is_offline=is_offline,
        front_storage_path=front_storage_path,
        back_storage_path=back_storage_path,
        scan_record=created_scan,
        product_id=product_id,
    )

    logger.info("Scan upload processed successfully: %s", result)
    return result


def get_scan_by_id(scan_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve scan record from database by ID.

    Args:
        scan_id: Scan UUID.

    Returns:
        Scan record dict or None if not found.
    """
    return db.get_scan(scan_id)


class SaveExtractionResult(dict):
    """Container for field extraction persistence result.

    Supports dictionary key access, attribute access, and tuple unpacking:
        status, saved_count = save_scan_extraction_results(...)
        result.saved_count
        result['status']
    """

    def __init__(
        self,
        status: str = "success",
        saved_count: int = 0,
        scan_id: str = "",
        fields: Optional[List[Dict[str, Any]]] = None,
        side: str = "front",
        is_offline: bool = False,
        message: str = "",
    ) -> None:
        super().__init__(
            status=status,
            persistence_status=status,
            saved_count=saved_count,
            count=saved_count,
            scan_id=scan_id,
            fields=fields or [],
            side=side,
            is_offline=is_offline,
            message=message,
            success=(status in ("success", "processed")),
        )
        self.status = status
        self.persistence_status = status
        self.saved_count = saved_count
        self.count = saved_count
        self.scan_id = scan_id
        self.fields = fields or []
        self.side = side
        self.is_offline = is_offline
        self.message = message
        self.success = (status in ("success", "processed"))

    def __iter__(self):
        # Enables tuple unpacking: status, count = save_scan_extraction_results(...)
        yield self.status
        yield self.saved_count

    def __len__(self) -> int:
        return 2

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, int):
            return [self.status, self.saved_count][item]
        return super().__getitem__(item)

    def __repr__(self) -> str:
        return (
            f"<SaveExtractionResult status='{self.status}' saved_count={self.saved_count} "
            f"scan_id='{self.scan_id}' side='{self.side}'>"
        )


def save_scan_extraction_results(
    scan_id: str,
    parsed_fields_result: Any,
    font_measurement_report: Optional[Any] = None,
    side: str = "front",
) -> SaveExtractionResult:
    """Extract, enrich, and persist OCR parsed fields and font measurements to database.

    Args:
        scan_id: UUID of the parent scan.
        parsed_fields_result: ParsedFieldsResult instance, dict, or list of extracted fields.
        font_measurement_report: Optional FontMeasurementReport instance or dict of measurements.
        side: Packaging panel side ('front', 'back', or 'consolidated'). Default 'front'.

    Returns:
        SaveExtractionResult with persistence status, saved_count, scan_id, and list of fields.

    Raises:
        ValueError: If scan_id is missing or invalid.
    """
    if not scan_id or not str(scan_id).strip():
        raise ValueError("scan_id is required and cannot be empty.")

    scan_id_str = str(scan_id).strip()
    logger.info("Persisting extracted fields for scan_id=%s, side=%s...", scan_id_str, side)

    # 1. Ensure scan record exists in scans table (satisfies foreign key constraints)
    existing_scan = db.get_scan(scan_id_str)
    if existing_scan is None:
        logger.info("Scan %s not found in DB. Creating initial scan entry...", scan_id_str)
        db.create_scan({
            "id": scan_id_str,
            "scan_id": scan_id_str,
            "status": "processing",
            "notes": f"Auto-created during extraction persistence for {side} label",
        })

    # 2. Extract fields from parsed_fields_result
    fields_dict: Dict[str, Any] = {}
    if parsed_fields_result is None:
        fields_dict = {}
    elif hasattr(parsed_fields_result, "fields"):
        fields_dict = getattr(parsed_fields_result, "fields") or {}
    elif isinstance(parsed_fields_result, dict):
        if "fields" in parsed_fields_result and isinstance(parsed_fields_result["fields"], dict):
            fields_dict = parsed_fields_result["fields"]
        else:
            fields_dict = parsed_fields_result
    elif isinstance(parsed_fields_result, (list, tuple)):
        for idx, item in enumerate(parsed_fields_result):
            name = (
                getattr(item, "field_name", None)
                or (item.get("field_name") if isinstance(item, dict) else None)
                or f"field_{idx}"
            )
            fields_dict[name] = item

    # 3. Extract font measurements from font_measurement_report
    measurements_dict: Dict[str, Any] = {}
    if font_measurement_report is not None:
        if hasattr(font_measurement_report, "measurements"):
            measurements_dict = getattr(font_measurement_report, "measurements") or {}
        elif isinstance(font_measurement_report, dict):
            measurements_dict = font_measurement_report.get("measurements", font_measurement_report)

    # 4. Construct unified field records
    fields_data: List[Dict[str, Any]] = []

    for field_name, f_obj in fields_dict.items():
        # Raw text
        raw_text = ""
        if hasattr(f_obj, "raw_text"):
            raw_text = f_obj.raw_text or ""
        elif isinstance(f_obj, dict):
            raw_text = f_obj.get("raw_text") or f_obj.get("text") or ""
        else:
            raw_text = str(f_obj)

        # Extracted value & unit
        val = ""
        unit = None
        if hasattr(f_obj, "extracted_value"):
            val = f_obj.extracted_value or ""
            unit = getattr(f_obj, "unit", None)
        elif isinstance(f_obj, dict):
            val = f_obj.get("extracted_value") or f_obj.get("parsed_value") or f_obj.get("value") or ""
            unit = f_obj.get("unit")
        else:
            val = str(f_obj)

        # Parsed value
        if isinstance(f_obj, dict) and "parsed_value" in f_obj and f_obj["parsed_value"] is not None:
            parsed_value = str(f_obj["parsed_value"])
        elif unit:
            parsed_value = f"{val} {unit}".strip()
        else:
            parsed_value = str(val) if val is not None else ""

        # Bounding box
        bbox = None
        if hasattr(f_obj, "bbox"):
            bbox = f_obj.bbox
        elif isinstance(f_obj, dict):
            bbox = f_obj.get("bounding_box") or f_obj.get("bbox")

        if isinstance(bbox, tuple):
            bbox = list(bbox)

        # Font height in px
        font_height_px = 0.0
        if hasattr(f_obj, "height_px") and f_obj.height_px is not None:
            font_height_px = float(f_obj.height_px)
        elif isinstance(f_obj, dict):
            font_height_px = float(f_obj.get("font_height_px") or f_obj.get("height_px", 0.0))

        # Confidence
        confidence = 1.0
        if hasattr(f_obj, "confidence") and f_obj.confidence is not None:
            confidence = float(f_obj.confidence)
        elif isinstance(f_obj, dict) and f_obj.get("confidence") is not None:
            confidence = float(f_obj["confidence"])

        # Font measurement values: font_height_mm and is_rule7_compliant
        font_height_mm = None
        is_rule7_compliant = None

        m = measurements_dict.get(field_name)
        if m is not None:
            # font_height_mm
            if hasattr(m, "font_height_mm") and m.font_height_mm is not None:
                font_height_mm = float(m.font_height_mm)
            elif isinstance(m, dict) and m.get("font_height_mm") is not None:
                font_height_mm = float(m["font_height_mm"])

            # is_rule7_compliant
            if hasattr(m, "is_rule7_compliant") and m.is_rule7_compliant is not None:
                is_rule7_compliant = bool(m.is_rule7_compliant)
            elif isinstance(m, dict) and m.get("is_rule7_compliant") is not None:
                is_rule7_compliant = bool(m["is_rule7_compliant"])

            # bbox_height_px fallback
            if font_height_px == 0.0:
                if hasattr(m, "bbox_height_px") and m.bbox_height_px is not None:
                    font_height_px = float(m.bbox_height_px)
                elif isinstance(m, dict) and m.get("bbox_height_px") is not None:
                    font_height_px = float(m["bbox_height_px"])
        else:
            if hasattr(f_obj, "font_height_mm") and getattr(f_obj, "font_height_mm") is not None:
                font_height_mm = float(getattr(f_obj, "font_height_mm"))
            elif isinstance(f_obj, dict) and f_obj.get("font_height_mm") is not None:
                font_height_mm = float(f_obj["font_height_mm"])

            if hasattr(f_obj, "is_rule7_compliant") and getattr(f_obj, "is_rule7_compliant") is not None:
                is_rule7_compliant = bool(getattr(f_obj, "is_rule7_compliant"))
            elif isinstance(f_obj, dict) and f_obj.get("is_rule7_compliant") is not None:
                is_rule7_compliant = bool(f_obj["is_rule7_compliant"])

        fields_data.append({
            "scan_id": scan_id_str,
            "side": side,
            "field_name": field_name,
            "raw_text": raw_text,
            "parsed_value": parsed_value,
            "bounding_box": bbox,
            "font_height_px": font_height_px,
            "font_height_mm": font_height_mm,
            "confidence": confidence,
            "is_rule7_compliant": is_rule7_compliant,
            "is_corrected": False,
        })

    # 5. Save fields via db.save_extracted_fields(scan_id, fields_data)
    saved_records = db.save_extracted_fields(scan_id_str, fields_data)
    saved_count = len(saved_records)

    # 6. Update scan status in scans table to 'processed'
    db.update_scan(scan_id_str, {"status": "processed"})
    logger.info("Scan %s status updated to 'processed'. Stored %d fields.", scan_id_str, saved_count)

    is_offline = db.is_offline_mode()
    mode_str = "offline mock" if is_offline else "Supabase"
    msg = f"Saved {saved_count} fields to {mode_str} for scan {scan_id_str} ({side})"

    return SaveExtractionResult(
        status="success",
        saved_count=saved_count,
        scan_id=scan_id_str,
        fields=saved_records,
        side=side,
        is_offline=is_offline,
        message=msg,
    )

