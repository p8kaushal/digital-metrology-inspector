"""Verification test script for Task 2 (Digital Metrology Inspector).

Verifies:
1. schema.sql syntax and structural completeness:
   - DDL for products, scans, extracted_fields, rules, compliance_results
   - Foreign key constraints
   - Indexes and timestamps triggers
   - Storage buckets configuration
2. src/db.py module functionality:
   - Clean import and status check
   - CRUD helper operations (products, scans, extracted_fields, rules, compliance_results)
   - File upload / storage mock handling
   - Resilient offline fallback behavior
"""

import os
import re
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_schema_sql_syntax_and_structure():
    """Verify schema.sql file exists and is syntactically structured SQL."""
    schema_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "schema.sql"))
    assert os.path.isfile(schema_path), f"schema.sql not found at {schema_path}"

    with open(schema_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert len(content.strip()) > 0, "schema.sql is empty"

    # Check required tables
    required_tables = [
        "products",
        "scans",
        "extracted_fields",
        "rules",
        "compliance_results",
    ]
    for table in required_tables:
        pattern = rf"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?{table}\s*\("
        match = re.search(pattern, content, re.IGNORECASE)
        assert match is not None, f"Table '{table}' DDL definition missing in schema.sql"

    # Check foreign keys
    assert "REFERENCES products" in content, "Foreign key reference to products table missing"
    assert "REFERENCES scans" in content, "Foreign key reference to scans table missing"
    assert "REFERENCES rules" in content, "Foreign key reference to rules table missing"

    # Check indexes
    assert "CREATE INDEX" in content, "No indexes defined in schema.sql"
    for table in required_tables:
        assert f"idx_{table}" in content, f"Expected index for {table} not found in schema.sql"

    # Check timestamps and triggers
    assert "update_updated_at_column" in content, "updated_at trigger function missing"
    assert "CREATE TRIGGER" in content, "Trigger definitions missing"

    # Check storage buckets
    assert "product-images" in content, "product-images bucket definition missing"
    assert "inspection-reports" in content, "inspection-reports bucket definition missing"

    # Basic SQL syntax verification: check for balanced parentheses and quotes outside comments
    # Strip comments first
    cleaned_lines = []
    for line in content.splitlines():
        line_clean = re.sub(r"--.*$", "", line)
        cleaned_lines.append(line_clean)
    cleaned_sql = "\n".join(cleaned_lines)

    # Count quotes
    single_quotes = cleaned_sql.count("'") - cleaned_sql.count("\\'")
    assert single_quotes % 2 == 0, f"Unbalanced single quotes in schema.sql (count: {single_quotes})"

    # Verify statement terminators
    statements = [s.strip() for s in cleaned_sql.split(";") if s.strip()]
    assert len(statements) >= 10, f"Expected multiple DDL/DML statements, found {len(statements)}"

    print(f"✓ schema.sql passed structural and syntax checks ({len(statements)} statements verified).")


def test_db_module_import_and_helpers():
    """Verify src/db.py imports cleanly and executes all helpers properly."""
    from src import db

    # 1. Connection / status check
    status = db.get_db_status()
    assert isinstance(status, dict), "get_db_status() should return a dictionary"
    assert "status" in status, "get_db_status() missing 'status'"
    print(f"✓ db.get_db_status() -> {status}")

    # 2. Product operations
    prod = db.create_product({
        "name": "Tata Tea Gold 250g",
        "brand": "Tata Tea",
        "category": "Packaged Food / Beverages",
        "net_quantity_declared": "250g",
        "mrp_declared": 160.00,
        "manufacturer_name": "Tata Consumer Products Limited",
    })
    assert prod is not None and "id" in prod, "create_product failed"
    prod_id = prod["id"]
    fetched_prod = db.get_product(prod_id)
    assert fetched_prod is not None and fetched_prod["name"] == "Tata Tea Gold 250g", "get_product failed"
    print(f"✓ Product CRUD verified (ID: {prod_id})")

    # 3. Scan operations
    scan = db.create_scan({
        "product_id": prod_id,
        "front_image_url": "mock://product-images/test_front.jpg",
        "back_image_url": "mock://product-images/test_back.jpg",
        "front_coin_detected": True,
        "front_coin_diameter_px": 219.0,
        "front_calibration_ratio": 10.0,
        "status": "processing",
    })
    assert scan is not None and "id" in scan, "create_scan failed"
    scan_id = scan["id"]

    updated_scan = db.update_scan(scan_id, {"status": "completed"})
    assert updated_scan is not None and updated_scan["status"] == "completed", "update_scan failed"
    print(f"✓ Scan CRUD verified (ID: {scan_id})")

    # 4. Extracted fields operations
    fields_to_save = [
        {
            "scan_id": scan_id,
            "side": "front",
            "field_name": "mrp",
            "raw_text": "MRP Rs. 160.00 (incl. of all taxes)",
            "parsed_value": "160.00",
            "font_height_px": 25.0,
            "font_height_mm": 2.5,
            "confidence": 0.96,
        },
        {
            "scan_id": scan_id,
            "side": "front",
            "field_name": "net_quantity",
            "raw_text": "Net Qty: 250 g",
            "parsed_value": "250g",
            "font_height_px": 22.0,
            "font_height_mm": 2.2,
            "confidence": 0.94,
        },
    ]
    saved_fields = db.save_extracted_fields(fields_to_save)
    assert len(saved_fields) == 2, "save_extracted_fields failed"

    fetched_fields = db.get_extracted_fields(scan_id, side="front")
    assert len(fetched_fields) == 2, "get_extracted_fields failed"
    field_id = fetched_fields[0]["id"]

    corrected = db.update_extracted_field(field_id, {"parsed_value": "160.00 INR"})
    assert corrected is not None and corrected["is_corrected"] is True, "update_extracted_field failed"
    print(f"✓ Extracted fields operations verified ({len(saved_fields)} fields saved and updated)")

    # 5. Rules operations
    rules = db.get_rules(active_only=True)
    assert len(rules) >= 5, f"Expected at least 5 default rules, found {len(rules)}"
    rule_codes = [r["rule_code"] for r in rules]
    assert "RULE_6_1_A" in rule_codes, "RULE_6_1_A missing from default rules"
    assert "RULE_6_1_E" in rule_codes, "RULE_6_1_E missing from default rules"
    print(f"✓ Rules retrieval verified ({len(rules)} active rules available)")

    # 6. Compliance results operations
    compliance_payload = [
        {
            "scan_id": scan_id,
            "rule_code": "RULE_6_1_E",
            "status": "PASS",
            "severity": "CRITICAL",
            "message": "MRP declared properly inclusive of taxes.",
            "measured_font_height_mm": 2.5,
            "required_min_font_height_mm": 1.0,
        },
        {
            "scan_id": scan_id,
            "rule_code": "RULE_7_FONT_SIZE_NET_QTY",
            "status": "PASS",
            "severity": "HIGH",
            "message": "Net quantity font height (2.2mm) exceeds minimum requirement (1.0mm).",
            "measured_font_height_mm": 2.2,
            "required_min_font_height_mm": 1.0,
        },
    ]
    saved_comp = db.save_compliance_results(compliance_payload)
    assert len(saved_comp) == 2, "save_compliance_results failed"

    fetched_comp = db.get_compliance_results(scan_id)
    assert len(fetched_comp) == 2, "get_compliance_results failed"
    print(f"✓ Compliance results verified ({len(saved_comp)} results stored)")

    # 7. Storage upload mock/live operations
    upload_res = db.upload_file_to_storage(
        bucket_name="product-images",
        file_bytes=b"fake_image_bytes_12345",
        destination_path="scans/test_scan_front.jpg",
        content_type="image/jpeg",
    )
    assert "url" in upload_res and upload_res["path"] == "scans/test_scan_front.jpg", "upload_file_to_storage failed"
    pub_url = db.get_file_public_url("product-images", "scans/test_scan_front.jpg")
    assert pub_url is not None and len(pub_url) > 0, "get_file_public_url failed"
    print(f"✓ Storage upload operations verified (URL: {upload_res['url']})")


def run_all_tests():
    print("=" * 60)
    print("STARTING TASK 2 VERIFICATION SUITE")
    print("=" * 60)
    test_schema_sql_syntax_and_structure()
    test_db_module_import_and_helpers()
    print("=" * 60)
    print("ALL TASK 2 VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
