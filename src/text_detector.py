"""Digital Metrology Inspector - Text Region Detection Module.

Extracts localized text regions from packaging label images.
Supports:
1. Morphological Contour bounding box detection (OpenCV CLAHE + adaptive thresholding)
2. PaddleOCR detection pipeline when available
3. Reference coin ROI exclusion (prevents coin numerals/edges from being misclassified as text)
4. Visualization with cyan bounding boxes on annotated output.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image

# Ensure PaddleX cache home is within workspace
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", os.path.abspath(".paddlex"))


@dataclass
class TextRegion:
    bbox: list[int]  # [x_min, y_min, x_max, y_max]
    polygon: list[list[int]]  # [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
    width_px: float
    height_px: float
    confidence: float


@dataclass
class TextDetectionResult:
    regions: list[TextRegion] = field(default_factory=list)
    total_regions: int = 0
    annotated_image: Optional[np.ndarray] = None
    message: str = ""


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
        return image_input.copy()
    else:
        raise ValueError(f"Unsupported image input type: {type(image_input)}")


def is_in_coin_roi(
    bbox: list[int],
    coin_center: Optional[Tuple[int, int]],
    coin_radius: Optional[float],
    margin_ratio: float = 1.15,
) -> bool:
    """Check if a bounding box intersects or is contained within the coin ROI."""
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


def merge_boxes_into_lines(
    boxes: List[Tuple[int, int, int, int]],
    max_x_gap_ratio: float = 2.0,
    min_y_overlap_ratio: float = 0.4,
) -> List[Tuple[int, int, int, int]]:
    """Iteratively merge horizontally adjacent text bounding boxes on the same line.

    boxes: List of (x, y, w, h)
    Returns: List of merged (x, y, w, h) sorted in reading order.
    """
    if not boxes:
        return []

    current = list(boxes)
    while True:
        merged = []
        has_merged = False
        for b in current:
            x1, y1, w1, h1 = b
            x2, y2 = x1 + w1, y1 + h1
            matched = False
            for i, mb in enumerate(merged):
                mx1, my1, mw, mh = mb
                mx2, my2 = mx1 + mw, my1 + mh
                overlap_y = max(0, min(y2, my2) - max(y1, my1))
                min_h = min(h1, mh)
                if min_h > 0 and (overlap_y / min_h) >= min_y_overlap_ratio:
                    if x1 <= mx2 and x2 >= mx1:
                        x_dist = 0
                    else:
                        x_dist = max(0, max(x1 - mx2, mx1 - x2))
                    if x_dist <= max(h1, mh) * max_x_gap_ratio:
                        new_x1 = min(x1, mx1)
                        new_y1 = min(y1, my1)
                        new_x2 = max(x2, mx2)
                        new_y2 = max(y2, my2)
                        merged[i] = (
                            new_x1,
                            new_y1,
                            new_x2 - new_x1,
                            new_y2 - new_y1,
                        )
                        has_merged = True
                        matched = True
                        break
            if not matched:
                merged.append(b)
        current = merged
        if not has_merged:
            break

    return sorted(current, key=lambda b: (round(b[1] / 20.0), b[0]))


def detect_text_regions_morphological(
    img: np.ndarray,
    coin_center: Optional[Tuple[int, int]] = None,
    coin_radius: Optional[float] = None,
    min_width: int = 12,
    min_height: int = 8,
    min_area: int = 80,
    merge_lines: bool = True,
) -> List[TextRegion]:
    """Detect text regions using OpenCV CLAHE, adaptive thresholding, and morphological operations."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 1. CLAHE contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl_gray = clahe.apply(gray)

    # 2. Adaptive thresholding
    thresh = cv2.adaptiveThreshold(
        cl_gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        15,
        6,
    )

    # 3. Exclude Coin ROI area directly in binary threshold
    if coin_center is not None and coin_radius is not None and coin_radius > 0:
        cx, cy = int(coin_center[0]), int(coin_center[1])
        r = int(coin_radius * 1.15)
        cv2.circle(thresh, (cx, cy), r, 0, -1)

    # 4. Morphological closing to bridge character gaps
    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel_close)

    # 5. Extract contours
    contours, _ = cv2.findContours(
        closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    h_img, w_img = img.shape[:2]
    max_area = 0.85 * (h_img * w_img)

    raw_boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if w < min_width or h < min_height or area < min_area or area > max_area:
            continue
        # Double-check coin ROI exclusion
        if is_in_coin_roi([x, y, x + w, y + h], coin_center, coin_radius):
            continue
        raw_boxes.append((x, y, w, h))

    # 6. Optionally merge adjacent boxes on the same line
    if merge_lines:
        boxes = merge_boxes_into_lines(raw_boxes)
    else:
        boxes = sorted(raw_boxes, key=lambda b: (round(b[1] / 20.0), b[0]))

    # 7. Convert to TextRegion objects
    regions: List[TextRegion] = []
    for x, y, w, h in boxes:
        # Re-check coin ROI exclusion post-merge
        if is_in_coin_roi([x, y, x + w, y + h], coin_center, coin_radius):
            continue

        x_min, y_min = max(0, x), max(0, y)
        x_max, y_max = min(w_img, x + w), min(h_img, y + h)

        # Calculate heuristic confidence based on stroke density
        roi_thresh = thresh[y_min:y_max, x_min:x_max]
        if roi_thresh.size > 0:
            stroke_ratio = np.count_nonzero(roi_thresh) / float(roi_thresh.size)
            if 0.05 <= stroke_ratio <= 0.60:
                conf = float(
                    round(min(0.98, 0.82 + 0.16 * (stroke_ratio / 0.3)), 2)
                )
            else:
                conf = 0.75
        else:
            conf = 0.70

        polygon = [
            [x_min, y_min],
            [x_max, y_min],
            [x_max, y_max],
            [x_min, y_max],
        ]

        regions.append(
            TextRegion(
                bbox=[x_min, y_min, x_max, y_max],
                polygon=polygon,
                width_px=float(x_max - x_min),
                height_px=float(y_max - y_min),
                confidence=conf,
            )
        )

    return regions


def _try_detect_paddleocr(
    img: np.ndarray,
    coin_center: Optional[Tuple[int, int]],
    coin_radius: Optional[float],
) -> Optional[List[TextRegion]]:
    """Attempt PaddleOCR detection if local models are available."""
    pdx_cache = os.environ.get(
        "PADDLE_PDX_CACHE_HOME", os.path.abspath(".paddlex")
    )
    official_models_dir = os.path.join(pdx_cache, "official_models")
    if not os.path.isdir(official_models_dir) or not os.listdir(
        official_models_dir
    ):
        return None

    try:
        from paddleocr import PaddleOCR

        ocr = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang="en",
        )
        raw_results = ocr.ocr(img, det=True, rec=False)
        if not raw_results or not raw_results[0]:
            return []

        h_img, w_img = img.shape[:2]
        regions: List[TextRegion] = []
        for poly in raw_results[0]:
            poly_np = np.array(poly, dtype=np.int32)
            x_min = int(np.min(poly_np[:, 0]))
            y_min = int(np.min(poly_np[:, 1]))
            x_max = int(np.max(poly_np[:, 0]))
            y_max = int(np.max(poly_np[:, 1]))

            bbox = [
                max(0, x_min),
                max(0, y_min),
                min(w_img, x_max),
                min(h_img, y_max),
            ]
            if is_in_coin_roi(bbox, coin_center, coin_radius):
                continue

            width = float(bbox[2] - bbox[0])
            height = float(bbox[3] - bbox[1])
            if width < 8 or height < 6:
                continue

            regions.append(
                TextRegion(
                    bbox=bbox,
                    polygon=[[int(p[0]), int(p[1])] for p in poly],
                    width_px=width,
                    height_px=height,
                    confidence=0.95,
                )
            )
        return regions
    except Exception:
        return None


def draw_annotated_image(
    img: np.ndarray,
    regions: List[TextRegion],
    coin_center: Optional[Tuple[int, int]] = None,
    coin_radius: Optional[float] = None,
) -> np.ndarray:
    """Draw cyan bounding boxes and index tags on detected text regions."""
    annotated = img.copy()

    # Cyan in BGR format: B=255, G=255, R=0
    CYAN_BGR = (255, 255, 0)

    # Optionally draw coin exclusion circle if provided
    if coin_center is not None and coin_radius is not None and coin_radius > 0:
        cx, cy = int(coin_center[0]), int(coin_center[1])
        r = int(coin_radius)
        cv2.circle(annotated, (cx, cy), r, (140, 140, 140), 1, cv2.LINE_AA)
        cv2.putText(
            annotated,
            "Coin (Excluded)",
            (max(5, cx - r), max(15, cy - r - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (140, 140, 140),
            1,
            cv2.LINE_AA,
        )

    for i, r in enumerate(regions):
        x_min, y_min, x_max, y_max = r.bbox
        # Draw Cyan bounding box
        cv2.rectangle(annotated, (x_min, y_min), (x_max, y_max), CYAN_BGR, 2)

        # Small index tag
        tag = f"#{i+1}"
        tag_y = max(14, y_min - 4)
        cv2.putText(
            annotated,
            tag,
            (x_min, tag_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            CYAN_BGR,
            1,
            cv2.LINE_AA,
        )

    return annotated


def detect_text_regions(
    image_input: Union[str, Image.Image, np.ndarray],
    coin_center: Optional[Tuple[int, int]] = None,
    coin_radius: Optional[float] = None,
    method: str = "auto",
    merge_lines: bool = True,
) -> TextDetectionResult:
    """Detect bounding boxes of text regions from an input image.

    Parameters
    ----------
    image_input : str, PIL.Image.Image, or np.ndarray
        Path to image, PIL Image instance, or BGR numpy array.
    coin_center : tuple of (int, int), optional
        Coordinates of the coin center (x, y) to exclude from text detection.
    coin_radius : float, optional
        Radius of the coin in pixels to exclude from text detection.
    method : str, default 'auto'
        Detection method: 'auto', 'morphology', or 'paddleocr'.
    merge_lines : bool, default True
        Whether to merge horizontally adjacent text blocks into text lines.

    Returns
    -------
    TextDetectionResult
        Dataclass containing regions, total_regions count, annotated_image, and status message.
    """
    try:
        img = load_image(image_input)
    except Exception as exc:
        return TextDetectionResult(
            regions=[],
            total_regions=0,
            annotated_image=None,
            message=f"Image load error: {exc}",
        )

    regions: List[TextRegion] = []
    used_method = "morphology"

    # Option B: Try PaddleOCR if requested or in auto mode
    if method in ("paddleocr", "auto"):
        paddle_regions = _try_detect_paddleocr(img, coin_center, coin_radius)
        if paddle_regions is not None:
            regions = paddle_regions
            used_method = "paddleocr"
        elif method == "paddleocr":
            return TextDetectionResult(
                regions=[],
                total_regions=0,
                annotated_image=img,
                message="PaddleOCR detection pipeline is unavailable.",
            )

    # Option A: Morphological Contour detection
    if used_method == "morphology":
        regions = detect_text_regions_morphological(
            img=img,
            coin_center=coin_center,
            coin_radius=coin_radius,
            merge_lines=merge_lines,
        )

    annotated = draw_annotated_image(
        img=img,
        regions=regions,
        coin_center=coin_center,
        coin_radius=coin_radius,
    )

    coin_msg = (
        f" (Coin ROI at {coin_center} excluded)"
        if coin_center and coin_radius
        else ""
    )
    msg = (
        f"Detected {len(regions)} text region(s) using {used_method} pipeline{coin_msg}."
        if regions
        else f"No text regions detected using {used_method} pipeline{coin_msg}."
    )

    return TextDetectionResult(
        regions=regions,
        total_regions=len(regions),
        annotated_image=annotated,
        message=msg,
    )
