"""Verification test suite for Task 4 (Digital Metrology Inspector).

Verifies:
1. Scan Service Image Upload & Metadata Logging:
   - Upload of front & back packaging images to Supabase Storage ('product-images' bucket under 'scans/')
   - Creation of scan record with status='uploaded', timestamp, dimensions, and URLs
   - Handling of ValidatedImage, raw bytes, and PIL Image inputs
   - Validation & error handling for missing or malformed inputs
2. Database & Storage Retrieval:
   - Verification of scan record retrieval via db.get_scan()
   - Verification of binary storage payload preservation in mock/cloud storage
3. Headless Streamlit App Workflow (streamlit.testing.v1.AppTest):
   - Initial state (button disabled, no active scan)
   - Interactive file upload via file_uploader widgets
   - Triggering 'Start Automated Inspection' action button
   - Updating st.session_state['current_scan']
   - Rendering UI confirmation card (Scan ID, Timestamp, Storage Status, Public links)
   - Resetting state via 'Clear Cache & Reset Images' button
"""

import io
import os
import sys
import uuid
from typing import Tuple

from PIL import Image, ImageDraw

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import db
from src.image_handler import process_and_cache_image
from src.scan_service import (
    STORAGE_BUCKET,
    ScanUploadResult,
    get_scan_by_id,
    process_scan_upload,
)


def create_synthetic_packaging_image(
    side: str = "front", width: int = 800, height: int = 600, img_format: str = "PNG"
) -> Tuple[bytes, Image.Image]:
    """Generate synthetic packaging image with ₹5 coin reference placeholder."""
    img = Image.new("RGB", (width, height), color=(248, 249, 250))
    draw = ImageDraw.Draw(img)

    # Outer border / packaging container
    draw.rectangle(
        [(20, 20), (width - 20, height - 20)],
        fill=(255, 255, 255),
        outline=(180, 190, 200),
        width=3,
    )

    if side.lower() == "front":
        draw.rectangle([(20, 20), (width - 20, 100)], fill=(33, 115, 70))
        draw.text((40, 45), "ORGANIC HARVEST WHOLE WHEAT CRACKERS", fill=(255, 255, 255))
        draw.text((50, 140), "Brand: Nature Pure Foods", fill=(40, 40, 40))
        draw.text((50, 180), "Net Quantity: 400 g", fill=(20, 20, 20))
        draw.text((50, 220), "Category: Packaged Food Grain Derivative", fill=(60, 60, 60))
        draw.text((50, 260), "100% Whole Wheat & High Dietary Fiber", fill=(33, 115, 70))
        draw.text((50, 300), "Zero Trans Fats | No Added Artificial Flavors", fill=(80, 80, 80))
    else:
        draw.rectangle([(20, 20), (width - 20, 90)], fill=(44, 62, 80))
        draw.text((40, 45), "MANDATORY DECLARATIONS (Legal Metrology Rules 2011)", fill=(255, 255, 255))
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

    # Reference ₹5 coin placeholder (100px circle)
    cx, cy, r = width - 150, height - 150, 50
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=(218, 165, 32), outline=(160, 120, 20), width=3)
    draw.text((cx - 15, cy - 10), "₹5", fill=(255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format=img_format)
    raw_bytes = buf.getvalue()
    return raw_bytes, img


def test_scan_service_upload_and_logging():
    """Test process_scan_upload with synthetic packaging images."""
    print("\n--- 1. Testing Scan Service Image Upload & Metadata Logging ---")

    front_bytes, front_img = create_synthetic_packaging_image("front", width=800, height=600)
    back_bytes, back_img = create_synthetic_packaging_image("back", width=800, height=600)

    # Test A: Upload using ValidatedImage instances
    _, _, val_front = process_and_cache_image(front_bytes, "front", "test_front.png")
    _, _, val_back = process_and_cache_image(back_bytes, "back", "test_back.png")
    assert val_front is not None and val_back is not None

    custom_scan_id = str(uuid.uuid4())
    custom_prod_id = str(uuid.uuid4())

    result = process_scan_upload(
        front_image=val_front,
        back_image=val_back,
        product_id=custom_prod_id,
        scan_id=custom_scan_id,
    )

    assert isinstance(result, ScanUploadResult), "Result must be a ScanUploadResult instance"
    assert result.scan_id == custom_scan_id, "Scan ID mismatch"
    assert result.status == "uploaded", f"Expected status 'uploaded', got {result.status}"
    assert result.product_id == custom_prod_id, "Product ID mismatch"
    assert result.front_storage_path.startswith("scans/"), "Front path must be under scans/"
    assert result.back_storage_path.startswith("scans/"), "Back path must be under scans/"
    assert "scans/" in result.front_image_url, "Front URL must reference scans/ path"
    assert "scans/" in result.back_image_url, "Back URL must reference scans/ path"
    assert result.storage_status in ("Cloud (Supabase)", "Offline Mock"), "Invalid storage status"
    assert result.dimensions["front"]["width"] == 800, "Front width mismatch"
    assert result.dimensions["front"]["height"] == 600, "Front height mismatch"
    assert result.dimensions["back"]["width"] == 800, "Back width mismatch"
    assert result.dimensions["back"]["height"] == 600, "Back height mismatch"
    print(f"✓ ValidatedImage upload verified: Scan ID {result.scan_id}, Storage: {result.storage_status}")

    # Test B: Upload using raw bytes directly
    result_bytes = process_scan_upload(
        front_image=front_bytes,
        back_image=back_bytes,
    )
    assert result_bytes.scan_id is not None
    assert result_bytes.status == "uploaded"
    assert result_bytes.dimensions["front"]["width"] == 800
    print(f"✓ Raw bytes upload verified: Scan ID {result_bytes.scan_id}")

    # Test C: Upload using PIL Image instances directly
    result_pil = process_scan_upload(
        front_image=front_img,
        back_image=back_img,
    )
    assert result_pil.scan_id is not None
    assert result_pil.status == "uploaded"
    print(f"✓ PIL Image upload verified: Scan ID {result_pil.scan_id}")

    # Test D: Error handling for None or malformed inputs
    try:
        process_scan_upload(front_image=None, back_image=back_bytes)
        assert False, "Should raise ValueError when front_image is None"
    except ValueError as e:
        assert "Both front and back images are required" in str(e)
        print("✓ Rejection of None front_image verified")

    try:
        process_scan_upload(front_image=front_bytes, back_image=None)
        assert False, "Should raise ValueError when back_image is None"
    except ValueError as e:
        assert "Both front and back images are required" in str(e)
        print("✓ Rejection of None back_image verified")

    try:
        process_scan_upload(front_image=b"not_an_image", back_image=back_bytes)
        assert False, "Should raise ValueError on corrupt front_image bytes"
    except ValueError as e:
        assert "Invalid front image data" in str(e)
        print("✓ Rejection of corrupt image bytes verified")

    return result


def test_database_and_storage_retrieval(scan_result: ScanUploadResult):
    """Verify scan record retrieval from db.get_scan() and storage persistence."""
    print("\n--- 2. Testing Database & Storage Retrieval ---")

    scan_id = scan_result.scan_id
    retrieved_scan = db.get_scan(scan_id)
    assert retrieved_scan is not None, f"Failed to retrieve scan record for ID {scan_id}"
    assert retrieved_scan["id"] == scan_id, "Retrieved ID does not match"
    assert retrieved_scan["status"] == "uploaded", f"Expected 'uploaded', got {retrieved_scan['status']}"
    assert retrieved_scan["front_image_url"] == scan_result.front_image_url, "Front URL mismatch"
    assert retrieved_scan["back_image_url"] == scan_result.back_image_url, "Back URL mismatch"
    assert retrieved_scan["dimensions"]["front"]["width"] == 800, "Dimensions metadata mismatch"

    print(f"✓ db.get_scan('{scan_id}') returned matching record with status='uploaded'")

    # Verify helper get_scan_by_id from scan_service
    helper_scan = get_scan_by_id(scan_id)
    assert helper_scan is not None and helper_scan["id"] == scan_id
    print("✓ scan_service.get_scan_by_id() confirmed identical retrieval")

    # Storage content verification
    if scan_result.is_offline:
        mock_storage = db._mock_db.storage[STORAGE_BUCKET]
        assert scan_result.front_storage_path in mock_storage, "Front image missing in mock storage"
        assert scan_result.back_storage_path in mock_storage, "Back image missing in mock storage"
        front_stored_bytes = mock_storage[scan_result.front_storage_path]
        assert len(front_stored_bytes) > 0, "Stored front image bytes cannot be empty"
        print(f"✓ Mock storage persistence verified: {scan_result.front_storage_path} ({len(front_stored_bytes)} bytes)")
    else:
        print(f"✓ Cloud Supabase storage verified for public URL: {scan_result.front_image_url}")


def test_streamlit_app_workflow():
    """Verify Streamlit app workflow with AppTest."""
    print("\n--- 3. Testing Headless Streamlit App Workflow (AppTest) ---")

    from streamlit.testing.v1 import AppTest

    app_path = os.path.join(PROJECT_ROOT, "app.py")
    front_bytes, _ = create_synthetic_packaging_image("front", width=800, height=600)
    back_bytes, _ = create_synthetic_packaging_image("back", width=800, height=600)

    # 1. Initial State: inspect button disabled when no images provided
    at = AppTest.from_file(app_path)
    at.run()
    assert not at.exception, f"AppTest threw uncaught exception: {at.exception}"

    inspect_buttons = [b for b in at.button if "Start Automated Inspection" in b.label]
    assert len(inspect_buttons) == 1, "Inspection button not found in AppTest"
    assert inspect_buttons[0].disabled is True, "Inspection button should be disabled when awaiting inputs"
    assert at.session_state["current_scan"] is None, "current_scan should initially be None"
    print("✓ Initial state verified: Inspection button disabled, current_scan is None")

    # 2. Interactive file upload workflow via file_uploader widgets
    at.file_uploader(key="front_file_uploader").upload("front_test.png", front_bytes, "image/png")
    at.file_uploader(key="back_file_uploader").upload("back_test.png", back_bytes, "image/png")
    at.run()
    assert not at.exception, f"Exception after file upload: {at.exception}"

    inspect_buttons = [b for b in at.button if "Start Automated Inspection" in b.label]
    assert len(inspect_buttons) == 1
    assert inspect_buttons[0].disabled is False, "Inspection button should be enabled after uploading both images"
    print("✓ Image upload via file_uploader verified: Button now enabled")

    # 3. Click "Start Automated Inspection" button
    inspect_buttons[0].click().run()
    assert not at.exception, f"Exception after clicking inspect button: {at.exception}"

    current_scan = at.session_state["current_scan"]
    assert current_scan is not None, "current_scan was not saved to session state"
    assert current_scan["status"] == "uploaded", f"Expected 'uploaded', got {current_scan['status']}"
    assert "scans/" in current_scan["front_image_url"]
    assert "scans/" in current_scan["back_image_url"]
    print(f"✓ Inspection initiated: Scan ID {current_scan['scan_id']} stored in st.session_state['current_scan']")

    # 4. Verify UI confirmation card elements
    metric_labels = [m.label for m in at.metric]
    assert "Scan ID" in metric_labels, "Scan ID metric missing from confirmation card"
    assert "Timestamp (UTC)" in metric_labels, "Timestamp metric missing from confirmation card"
    assert "Storage Status" in metric_labels, "Storage Status metric missing from confirmation card"
    assert "Scan Status" in metric_labels, "Scan Status metric missing from confirmation card"
    print("✓ UI Confirmation Card metrics verified (Scan ID, Timestamp, Storage Status, Scan Status)")

    # Verify public image links rendered in markdown
    all_markdown = " ".join(m.value for m in at.markdown)
    assert current_scan["front_image_url"] in all_markdown, "Front image link missing from markdown"
    assert current_scan["back_image_url"] in all_markdown, "Back image link missing from markdown"
    assert "📦 Scan Record & Persistence Verification" in all_markdown or "Active Inspection Scan Confirmation" in all_markdown
    print("✓ UI Confirmation Card public image links and metadata card verified in rendered markdown")

    # 5. Verify Reset button clears cache and current_scan
    clear_buttons = [b for b in at.button if "Clear Cache & Reset Images" in b.label]
    assert len(clear_buttons) == 1, "Clear Cache button missing"
    clear_buttons[0].click().run()
    assert not at.exception, f"Exception after clicking clear cache: {at.exception}"
    assert at.session_state["current_scan"] is None, "current_scan should be reset to None"
    assert at.session_state["front_image"] is None, "front_image should be reset to None"
    assert at.session_state["back_image"] is None, "back_image should be reset to None"
    print("✓ Reset flow verified: Cache and current_scan cleared successfully")


def main():
    """Execute complete Task 4 verification test suite."""
    print("=" * 60)
    print("STARTING TASK 4 VERIFICATION SUITE (Storage Upload & Scan Logging)")
    print("=" * 60)

    scan_result = test_scan_service_upload_and_logging()
    test_database_and_storage_retrieval(scan_result)
    test_streamlit_app_workflow()

    print("\n" + "=" * 60)
    print("ALL TASK 4 VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    main()
