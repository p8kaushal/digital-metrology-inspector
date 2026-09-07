"""Digital Metrology Inspector - Image Handling Module.

Provides robust validation, PIL preview generation, metadata calculation,
and local disk caching for front and back packaged commodity images.
"""

from datetime import datetime
import io
import os
import re
from typing import Any, Dict, Optional, Tuple, Union

from PIL import Image

# Project base directories
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_CACHE_DIR = os.path.join(PROJECT_ROOT, "data", "scans_cache")

# Supported image configurations
SUPPORTED_FORMATS = {"JPEG", "JPG", "PNG", "WEBP"}
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MIN_IMAGE_DIMENSION = 50  # 50x50 pixels minimum


class ValidatedImage(dict):
    """Container holding validated image data, PIL instance, metadata, and local cache path.

    Inherits from dict for seamless dictionary access (e.g. img['metadata']),
    while providing convenient direct attribute access (e.g. img.width).
    """

    def __init__(
        self,
        image: Image.Image,
        raw_bytes: bytes,
        metadata: Dict[str, Any],
        cache_path: str,
        side: str,
        filename: str = "",
    ):
        clean_side = side.lower().strip()
        super().__init__(
            image=image,
            bytes=raw_bytes,
            metadata=metadata,
            cache_path=cache_path,
            side=clean_side,
            filename=filename,
            width=metadata.get("width", image.width),
            height=metadata.get("height", image.height),
            dimensions=metadata.get("dimensions", f"{image.width} × {image.height}"),
            aspect_ratio=metadata.get("aspect_ratio", 0.0),
            aspect_ratio_str=metadata.get("aspect_ratio_str", ""),
            size_kb=metadata.get("size_kb", 0.0),
            format=metadata.get("format", image.format or "UNKNOWN"),
            mode=metadata.get("mode", image.mode),
        )
        self.image = image
        self.bytes = raw_bytes
        self.metadata = metadata
        self.cache_path = cache_path
        self.side = clean_side
        self.filename = filename
        self.width: int = metadata.get("width", image.width)
        self.height: int = metadata.get("height", image.height)
        self.dimensions: str = metadata.get("dimensions", f"{image.width} × {image.height}")
        self.aspect_ratio: float = metadata.get("aspect_ratio", 0.0)
        self.aspect_ratio_str: str = metadata.get("aspect_ratio_str", "")
        self.size_kb: float = metadata.get("size_kb", 0.0)
        self.format: str = metadata.get("format", image.format or "UNKNOWN")
        self.mode: str = metadata.get("mode", image.mode)

    def get_pil_image(self) -> Image.Image:
        """Return the underlying PIL Image."""
        return self.image

    def to_dict(self) -> Dict[str, Any]:
        """Return a copy of the validated image dictionary."""
        return dict(self)

    def __repr__(self) -> str:
        return (
            f"<ValidatedImage side='{self.side}' format='{self.format}' "
            f"dimensions='{self.dimensions}' size='{self.size_kb} KB' path='{self.cache_path}'>"
        )


def ensure_cache_dir(cache_dir: str = DEFAULT_CACHE_DIR) -> str:
    """Ensure that the local scan cache directory exists."""
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def compute_image_metadata(img: Image.Image, raw_bytes: bytes, filename: str = "") -> Dict[str, Any]:
    """Calculate and format comprehensive metadata for an image."""
    width, height = img.size
    size_bytes = len(raw_bytes)
    size_kb = round(size_bytes / 1024.0, 2)
    size_mb = round(size_bytes / (1024.0 * 1024.0), 2)

    aspect_ratio = round(width / height, 2) if height > 0 else 0.0
    aspect_ratio_str = f"{width}:{height} ({aspect_ratio}:1)"

    img_format = (img.format or "UNKNOWN").upper()
    if img_format == "JPEG" and filename.lower().endswith((".jpg", ".jpeg")):
        img_format = "JPEG"

    return {
        "width": width,
        "height": height,
        "dimensions": f"{width} × {height}",
        "aspect_ratio": aspect_ratio,
        "aspect_ratio_str": aspect_ratio_str,
        "size_bytes": size_bytes,
        "size_kb": size_kb,
        "size_mb": size_mb,
        "format": img_format,
        "mode": img.mode,
        "filename": filename or f"image_{width}x{height}",
    }


def validate_image_bytes(
    data: bytes, filename: str = ""
) -> Tuple[bool, Optional[str], Optional[Image.Image], Optional[Dict[str, Any]]]:
    """Validate image bytes for non-emptiness, valid format, integrity, and minimum dimensions.

    Returns:
        (is_valid, error_message, pil_image, metadata_dict)
    """
    if not data or len(data) == 0:
        return False, "Image data is empty (0 bytes).", None, None

    if len(data) > MAX_IMAGE_SIZE_BYTES:
        return (
            False,
            f"Image file size ({round(len(data) / (1024 * 1024), 2)} MB) exceeds maximum allowed limit (50 MB).",
            None,
            None,
        )

    try:
        # Open image using PIL
        stream = io.BytesIO(data)
        img = Image.open(stream)

        # Verify format
        detected_format = (img.format or "").upper()
        if detected_format not in SUPPORTED_FORMATS:
            return (
                False,
                f"Unsupported image format '{detected_format}'. Allowed formats: JPG, JPEG, PNG, WEBP.",
                None,
                None,
            )

        # Force decode image to detect corrupt/truncated bytes
        img.load()

        # Check dimensions
        width, height = img.size
        if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
            return (
                False,
                f"Image dimensions ({width}x{height}) too small. Minimum required: {MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION}.",
                None,
                None,
            )

        # Create a clean RGB copy for consistent preview generation
        if img.mode not in ("RGB", "RGBA"):
            preview_img = img.convert("RGB")
        else:
            preview_img = img.copy()

        metadata = compute_image_metadata(img, data, filename=filename)
        return True, None, preview_img, metadata

    except Exception as e:
        return False, f"Failed to decode or parse image file: {str(e)}", None, None


def save_to_cache(
    raw_bytes: bytes,
    side: str,
    file_extension: str = "png",
    cache_dir: str = DEFAULT_CACHE_DIR,
    custom_filename: Optional[str] = None,
) -> str:
    """Save raw image bytes into the local scan cache directory.

    Saves a timestamped version and ensures the file is persisted to disk.
    Returns the absolute path of the cached file.
    """
    ensure_cache_dir(cache_dir)
    clean_side = side.lower().strip()
    clean_ext = file_extension.lstrip(".").lower()
    if clean_ext not in {"jpg", "jpeg", "png", "webp"}:
        clean_ext = "png"

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    if custom_filename:
        # Clean custom filename
        safe_name = re.sub(r"[^\w\-.]", "_", custom_filename)
        cache_filename = f"{clean_side}_{safe_name}"
    else:
        cache_filename = f"{clean_side}_{timestamp_str}.{clean_ext}"

    cache_path = os.path.join(cache_dir, cache_filename)

    with open(cache_path, "wb") as f:
        f.write(raw_bytes)

    # Also maintain a canonical latest copy: {side}_scan.{clean_ext}
    canonical_path = os.path.join(cache_dir, f"{clean_side}_scan.{clean_ext}")
    try:
        with open(canonical_path, "wb") as f:
            f.write(raw_bytes)
    except Exception:
        pass

    return cache_path


def process_and_cache_image(
    file_or_bytes: Union[bytes, io.BytesIO, Any],
    side: str,
    filename: Optional[str] = None,
    cache_dir: str = DEFAULT_CACHE_DIR,
) -> Tuple[bool, Optional[str], Optional[ValidatedImage]]:
    """Extract bytes from an input source, validate it, save to cache, and wrap in ValidatedImage.

    Args:
        file_or_bytes: Raw bytes, BytesIO, or Streamlit UploadedFile/CameraInput
        side: 'front' or 'back'
        filename: Optional original filename
        cache_dir: Cache directory path

    Returns:
        (success, error_message, validated_image)
    """
    if file_or_bytes is None:
        return False, "No image provided.", None

    # Extract raw bytes and filename
    if isinstance(file_or_bytes, bytes):
        raw_bytes = file_or_bytes
        file_name = filename or f"{side}_input.png"
    elif hasattr(file_or_bytes, "getvalue"):
        # Streamlit UploadedFile / CameraInput
        raw_bytes = file_or_bytes.getvalue()
        file_name = getattr(file_or_bytes, "name", filename or f"{side}_input.png")
    elif hasattr(file_or_bytes, "read"):
        raw_bytes = file_or_bytes.read()
        file_name = getattr(file_or_bytes, "name", filename or f"{side}_input.png")
    else:
        return False, f"Unsupported image input type: {type(file_or_bytes)}", None

    is_valid, error_msg, pil_img, metadata = validate_image_bytes(raw_bytes, filename=file_name)
    if not is_valid or pil_img is None or metadata is None:
        return False, error_msg, None

    # Determine extension
    ext = "png"
    fmt = metadata.get("format", "").upper()
    if fmt == "JPEG":
        ext = "jpg"
    elif fmt == "WEBP":
        ext = "webp"
    elif fmt == "PNG":
        ext = "png"

    cache_path = save_to_cache(
        raw_bytes=raw_bytes,
        side=side,
        file_extension=ext,
        cache_dir=cache_dir,
        custom_filename=filename or file_name,
    )

    validated = ValidatedImage(
        image=pil_img,
        raw_bytes=raw_bytes,
        metadata=metadata,
        cache_path=cache_path,
        side=side,
        filename=file_name,
    )

    return True, None, validated


def check_inspection_readiness(session_state: Dict[str, Any]) -> Tuple[bool, Dict[str, bool]]:
    """Determine if front and back label images are both validated and ready in session state."""
    front_img = session_state.get("front_image")
    back_img = session_state.get("back_image")

    front_ready = isinstance(front_img, (dict, ValidatedImage)) and bool(front_img.get("image") or front_img.get("cache_path"))
    back_ready = isinstance(back_img, (dict, ValidatedImage)) and bool(back_img.get("image") or back_img.get("cache_path"))

    return (front_ready and back_ready), {"front": front_ready, "back": back_ready}
