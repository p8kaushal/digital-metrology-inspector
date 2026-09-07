"""Digital Metrology Inspector - Streamlit Application.

Prototype compliance verification system for Legal Metrology (Packaged Commodities) Rules, 2011.
Provides dual image handling (Front & Back packaging labels) with file upload and camera capture,
validation, PIL preview generation, metadata display, and scan caching.
"""

import os
import streamlit as st
from PIL import Image
import cv2
from src.coin_detector import detect_coin
from src.calibration import compute_calibration

from src.image_handler import (
    DEFAULT_CACHE_DIR,
    check_inspection_readiness,
    ensure_cache_dir,
    process_and_cache_image,
)
from src.scan_service import process_scan_upload

# Configure page
st.set_page_config(
    page_title="Digital Metrology Inspector",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Ensure scan cache directory exists
ensure_cache_dir(DEFAULT_CACHE_DIR)

# Initialize Session State
if "front_image" not in st.session_state:
    st.session_state["front_image"] = None
if "back_image" not in st.session_state:
    st.session_state["back_image"] = None
if "current_scan" not in st.session_state:
    st.session_state["current_scan"] = None

# Sidebar Instructions & System Info
with st.sidebar:
    st.title("📋 Metrology Guidelines")
    st.markdown(
        """
        ### 1. Inspection Setup
        - **Reference Coin**: Place a standard **₹5 coin** (21.9 mm fixed diameter) on the exact same plane as the product label.
        - **Illumination**: Ensure bright, glare-free lighting with sharp contrast on printed declarations.
        - **Orientation**: Ensure label text and coin are unoccluded and parallel to the camera lens.

        ---
        ### 2. Supported Formats & Limits
        - **Formats**: JPG, JPEG, PNG, WEBP
        - **Max File Size**: 50 MB
        - **Min Resolution**: 50 × 50 px (High-res 1080p+ recommended for OCR)
        - **Standard**: Legal Metrology (Packaged Commodities) Rules, 2011

        ---
        ### 3. Local Scan Cache
        - Active cache: `data/scans_cache/`
        """
    )

    if st.button("🗑️ Clear Cache & Reset Images", use_container_width=True):
        st.session_state["front_image"] = None
        st.session_state["back_image"] = None
        st.session_state["current_scan"] = None
        st.rerun()

    st.divider()
    st.info("System Ready for Image Input Handling.")

# Header
st.title("🔍 Digital Metrology Inspector")
st.caption("Automated Legal Metrology Compliance & Real-World Font Measurement (SIH26034)")

# Top Status Badges
all_ready, readiness = check_inspection_readiness(st.session_state)

status_col1, status_col2, status_col3 = st.columns([1, 1, 1.2])

with status_col1:
    if readiness["front"]:
        st.success("🟢 Front Label: **Ready for Inspection**")
    else:
        st.warning("🟠 Front Label: **Awaiting Image**")

with status_col2:
    if readiness["back"]:
        st.success("🟢 Back Label: **Ready for Inspection**")
    else:
        st.warning("🟠 Back Label: **Awaiting Image**")

with status_col3:
    if all_ready:
        st.success("✅ **Inspection Ready** (Both labels validated)")
    elif readiness["front"] or readiness["back"]:
        st.info("⏳ **Partial Input** (1 of 2 labels loaded)")
    else:
        st.info("ℹ️ **Awaiting Inputs** (Front + Back with ₹5 coin)")

st.markdown("---")


# Helper to render side-by-side inputs, validation, preview, and metadata
def render_label_input_column(side_title: str, side_key: str):
    """Render File Uploader & Camera Capture side-by-side, preview, and metadata."""
    st.subheader(side_title)
    st.write(f"Ensure **{side_key.title()} label** declarations and reference **₹5 coin** are clearly visible.")

    # Side-by-side Input Methods: File Uploader and Camera Capture
    input_col1, input_col2 = st.columns(2)

    with input_col1:
        st.markdown("**Option A: Upload File**")
        uploaded_file = st.file_uploader(
            f"Upload {side_key.title()} Image",
            type=["jpg", "jpeg", "png", "webp"],
            key=f"{side_key}_file_uploader",
            help=f"Select JPG, PNG, or WEBP image file for {side_key} packaging.",
        )

    with input_col2:
        st.markdown("**Option B: Camera Capture**")
        camera_photo = st.camera_input(
            f"Capture {side_key.title()} Photo",
            key=f"{side_key}_camera_input",
            help=f"Capture live camera photo of {side_key} packaging.",
        )

    # Determine Active Input Source
    active_source = None
    if uploaded_file is not None and camera_photo is not None:
        source_selection = st.radio(
            f"Active {side_key.title()} Image Source:",
            ["Uploaded File", "Camera Photo"],
            horizontal=True,
            key=f"{side_key}_source_selector",
        )
        active_source = uploaded_file if source_selection == "Uploaded File" else camera_photo
    elif uploaded_file is not None:
        active_source = uploaded_file
    elif camera_photo is not None:
        active_source = camera_photo

    # Process and Validate Image
    if active_source is not None:
        file_name = getattr(active_source, "name", f"{side_key}_captured.png")
        success, err_msg, validated = process_and_cache_image(
            file_or_bytes=active_source,
            side=side_key,
            filename=file_name,
        )

        if success and validated is not None:
            st.session_state[f"{side_key}_image"] = validated
            st.success(f"✓ {side_key.title()} Image Validated & Cached successfully")
        else:
            st.error(f"❌ {side_key.title()} Image Error: {err_msg}")
            st.session_state[f"{side_key}_image"] = None
    elif st.session_state.get(f"{side_key}_image") is not None:
        # Preserve already validated image in session state
        pass
    else:
        st.session_state[f"{side_key}_image"] = None

    # Render Preview & Metadata if Valid Image in Session State
    validated_img = st.session_state.get(f"{side_key}_image")
    if validated_img is not None:
        st.markdown("#### 🖼️ Image Preview & Specifications")

        if st.button(f"🔍 Detect ₹5 Coin in {side_key.title()}", key=f"detect_coin_{side_key}"):
            with st.spinner(f"Detecting coin in {side_key} image..."):
                res = detect_coin(validated_img.cache_path)
                if res.detected:
                    st.success(res.message)
                    calib_res = compute_calibration(res)
                    if calib_res.is_calibrated:
                        st.info(f"📐 **Calibration Ratio:** `{calib_res.pixels_per_mm:.2f} px/mm`")
                    st.image(
                        cv2.cvtColor(res.annotated_image, cv2.COLOR_BGR2RGB),
                        caption=f"{side_key.title()} Coin Detected: D={res.pixel_diameter:.1f}px",
                        use_container_width=True
                    )
                else:
                    st.warning(res.message)

        st.image(
            validated_img.image,
            caption=f"{side_key.title()} Label Preview ({validated_img.width} × {validated_img.height} px)",
            use_container_width=True,
        )

        # Metadata cards
        meta = validated_img.metadata
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Dimensions", f"{meta['width']} × {meta['height']} px")
        m2.metric("Aspect Ratio", f"{meta['aspect_ratio']}:1")
        m3.metric("File Size", f"{meta['size_kb']} KB")
        m4.metric("Format", f"{meta['format']} ({meta['mode']})")

        rel_cache_path = os.path.relpath(validated_img.cache_path, os.getcwd())
        st.caption(f"💾 **Cached locally at:** `{rel_cache_path}`")
    else:
        st.info(f"Awaiting {side_key} label image upload or camera capture...")


# Side-by-side Front and Back Label Panels
col_front, col_back = st.columns(2)

with col_front:
    render_label_input_column("📷 Front Packaging Label", "front")

with col_back:
    render_label_input_column("📷 Back Packaging Label", "back")

st.markdown("---")

# Inspection Workflow Section
st.subheader("⚙️ Metrology Compliance Inspection Workflow")

# Re-check readiness after both columns have executed
all_ready, readiness = check_inspection_readiness(st.session_state)

workflow_col1, workflow_col2 = st.columns([2, 1])

with workflow_col1:
    if all_ready:
        st.success(
            "🎉 **Both Front and Back packaging images are validated and cached!**\n\n"
            "Ready to proceed with Reference Coin Detection (₹5 coin / 21.9mm calibration) and OCR text extraction."
        )
    elif readiness["front"] and not readiness["back"]:
        st.warning("⚠️ **Front label is loaded, but Back label is missing.** Please provide the Back label image.")
    elif not readiness["front"] and readiness["back"]:
        st.warning("⚠️ **Back label is loaded, but Front label is missing.** Please provide the Front label image.")
    else:
        st.info("ℹ️ Upload or capture both Front and Back images (with reference ₹5 coin) to begin inspection.")

with workflow_col2:
    run_inspection = st.button(
        "🚀 Start Automated Inspection",
        type="primary",
        disabled=(not all_ready),
        use_container_width=True,
    )

if run_inspection:
    with st.spinner("Processing packaging images and uploading to storage..."):
        try:
            scan_result = process_scan_upload(
                front_image=st.session_state["front_image"],
                back_image=st.session_state["back_image"],
            )
            st.session_state["current_scan"] = scan_result
            st.balloons()
            st.success("✅ Inspection scan initialized! Images uploaded and metadata logged to database.")
        except Exception as exc:
            st.error(f"❌ Failed to process scan upload: {exc}")

# Confirmation Card for Active / Uploaded Scan
if st.session_state.get("current_scan") is not None:
    current_scan = st.session_state["current_scan"]
    st.markdown("---")
    st.markdown("### 📋 Active Inspection Scan Confirmation")

    # Key metrics row
    card_col1, card_col2, card_col3, card_col4 = st.columns(4)
    with card_col1:
        scan_id_val = current_scan.get("scan_id", "")
        short_id = f"{scan_id_val[:8]}..." if len(scan_id_val) > 12 else scan_id_val
        st.metric("Scan ID", short_id, help=scan_id_val)
    with card_col2:
        raw_ts = current_scan.get("timestamp", "")
        formatted_ts = raw_ts[:19].replace("T", " ") if "T" in raw_ts else raw_ts
        st.metric("Timestamp (UTC)", formatted_ts)
    with card_col3:
        st.metric("Storage Status", current_scan.get("storage_status", "Offline Mock"))
    with card_col4:
        st.metric("Scan Status", current_scan.get("status", "uploaded").upper())

    # Metadata & Public Links Container Card
    st.markdown(
        f"""
        <div style="background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; padding: 18px; margin-top: 12px; margin-bottom: 12px;">
            <h4 style="margin-top: 0; color: #1e293b;">📦 Scan Record & Persistence Verification</h4>
            <p style="margin-bottom: 8px; color: #334155;">
                <strong>Scan UUID:</strong> <code>{current_scan.get('scan_id')}</code><br>
                <strong>Timestamp:</strong> <code>{current_scan.get('timestamp')}</code><br>
                <strong>Storage Mode:</strong> <span style="font-weight: 600; color: {'#0d6efd' if not current_scan.get('is_offline') else '#fd7e14'};">{current_scan.get('storage_status')}</span><br>
                <strong>Label Dimensions:</strong> {current_scan.get('dimensions', {}).get('summary', 'N/A')}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Public image links
    st.markdown(
        f"""
**Public Image Links:**
- 🔗 **Front Label Image:** [{current_scan.get('front_image_url')}]({current_scan.get('front_image_url')})
- 🔗 **Back Label Image:** [{current_scan.get('back_image_url')}]({current_scan.get('back_image_url')})
        """
    )

    st.info(
        "Scan registered in database table `scans`. Storage upload verified. "
        "Next steps: Task 5 (Coin Detection) and Task 6 (Pixels/mm Calibration)."
    )

