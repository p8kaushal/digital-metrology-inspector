# Project: Digital Metrology Inspector (SIH26034)

## 1. Problem Statement

Ministry: Department of Consumer Affairs, Government of India
PS ID: SIH26034 (Legal Metrology / Packaged Commodities compliance)

Every packaged commodity sold in India must legally display specific
information under the **Legal Metrology (Packaged Commodities) Rules, 2011**:
- MRP (Maximum Retail Price)
- Net Quantity
- Manufacturer/Packer/Importer name and address
- Month & Year of Manufacture/Import
- Consumer Care details
- Country of Origin (where applicable)
- Unit Sale Price (price per standard unit, e.g. per 100g/100ml)
- Minimum font size/area for key declarations (Rule 7)

Today, verifying this is done manually by inspectors — slow, inconsistent,
and impossible to scale across millions of products (physical retail and
e-commerce).

## 2. Our Solution: Digital Metrology Inspector

A smart compliance system that lets an inspector (or eventually a business
or consumer) photograph a product's front and back label alongside a ₹5
coin (used as a fixed-size reference object), and the system:

1. Extracts all label text automatically (OCR)
2. Structures it into defined fields (MRP, Net Qty, Mfg Date, etc.)
3. Measures the **real-world printed font size in millimeters**, using the
   ₹5 coin's known fixed diameter (21.9mm) as a pixel-to-mm calibration
   reference — solving the hardest technical requirement in the PS (Rule 7
   font-size/area verification), which most competing solutions cannot
   solve since barcodes (the "obvious" reference) legally vary in printed
   size by 80–200% under GS1 standards and cannot be trusted as a fixed
   reference.
4. Generates an editable Word document + PDF report listing every
   extracted field and its measured font size (Phase 1)
5. Compares extracted data against the digitized Legal Metrology Rules,
   2011 and produces a full compliance verdict report, flagging exact
   rule violations in plain language (Phase 2)
6. Adds intelligence, robustness, and multi-stakeholder portals over time
   (Phase 3): regional language support, glare/shiny-label handling, risk
   scoring for repeat offenders, a business pre-compliance self-check
   portal, and a consumer verification portal.

## 3. Current Prototype Scope (what we are building right now)

**In scope for MVP (Phase 1 + Phase 2):**
- Simple, matte/non-shiny, English-labeled packaged products only
- Front + back image capture, each with a ₹5 coin visible in frame
- Accurate field extraction + font-size measurement
- Editable Word/PDF report generation
- Rule-engine based compliance verdict against Legal Metrology Rules 2011

**Explicitly out of scope for now (Phase 3, future work):**
- Regional language labels
- Shiny/reflective/glare-heavy packaging
- Curved/irregular label surfaces
- Business and consumer-facing portals
- Risk scoring / ML-based prioritization
- Any dashboard UI beyond the simple inspector-facing Streamlit tool

## 4. Tech Stack (all free / open-source — no paid APIs in the pipeline)

| Layer | Tool | Why |
|---|---|---|
| UI | Streamlit | Fast to build, sufficient for a judge-facing prototype demo, no separate frontend/backend split needed |
| Computer Vision (coin detection, calibration) | OpenCV | Standard, free, well-documented for circle detection (Hough Circle Transform) and geometric calibration |
| OCR | PaddleOCR (PP-OCRv4) | Free, fully open-source, runs locally (zero API cost), strong on real-world photo text (better than Tesseract for this use case), built-in multilingual support for future Phase 3 language expansion |
| Field parsing | Python (regex + keyword-proximity matching) | Deterministic, explainable, no training data required — appropriate for MVP; upgradeable to a layout-aware model later if needed |
| Rule Engine | Python, rules defined in a structured config (stored in Supabase) | Deterministic and auditable — compliance decisions must be traceable to an exact rule, not a black-box prediction |
| Report Generation | python-docx (Word) → converted to PDF | Produces genuinely editable Word output as required, with PDF export for sharing |
| Database | Supabase (Postgres, free tier) | Stores structured extracted fields, scan metadata, compliance results, rule definitions, and correction logs |
| File Storage | Supabase Storage (free tier) | Stores uploaded images and generated report files |
| Risk Scoring (Phase 3 only) | scikit-learn | Free, open-source, interpretable models (logistic regression / Random Forest) — explainability matters more than raw accuracy in a compliance context |

**No paid inference APIs (OpenAI, Google Vision, AWS Textract, etc.) are used
anywhere in the core pipeline.** Google/Gemini model usage (via Antigravity)
is reserved strictly for agentic coding assistance during development —
never called at runtime by the deployed prototype itself.

## 5. Reference Calibration Method (key differentiator)

- Fixed reference object: **Indian ₹5 coin**, real diameter = 21.9mm
  (do not use a barcode — GS1 permits 80–200% scaling of printed barcode
  size, making it an unreliable measurement reference)
- Detect the coin in-frame using Hough Circle Transform (OpenCV)
- Compute `pixels_per_mm = coin_pixel_diameter / 21.9`
- Apply this ratio to measured text bounding-box heights to get real-world
  font height in mm for comparison against Rule 7's minimum size
  requirements

## 6. Data Flow Summary

```
User captures front + back image (each with ₹5 coin in frame)
        ↓
Upload to Supabase Storage, log scan in Supabase DB
        ↓
Coin detection (OpenCV) → pixel-to-mm calibration ratio
        ↓
Text region detection + OCR (PaddleOCR)
        ↓
Field structuring (regex/keyword matching) → structured record
        ↓
Font height measurement (calibrated to mm)
        ↓
Store structured fields in Supabase
        ↓
[Phase 1 stop: generate Word/PDF report of extracted data + measurements]
        ↓
[Phase 2: Rule Engine compares structured data against Legal Metrology
 Rules 2011 config in Supabase] → compliance verdict
        ↓
Generate final compliance report (Word/PDF) with plain-language violations
        ↓
Store compliance result in Supabase, upload report to Storage
```

## 7. Success Criteria for This Prototype

- Correctly extracts all standard mandatory fields from 5-10 real,
  self-photographed sample products (matte, English-labeled)
- Font-size measurement is within a reasonable margin of a manual
  ruler-measurement on the same products (validate this manually)
- Generates a clean, genuinely editable Word document (not an image-based
  PDF pretending to be editable)
- Rule engine correctly flags at least one deliberately-introduced
  violation (e.g., a mocked-up product with an undersized MRP declaration
  or missing net quantity)
- All data persists correctly in Supabase and can be retrieved after a
  restart (proves the storage layer isn't just in-memory/session-based)
