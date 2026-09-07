# Build Instructions for Antigravity

Read `PROJECT.md` first for full context on what we're building and why,
before executing any task below. These instructions govern *how* you work,
not *what* you're building.

## Core Working Principles

1. **One task at a time, verified before moving on.** Never start the next
   task in the list until the current one has been explicitly verified
   (see Verification Protocol below) and I have confirmed it's correct.
   Do not batch multiple unrelated tasks into one change.

2. **Use the editable task list below as the single source of truth.**
   Before starting work in any session, re-read the current state of the
   task list. Mark tasks as `[ ] pending`, `[~] in progress`, or `[x] done`
   directly in this file as you go, so progress persists across sessions
   without needing to be re-explained.

3. **Use subagents per task, with the right model for the job — not the
   most powerful model by default.** Token/credit efficiency is a hard
   requirement, not a nice-to-have. Model selection guide:
   - **Simple, mechanical tasks** (scaffolding, boilerplate config,
     installing dependencies, writing straightforward CRUD-style Supabase
     schema, simple file I/O): use the **fastest/lightest available model**
     in Antigravity's model picker (e.g., Gemini Flash tier). Do not use a
     heavier reasoning model for these.
   - **Genuinely hard logic** (coin detection + calibration math, OCR
     field-parsing/regex design, rule-engine logic, debugging a subtle
     bug): use the **stronger reasoning model** (e.g., Gemini Pro tier),
     but only for that specific subagent's task — return to the lighter
     model for the next mechanical task afterward.
   - **Never use the heaviest/most expensive model for exploratory or
     trial-and-error work.** If a task requires iteration, do the first
     exploratory pass with the lightest model, and only escalate to a
     stronger model if that fails.
   - When in doubt about which tier a task needs, default to the lighter
     model first and escalate only if it visibly struggles.

4. **Minimize redundant context/re-reads.** Do not re-read the entire
   codebase or entire PROJECT.md/INSTRUCTIONS.md on every single subagent
   call. Pass only the specific file(s) or function(s) relevant to the
   current task as context. Summarize prior decisions in short notes
   rather than re-including full prior conversation history.

5. **No speculative building.** Only build what the current task
   explicitly requires. Do not pre-emptively add Phase 2/Phase 3 features
   while working on a Phase 1 task, even if it seems convenient. This
   keeps changes reviewable and keeps token usage predictable.

6. **All tools/models used in the actual application must be free and
   open-source, per PROJECT.md.** Do not introduce a paid API (OCR,
   vision, or otherwise) into the runtime pipeline under any circumstance,
   even if it would be more accurate or faster to implement. If you
   believe a paid tool is genuinely necessary, stop and flag it for
   discussion instead of implementing it.

## Verification Protocol (required after every task)

After completing a task, before marking it done:

1. **Run it.** If it's a script/module, execute it against at least one
   real sample input (not just a hypothetical trace-through).
2. **Show the actual output** (extracted text, calculated values, file
   generated, DB row inserted, etc.) — not just "it should work now."
3. **Check it against the task's specific success condition** (defined per
   task in the task list below).
4. **Explicitly state what was verified and how**, in a short note, before
   proceeding — e.g., "Verified: coin detected correctly in 4/4 test
   images, pixel diameter values look consistent with expected coin size
   ratio across images taken at different distances."
5. If verification fails or is ambiguous, stop and report the failure
   clearly rather than proceeding to the next task or silently retrying
   with a different approach.

## Editable Task List

### Phase 1 — Core Extraction & Measurement

- [x] 1. Project scaffolding (repo structure, venv/dependencies, Streamlit skeleton)
- [x] 2. Supabase project setup — schema for `products`, `scans`, `extracted_fields`; storage bucket created
- [x] 3. Image input handling — Streamlit UI accepts front + back image capture/upload
- [x] 4. Upload raw images to Supabase Storage; log scan metadata to `scans` table
- [x] 5. Coin detection module (OpenCV Hough Circle Transform) — detect ₹5 coin, get pixel diameter
- [x] 6. Calibration module — compute pixels-per-mm ratio using 21.9mm fixed coin diameter
- [x] 7. Text region detection on label images (front/back separately)
- [x] 8. OCR extraction via PaddleOCR on detected text regions
- [x] 9. Field structuring/parsing — regex/keyword matching into structured fields (MRP, Net Qty, Manufacturer, Mfg/Expiry Date, Batch No., Consumer Care, Country of Origin)
- [x] 10. Font-height measurement for key fields, converted to mm via calibration ratio
- [x] 11. Store structured extraction results in Supabase (`extracted_fields`, linked to scan ID)
- [x] 12. Data consolidation — merge front + back records into one product record
- [x] 13. Report generation — editable Word doc (python-docx) + PDF export, listing all fields + font measurements per side
- [x] 14. Upload generated report to Supabase Storage; save retrievable link
- [x] 15. Manual correction UI in Streamlit — inspector reviews/edits fields before finalizing; corrections logged to Supabase
- [ ] 16. Phase 1 test pass — validate against 5-10 real self-photographed sample products; document accuracy results

### Phase 2 — Compliance Rule Engine

- [ ] 17. Digitize Legal Metrology Rules 2011 (Rule 6, Rule 7, Rule 18, etc.) into a structured config stored in Supabase (`rules` table)
- [ ] 18. Rule engine core — deterministic checker comparing extracted fields + measured font sizes against rule config
- [ ] 19. Violation classification — categorize by rule reference, severity, plain-language explanation
- [ ] 20. Extend report generator into full compliance report (Word/PDF): extracted data + font measurements + pass/fail per rule + overall verdict
- [ ] 21. Digital evidence layer — timestamp (+ optional geo-tag) embedded in report; results stored in Supabase (`compliance_results`)
- [ ] 22. Phase 2 test pass — validate against compliant + deliberately non-compliant mock samples; document results

### Phase 3 — Intelligence & Robustness Layer (do not start until Phase 1 & 2 fully verified and confirmed)

- [ ] 23. Confidence scoring / low-confidence review flagging
- [ ] 24. Feedback loop using Supabase-logged corrections to improve field-parsing rules
- [ ] 25. Regional language support (extend PaddleOCR multilingual models)
- [ ] 26. Shiny/reflective label handling (OpenCV glare reduction / CLAHE preprocessing)
- [ ] 27. Broader product/label-format support (curved labels, multi-panel packaging)
- [ ] 28. Risk scoring module (scikit-learn, interpretable models only)
- [ ] 29. Dashboard/portal layer — regulator dashboard, business pre-compliance portal, consumer verification portal

## Token/Credit Efficiency Rules (explicit)

- Do not regenerate entire files when a small edit (e.g., `str_replace`
  equivalent) will do.
- Do not ask the model to "explain the whole codebase" or produce large
  summaries unless specifically requested — keep exchanges scoped to the
  active task.
- Batch small, related sub-steps within a single task into one subagent
  call rather than spawning a new subagent per sub-step (e.g., steps like
  "write the function" + "write its test" for the same small module can
  be one call).
- Cache/reuse prior verified outputs (e.g., a working calibration ratio
  formula) instead of re-deriving them from scratch in later tasks.
- If a task fails twice with the lighter model, escalate once to the
  stronger model — do not loop indefinitely on the light model, as
  repeated failed attempts waste more tokens than one correct escalation.

## Stop Conditions (always pause and ask before proceeding)

- Before introducing any new external dependency/library not listed in
  PROJECT.md's tech stack.
- Before making any change that would require a paid API key or paid
  tier of any service.
- Before starting Phase 2 tasks while any Phase 1 task remains unverified.
- Before starting Phase 3 tasks under any circumstance until explicitly
  told to begin Phase 3.
- If OCR/field-extraction accuracy on the Phase 1 test pass (task 16) is
  clearly poor (e.g., major fields consistently missed) — stop and report
  rather than proceeding to build the rule engine on top of unreliable data.
