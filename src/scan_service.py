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
from typing import Any, Dict, Optional, Tuple, Union

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
