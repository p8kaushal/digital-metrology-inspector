"""Digital Metrology Inspector - Scan Service Module.

Coordinates raw packaging image uploads to Supabase Storage ('product-images' bucket
under 'scans/') and persists scan metadata (scan_id, timestamp, URLs, dimensions,
status='uploaded') to the 'scans' database table via src/db.py.
Handles live Supabase connections and graceful offline mock fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import io
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image

from src import db
from src.consolidation import (
    ConsolidatedProductRecord,
    MANDATORY_DECLARATIONS,
    consolidate_scan_records,
)
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
REPORT_STORAGE_BUCKET = "inspection-reports"
REPORT_STORAGE_PREFIX = "reports"


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

    # Case 5: File path string
    elif isinstance(img_input, str):
        if not os.path.exists(img_input):
            raise FileNotFoundError(f"Image path for {side} label not found: {img_input}")
        with open(img_input, "rb") as f_in:
            raw_bytes = f_in.read()
        filename = os.path.basename(img_input)
        is_valid, err_msg, pil_img, meta = validate_image_bytes(raw_bytes, filename=filename)
        if not is_valid or pil_img is None:
            raise ValueError(f"Invalid {side} image data from {img_input}: {err_msg}")
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


# ==============================================================================
# Task 14: Inspection Report Storage & Link Retrieval
# ==============================================================================

class ReportUploadResult(dict):
    """Container for inspection report storage upload result and retrievable cloud links.

    Supports both dictionary key access (result['report_url']) and attribute
    access (result.report_url) for developer convenience.
    """

    def __init__(
        self,
        scan_id: str,
        report_url: str,
        pdf_url: Optional[str] = None,
        docx_url: Optional[str] = None,
        status: str = "success",
        upload_status: str = "uploaded",
        is_offline: bool = False,
        storage_bucket: str = REPORT_STORAGE_BUCKET,
        docx_storage_path: str = "",
        pdf_storage_path: Optional[str] = None,
        updated_scan: Optional[Dict[str, Any]] = None,
    ) -> None:
        resolved_docx_url = docx_url or report_url
        super().__init__(
            scan_id=scan_id,
            id=scan_id,
            report_url=report_url,
            docx_url=resolved_docx_url,
            pdf_url=pdf_url,
            status=status,
            upload_status=upload_status,
            is_offline=is_offline,
            storage_bucket=storage_bucket,
            bucket=storage_bucket,
            docx_storage_path=docx_storage_path,
            pdf_storage_path=pdf_storage_path,
            updated_scan=updated_scan,
        )
        self.scan_id = scan_id
        self.id = scan_id
        self.report_url = report_url
        self.docx_url = resolved_docx_url
        self.pdf_url = pdf_url
        self.status = status
        self.upload_status = upload_status
        self.is_offline = is_offline
        self.storage_bucket = storage_bucket
        self.bucket = storage_bucket
        self.docx_storage_path = docx_storage_path
        self.pdf_storage_path = pdf_storage_path
        self.updated_scan = updated_scan

    def __repr__(self) -> str:
        return (
            f"<ReportUploadResult scan_id='{self.scan_id}' status='{self.status}' "
            f"report_url='{self.report_url}' pdf_url='{self.pdf_url}' "
            f"storage='{self.upload_status}'>"
        )


def upload_inspection_report(
    scan_id: str,
    docx_path: str,
    pdf_path: Optional[str] = None,
    bucket_name: str = REPORT_STORAGE_BUCKET,
) -> ReportUploadResult:
    """Upload inspection report files (.docx and optional .pdf) to Supabase Storage and update scan record.

    1. Uploads Word .docx report to Supabase Storage ('inspection-reports' bucket under
       'reports/{scan_id}/inspection_report.docx').
    2. Uploads PDF .pdf report (if provided and exists) under 'reports/{scan_id}/inspection_report.pdf'.
    3. Retrieves public storage URLs.
    4. Updates 'report_url' in Supabase scans table via db.update_scan().
    5. Returns ReportUploadResult container with report_url, pdf_url, and upload status.

    Args:
        scan_id: Scan UUID string.
        docx_path: Local filesystem path to generated Word (.docx) inspection report.
        pdf_path: Optional local filesystem path to generated PDF (.pdf) inspection report.
        bucket_name: Storage bucket name (default 'inspection-reports').

    Returns:
        ReportUploadResult containing report_url, pdf_url, upload_status, and scan update metadata.

    Raises:
        ValueError: If scan_id or docx_path is missing or empty.
        FileNotFoundError: If docx_path does not exist on disk.
    """
    if not scan_id or not str(scan_id).strip():
        raise ValueError("scan_id is required and cannot be empty.")
    scan_id_str = str(scan_id).strip()

    if not docx_path or not str(docx_path).strip():
        raise ValueError("docx_path is required and cannot be empty.")
    docx_path_str = str(docx_path).strip()

    if not os.path.exists(docx_path_str):
        raise FileNotFoundError(f"Word inspection report not found at: {docx_path_str}")

    logger.info("Uploading inspection report for scan_id=%s...", scan_id_str)

    # 1. Read Word (.docx) report bytes and upload to Supabase Storage
    with open(docx_path_str, "rb") as f_docx:
        docx_bytes = f_docx.read()

    docx_storage_path = f"reports/{scan_id_str}/inspection_report.docx"
    docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    logger.info("Uploading Word report to %s:%s...", bucket_name, docx_storage_path)
    docx_upload = db.upload_file_to_storage(
        bucket_name=bucket_name,
        file_bytes=docx_bytes,
        destination_path=docx_storage_path,
        content_type=docx_mime,
    )
    docx_url = docx_upload.get("url", "")
    docx_offline = docx_upload.get("offline", False)
    report_url = docx_url

    # 2. Process optional PDF report
    pdf_url: Optional[str] = None
    pdf_storage_path: Optional[str] = None
    pdf_offline: bool = False

    if pdf_path and str(pdf_path).strip():
        pdf_path_str = str(pdf_path).strip()
        if os.path.exists(pdf_path_str):
            with open(pdf_path_str, "rb") as f_pdf:
                pdf_bytes = f_pdf.read()

            pdf_storage_path = f"reports/{scan_id_str}/inspection_report.pdf"
            pdf_mime = "application/pdf"

            logger.info("Uploading PDF report to %s:%s...", bucket_name, pdf_storage_path)
            pdf_upload = db.upload_file_to_storage(
                bucket_name=bucket_name,
                file_bytes=pdf_bytes,
                destination_path=pdf_storage_path,
                content_type=pdf_mime,
            )
            pdf_url = pdf_upload.get("url")
            pdf_offline = pdf_upload.get("offline", False)
        else:
            logger.warning(
                "Specified pdf_path not found on disk: %s. Skipping PDF upload.",
                pdf_path_str,
            )

    is_offline = docx_offline or pdf_offline or db.is_offline_mode()
    upload_status = "Offline Mock" if is_offline else "Cloud (Supabase)"

    # 3. Ensure scan record exists in scans table (satisfies foreign key / mock store consistency)
    existing_scan = db.get_scan(scan_id_str)
    if existing_scan is None:
        logger.info("Scan %s not found in DB. Creating initial scan record...", scan_id_str)
        db.create_scan({
            "id": scan_id_str,
            "scan_id": scan_id_str,
            "status": "processed",
            "report_url": report_url,
            "notes": f"Auto-created during inspection report upload. Storage: {upload_status}.",
        })

    # 4. Update report_url in Supabase scans table via db.update_scan()
    logger.info("Updating scan %s record with report_url: %s", scan_id_str, report_url)
    updated_scan = db.update_scan(scan_id_str, {"report_url": report_url})

    result = ReportUploadResult(
        scan_id=scan_id_str,
        report_url=report_url,
        pdf_url=pdf_url,
        docx_url=docx_url,
        status="success",
        upload_status=upload_status,
        is_offline=is_offline,
        storage_bucket=bucket_name,
        docx_storage_path=docx_storage_path,
        pdf_storage_path=pdf_storage_path,
        updated_scan=updated_scan,
    )

    logger.info("Inspection report uploaded successfully for scan %s: %s", scan_id_str, result)
    return result


# ==============================================================================
# Task 15: Inspector Manual Verification & Field Corrections
# ==============================================================================

@dataclass
class ManualCorrectionResult(ConsolidatedProductRecord):
    """Container for manual correction application results.

    Inherits from ConsolidatedProductRecord to provide direct attribute and dict
    access to consolidated fields, while also tracking logged corrections audit entries.
    """

    logged_corrections: List[Dict[str, Any]] = field(default_factory=list)
    corrections_count: int = 0
    scan_id: str = ""
    inspector_id: str = "INS-001"
    status: str = "success"
    message: str = ""

    @property
    def record(self) -> ConsolidatedProductRecord:
        """Self-reference to the underlying consolidated record."""
        return self

    def __repr__(self) -> str:
        return (
            f"<ManualCorrectionResult scan_id='{self.scan_id}' "
            f"corrections_count={self.corrections_count} "
            f"completeness_pct={self.completeness_pct:.1f}% "
            f"inspector_id='{self.inspector_id}'>"
        )


def apply_manual_corrections(
    scan_id: str,
    corrections_dict: Dict[str, Any],
    inspector_id: str = "INS-001",
    reason: Optional[str] = None,
    current_record: Optional[ConsolidatedProductRecord] = None,
) -> ManualCorrectionResult:
    """Apply manual inspector corrections to extracted fields and product master record.

    Performs:
    1. Validates scan_id and ensures parent scan record exists in database.
    2. Updates or creates extracted_fields in DB with is_corrected=True and new value.
    3. Logs each change to the Supabase correction_logs audit table via db.log_field_correction().
    4. Re-consolidates product record with updated values, recalculating Legal Metrology
       mandatory declaration completeness and missing fields.
    5. Synchronizes the updated consolidated product record in the database (products table)
       and links it to the scan.

    Args:
        scan_id: UUID of the parent scan.
        corrections_dict: Mapping of field_name to new value, or dict containing
            {'value': ..., 'original_value': ..., 'reason': ...}.
        inspector_id: Badge or ID of inspecting officer (default 'INS-001').
        reason: Optional default audit justification for the corrections.
        current_record: Optional in-memory ConsolidatedProductRecord to base updates on.

    Returns:
        ManualCorrectionResult containing updated consolidated record fields and audit logs.

    Raises:
        ValueError: If scan_id is missing or empty.
    """
    if not scan_id or not str(scan_id).strip():
        raise ValueError("scan_id is required and cannot be empty.")

    scan_id_str = str(scan_id).strip()
    inspector_id_str = str(inspector_id or "INS-001").strip()
    logger.info("Applying manual corrections for scan_id=%s by inspector=%s...", scan_id_str, inspector_id_str)

    # 1. Ensure parent scan record exists in scans table
    scan_record = db.get_scan(scan_id_str)
    product_id = None
    if scan_record and scan_record.get("product_id"):
        product_id = scan_record.get("product_id")
    elif current_record and getattr(current_record, "product_id", None):
        product_id = current_record.product_id
    else:
        product_id = str(uuid.uuid4())

    if scan_record is None:
        logger.info("Scan %s not found in DB. Auto-creating scan entry...", scan_id_str)
        scan_record = db.create_scan({
            "id": scan_id_str,
            "scan_id": scan_id_str,
            "product_id": product_id,
            "status": "processing",
            "notes": f"Auto-created during manual correction application by {inspector_id_str}",
        })

    # 2. Retrieve existing extracted fields from DB
    existing_db_fields = db.get_extracted_fields(scan_id_str)
    existing_product = db.get_product(product_id) if product_id else None

    # 3. Establish base ConsolidatedProductRecord
    if current_record is not None:
        base_record = ConsolidatedProductRecord(
            product_id=current_record.product_id or product_id,
            brand_name=current_record.brand_name,
            mrp=current_record.mrp,
            net_quantity=current_record.net_quantity,
            mfg_date=current_record.mfg_date,
            expiry_date=current_record.expiry_date,
            batch_number=current_record.batch_number,
            manufacturer_details=current_record.manufacturer_details,
            consumer_care=current_record.consumer_care,
            country_of_origin=current_record.country_of_origin,
            unit_sale_price=current_record.unit_sale_price,
            front_fields=dict(current_record.front_fields or {}),
            back_fields=dict(current_record.back_fields or {}),
            font_measurements=dict(current_record.font_measurements or {}),
            completeness_pct=current_record.completeness_pct,
            missing_declarations=list(current_record.missing_declarations or []),
            resolved_conflicts=list(current_record.resolved_conflicts or []),
        )
    elif existing_product:
        mrp_str = str(existing_product.get("mrp") or existing_product.get("mrp_declared") or "")
        net_qty_str = str(existing_product.get("net_quantity") or existing_product.get("net_quantity_declared") or "")
        base_record = ConsolidatedProductRecord(
            product_id=product_id,
            brand_name=existing_product.get("name") or existing_product.get("brand") or "",
            mrp=mrp_str,
            net_quantity=net_qty_str,
            mfg_date=existing_product.get("mfg_date") or "",
            expiry_date=existing_product.get("expiry_date") or "",
            batch_number=existing_product.get("batch_number") or "",
            manufacturer_details=existing_product.get("manufacturer_name") or existing_product.get("manufacturer_details") or "",
            consumer_care=existing_product.get("consumer_care") or "",
            country_of_origin=existing_product.get("country_of_origin") or "",
            unit_sale_price=existing_product.get("unit_sale_price") or "",
        )
    else:
        # Reconstruct from existing extracted fields in DB
        f_fields = {f["field_name"]: f for f in existing_db_fields if f.get("side") == "front"}
        b_fields = {f["field_name"]: f for f in existing_db_fields if f.get("side") == "back"}
        if f_fields or b_fields:
            base_record = consolidate_scan_records(
                front_parsed=f_fields,
                back_parsed=b_fields,
                scan_id=scan_id_str,
            )
        else:
            base_record = ConsolidatedProductRecord(product_id=product_id)

    # Field alias mapping for standard declarations
    ALIAS_MAP = {
        "brand": "brand_name",
        "brand_name": "brand_name",
        "name": "brand_name",
        "mrp": "mrp",
        "mrp_declared": "mrp",
        "net_quantity": "net_quantity",
        "net_quantity_declared": "net_quantity",
        "net_qty": "net_quantity",
        "manufacturer": "manufacturer_details",
        "manufacturer_details": "manufacturer_details",
        "manufacturer_name": "manufacturer_details",
        "mfg_date": "mfg_date",
        "date_of_manufacture": "mfg_date",
        "expiry_date": "expiry_date",
        "exp_date": "expiry_date",
        "batch_number": "batch_number",
        "batch_no": "batch_number",
        "lot_number": "batch_number",
        "consumer_care": "consumer_care",
        "consumer_care_details": "consumer_care",
        "country_of_origin": "country_of_origin",
        "origin_country": "country_of_origin",
        "unit_sale_price": "unit_sale_price",
        "usp": "unit_sale_price",
    }

    logged_corrections: List[Dict[str, Any]] = []

    # 4. Iterate over corrections and update DB + record
    for raw_key, corr_item in (corrections_dict or {}).items():
        key_clean = str(raw_key).strip().lower()
        canonical_key = ALIAS_MAP.get(key_clean, key_clean)

        if isinstance(corr_item, dict):
            new_val = corr_item.get("value") or corr_item.get("corrected_value") or corr_item.get("corrected") or ""
            spec_orig = corr_item.get("original_value") or corr_item.get("original")
            spec_reason = corr_item.get("reason") or reason
        else:
            new_val = str(corr_item) if corr_item is not None else ""
            spec_orig = None
            spec_reason = reason

        new_val_str = str(new_val).strip()

        # Determine original value
        if spec_orig is not None:
            orig_val_str = str(spec_orig).strip()
        else:
            rec_val = getattr(base_record, canonical_key, None)
            if rec_val:
                orig_val_str = str(rec_val).strip()
            else:
                db_match = next((f for f in existing_db_fields if f.get("field_name") in (canonical_key, raw_key, key_clean)), None)
                if db_match:
                    orig_val_str = str(db_match.get("parsed_value") or db_match.get("raw_text") or "").strip()
                elif existing_product and canonical_key in existing_product:
                    orig_val_str = str(existing_product.get(canonical_key) or "").strip()
                else:
                    orig_val_str = ""

        # (a) Update extracted_fields in DB with is_corrected=True and new value
        matching_fields = [
            f for f in existing_db_fields
            if f.get("field_name") in (canonical_key, raw_key, key_clean)
        ]

        if matching_fields:
            for f_row in matching_fields:
                db.update_extracted_field(
                    f_row["id"],
                    {
                        "parsed_value": new_val_str,
                        "raw_text": new_val_str,
                        "is_corrected": True,
                    },
                )
                f_row["parsed_value"] = new_val_str
                f_row["is_corrected"] = True
        else:
            # Create a consolidated extracted_fields record for newly declared statutory field
            new_db_field = db.save_extracted_fields(scan_id_str, [{
                "scan_id": scan_id_str,
                "side": "consolidated",
                "field_name": canonical_key,
                "raw_text": new_val_str,
                "parsed_value": new_val_str,
                "confidence": 1.0,
                "is_corrected": True,
            }])
            if new_db_field:
                existing_db_fields.extend(new_db_field)

        # (b) Log entry to correction_logs
        log_entry = db.log_field_correction(
            scan_id=scan_id_str,
            field_name=canonical_key,
            original_value=orig_val_str if orig_val_str else None,
            corrected_value=new_val_str,
            inspector_id=inspector_id_str,
            reason=spec_reason,
        )
        logged_corrections.append(log_entry)

        # (c) Update attribute on base_record
        if hasattr(base_record, canonical_key):
            setattr(base_record, canonical_key, new_val_str)

    # 5. Recompute completeness across the 9 mandatory declarations
    missing_declarations = []
    for decl in MANDATORY_DECLARATIONS:
        decl_val = getattr(base_record, decl, "")
        if not decl_val or not str(decl_val).strip():
            missing_declarations.append(decl)

    base_record.missing_declarations = missing_declarations
    present_count = len(MANDATORY_DECLARATIONS) - len(missing_declarations)
    base_record.completeness_pct = round((present_count / float(len(MANDATORY_DECLARATIONS))) * 100.0, 2)
    base_record.product_id = product_id

    # 6. Synchronize updated product record in database
    db_payload = base_record.to_db_payload()
    if db.get_product(product_id):
        db.update_product(product_id, db_payload)
    else:
        db.create_product(db_payload)

    # Link product in scans table
    db.update_scan(scan_id_str, {"product_id": product_id})

    logger.info(
        "Manual corrections applied for scan %s: %d field(s) corrected. Updated completeness: %.1f%% (%d/%d).",
        scan_id_str,
        len(logged_corrections),
        base_record.completeness_pct,
        present_count,
        len(MANDATORY_DECLARATIONS),
    )

    return ManualCorrectionResult(
        product_id=base_record.product_id,
        brand_name=base_record.brand_name,
        mrp=base_record.mrp,
        net_quantity=base_record.net_quantity,
        mfg_date=base_record.mfg_date,
        expiry_date=base_record.expiry_date,
        batch_number=base_record.batch_number,
        manufacturer_details=base_record.manufacturer_details,
        consumer_care=base_record.consumer_care,
        country_of_origin=base_record.country_of_origin,
        unit_sale_price=base_record.unit_sale_price,
        front_fields=base_record.front_fields,
        back_fields=base_record.back_fields,
        font_measurements=base_record.font_measurements,
        completeness_pct=base_record.completeness_pct,
        missing_declarations=base_record.missing_declarations,
        resolved_conflicts=base_record.resolved_conflicts,
        logged_corrections=logged_corrections,
        corrections_count=len(logged_corrections),
        scan_id=scan_id_str,
        inspector_id=inspector_id_str,
        status="success",
        message=f"Applied {len(logged_corrections)} manual correction(s) for scan {scan_id_str}",
    )

