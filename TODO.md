# Project TODO List — Digital Metrology Inspector

This file serves as the dedicated progress tracker for all tasks across Phase 1, Phase 2, and Phase 3.

---

## Phase 1 — Core Extraction & Measurement

- [x] **Task 1: Project Scaffolding**
  - *Details:* Repository structure, Python `venv` & `requirements.txt`, Streamlit skeleton, comprehensive `.gitignore`.
  - *Completed:* 2026-09-07

- [x] **Task 2: Supabase Project Setup & Database Schema**
  - *Details:* `schema.sql` (products, scans, extracted_fields, rules, compliance_results DDL), `src/db.py` client integration & offline mock mode.
  - *Completed:* 2026-09-07

- [x] **Task 3: Image Input Handling**
  - *Details:* Streamlit UI for front + back image upload & camera capture, validation module, metadata extraction, local caching, readiness evaluator.
  - *Completed:* 2026-09-07

- [x] **Task 4: Storage Upload & Scan Logging**
  - *Details:* Upload raw images to Supabase Storage bucket (`product-images`), log scan metadata to `scans` table.
  - *Completed:* 2026-09-07

- [x] **Task 5: Coin Detection Module**
  - *Details:* OpenCV Hough Circle Transform — detect ₹5 coin in label frame, calculate pixel diameter.

- [ ] **Task 6: Calibration Module**
  - *Details:* Compute pixels-per-mm ratio using 21.9mm fixed coin diameter.

- [ ] **Task 7: Text Region Detection**
  - *Details:* Detect text regions on front and back label images separately.

- [ ] **Task 8: OCR Extraction**
  - *Details:* PaddleOCR text extraction on detected label regions.

- [ ] **Task 9: Field Structuring & Parsing**
  - *Details:* Regex/keyword proximity matching into structured fields (MRP, Net Qty, Manufacturer, Mfg Date, Batch No, Consumer Care, Country of Origin).

- [ ] **Task 10: Font-Height Measurement**
  - *Details:* Measure bounding box heights for key fields in mm using calibration ratio.

- [ ] **Task 11: Store Extraction Results**
  - *Details:* Persist structured fields to Supabase `extracted_fields` table.

- [ ] **Task 12: Data Consolidation**
  - *Details:* Merge front + back label records into unified product record.

- [ ] **Task 13: Report Generation**
  - *Details:* Generate editable Word document (`python-docx`) + PDF export.

- [ ] **Task 14: Report Upload**
  - *Details:* Upload report to Supabase Storage (`inspection-reports`) & save retrievable link.

- [ ] **Task 15: Manual Correction UI**
  - *Details:* Streamlit interface for inspector field edits & correction logging.

- [ ] **Task 16: Phase 1 Test Pass**
  - *Details:* Validate against 5-10 real self-photographed sample products.

---

## Phase 2 — Compliance Rule Engine

- [ ] **Task 17: Digitize Legal Metrology Rules 2011**
  - *Details:* Store Rule 6, Rule 7, Rule 18 in `rules` table.

- [ ] **Task 18: Rule Engine Core**
  - *Details:* Deterministic checker comparing fields & font sizes against rule config.

- [ ] **Task 19: Violation Classification**
  - *Details:* Categorize rule reference, severity, and plain-language explanation.

- [ ] **Task 20: Full Compliance Report**
  - *Details:* Word/PDF report showing pass/fail per rule & overall verdict.

- [ ] **Task 21: Digital Evidence Layer**
  - *Details:* Timestamp & geo-tag embedding in report + store in `compliance_results`.

- [ ] **Task 22: Phase 2 Test Pass**
  - *Details:* Validate compliant & non-compliant sample products.

---

## Phase 3 — Intelligence & Robustness Layer (Future)

- [ ] **Task 23:** Confidence scoring / low-confidence flagging
- [ ] **Task 24:** Feedback loop using logged corrections
- [ ] **Task 25:** Regional language support (PaddleOCR multilingual)
- [ ] **Task 26:** Shiny/reflective label handling (CLAHE / glare reduction)
- [ ] **Task 27:** Curved & multi-panel label support
- [ ] **Task 28:** Risk scoring module (scikit-learn interpretable models)
- [ ] **Task 29:** Multi-stakeholder dashboards (regulator, business, consumer)
