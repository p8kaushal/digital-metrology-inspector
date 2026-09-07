#!/usr/bin/env python3
"""Verification Script: Image Optimization & Processing Speed Acceleration.

Verifies:
1. optimize_image_resolution downsamples images where max(width, height) > 1920px.
2. Exact aspect ratio is preserved without distortion.
3. Downstream modules (Coin Detection, Text Region Detection, PaddleOCR, Font Measurement)
   operate seamlessly on the optimized 1920px image.
4. Total execution time on raw 12-megapixel product_1_back.jpg drops from > 700s to < 30s.
"""

import os
import sys
import time
from PIL import Image

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.calibration import compute_calibration
from src.coin_detector import detect_coin
from src.field_parser import parse_ocr_lines
from src.font_measurement import measure_font_heights
from src.image_handler import (
    DEFAULT_MAX_DIMENSION,
    optimize_image_resolution,
    process_and_cache_image,
)
from src.ocr_engine import extract_text_from_image, get_paddle_ocr
from src.text_detector import detect_text_regions


def run_verification(image_path: str = "test_samples/product_1/product_1_back.jpg"):
    print("=" * 75)
    print("DIGITAL METROLOGY INSPECTOR: IMAGE OPTIMIZATION VERIFICATION")
    print("=" * 75)

    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Target sample image not found at: {image_path}")

    # Inspect original image resolution
    with Image.open(image_path) as raw_img:
        orig_w, orig_h = raw_img.size
        orig_res = f"{orig_w}x{orig_h}"
        orig_aspect = round(orig_w / orig_h, 4) if orig_h > 0 else 0

    print(f"Target Packaging Image      : {image_path}")
    print(f"Original Image Resolution   : {orig_res} ({orig_aspect}:1)")
    print(f"Original File Size          : {round(os.path.getsize(image_path) / (1024 * 1024), 2)} MB")

    # Ensure PaddleOCR singleton is ready
    get_paddle_ocr()

    print("\nStarting timed pipeline execution...")
    t_start = time.time()

    # Step 1: Ingestion & Resolution Optimization
    with open(image_path, "rb") as f:
        raw_bytes = f.read()

    success, err_msg, validated_img = process_and_cache_image(
        file_or_bytes=raw_bytes,
        side="back",
        filename=os.path.basename(image_path),
        max_dimension=DEFAULT_MAX_DIMENSION,
    )
    if not success or validated_img is None:
        raise RuntimeError(f"process_and_cache_image failed: {err_msg}")

    new_res = f"{validated_img.width}x{validated_img.height}"
    new_aspect = round(validated_img.width / validated_img.height, 4)

    # Step 2: Coin Detection & Calibration
    coin_res = detect_coin(validated_img.cache_path)
    calib_res = compute_calibration(coin_res) if coin_res.detected else None

    # Step 3: Text Region Detection
    c_center = coin_res.center if coin_res.detected else None
    c_radius = coin_res.radius if coin_res.detected else None
    text_res = detect_text_regions(
        validated_img.cache_path,
        coin_center=c_center,
        coin_radius=c_radius,
    )

    # Step 4: PaddleOCR Line Extraction
    ocr_res = extract_text_from_image(
        validated_img.cache_path,
        coin_center=c_center,
        coin_radius=c_radius,
    )

    # Step 5: Statutory Field Parsing
    parsed_res = parse_ocr_lines(ocr_res)

    # Step 6: Font Height Measurement & Rule 7 Evaluation
    font_res = measure_font_heights(parsed_res, calib_res)

    t_end = time.time()
    exec_time = round(t_end - t_start, 2)

    print("\n" + "-" * 75)
    print("PIPELINE EXECUTION METRICS")
    print("-" * 75)
    print(f"Original Image Resolution   : {orig_res}")
    print(f"New Resized Resolution      : {new_res} ({new_aspect}:1)")
    print(f"Aspect Ratio Invariance     : delta={abs(orig_aspect - new_aspect):.6f}")
    print(f"Total Execution Time        : {exec_time} seconds")
    print(f"Coin Detected               : {coin_res.detected} (D={coin_res.pixel_diameter:.1f}px, ratio={calib_res.pixels_per_mm:.2f} px/mm)")
    print(f"Text Regions Detected       : {text_res.total_regions}")
    print(f"OCR Lines Extracted         : {ocr_res.total_lines} lines (Avg Conf: {ocr_res.avg_confidence:.1%})")
    print(f"Cached Disk Image           : {validated_img.cache_path}")
    print(f"Cached Image Dimensions     : {validated_img.dimensions}")
    print(f"Is Optimized Flag           : {validated_img.is_optimized}")
    print("-" * 75)

    # Assertions
    assert validated_img.is_optimized, "Image should be flagged as is_optimized=True"
    assert max(validated_img.width, validated_img.height) <= DEFAULT_MAX_DIMENSION, (
        f"Max dimension {max(validated_img.width, validated_img.height)} exceeds limit {DEFAULT_MAX_DIMENSION}"
    )
    assert abs(orig_aspect - new_aspect) < 1e-3, "Aspect ratio was not preserved during downscaling"
    assert exec_time < 30.0, f"Execution time {exec_time}s exceeds 30.0 seconds threshold!"

    print("\n[VERIFICATION RESULT]: ALL ASSERTIONS PASSED!")
    print(f"✓ Total execution time ({exec_time}s) dropped significantly below 30.0s threshold.")
    print(f"✓ Resolution successfully downsampled from {orig_res} to {new_res} with exact aspect ratio.")
    print("=" * 75)
    return exec_time


if __name__ == "__main__":
    run_verification()
