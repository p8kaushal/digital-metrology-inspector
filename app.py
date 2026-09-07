"""Digital Metrology Inspector - Streamlit Application.

Prototype compliance verification system for Legal Metrology (Packaged Commodities) Rules, 2011.
Provides dual image handling (Front & Back packaging labels) with file upload and camera capture,
validation, PIL preview generation, metadata display, and scan caching.
"""

import os
import uuid
import streamlit as st
from PIL import Image
import cv2
import numpy as np
from src.coin_detector import detect_coin
from src.calibration import compute_calibration
from src.text_detector import detect_text_regions
from src.ocr_engine import extract_text_from_image
from src.field_parser import parse_ocr_lines
from src.font_measurement import measure_font_heights

from src.image_handler import (
    DEFAULT_CACHE_DIR,
    check_inspection_readiness,
    ensure_cache_dir,
    process_and_cache_image,
)
from src.scan_service import (
    ReportUploadResult,
    process_scan_upload,
    save_scan_extraction_results,
    upload_inspection_report,
)
from src.consolidation import ConsolidatedProductRecord, consolidate_scan_records
from src.report_generator import ReportGenerationResult, generate_inspection_report

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
if "front_persistence" not in st.session_state:
    st.session_state["front_persistence"] = None
if "back_persistence" not in st.session_state:
    st.session_state["back_persistence"] = None
if "active_scan_id" not in st.session_state:
    st.session_state["active_scan_id"] = None
if "consolidated_record" not in st.session_state:
    st.session_state["consolidated_record"] = None
if "report_result" not in st.session_state:
    st.session_state["report_result"] = None
if "report_upload_result" not in st.session_state:
    st.session_state["report_upload_result"] = None

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
        st.session_state["front_coin"] = None
        st.session_state["back_coin"] = None
        st.session_state["front_calibration"] = None
        st.session_state["back_calibration"] = None
        st.session_state["front_text_result"] = None
        st.session_state["back_text_result"] = None
        st.session_state["front_ocr_result"] = None
        st.session_state["back_ocr_result"] = None
        st.session_state["front_parsed_fields"] = None
        st.session_state["back_parsed_fields"] = None
        st.session_state["front_font_report"] = None
        st.session_state["back_font_report"] = None
        st.session_state["front_persistence"] = None
        st.session_state["back_persistence"] = None
        st.session_state["active_scan_id"] = None
        st.session_state["consolidated_record"] = None
        st.session_state["report_result"] = None
        st.session_state["report_upload_result"] = None
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

        # Action Buttons: Coin Detection, Text Region Detection, & OCR Extraction
        btn_col1, btn_col2, btn_col3 = st.columns(3)
        with btn_col1:
            if st.button(
                f"🔍 Detect Coin ({side_key.title()})",
                key=f"detect_coin_{side_key}",
                use_container_width=True,
            ):
                with st.spinner(f"Detecting ₹5 coin in {side_key} image..."):
                    coin_res = detect_coin(validated_img.cache_path)
                    st.session_state[f"{side_key}_coin"] = coin_res
                    if coin_res.detected:
                        calib_res = compute_calibration(coin_res)
                        st.session_state[f"{side_key}_calibration"] = calib_res
                    else:
                        st.session_state[f"{side_key}_calibration"] = None

        with btn_col2:
            if st.button(
                f"📝 Detect Regions ({side_key.title()})",
                key=f"detect_text_{side_key}",
                use_container_width=True,
            ):
                with st.spinner(f"Detecting text regions in {side_key} image..."):
                    coin_res = st.session_state.get(f"{side_key}_coin")
                    if coin_res is None or not getattr(coin_res, "detected", False):
                        coin_res = detect_coin(validated_img.cache_path)
                        if coin_res.detected:
                            st.session_state[f"{side_key}_coin"] = coin_res
                            st.session_state[f"{side_key}_calibration"] = compute_calibration(coin_res)

                    c_center = coin_res.center if (coin_res and coin_res.detected) else None
                    c_radius = coin_res.radius if (coin_res and coin_res.detected) else None

                    text_res = detect_text_regions(
                        image_input=validated_img.cache_path,
                        coin_center=c_center,
                        coin_radius=c_radius,
                    )
                    st.session_state[f"{side_key}_text_result"] = text_res

        with btn_col3:
            if st.button(
                f"🔤 Perform OCR Extraction",
                key=f"ocr_button_{side_key}",
                use_container_width=True,
            ):
                with st.spinner(f"Extracting text via OCR ({side_key.title()})..."):
                    coin_res = st.session_state.get(f"{side_key}_coin")
                    if coin_res is None or not getattr(coin_res, "detected", False):
                        coin_res = detect_coin(validated_img.cache_path)
                        if coin_res.detected:
                            st.session_state[f"{side_key}_coin"] = coin_res
                            st.session_state[f"{side_key}_calibration"] = compute_calibration(coin_res)

                    c_center = coin_res.center if (coin_res and coin_res.detected) else None
                    c_radius = coin_res.radius if (coin_res and coin_res.detected) else None

                    ocr_res = extract_text_from_image(
                        image_input=validated_img.cache_path,
                        coin_center=c_center,
                        coin_radius=c_radius,
                    )
                    st.session_state[f"{side_key}_ocr_result"] = ocr_res

        # Coin status feedback
        coin_res = st.session_state.get(f"{side_key}_coin")
        if coin_res is not None:
            if coin_res.detected:
                st.success(f"✓ {coin_res.message}")
                calib_res = st.session_state.get(f"{side_key}_calibration")
                if calib_res and calib_res.is_calibrated:
                    st.info(f"📐 **Calibration:** `{calib_res.pixels_per_mm:.2f} px/mm` (Coin D: {coin_res.pixel_diameter:.1f}px)")
            else:
                st.warning(f"⚠️ {coin_res.message}")

        # Text region status & metrics feedback
        text_res = st.session_state.get(f"{side_key}_text_result")
        if text_res is not None:
            if text_res.total_regions > 0:
                st.success(f"✓ {text_res.message}")
                calib_res = st.session_state.get(f"{side_key}_calibration")
                tm1, tm2, tm3 = st.columns(3)
                tm1.metric("Text Regions", text_res.total_regions)
                avg_w = np.mean([r.width_px for r in text_res.regions])
                avg_h = np.mean([r.height_px for r in text_res.regions])
                tm2.metric("Avg Region Width", f"{avg_w:.1f} px")
                if calib_res and calib_res.is_calibrated:
                    avg_h_mm = avg_h / calib_res.pixels_per_mm
                    tm3.metric("Avg Region Height", f"{avg_h:.1f} px ({avg_h_mm:.2f} mm)")
                else:
                    tm3.metric("Avg Region Height", f"{avg_h:.1f} px")
            else:
                st.warning(f"⚠️ {text_res.message}")

        # OCR extraction status, metrics & text display
        ocr_res = st.session_state.get(f"{side_key}_ocr_result")
        if ocr_res is not None:
            if ocr_res.total_lines > 0:
                st.success(f"✓ Extracted {ocr_res.total_lines} line(s) via {ocr_res.engine_used.upper()} (Avg Confidence: {ocr_res.avg_confidence:.1%})")
                om1, om2, om3 = st.columns(3)
                om1.metric("Extracted Lines", ocr_res.total_lines)
                om2.metric("Avg Confidence", f"{ocr_res.avg_confidence:.1%}")
                om3.metric("OCR Engine", ocr_res.engine_used.upper())

                with st.expander(f"🔤 Extracted Text & Line Details ({ocr_res.total_lines} lines)", expanded=True):
                    st.markdown("**Full Extracted Text Summary:**")
                    st.text_area(
                        "Extracted Text Summary",
                        value=ocr_res.full_text,
                        height=110,
                        disabled=True,
                        key=f"full_text_{side_key}",
                        label_visibility="collapsed",
                    )

                    calib_res = st.session_state.get(f"{side_key}_calibration")
                    ocr_table = []
                    for idx, line in enumerate(ocr_res.lines):
                        row = {
                            "Line #": idx + 1,
                            "Extracted Text": line.text,
                            "Confidence": f"{line.confidence:.2%}",
                            "BBox": str(line.bbox),
                            "Height (px)": f"{line.height_px:.1f}",
                        }
                        if calib_res and calib_res.is_calibrated:
                            row["Height (mm)"] = f"{(line.height_px / calib_res.pixels_per_mm):.2f}"
                        ocr_table.append(row)
                    st.dataframe(ocr_table, use_container_width=True)
            else:
                st.warning(f"⚠️ No text lines extracted via OCR engine ({ocr_res.engine_used}).")
                
            if ocr_res.total_lines > 0:
                parsed_res = parse_ocr_lines(ocr_res)
                st.session_state[f"{side_key}_parsed_fields"] = parsed_res

                calib_res = st.session_state.get(f"{side_key}_calibration")
                font_report = measure_font_heights(parsed_res, calib_res)
                st.session_state[f"{side_key}_font_report"] = font_report

                # Automatically persist extraction results to Supabase (Task 11)
                active_scan = st.session_state.get("current_scan")
                if active_scan and active_scan.get("scan_id"):
                    active_scan_id = active_scan.get("scan_id")
                else:
                    if not st.session_state.get("active_scan_id"):
                        st.session_state["active_scan_id"] = str(uuid.uuid4())
                    active_scan_id = st.session_state["active_scan_id"]

                persist_res = save_scan_extraction_results(
                    scan_id=active_scan_id,
                    parsed_fields_result=parsed_res,
                    font_measurement_report=font_report,
                    side=side_key,
                )
                st.session_state[f"{side_key}_persistence"] = persist_res

                with st.expander(f"📋 Extracted Mandatory Fields ({parsed_res.total_fields_found}) & Font Measurements", expanded=True):
                    if parsed_res.missing_mandatory_fields:
                        st.warning(f"⚠️ Missing Mandatory Fields: {', '.join([f.replace('_', ' ').title() for f in parsed_res.missing_mandatory_fields])}")

                    # Persistence Confirmation Badge
                    if persist_res and persist_res.saved_count > 0:
                        st.success(f"💾 Saved {persist_res.saved_count} fields to Supabase")

                    # Rule 7 Compliance Visual Metrics and Badges
                    fm1, fm2, fm3 = st.columns(3)
                    fm1.metric("Mandatory Fields Found", f"{parsed_res.total_fields_found}/9")
                    if font_report.calibrated_fields_count > 0:
                        fm2.metric(
                            "Rule 7 Compliance",
                            f"{font_report.compliant_fields_count}/{font_report.calibrated_fields_count} Passed",
                            delta="100% Compliant" if font_report.non_compliant_fields_count == 0 else f"-{font_report.non_compliant_fields_count} Deficit",
                            delta_color="normal" if font_report.non_compliant_fields_count == 0 else "inverse",
                        )
                        fm3.metric("Calibration Ratio", f"{font_report.calibration_ratio_used:.2f} px/mm")
                        if font_report.non_compliant_fields_count > 0:
                            st.warning(f"⚠️ **Rule 7 Notice:** {font_report.non_compliant_fields_count} field(s) have measured font heights below the statutory minimum.")
                        else:
                            st.success("🟢 **Rule 7 Verified:** All measured declarations meet or exceed statutory minimum font heights!")
                    else:
                        fm2.metric("Rule 7 Status", "⚪ Uncalibrated")
                        fm3.metric("Calibration Ratio", "Not Calibrated")
                        st.info("ℹ️ Coin reference not calibrated. Font heights shown in raw pixels; calibrate with ₹5 coin for mm measurement and Rule 7 verification.")

                    parsed_table = []
                    for fname, fval in parsed_res.fields.items():
                        m = font_report.measurements.get(fname)
                        if m:
                            font_height_disp = m.formatted_display
                            rule7_badge = m.compliance_badge
                        else:
                            font_height_disp = f"{fval.height_px:.1f} px"
                            rule7_badge = "⚪ Uncalibrated"

                        parsed_table.append({
                            "Field": fname.replace('_', ' ').title(),
                            "Extracted Value": f"{fval.extracted_value} {fval.unit if fval.unit else ''}".strip(),
                            "Font Height (mm)": font_height_disp,
                            "Rule 7 Compliance": rule7_badge,
                            "Confidence": f"{fval.confidence:.2%}",
                            "Matched Text": fval.raw_text,
                        })
                    if parsed_table:
                        st.dataframe(parsed_table, use_container_width=True)

        # Visual preview hierarchy: OCR annotated > Text Region annotated > Coin annotated > Raw
        if ocr_res is not None and ocr_res.annotated_image is not None:
            st.image(
                cv2.cvtColor(ocr_res.annotated_image, cv2.COLOR_BGR2RGB),
                caption=f"{side_key.title()} OCR Extracted Overlay ({ocr_res.total_lines} lines detected via {ocr_res.engine_used.upper()})",
                use_container_width=True,
            )
        elif text_res is not None and text_res.annotated_image is not None:
            st.image(
                cv2.cvtColor(text_res.annotated_image, cv2.COLOR_BGR2RGB),
                caption=f"{side_key.title()} Detected Text Regions ({text_res.total_regions} cyan boxes)",
                use_container_width=True,
            )
            with st.expander(f"📋 View Detected Text Regions Details ({text_res.total_regions})"):
                calib_res = st.session_state.get(f"{side_key}_calibration")
                region_data = []
                for idx, reg in enumerate(text_res.regions):
                    item = {
                        "Region #": idx + 1,
                        "Bounding Box": str(reg.bbox),
                        "Width (px)": f"{reg.width_px:.1f}",
                        "Height (px)": f"{reg.height_px:.1f}",
                        "Confidence": f"{reg.confidence:.2f}",
                    }
                    if calib_res and calib_res.is_calibrated:
                        item["Height (mm)"] = f"{(reg.height_px / calib_res.pixels_per_mm):.2f}"
                    region_data.append(item)
                st.dataframe(region_data, use_container_width=True)
        elif coin_res is not None and coin_res.annotated_image is not None:
            st.image(
                cv2.cvtColor(coin_res.annotated_image, cv2.COLOR_BGR2RGB),
                caption=f"{side_key.title()} Coin Detected: D={coin_res.pixel_diameter:.1f}px",
                use_container_width=True,
            )
        else:
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

# ==============================================================================
# 📦 Consolidated Product Master Record (Task 12)
# ==============================================================================
front_parsed_data = st.session_state.get("front_parsed_fields")
back_parsed_data = st.session_state.get("back_parsed_fields")

if front_parsed_data is not None or back_parsed_data is not None or st.session_state.get("consolidated_record") is not None:
    active_scan = st.session_state.get("current_scan")
    active_scan_id = active_scan.get("scan_id") if active_scan else st.session_state.get("active_scan_id")
    front_fonts = st.session_state.get("front_font_report")
    back_fonts = st.session_state.get("back_font_report")

    if front_parsed_data is not None or back_parsed_data is not None:
        consolidated_rec = consolidate_scan_records(
            front_parsed=front_parsed_data,
            back_parsed=back_parsed_data,
            front_fonts=front_fonts,
            back_fonts=back_fonts,
            scan_id=active_scan_id,
        )
        st.session_state["consolidated_record"] = consolidated_rec
    else:
        consolidated_rec = st.session_state.get("consolidated_record")

    if consolidated_rec is not None:
        st.markdown("---")
        with st.expander("📦 Consolidated Product Master Record", expanded=True):
            total_mandatory = 9
            present_count = 9 - len(consolidated_rec.missing_declarations)
            completeness_str = (
                f"{consolidated_rec.completeness_pct:.0f}%"
                if consolidated_rec.completeness_pct in (0.0, 100.0)
                else f"{consolidated_rec.completeness_pct:.1f}%"
            )
            badge_text = f"Mandatory Completeness: {completeness_str} ({present_count}/{total_mandatory} fields)"

            if consolidated_rec.completeness_pct == 100.0:
                st.success(f"✅ {badge_text}")
            else:
                st.warning(f"⚠️ {badge_text}")

            # Key summary metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Brand / Commodity", consolidated_rec.brand_name or "Packaged Commodity")
            m2.metric("Completeness", f"{consolidated_rec.completeness_pct:.1f}%")
            m3.metric("Mandatory Fields", f"{present_count}/{total_mandatory} Present")
            uuid_display = (
                f"{consolidated_rec.product_id[:8]}..."
                if len(consolidated_rec.product_id) > 10
                else consolidated_rec.product_id
            )
            m4.metric("Product UUID", uuid_display, help=consolidated_rec.product_id)

            # Consolidated Declarations Table
            DECLARATION_TITLES = {
                "brand_name": "Brand / Common Commodity Name",
                "mrp": "Maximum Retail Price (MRP)",
                "net_quantity": "Net Quantity",
                "manufacturer_details": "Manufacturer / Packer Details",
                "mfg_date": "Date of Manufacture / Packaging",
                "expiry_date": "Expiry / Best Before Date",
                "batch_number": "Batch / Lot Number",
                "consumer_care": "Consumer Care Information",
                "country_of_origin": "Country of Origin",
                "unit_sale_price": "Unit Sale Price (USP)",
            }

            table_rows = []
            for d_key, d_title in DECLARATION_TITLES.items():
                val = getattr(consolidated_rec, d_key, "")
                is_present = bool(str(val).strip())

                # Identify source side
                in_f = d_key in (consolidated_rec.front_fields or {})
                in_b = d_key in (consolidated_rec.back_fields or {})
                if in_f and in_b:
                    source_side = "Front & Back"
                elif in_f:
                    source_side = "Front Label"
                elif in_b:
                    source_side = "Back Label"
                else:
                    source_side = "—"

                # Font measurement & Rule 7 badge
                font_m = (consolidated_rec.font_measurements or {}).get(d_key)
                if font_m:
                    if hasattr(font_m, "formatted_display"):
                        font_display = font_m.formatted_display
                        rule7_badge = font_m.compliance_badge
                    elif isinstance(font_m, dict):
                        fh = font_m.get("font_height_mm")
                        font_display = f"{fh:.2f} mm" if fh is not None else "Uncalibrated"
                        rule7_badge = "🟢 PASS" if font_m.get("is_rule7_compliant") else "🔴 DEFICIT"
                    else:
                        font_display = str(font_m)
                        rule7_badge = "⚪ Uncalibrated"
                else:
                    font_display = "—"
                    rule7_badge = "⚪ Not Measured"

                status_icon = "🟢 Declared" if is_present else "🔴 Missing"
                table_rows.append({
                    "Declaration": d_title,
                    "Consolidated Value": val if is_present else "Not Declared",
                    "Source Panel": source_side,
                    "Font Height (mm)": font_display,
                    "Rule 7 Status": rule7_badge,
                    "Status": status_icon,
                })

            st.dataframe(table_rows, use_container_width=True)

            # Missing Declarations Alert
            if consolidated_rec.missing_declarations:
                missing_labels = [
                    DECLARATION_TITLES.get(d, d.replace("_", " ").title())
                    for d in consolidated_rec.missing_declarations
                ]
                st.warning(f"⚠️ **Missing Mandatory Declarations ({len(consolidated_rec.missing_declarations)}/9):** {', '.join(missing_labels)}")
            else:
                st.success("🟢 **All 9 Statutory Declarations Detected:** Packaging satisfies mandatory disclosure requirements.")

            # Resolved Field Conflicts Expander
            if consolidated_rec.resolved_conflicts:
                with st.expander(f"⚖️ Resolved Panel Conflicts ({len(consolidated_rec.resolved_conflicts)})", expanded=False):
                    conflict_rows = []
                    for c in consolidated_rec.resolved_conflicts:
                        conflict_rows.append({
                            "Field": DECLARATION_TITLES.get(c.get("field_name"), c.get("field_name", "").title()),
                            "Front Panel": f"{c.get('front_value')} (conf: {c.get('front_confidence', 0):.0%})",
                            "Back Panel": f"{c.get('back_value')} (conf: {c.get('back_confidence', 0):.0%})",
                            "Selected": f"{c.get('selected_side', '').title()} Panel: {c.get('selected_value')}",
                            "Reason": c.get("reason"),
                        })
                    st.dataframe(conflict_rows, use_container_width=True)

            st.caption(f"💾 **Product Master Record Synced with Database:** Table `products` | Record ID: `{consolidated_rec.product_id}`")

            # 📄 Inspection Report Generation & Export (Task 13)
            st.markdown("---")
            st.markdown("#### 📄 Statutory Metrology Inspection Report (Task 13)")
            st.write(
                "Generate an official, genuinely editable Word document (`.docx`) and PDF inspection report "
                "incorporating Department of Consumer Affairs Legal Metrology headers, metadata, "
                "₹5 coin calibration ratio, statutory declarations table, and packaging digital evidence."
            )

            rep_btn_col, rep_dl_word, rep_dl_pdf = st.columns([1.5, 1.4, 1.4])
            with rep_btn_col:
                gen_report_btn = st.button(
                    "📄 Generate Inspection Report",
                    key="btn_generate_inspection_report",
                    type="primary",
                    use_container_width=True,
                )

            if gen_report_btn:
                with st.spinner("Generating official Legal Metrology inspection report (.docx & .pdf)..."):
                    try:
                        scan_id_for_rep = (
                            active_scan_id
                            or (active_scan.get("scan_id") if active_scan else None)
                            or getattr(consolidated_rec, "product_id", None)
                            or str(uuid.uuid4())
                        )
                        f_img_obj = st.session_state.get("front_image")
                        b_img_obj = st.session_state.get("back_image")
                        f_path = getattr(f_img_obj, "cache_path", None) if f_img_obj else None
                        b_path = getattr(b_img_obj, "cache_path", None) if b_img_obj else None

                        rep_res = generate_inspection_report(
                            consolidated_record=consolidated_rec,
                            front_image=f_path,
                            back_image=b_path,
                            font_report=st.session_state.get("front_font_report") or st.session_state.get("back_font_report"),
                            calibration_result=st.session_state.get("front_calibration") or st.session_state.get("back_calibration"),
                            output_dir="reports",
                            scan_id=scan_id_for_rep,
                        )
                        st.session_state["report_result"] = rep_res
                        st.success(f"✅ Inspection report generated successfully in {rep_res.generation_time_sec:.2f}s!")

                        # Task 14: Automatically trigger upload_inspection_report upon report generation
                        upload_res = upload_inspection_report(
                            scan_id=scan_id_for_rep,
                            docx_path=rep_res.docx_path,
                            pdf_path=rep_res.pdf_path,
                        )
                        st.session_state["report_upload_result"] = upload_res
                        storage_tag = upload_res.get("upload_status", "Supabase Storage")
                        st.success(f"☁️ Report uploaded to cloud storage ({storage_tag}): {upload_res.report_url}")
                    except Exception as exc:
                        st.error(f"❌ Failed to generate inspection report: {exc}")

            current_report = st.session_state.get("report_result")
            if current_report is not None:
                docx_p = current_report.docx_path
                pdf_p = current_report.pdf_path

                if docx_p and os.path.exists(docx_p):
                    with open(docx_p, "rb") as f_docx:
                        docx_bytes = f_docx.read()
                    with rep_dl_word:
                        st.download_button(
                            label="📥 Download Editable Word (.docx)",
                            data=docx_bytes,
                            file_name=os.path.basename(docx_p),
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key="download_report_docx",
                            use_container_width=True,
                        )

                if pdf_p and os.path.exists(pdf_p):
                    with open(pdf_p, "rb") as f_pdf:
                        pdf_bytes = f_pdf.read()
                    with rep_dl_pdf:
                        st.download_button(
                            label="📥 Download Inspection PDF (.pdf)",
                            data=pdf_bytes,
                            file_name=os.path.basename(pdf_p),
                            mime="application/pdf",
                            key="download_report_pdf",
                            use_container_width=True,
                        )
                else:
                    with rep_dl_pdf:
                        st.info("ℹ️ PDF Export unavailable (conversion tool not installed).")

            # Task 14: Display Cloud Storage Link Badge and Retrievable Links
            current_upload = st.session_state.get("report_upload_result")
            if current_upload is not None:
                st.markdown("---")
                st.markdown("##### ☁️ Cloud Storage Report Archive (Supabase)")
                badge_bg = "#059669" if not current_upload.get("is_offline") else "#4f46e5"
                badge_label = "☁️ Supabase Cloud Storage" if not current_upload.get("is_offline") else "📦 Offline Mock Storage"
                docx_link = current_upload.get("report_url") or current_upload.get("docx_url")
                pdf_link = current_upload.get("pdf_url")
                bucket_name = current_upload.get("storage_bucket", "inspection-reports")

                st.markdown(
                    f"""
                    <div style="background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 14px 18px; margin-top: 8px; margin-bottom: 12px;">
                        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
                            <span style="background-color: {badge_bg}; color: white; padding: 4px 12px; border-radius: 16px; font-size: 0.85em; font-weight: 600; letter-spacing: 0.3px;">
                                {badge_label}
                            </span>
                            <span style="font-size: 0.82em; color: #64748b; font-family: monospace;">
                                Bucket: {bucket_name}
                            </span>
                        </div>
                        <div style="font-size: 0.92em; color: #1e293b; line-height: 1.6;">
                            <b>Retrievable Inspection Report Links:</b>
                            <ul style="margin: 6px 0 0 0; padding-left: 20px;">
                                <li><b>Word (.docx):</b> <a href="{docx_link}" target="_blank" style="color: #2563eb; word-break: break-all;">{docx_link}</a></li>
                                {f'<li><b>PDF (.pdf):</b> <a href="{pdf_link}" target="_blank" style="color: #2563eb; word-break: break-all;">{pdf_link}</a></li>' if pdf_link else ''}
                            </ul>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                link_col1, link_col2 = st.columns(2)
                with link_col1:
                    st.info(f"📄 **Cloud Word Report:** [{docx_link}]({docx_link})")
                with link_col2:
                    if pdf_link:
                        st.info(f"📑 **Cloud PDF Report:** [{pdf_link}]({pdf_link})")
                    else:
                        st.caption("ℹ️ PDF cloud link not available (PDF export was skipped).")

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

            # Re-persist any already extracted fields under the official scan_id
            for s_key in ("front", "back"):
                parsed = st.session_state.get(f"{s_key}_parsed_fields")
                report = st.session_state.get(f"{s_key}_font_report")
                if parsed:
                    p_res = save_scan_extraction_results(
                        scan_id=scan_result.scan_id,
                        parsed_fields_result=parsed,
                        font_measurement_report=report,
                        side=s_key,
                    )
                    st.session_state[f"{s_key}_persistence"] = p_res

            # Consolidate and link to the official scan_id (Task 12)
            f_p = st.session_state.get("front_parsed_fields")
            b_p = st.session_state.get("back_parsed_fields")
            if f_p or b_p:
                cons_rec = consolidate_scan_records(
                    front_parsed=f_p,
                    back_parsed=b_p,
                    front_fonts=st.session_state.get("front_font_report"),
                    back_fonts=st.session_state.get("back_font_report"),
                    scan_id=scan_result.scan_id,
                )
                st.session_state["consolidated_record"] = cons_rec

            st.balloons()
            st.success("✅ Inspection scan initialized! Images uploaded and metadata logged to database.")
        except Exception as exc:
            st.error(f"❌ Failed to process scan upload: {exc}")

# Confirmation Card for Active / Uploaded Scan
if st.session_state.get("current_scan") is not None:
    current_scan = st.session_state["current_scan"]
    st.markdown("---")
    st.markdown("### 📋 Active Inspection Scan Confirmation")

    # Aggregate persistence statistics across front and back sides
    front_p = st.session_state.get("front_persistence")
    back_p = st.session_state.get("back_persistence")
    total_saved_fields = (front_p.saved_count if front_p else 0) + (back_p.saved_count if back_p else 0)

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
        display_status = "PROCESSED" if total_saved_fields > 0 else current_scan.get("status", "uploaded").upper()
        st.metric("Scan Status", display_status)

    if total_saved_fields > 0:
        st.success(f"💾 Saved {total_saved_fields} fields to Supabase")

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
        "Completed: Task 5 through Task 13 (Report Generation). "
        "Next step: Task 14 (Report Upload to Supabase Storage)."
    )

