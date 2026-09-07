"""Digital Metrology Inspector - Streamlit Application Skeleton.

Prototype compliance verification system for Legal Metrology (Packaged Commodities) Rules, 2011.
"""

import streamlit as st

st.set_page_config(
    page_title="Digital Metrology Inspector",
    page_icon="🔍",
    layout="wide",
)

# Sidebar Instructions
with st.sidebar:
    st.title("📋 Guidelines & Scope")
    st.markdown(
        """
        ### How to Inspect a Product
        1. **Reference Coin**: Place a standard **₹5 coin** (21.9 mm diameter) flat on the same plane next to the product label.
        2. **Capture Front & Back**: Photograph both front and back packaging labels in clear, non-glare lighting.
        3. **Upload**: Upload both images using the panel on the right.
        
        ---
        ### Current Prototype Scope
        - **Language**: English labels
        - **Packaging**: Flat/matte surfaces
        - **Reference**: Indian ₹5 coin (21.9 mm)
        - **Standard**: Legal Metrology (Packaged Commodities) Rules, 2011
        """
    )
    st.info("System Ready for Inspection Workflow.")

# Header
st.title("🔍 Digital Metrology Inspector")
st.caption("Automated Legal Metrology Compliance & Real-World Font Measurement (SIH26034)")
st.markdown("---")

# Main Image Upload Interface
col1, col2 = st.columns(2)

with col1:
    st.subheader("📷 Front Label")
    st.write("Ensure front label and reference ₹5 coin are clearly visible.")
    front_image = st.file_uploader(
        "Upload Front Image",
        type=["jpg", "jpeg", "png"],
        key="front_image_uploader",
    )
    if front_image:
        st.image(front_image, caption="Front Label Preview", use_container_width=True)
    else:
        st.info("Awaiting front label image upload...")

with col2:
    st.subheader("📷 Back Label")
    st.write("Ensure back declarations and reference ₹5 coin are clearly visible.")
    back_image = st.file_uploader(
        "Upload Back Image",
        type=["jpg", "jpeg", "png"],
        key="back_image_uploader",
    )
    if back_image:
        st.image(back_image, caption="Back Label Preview", use_container_width=True)
    else:
        st.info("Awaiting back label image upload...")

st.markdown("---")

# Processing Action Placeholder
st.subheader("⚙️ Inspection Workflow")
run_inspection = st.button("Start Metrology Compliance Inspection", type="primary", disabled=(front_image is None and back_image is None))

if run_inspection:
    st.warning("Inspection pipeline will be connected in subsequent phases (coin detection, calibration, OCR, rule evaluation).")
else:
    st.info("Upload product label images to begin inspection.")
