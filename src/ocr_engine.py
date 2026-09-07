"""Digital Metrology Inspector - OCR Extraction Engine.

Handles text extraction from packaging label images per Legal Metrology (Packaged Commodities) Rules, 2011.
Supports:
1. PaddleOCR deep learning pipeline (PP-OCRv6) with lazy initialization.
2. Tesseract OCR and fallback mechanisms.
3. Reference coin ROI masking and filtering (prevents coin numerals/text from being extracted).
4. Rich annotated image generation displaying bounding boxes, text tags, and confidence scores.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image

# Configure logger
logger = logging.getLogger("ocr_engine")

# Ensure PaddleX cache home is within workspace
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", os.path.abspath(".paddlex"))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


@dataclass
class OCRLineItem:
    """Individual line item detected and extracted by the OCR engine."""

    text: str
    confidence: float
    bbox: list[int]  # [x_min, y_min, x_max, y_max]
    polygon: list[list[int]]  # [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
    width_px: float
    height_px: float


@dataclass
class OCRExtractionResult:
    """Consolidated result of OCR extraction on a label image."""

    lines: list[OCRLineItem] = field(default_factory=list)
    full_text: str = ""
    total_lines: int = 0
    avg_confidence: float = 0.0
    annotated_image: Optional[np.ndarray] = None
    engine_used: str = "none"


def load_image(image_input: Union[str, Image.Image, np.ndarray]) -> np.ndarray:
    """Load an image from filepath, PIL Image, or numpy array into BGR format."""
    if isinstance(image_input, str):
        if not os.path.exists(image_input):
            raise ValueError(f"Image path does not exist: {image_input}")
        img = cv2.imread(image_input)
        if img is None:
            raise ValueError(f"Failed to read image from path: {image_input}")
        return img
    elif isinstance(image_input, Image.Image):
        return cv2.cvtColor(np.array(image_input), cv2.COLOR_RGB2BGR)
    elif isinstance(image_input, np.ndarray):
        if image_input.size == 0:
            raise ValueError("Input image array is empty.")
        return image_input.copy()
    else:
        raise ValueError(f"Unsupported image input type: {type(image_input)}")


def is_in_coin_roi(
    bbox: list[int],
    coin_center: Optional[Tuple[int, int]],
    coin_radius: Optional[float],
    margin_ratio: float = 1.15,
) -> bool:
    """Check if a bounding box intersects or is contained within the reference coin ROI."""
    if coin_center is None or coin_radius is None or coin_radius <= 0:
        return False

    cx, cy = coin_center
    x_min, y_min, x_max, y_max = bbox
    effective_r = coin_radius * margin_ratio

    # Center of bbox
    box_cx = (x_min + x_max) / 2.0
    box_cy = (y_min + y_max) / 2.0
    dist_center = ((box_cx - cx) ** 2 + (box_cy - cy) ** 2) ** 0.5
    if dist_center <= effective_r:
        return True

    # Closest point on bounding box to coin center
    closest_x = max(x_min, min(cx, x_max))
    closest_y = max(y_min, min(cy, y_max))
    dist_closest = ((closest_x - cx) ** 2 + (closest_y - cy) ** 2) ** 0.5
    if dist_closest <= effective_r * 0.95:
        return True

    return False


def preprocess_for_dot_matrix(img: np.ndarray) -> np.ndarray:
    """Apply CLAHE, bilateral filtering, adaptive thresholding, and morphological closing to enhance dot-matrix text."""
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Apply CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # Bilateral filter to smooth noise but preserve edges
    filtered = cv2.bilateralFilter(enhanced, 9, 75, 75)

    # Adaptive thresholding with sufficiently large block size to avoid salt-and-pepper noise
    thresh = cv2.adaptiveThreshold(
        filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 5
    )

    # Morphological closing to connect dot gaps
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    # Convert back to BGR for PaddleOCR (inverting back to white background)
    closed_inv = cv2.bitwise_not(closed)
    return cv2.cvtColor(closed_inv, cv2.COLOR_GRAY2BGR)


def bbox_overlap_ratio(box1: list[int], box2: list[int]) -> float:
    """Calculate the overlap ratio between two bounding boxes: intersection / min(area1, area2)."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter_w = max(0, x2 - x1)
    inter_h = max(0, y2 - y1)
    inter_area = inter_w * inter_h

    if inter_area <= 0:
        return 0.0

    area1 = max(1, (box1[2] - box1[0]) * (box1[3] - box1[1]))
    area2 = max(1, (box2[2] - box2[0]) * (box2[3] - box2[1]))

    return float(inter_area) / float(min(area1, area2))


_paddle_ocr_singleton = None
_paddle_ocr_init_failed = False


def get_paddle_ocr():
    """Lazily initialize and cache the PaddleOCR engine instance."""
    global _paddle_ocr_singleton, _paddle_ocr_init_failed
    if _paddle_ocr_singleton is not None:
        return _paddle_ocr_singleton
    if _paddle_ocr_init_failed:
        return None

    try:
        pdx_cache = os.environ.get(
            "PADDLE_PDX_CACHE_HOME", os.path.abspath(".paddlex")
        )
        os.environ["PADDLE_PDX_CACHE_HOME"] = pdx_cache
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

        from paddleocr import PaddleOCR

        # Initialize PaddleOCR with orientation/unwarping disabled for speed and local model usage
        _paddle_ocr_singleton = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang="en",
        )
        return _paddle_ocr_singleton
    except Exception as exc:
        logger.warning(f"PaddleOCR lazy initialization failed: {exc}")
        _paddle_ocr_init_failed = True
        return None


def set_paddle_ocr_singleton(instance):
    """Set or mock the PaddleOCR instance (useful for unit testing)."""
    global _paddle_ocr_singleton, _paddle_ocr_init_failed
    _paddle_ocr_singleton = instance
    _paddle_ocr_init_failed = False


def reset_paddle_ocr_singleton():
    """Reset cached PaddleOCR instance."""
    global _paddle_ocr_singleton, _paddle_ocr_init_failed
    _paddle_ocr_singleton = None
    _paddle_ocr_init_failed = False


def _extract_tesseract(
    img: np.ndarray,
    coin_center: Optional[Tuple[int, int]] = None,
    coin_radius: Optional[float] = None,
) -> Optional[List[OCRLineItem]]:
    """Extract text lines using Tesseract TSV output."""
    tess_path = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract"
    if not os.path.exists(tess_path):
        return None

    try:
        _, encoded = cv2.imencode(".png", img)
        res = subprocess.run(
            [tess_path, "stdin", "stdout", "--psm", "6", "tsv"],
            input=encoded.tobytes(),
            capture_output=True,
            timeout=10,
        )
        if res.returncode != 0:
            return None

        stdout_str = res.stdout.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(stdout_str), delimiter="\t")
        words_by_line = {}
        for row in reader:
            try:
                conf = float(row.get("conf", -1))
                text = row.get("text", "").strip()
            except (ValueError, TypeError):
                continue
            if conf > 0 and text:
                key = (
                    row.get("block_num", "0"),
                    row.get("par_num", "0"),
                    row.get("line_num", "0"),
                )
                if key not in words_by_line:
                    words_by_line[key] = []
                words_by_line[key].append(
                    {
                        "text": text,
                        "conf": conf,
                        "left": int(row["left"]),
                        "top": int(row["top"]),
                        "width": int(row["width"]),
                        "height": int(row["height"]),
                    }
                )

        lines = []
        for _, words in words_by_line.items():
            line_text = " ".join(w["text"] for w in words).strip()
            if not line_text:
                continue
            min_x = min(w["left"] for w in words)
            min_y = min(w["top"] for w in words)
            max_x = max(w["left"] + w["width"] for w in words)
            max_y = max(w["top"] + w["height"] for w in words)
            bbox = [min_x, min_y, max_x, max_y]

            if is_in_coin_roi(bbox, coin_center, coin_radius):
                continue

            avg_c = float(np.mean([w["conf"] for w in words])) / 100.0
            lines.append(
                OCRLineItem(
                    text=line_text,
                    confidence=round(avg_c, 4),
                    bbox=bbox,
                    polygon=[
                        [min_x, min_y],
                        [max_x, min_y],
                        [max_x, max_y],
                        [min_x, max_y],
                    ],
                    width_px=float(max_x - min_x),
                    height_px=float(max_y - min_y),
                )
            )
        return lines
    except Exception as exc:
        logger.warning(f"Tesseract extraction failed: {exc}")
        return None


def draw_ocr_annotated_image(
    img: np.ndarray,
    lines: List[OCRLineItem],
    coin_center: Optional[Tuple[int, int]] = None,
    coin_radius: Optional[float] = None,
) -> np.ndarray:
    """Draw bounding boxes, line indices, text tags, and confidence on detected OCR lines."""
    annotated = img.copy()
    h_img, w_img = annotated.shape[:2]

    # Draw Coin ROI exclusion if provided
    if coin_center is not None and coin_radius is not None and coin_radius > 0:
        cx, cy = int(coin_center[0]), int(coin_center[1])
        r = int(coin_radius)
        cv2.circle(annotated, (cx, cy), r, (130, 130, 130), 2, cv2.LINE_AA)
        cv2.circle(annotated, (cx, cy), 3, (130, 130, 130), -1)
        cv2.putText(
            annotated,
            "Coin (Excluded)",
            (max(5, cx - r), max(18, cy - r - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (130, 130, 130),
            1,
            cv2.LINE_AA,
        )

    # Palette: Green / Emerald for OCR line items
    BOX_COLOR = (0, 200, 50)  # BGR: emerald green
    TAG_BG_COLOR = (0, 140, 30)  # BGR: darker green badge background
    TEXT_COLOR = (255, 255, 255)  # White text inside badge

    for idx, item in enumerate(lines):
        x_min, y_min, x_max, y_max = item.bbox

        # 1. Bounding box
        cv2.rectangle(annotated, (x_min, y_min), (x_max, y_max), BOX_COLOR, 2)

        # 2. Label badge
        display_text = f"#{idx+1}: {item.text[:24]} ({item.confidence:.0%})"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.40
        thickness = 1
        (label_w, label_h), _ = cv2.getTextSize(
            display_text, font, font_scale, thickness
        )

        # Badge position (above bbox if space, else inside top)
        if y_min - label_h - 6 >= 0:
            badge_y1 = y_min - label_h - 6
            badge_y2 = y_min
            text_y = y_min - 4
        else:
            badge_y1 = y_min
            badge_y2 = y_min + label_h + 6
            text_y = y_min + label_h + 2

        badge_x1 = max(0, x_min)
        badge_x2 = min(w_img, x_min + label_w + 6)

        cv2.rectangle(
            annotated,
            (badge_x1, badge_y1),
            (badge_x2, badge_y2),
            TAG_BG_COLOR,
            -1,
        )
        cv2.putText(
            annotated,
            display_text,
            (badge_x1 + 3, text_y),
            font,
            font_scale,
            TEXT_COLOR,
            thickness,
            cv2.LINE_AA,
        )

    return annotated


def extract_text_from_image(
    image_input: Union[str, Image.Image, np.ndarray],
    coin_center: Optional[Tuple[int, int]] = None,
    coin_radius: Optional[float] = None,
    engine: Optional[str] = None,
) -> OCRExtractionResult:
    """Extract text line items from a packaging label image with bounding boxes and confidence scores.

    Parameters
    ----------
    image_input : str, PIL.Image.Image, or np.ndarray
        Input packaging label image.
    coin_center : tuple of (int, int), optional
        Coordinates of reference coin center (x, y) to mask/exclude.
    coin_radius : float, optional
        Radius of reference coin in pixels to mask/exclude.
    engine : str, optional
        Force specific OCR engine ('paddleocr', 'tesseract', or None for auto).

    Returns
    -------
    OCRExtractionResult
        Consolidated extraction result with line items, full text, metrics, and annotated image.
    """
    try:
        img = load_image(image_input)
    except Exception as exc:
        return OCRExtractionResult(
            lines=[],
            full_text="",
            total_lines=0,
            avg_confidence=0.0,
            annotated_image=None,
            engine_used=f"error: {exc}",
        )

    # Coin ROI masking on working copy
    masked_img = img.copy()
    if coin_center is not None and coin_radius is not None and coin_radius > 0:
        cx, cy = int(coin_center[0]), int(coin_center[1])
        r = int(coin_radius * 1.15)
        # Fill circle with white to avoid detecting coin markings as label text
        cv2.circle(masked_img, (cx, cy), r, (255, 255, 255), -1)

    lines: List[OCRLineItem] = []
    used_engine = "none"

    # Option 1: PaddleOCR
    if engine is None or engine.lower() == "paddleocr":
        ocr = get_paddle_ocr()
        if ocr is not None:
            try:
                # Multi-pass: raw and preprocessed
                images_to_process = [masked_img, preprocess_for_dot_matrix(masked_img)]
                used_engine = "paddleocr"
                
                for img_pass in images_to_process:
                    preds = list(ocr.predict(img_pass))
                    if preds and len(preds) > 0:
                        item = preds[0]
                        rec_texts = item.get("rec_texts", [])
                        rec_scores = item.get("rec_scores", [])
                        rec_boxes = item.get("rec_boxes", [])
                        rec_polys = item.get("rec_polys", [])

                        for idx in range(len(rec_texts)):
                            text = str(rec_texts[idx]).strip()
                            if not text:
                                continue
                            conf = (
                                float(rec_scores[idx])
                                if idx < len(rec_scores)
                                else 0.9
                            )

                            if idx < len(rec_boxes):
                                b = rec_boxes[idx]
                                x1, y1, x2, y2 = (
                                    int(b[0]),
                                    int(b[1]),
                                    int(b[2]),
                                    int(b[3]),
                                )
                            else:
                                continue

                            x_min, x_max = min(x1, x2), max(x1, x2)
                            y_min, y_max = min(y1, y2), max(y1, y2)
                            if (x_max - x_min) < 8 or (y_max - y_min) < 8:
                                continue
                            bbox = [x_min, y_min, x_max, y_max]

                            # Ensure line does not intersect coin ROI
                            if is_in_coin_roi(bbox, coin_center, coin_radius):
                                continue

                            if idx < len(rec_polys):
                                poly_arr = np.array(rec_polys[idx], dtype=np.int32)
                                polygon = [
                                    [int(pt[0]), int(pt[1])] for pt in poly_arr
                                ]
                            else:
                                polygon = [
                                    [x_min, y_min],
                                    [x_max, y_min],
                                    [x_max, y_max],
                                    [x_min, y_max],
                                ]
                            
                            # Multi-pass deduplication:
                            # 1. High spatial overlap indicates the same physical line already extracted
                            # 2. Duplicate text at close vertical proximity is skipped
                            is_dup = False
                            for existing in lines:
                                overlap = bbox_overlap_ratio(bbox, existing.bbox)
                                if overlap > 0.40:
                                    is_dup = True
                                    break
                                norm_new = text.strip().lower()
                                norm_exist = existing.text.strip().lower()
                                if norm_new == norm_exist and abs(bbox[1] - existing.bbox[1]) < 40:
                                    is_dup = True
                                    break
                                if (norm_new in norm_exist or norm_exist in norm_new) and overlap > 0.20:
                                    is_dup = True
                                    break

                            if is_dup:
                                continue

                            lines.append(
                                OCRLineItem(
                                    text=text,
                                    confidence=round(conf, 4),
                                    bbox=bbox,
                                    polygon=polygon,
                                    width_px=float(x_max - x_min),
                                    height_px=float(y_max - y_min),
                                )
                            )
            except Exception as exc:
                logger.warning(f"PaddleOCR prediction failed: {exc}")

    # Option 2: Tesseract Fallback (if PaddleOCR wasn't used, failed, or was explicitly requested)
    if not lines and (
        engine is None or engine.lower() in ("tesseract", "fallback")
    ):
        tess_lines = _extract_tesseract(masked_img, coin_center, coin_radius)
        if tess_lines is not None:
            lines = tess_lines
            used_engine = "tesseract"

    # Sort lines in natural reading order: top-to-bottom, left-to-right
    lines = sorted(lines, key=lambda l: (round(l.bbox[1] / 15.0), l.bbox[0]))

    full_text = "\n".join(item.text for item in lines)
    total_lines = len(lines)
    avg_conf = (
        round(float(np.mean([item.confidence for item in lines])), 4)
        if lines
        else 0.0
    )

    annotated = draw_ocr_annotated_image(
        img=img,
        lines=lines,
        coin_center=coin_center,
        coin_radius=coin_radius,
    )

    return OCRExtractionResult(
        lines=lines,
        full_text=full_text,
        total_lines=total_lines,
        avg_confidence=avg_conf,
        annotated_image=annotated,
        engine_used=used_engine,
    )
