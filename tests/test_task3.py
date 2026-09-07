"""Verification test script for Task 3 (Digital Metrology Inspector).

Verifies:
1. Synthetic image generation:
   - Generates front packaging label with ₹5 coin placeholder
   - Generates back packaging label with ₹5 coin placeholder
2. Image validation & metadata extraction:
   - Validates format (JPG/PNG/WEBP), dimensions, and non-emptiness
   - Calculates width, height, aspect ratio, and file size in KB
   - Handles corrupted/empty/unsupported inputs appropriately
3. Local scan cache persistence:
   - Saves copies of processed images to `data/scans_cache/`
   - Verifies cache file existence, naming, and byte parity
4. Streamlit session state & readiness badge logic:
   - Confirms `st.session_state['front_image']` and `st.session_state['back_image']`
   - Verifies readiness logic when empty, partial, and complete
5. Streamlit App execution:
   - Verifies headless app execution via `streamlit.testing.v1.AppTest`
"""

import io
import os
import sys
from typing import Tuple

import unittest
import numpy as np
from PIL import Image, ImageDraw

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.image_handler import (
    DEFAULT_CACHE_DIR,
    DEFAULT_MAX_DIMENSION,
    ValidatedImage,
    check_inspection_readiness,
    compute_image_metadata,
    ensure_cache_dir,
    optimize_image_resolution,
    process_and_cache_image,
    save_to_cache,
    validate_image_bytes,
)


def create_synthetic_packaging_image(
    side: str = "front", width: int = 800, height: int = 600, img_format: str = "PNG"
) -> Tuple[bytes, Image.Image]:
    """Generate a high-quality synthetic packaging label with a ₹5 coin placeholder."""
    img = Image.new("RGB", (width, height), color=(248, 249, 250))
    draw = ImageDraw.Draw(img)

    # Outer border / packaging container
    draw.rectangle([(20, 20), (width - 20, height - 20)], fill=(255, 255, 255), outline=(180, 190, 200), width=3)

    if side.lower() == "front":
        # Product Brand Header
        draw.rectangle([(20, 20), (width - 20, 100)], fill=(33, 115, 70))
        draw.text((40, 45), "ORGANIC HARVEST WHOLE WHEAT CRACKERS", fill=(255, 255, 255))

        # Front declarations
        draw.text((50, 140), "Brand: Nature Pure Foods", fill=(40, 40, 40))
        draw.text((50, 180), "Net Quantity: 400 g", fill=(20, 20, 20))
        draw.text((50, 220), "Category: Packaged Food Grain Derivative", fill=(60, 60, 60))
        draw.text((50, 260), "100% Whole Wheat & High Dietary Fiber", fill=(33, 115, 70))
        draw.text((50, 300), "Zero Trans Fats | No Added Artificial Flavors", fill=(80, 80, 80))

        # Front Graphic Box
        draw.rectangle([(50, 360), (350, 520)], fill=(240, 248, 240), outline=(100, 180, 120), width=2)
        draw.text((70, 430), "[ PRODUCT ILLUSTRATION / SERVING ]", fill=(60, 120, 80))

    else:
        # Back Mandatory Declarations Header
        draw.rectangle([(20, 20), (width - 20, 90)], fill=(44, 62, 80))
        draw.text((40, 45), "MANDATORY DECLARATIONS (Legal Metrology Rules 2011)", fill=(255, 255, 255))

        # Back Declarations
        declarations = [
            "Commodity: Crisp Wheat Crackers",
            "Net Quantity: 400 g (When packed)",
            "Maximum Retail Price (MRP): Rs. 75.00 (Incl. of all taxes)",
            "Unit Sale Price (USP): Rs. 0.1875 per 1 g",
            "Month & Year of Manufacture: 08/2026",
            "Batch Number: ONH-26-0812",
            "Country of Origin: India",
            "Manufacturer: Nature Pure Foods Ltd, Plot 42, GIDC, Vadodara, Gujarat - 390010",
            "Consumer Care Cell: +91 1800-425-9000 | support@naturepure.in",
        ]
        y = 120
        for line in declarations:
            draw.text((50, y), line, fill=(30, 30, 30))
            y += 32

    # Draw Reference ₹5 Coin Placeholder (Circle with 21.9mm reference representation)
    coin_center_x, coin_center_y = width - 150, height - 150
    coin_radius = 50  # 100px diameter circle

    # Outer coin rim (Brass / Gold tones)
    draw.ellipse(
        [
            (coin_center_x - coin_radius, coin_center_y - coin_radius),
            (coin_center_x + coin_radius, coin_center_y + coin_radius),
        ],
        fill=(218, 165, 32),
        outline=(160, 120, 20),
        width=3,
    )

    # Inner concentric ridge
    inner_r = coin_radius - 8
    draw.ellipse(
        [
            (coin_center_x - inner_r, coin_center_y - inner_r),
            (coin_center_x + inner_r, coin_center_y + inner_r),
        ],
        fill=(238, 190, 60),
        outline=(180, 140, 30),
        width=2,
    )

    # Coin Label text
    draw.text((coin_center_x - 12, coin_center_y - 18), "₹5", fill=(80, 50, 10))
    draw.text((coin_center_x - 30, coin_center_y + 4), "21.9 mm", fill=(80, 50, 10))
    draw.text((coin_center_x - 45, coin_center_y + coin_radius + 10), "REFERENCE COIN", fill=(100, 70, 20))

    # Convert to bytes
    buf = io.BytesIO()
    save_format = "JPEG" if img_format.upper() in ["JPG", "JPEG"] else "PNG"
    img.save(buf, format=save_format)
    img_bytes = buf.getvalue()

    return img_bytes, img


def test_synthetic_image_generation():
    """Verify generation of synthetic front and back label images."""
    print("\n--- 1. Testing Synthetic Image Generation ---")
    front_bytes, front_img = create_synthetic_packaging_image(side="front", width=800, height=600, img_format="PNG")
    back_bytes, back_img = create_synthetic_packaging_image(side="back", width=800, height=600, img_format="PNG")

    assert len(front_bytes) > 0, "Synthetic front image bytes are empty"
    assert len(back_bytes) > 0, "Synthetic back image bytes are empty"
    assert front_img.size == (800, 600), f"Unexpected front image size: {front_img.size}"
    assert back_img.size == (800, 600), f"Unexpected back image size: {back_img.size}"

    # Save to sample_data directory for persistence and reuse in downstream tasks
    samples_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "sample_data"))
    os.makedirs(samples_dir, exist_ok=True)
    front_path = os.path.join(samples_dir, "synthetic_front.png")
    back_path = os.path.join(samples_dir, "synthetic_back.png")

    with open(front_path, "wb") as f:
        f.write(front_bytes)
    with open(back_path, "wb") as f:
        f.write(back_bytes)

    assert os.path.isfile(front_path), "Failed to save synthetic front image"
    assert os.path.isfile(back_path), "Failed to save synthetic back image"

    print(f"✓ Generated synthetic Front image: {len(front_bytes)} bytes (saved at {front_path})")
    print(f"✓ Generated synthetic Back image: {len(back_bytes)} bytes (saved at {back_path})")
    return front_bytes, back_bytes


def test_image_validation_and_metadata(front_bytes: bytes, back_bytes: bytes):
    """Verify validation logic, error handling, and metadata calculation."""
    print("\n--- 2. Testing Image Validation & Metadata Extraction ---")

    # Positive validation for Front
    valid_f, err_f, img_f, meta_f = validate_image_bytes(front_bytes, filename="front.png")
    assert valid_f is True, f"Front image validation failed: {err_f}"
    assert img_f is not None, "Front PIL image is None"
    assert meta_f is not None, "Front metadata is None"
    assert meta_f["width"] == 800, f"Expected width 800, got {meta_f['width']}"
    assert meta_f["height"] == 600, f"Expected height 600, got {meta_f['height']}"
    assert meta_f["aspect_ratio"] == 1.33, f"Expected aspect ratio 1.33, got {meta_f['aspect_ratio']}"
    assert meta_f["size_kb"] > 0, "size_kb must be greater than 0"
    assert meta_f["format"] == "PNG", f"Expected format PNG, got {meta_f['format']}"
    print(f"✓ Front image metadata verified: {meta_f['dimensions']}, {meta_f['size_kb']} KB, ratio: {meta_f['aspect_ratio']}")

    # Positive validation for Back
    valid_b, err_b, img_b, meta_b = validate_image_bytes(back_bytes, filename="back.png")
    assert valid_b is True, f"Back image validation failed: {err_b}"
    assert meta_b["width"] == 800
    assert meta_b["height"] == 600
    print(f"✓ Back image metadata verified: {meta_b['dimensions']}, {meta_b['size_kb']} KB, ratio: {meta_b['aspect_ratio']}")

    # Negative Test 1: Empty bytes
    valid_empty, err_empty, _, _ = validate_image_bytes(b"")
    assert valid_empty is False, "Empty bytes should fail validation"
    assert "empty" in err_empty.lower(), f"Unexpected error message for empty bytes: {err_empty}"
    print(f"✓ Empty bytes rejection verified: '{err_empty}'")

    # Negative Test 2: Corrupted bytes
    corrupted_data = b"NOT_AN_IMAGE_HEADER_1234567890"
    valid_corrupt, err_corrupt, _, _ = validate_image_bytes(corrupted_data)
    assert valid_corrupt is False, "Corrupted bytes should fail validation"
    print(f"✓ Corrupt data rejection verified: '{err_corrupt}'")

    # Negative Test 3: Unsupported format (e.g. BMP)
    bmp_buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(bmp_buf, format="BMP")
    valid_bmp, err_bmp, _, _ = validate_image_bytes(bmp_buf.getvalue(), filename="test.bmp")
    assert valid_bmp is False, "BMP format should fail format validation"
    assert "unsupported" in err_bmp.lower(), f"Unexpected message for unsupported format: {err_bmp}"
    print(f"✓ Unsupported format rejection verified: '{err_bmp}'")

    # Negative Test 4: Too small dimensions (< 50px)
    tiny_buf = io.BytesIO()
    Image.new("RGB", (30, 30)).save(tiny_buf, format="PNG")
    valid_tiny, err_tiny, _, _ = validate_image_bytes(tiny_buf.getvalue(), filename="tiny.png")
    assert valid_tiny is False, "Image smaller than 50x50 should fail validation"
    assert "too small" in err_tiny.lower(), f"Unexpected message for small image: {err_tiny}"
    print(f"✓ Dimension threshold check verified: '{err_tiny}'")


def test_caching_and_session_state(front_bytes: bytes, back_bytes: bytes):
    """Verify processing, cache file creation in data/scans_cache/, and session state readiness."""
    print("\n--- 3. Testing Local Scan Cache & Session State Handling ---")

    test_cache_dir = DEFAULT_CACHE_DIR
    ensure_cache_dir(test_cache_dir)

    # Process Front image
    success_f, err_f, val_front = process_and_cache_image(
        file_or_bytes=front_bytes,
        side="front",
        filename="test_front_label.png",
        cache_dir=test_cache_dir,
    )
    assert success_f is True, f"Failed to process front image: {err_f}"
    assert isinstance(val_front, ValidatedImage), "Result is not a ValidatedImage instance"
    assert isinstance(val_front, dict), "ValidatedImage must inherit from dict"
    assert os.path.isfile(val_front.cache_path), f"Cache file not created at {val_front.cache_path}"
    assert os.path.getsize(val_front.cache_path) == len(front_bytes), "Cached file size does not match input"
    print(f"✓ Front image cached at: {val_front.cache_path} ({os.path.getsize(val_front.cache_path)} bytes)")

    # Canonical copy check
    canonical_front = os.path.join(test_cache_dir, "front_scan.png")
    assert os.path.isfile(canonical_front), f"Canonical front copy not found at {canonical_front}"
    print(f"✓ Canonical front file verified at: {canonical_front}")

    # Process Back image
    success_b, err_b, val_back = process_and_cache_image(
        file_or_bytes=back_bytes,
        side="back",
        filename="test_back_label.png",
        cache_dir=test_cache_dir,
    )
    assert success_b is True, f"Failed to process back image: {err_b}"
    assert os.path.isfile(val_back.cache_path), f"Cache file not created at {val_back.cache_path}"
    print(f"✓ Back image cached at: {val_back.cache_path} ({os.path.getsize(val_back.cache_path)} bytes)")

    # Test Session State & Readiness Logic
    mock_session = {"front_image": None, "back_image": None}

    # Case A: None loaded
    ready, status = check_inspection_readiness(mock_session)
    assert not ready, "Readiness should be False when images are None"
    assert not status["front"] and not status["back"]
    print("✓ Readiness check (empty): Not ready [front=False, back=False]")

    # Case B: Only front loaded
    mock_session["front_image"] = val_front
    ready, status = check_inspection_readiness(mock_session)
    assert not ready, "Readiness should be False when only front image is loaded"
    assert status["front"] and not status["back"]
    print("✓ Readiness check (partial - front only): Not ready [front=True, back=False]")

    # Case C: Only back loaded
    mock_session["front_image"] = None
    mock_session["back_image"] = val_back
    ready, status = check_inspection_readiness(mock_session)
    assert not ready, "Readiness should be False when only back image is loaded"
    assert not status["front"] and status["back"]
    print("✓ Readiness check (partial - back only): Not ready [front=False, back=True]")

    # Case D: Both front and back loaded
    mock_session["front_image"] = val_front
    mock_session["back_image"] = val_back
    ready, status = check_inspection_readiness(mock_session)
    assert ready, "Readiness should be True when both images are loaded"
    assert status["front"] and status["back"]
    print("✓ Readiness check (complete): READY FOR INSPECTION [front=True, back=True]")

    # Check attribute and dict access equivalence
    assert val_front["width"] == val_front.width == 800
    assert val_front["height"] == val_front.height == 600
    assert val_front["cache_path"] == val_front.cache_path
    print("✓ ValidatedImage dual dict/attribute access verified successfully")

    return val_front, val_back


def test_streamlit_headless_execution():
    """Verify that app.py runs without exceptions in headless Streamlit environment."""
    print("\n--- 4. Testing Headless Streamlit App Execution ---")
    try:
        from streamlit.testing.v1 import AppTest

        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        at = AppTest.from_file(app_path)
        at.run()

        assert not at.exception, f"Streamlit app raised uncaught exception: {at.exception}"

        # Verify page title and sidebar
        titles = [t.value for t in at.title]
        assert "🔍 Digital Metrology Inspector" in titles, "Main header missing from AppTest"
        print("✓ AppTest initialized cleanly and rendered main title and guidelines")

        # Verify button exists and is disabled initially
        inspect_buttons = [
            b for b in at.button
            if "Start Automated Inspection" in b.label or "Start Metrology Compliance Inspection" in b.label
        ]
        assert len(inspect_buttons) > 0, "Inspection button missing"
        assert inspect_buttons[0].disabled is True, "Inspection button must be disabled when images are absent"
        print("✓ Inspection button present and correctly disabled when awaiting inputs")

        print("✓ Headless Streamlit App execution passed all checks!")
    except Exception as e:
        print(f"AppTest verification encountered: {e}")
        raise e


def test_image_resolution_optimization():
    """Verify optimize_image_resolution proportionally resizes down preserving aspect ratio."""
    print("\n--- 5. Testing Image Resolution Optimization (Max Dimension 1920px) ---")

    # Case A: Landscape image exceeding 1920px (4032x3024)
    img_land = Image.new("RGB", (4032, 3024), color=(200, 200, 200))
    opt_land = optimize_image_resolution(img_land, max_dimension=1920)
    assert opt_land.size == (1920, 1440), f"Expected (1920, 1440), got {opt_land.size}"
    aspect_orig = round(4032 / 3024, 4)
    aspect_opt = round(opt_land.width / opt_land.height, 4)
    assert abs(aspect_orig - aspect_opt) < 1e-3, f"Aspect ratio altered: {aspect_orig} vs {aspect_opt}"
    print(f"✓ Landscape 4032x3024 downscaled to {opt_land.size} with exact aspect ratio preserved")

    # Case B: Portrait image exceeding 1920px (3024x4032)
    img_port = Image.new("RGB", (3024, 4032), color=(200, 200, 200))
    opt_port = optimize_image_resolution(img_port, max_dimension=1920)
    assert opt_port.size == (1440, 1920), f"Expected (1440, 1920), got {opt_port.size}"
    aspect_orig_p = round(3024 / 4032, 4)
    aspect_opt_p = round(opt_port.width / opt_port.height, 4)
    assert abs(aspect_orig_p - aspect_opt_p) < 1e-3, f"Aspect ratio altered: {aspect_orig_p} vs {aspect_opt_p}"
    print(f"✓ Portrait 3024x4032 downscaled to {opt_port.size} with exact aspect ratio preserved")

    # Case C: Image within 1920px (e.g. 800x600) remains untouched
    img_small = Image.new("RGB", (800, 600), color=(150, 150, 150))
    opt_small = optimize_image_resolution(img_small, max_dimension=1920)
    assert opt_small.size == (800, 600), f"Small image modified: {opt_small.size}"
    print(f"✓ Image within bounds (800x600) retained without modification")

    # Case D: OpenCV numpy array downscaling
    arr = np.zeros((3024, 4032, 3), dtype=np.uint8)
    opt_arr = optimize_image_resolution(arr, max_dimension=1920)
    assert opt_arr.shape == (1440, 1920, 3), f"OpenCV array shape mismatch: {opt_arr.shape}"
    print(f"✓ OpenCV ndarray downscaled from (3024, 4032) to {opt_arr.shape[:2]}")

    # Case E: Integration with process_and_cache_image on oversized image
    buf = io.BytesIO()
    img_land.save(buf, format="JPEG")
    raw_large_bytes = buf.getvalue()

    ok, err, val_large = process_and_cache_image(
        raw_large_bytes, side="back", filename="test_oversized.jpg"
    )
    assert ok is True, f"Failed to process oversized image: {err}"
    assert val_large is not None
    assert val_large.width == 1920 and val_large.height == 1440
    assert val_large.is_optimized is True
    assert val_large.metadata["original_dimensions"] == "4032 × 3024"
    assert os.path.isfile(val_large.cache_path)
    # Confirm cached file on disk is also 1920x1440
    with Image.open(val_large.cache_path) as disk_img:
        assert disk_img.size == (1920, 1440), f"Cached disk image size mismatch: {disk_img.size}"
        disk_size = disk_img.size
    print(f"✓ process_and_cache_image automatically optimized 4032x3024 -> {disk_size} on disk")


class TestTask3ImageHandling(unittest.TestCase):
    """Unittest TestCase wrapper for Task 3 verification suite."""

    def test_synthetic_image_generation(self):
        front_bytes, back_bytes = test_synthetic_image_generation()
        self.assertGreater(len(front_bytes), 0)
        self.assertGreater(len(back_bytes), 0)

    def test_image_validation_and_metadata(self):
        front_bytes, back_bytes = create_synthetic_packaging_image(side="front"), create_synthetic_packaging_image(side="back")
        test_image_validation_and_metadata(front_bytes[0], back_bytes[0])

    def test_caching_and_session_state(self):
        front_bytes, back_bytes = create_synthetic_packaging_image(side="front"), create_synthetic_packaging_image(side="back")
        test_caching_and_session_state(front_bytes[0], back_bytes[0])

    def test_image_resolution_optimization(self):
        test_image_resolution_optimization()

    def test_streamlit_headless_execution(self):
        test_streamlit_headless_execution()


def main():
    """Execute complete Task 3 verification suite."""
    print("=" * 60)
    print("STARTING TASK 3 VERIFICATION SUITE (Image Input Handling)")
    print("=" * 60)

    front_bytes, back_bytes = test_synthetic_image_generation()
    test_image_validation_and_metadata(front_bytes, back_bytes)
    val_front, val_back = test_caching_and_session_state(front_bytes, back_bytes)
    test_image_resolution_optimization()
    test_streamlit_headless_execution()

    print("\n" + "=" * 60)
    print("ALL TASK 3 VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    main()
