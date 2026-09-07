"""Database & Supabase client integration for Digital Metrology Inspector.

Provides helper functions for table operations (products, scans, extracted_fields,
rules, compliance_results) and storage uploads, with graceful fallback to an
in-memory mock store when running offline or without configured credentials.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# Configure logger
logger = logging.getLogger("metrology_inspector.db")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [DB] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Load environment variables
load_dotenv()

# Constants
DEFAULT_PLACEHOLDERS = (
    "https://your-project-id.supabase.co",
    "your-anon-or-service-role-key",
    "placeholder",
    "example.com",
)


def _get_utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class MockDatabase:
    """Thread-safe in-memory database fallback for offline execution."""

    def __init__(self) -> None:
        self.products: Dict[str, Dict[str, Any]] = {}
        self.scans: Dict[str, Dict[str, Any]] = {}
        self.extracted_fields: Dict[str, Dict[str, Any]] = {}
        self.rules: Dict[str, Dict[str, Any]] = {}
        self.compliance_results: Dict[str, Dict[str, Any]] = {}
        self.storage: Dict[str, Dict[str, bytes]] = {
            "product-images": {},
            "inspection-reports": {},
        }
        self._seed_default_rules()

    def _seed_default_rules(self) -> None:
        """Seed default Legal Metrology rules in mock store."""
        seed_rules = [
            {
                "id": str(uuid.uuid4()),
                "rule_code": "RULE_6_1_A",
                "rule_name": "Manufacturer / Packer / Importer Details",
                "legal_reference": "Rule 6(1)(a) of Legal Metrology (Packaged Commodities) Rules, 2011",
                "description": "The name and complete address of the manufacturer, packer, or importer must be clearly declared on the package.",
                "category": "mandatory_declaration",
                "severity": "CRITICAL",
                "parameters": {"required_field": "manufacturer_name", "address_required": True},
                "is_active": True,
                "created_at": _get_utc_now_iso(),
                "updated_at": _get_utc_now_iso(),
            },
            {
                "id": str(uuid.uuid4()),
                "rule_code": "RULE_6_1_B",
                "rule_name": "Generic or Common Name of Commodity",
                "legal_reference": "Rule 6(1)(b) of Legal Metrology (Packaged Commodities) Rules, 2011",
                "description": "The common or generic name of the commodity contained in the package must be stated.",
                "category": "mandatory_declaration",
                "severity": "HIGH",
                "parameters": {"required_field": "generic_name"},
                "is_active": True,
                "created_at": _get_utc_now_iso(),
                "updated_at": _get_utc_now_iso(),
            },
            {
                "id": str(uuid.uuid4()),
                "rule_code": "RULE_6_1_C",
                "rule_name": "Net Quantity Declaration",
                "legal_reference": "Rule 6(1)(c) of Legal Metrology (Packaged Commodities) Rules, 2011",
                "description": "The net quantity in terms of standard unit of weight or measure must be declared.",
                "category": "mandatory_declaration",
                "severity": "CRITICAL",
                "parameters": {
                    "required_field": "net_quantity",
                    "allowed_units": ["g", "kg", "ml", "l", "m", "cm", "u", "N"],
                },
                "is_active": True,
                "created_at": _get_utc_now_iso(),
                "updated_at": _get_utc_now_iso(),
            },
            {
                "id": str(uuid.uuid4()),
                "rule_code": "RULE_6_1_D",
                "rule_name": "Month and Year of Manufacture / Packaging / Import",
                "legal_reference": "Rule 6(1)(d) of Legal Metrology (Packaged Commodities) Rules, 2011",
                "description": "The month and year in which the commodity is manufactured or pre-packed or imported shall be declared.",
                "category": "mandatory_declaration",
                "severity": "HIGH",
                "parameters": {
                    "required_field": "mfg_date",
                    "format_patterns": ["MM/YYYY", "MMM YYYY", "MM/YY"],
                },
                "is_active": True,
                "created_at": _get_utc_now_iso(),
                "updated_at": _get_utc_now_iso(),
            },
            {
                "id": str(uuid.uuid4()),
                "rule_code": "RULE_6_1_E",
                "rule_name": "Maximum Retail Price (MRP)",
                "legal_reference": "Rule 6(1)(e) of Legal Metrology (Packaged Commodities) Rules, 2011",
                "description": "The retail sale price of the package shall be clearly indicated as Maximum Retail Price (MRP) inclusive of all taxes.",
                "category": "pricing",
                "severity": "CRITICAL",
                "parameters": {"required_field": "mrp", "must_include_tax_statement": True},
                "is_active": True,
                "created_at": _get_utc_now_iso(),
                "updated_at": _get_utc_now_iso(),
            },
            {
                "id": str(uuid.uuid4()),
                "rule_code": "RULE_6_1_F",
                "rule_name": "Consumer Care Contact Information",
                "legal_reference": "Rule 6(1)(f) of Legal Metrology (Packaged Commodities) Rules, 2011",
                "description": "The name, address, telephone number, and email address of the person/office to contact in case of consumer complaints.",
                "category": "mandatory_declaration",
                "severity": "HIGH",
                "parameters": {"required_fields": ["phone", "email"], "contact_must_be_present": True},
                "is_active": True,
                "created_at": _get_utc_now_iso(),
                "updated_at": _get_utc_now_iso(),
            },
            {
                "id": str(uuid.uuid4()),
                "rule_code": "RULE_7_FONT_SIZE_NET_QTY",
                "rule_name": "Minimum Font Height for Net Quantity Declaration",
                "legal_reference": "Rule 7 Table 1 of Legal Metrology (Packaged Commodities) Rules, 2011",
                "description": "The minimum height of numerals and letters in the net quantity declaration must comply with Table 1 (typically 1.0mm to 6.0mm depending on package weight/volume).",
                "category": "font_size",
                "severity": "HIGH",
                "parameters": {"min_height_mm_small": 1.0, "min_height_mm_medium": 2.0, "min_height_mm_large": 4.0},
                "is_active": True,
                "created_at": _get_utc_now_iso(),
                "updated_at": _get_utc_now_iso(),
            },
            {
                "id": str(uuid.uuid4()),
                "rule_code": "RULE_7_FONT_SIZE_GENERAL",
                "rule_name": "Minimum Font Height for General Mandatory Declarations",
                "legal_reference": "Rule 7 of Legal Metrology (Packaged Commodities) Rules, 2011",
                "description": "Mandatory declarations must not be smaller than the legally stipulated minimum height (normally 1.0mm).",
                "category": "font_size",
                "severity": "MEDIUM",
                "parameters": {"default_min_height_mm": 1.0},
                "is_active": True,
                "created_at": _get_utc_now_iso(),
                "updated_at": _get_utc_now_iso(),
            },
        ]
        for rule in seed_rules:
            self.rules[rule["rule_code"]] = rule


# Global mock database instance
_mock_db = MockDatabase()
_supabase_client = None
_client_initialized = False


def is_valid_credentials(url: Optional[str], key: Optional[str]) -> bool:
    """Check whether provided Supabase URL and Key are real and non-placeholder."""
    if not url or not key:
        return False
    url_clean = url.strip()
    key_clean = key.strip()
    if not url_clean or not key_clean:
        return False
    if any(placeholder in url_clean.lower() for placeholder in DEFAULT_PLACEHOLDERS):
        return False
    if any(placeholder in key_clean.lower() for placeholder in DEFAULT_PLACEHOLDERS):
        return False
    return True


def get_supabase_client():
    """Initialize and return Supabase client, or None if credentials are missing/offline."""
    global _supabase_client, _client_initialized
    if _client_initialized:
        return _supabase_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not is_valid_credentials(url, key):
        logger.warning(
            "Supabase credentials not configured or using placeholders. Running in offline mock mode."
        )
        _supabase_client = None
        _client_initialized = True
        return None

    try:
        from supabase import create_client

        _supabase_client = create_client(url.strip(), key.strip())
        logger.info("Successfully connected to Supabase: %s", url.strip())
    except Exception as exc:
        logger.warning("Failed to initialize Supabase client (%s). Falling back to mock mode.", exc)
        _supabase_client = None

    _client_initialized = True
    return _supabase_client


def is_offline_mode() -> bool:
    """Return True if running in offline mock mode."""
    return get_supabase_client() is None


def get_db_status() -> Dict[str, Any]:
    """Return current database connection status metadata."""
    url = os.getenv("SUPABASE_URL", "")
    offline = is_offline_mode()
    return {
        "status": "offline_mock" if offline else "connected",
        "is_offline": offline,
        "supabase_url": url if url and not any(p in url for p in DEFAULT_PLACEHOLDERS) else None,
        "mode_description": "Using in-memory mock database" if offline else "Connected to live Supabase backend",
    }


# ==============================================================================
# Helper Functions: Products
# ==============================================================================

def create_product(product_data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a product record.

    Args:
        product_data: Dictionary of product attributes.

    Returns:
        Created product record dictionary.
    """
    data = dict(product_data)
    data.setdefault("id", str(uuid.uuid4()))
    now = _get_utc_now_iso()
    data.setdefault("created_at", now)
    data.setdefault("updated_at", now)

    client = get_supabase_client()
    if client is not None:
        try:
            response = client.table("products").insert(data).execute()
            if response.data:
                return response.data[0]
        except Exception as exc:
            logger.error("Supabase insert error on products (%s). Falling back to mock store.", exc)

    _mock_db.products[data["id"]] = data
    return data


def get_product(product_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve product by ID.

    Args:
        product_id: UUID string.

    Returns:
        Product dictionary or None.
    """
    client = get_supabase_client()
    if client is not None:
        try:
            response = client.table("products").select("*").eq("id", product_id).execute()
            if response.data:
                return response.data[0]
        except Exception as exc:
            logger.error("Supabase query error on products (%s). Checking mock store.", exc)

    return _mock_db.products.get(product_id)


def list_products(limit: int = 50) -> List[Dict[str, Any]]:
    """List recent products."""
    client = get_supabase_client()
    if client is not None:
        try:
            response = client.table("products").select("*").order("created_at", desc=True).limit(limit).execute()
            if response.data:
                return response.data
        except Exception as exc:
            logger.error("Supabase list error on products (%s). Using mock store.", exc)

    return sorted(
        _mock_db.products.values(),
        key=lambda x: x.get("created_at", ""),
        reverse=True,
    )[:limit]


# ==============================================================================
# Helper Functions: Scans
# ==============================================================================

def create_scan(scan_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new scan record.

    Args:
        scan_data: Scan metadata including image URLs and calibration.

    Returns:
        Created scan dictionary.
    """
    data = dict(scan_data)
    data.setdefault("id", str(uuid.uuid4()))
    now = _get_utc_now_iso()
    data.setdefault("created_at", now)
    data.setdefault("updated_at", now)
    data.setdefault("status", "pending")

    client = get_supabase_client()
    if client is not None:
        try:
            response = client.table("scans").insert(data).execute()
            if response.data:
                return response.data[0]
        except Exception as exc:
            logger.error("Supabase insert error on scans (%s). Falling back to mock store.", exc)

    _mock_db.scans[data["id"]] = data
    return data


def update_scan(scan_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update an existing scan record.

    Args:
        scan_id: Scan UUID string.
        updates: Fields to update.

    Returns:
        Updated scan dictionary.
    """
    data = dict(updates)
    data["updated_at"] = _get_utc_now_iso()

    client = get_supabase_client()
    if client is not None:
        try:
            response = client.table("scans").update(data).eq("id", scan_id).execute()
            if response.data:
                return response.data[0]
        except Exception as exc:
            logger.error("Supabase update error on scans (%s). Falling back to mock store.", exc)

    if scan_id in _mock_db.scans:
        _mock_db.scans[scan_id].update(data)
        return _mock_db.scans[scan_id]
    return None


def get_scan(scan_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve scan record by ID."""
    client = get_supabase_client()
    if client is not None:
        try:
            response = client.table("scans").select("*").eq("id", scan_id).execute()
            if response.data:
                return response.data[0]
        except Exception as exc:
            logger.error("Supabase query error on scans (%s). Checking mock store.", exc)

    return _mock_db.scans.get(scan_id)


def list_scans(limit: int = 50) -> List[Dict[str, Any]]:
    """List recent scans."""
    client = get_supabase_client()
    if client is not None:
        try:
            response = client.table("scans").select("*").order("created_at", desc=True).limit(limit).execute()
            if response.data:
                return response.data
        except Exception as exc:
            logger.error("Supabase list error on scans (%s). Using mock store.", exc)

    return sorted(
        _mock_db.scans.values(),
        key=lambda x: x.get("created_at", ""),
        reverse=True,
    )[:limit]


# ==============================================================================
# Helper Functions: Extracted Fields
# ==============================================================================

def save_extracted_fields(fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Save extracted OCR fields for a scan.

    Args:
        fields: List of dictionaries with field extractions.

    Returns:
        List of saved field dictionaries.
    """
    now = _get_utc_now_iso()
    prepared_fields = []
    for f in fields:
        item = dict(f)
        item.setdefault("id", str(uuid.uuid4()))
        item.setdefault("created_at", now)
        item.setdefault("updated_at", now)
        item.setdefault("is_corrected", False)
        prepared_fields.append(item)

    client = get_supabase_client()
    if client is not None and prepared_fields:
        try:
            response = client.table("extracted_fields").insert(prepared_fields).execute()
            if response.data:
                return response.data
        except Exception as exc:
            logger.error("Supabase insert error on extracted_fields (%s). Falling back to mock store.", exc)

    for item in prepared_fields:
        _mock_db.extracted_fields[item["id"]] = item
    return prepared_fields


def get_extracted_fields(scan_id: str, side: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve extracted fields for a scan ID, optionally filtered by side.

    Args:
        scan_id: UUID of scan.
        side: Optional filter ('front', 'back', 'consolidated').

    Returns:
        List of extracted fields.
    """
    client = get_supabase_client()
    if client is not None:
        try:
            query = client.table("extracted_fields").select("*").eq("scan_id", scan_id)
            if side:
                query = query.eq("side", side)
            response = query.order("created_at").execute()
            if response.data:
                return response.data
        except Exception as exc:
            logger.error("Supabase query error on extracted_fields (%s). Checking mock store.", exc)

    results = [
        f for f in _mock_db.extracted_fields.values()
        if f.get("scan_id") == scan_id and (side is None or f.get("side") == side)
    ]
    return sorted(results, key=lambda x: x.get("created_at", ""))


def update_extracted_field(field_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update an extracted field (e.g., manual correction by inspector)."""
    data = dict(updates)
    data["updated_at"] = _get_utc_now_iso()
    data["is_corrected"] = True

    client = get_supabase_client()
    if client is not None:
        try:
            response = client.table("extracted_fields").update(data).eq("id", field_id).execute()
            if response.data:
                return response.data[0]
        except Exception as exc:
            logger.error("Supabase update error on extracted_fields (%s). Falling back to mock store.", exc)

    if field_id in _mock_db.extracted_fields:
        _mock_db.extracted_fields[field_id].update(data)
        return _mock_db.extracted_fields[field_id]
    return None


# ==============================================================================
# Helper Functions: Rules
# ==============================================================================

def get_rules(active_only: bool = True) -> List[Dict[str, Any]]:
    """Retrieve Legal Metrology rule configurations.

    Args:
        active_only: If True, only returns active rules.

    Returns:
        List of rule dictionaries.
    """
    client = get_supabase_client()
    if client is not None:
        try:
            query = client.table("rules").select("*")
            if active_only:
                query = query.eq("is_active", True)
            response = query.order("rule_code").execute()
            if response.data:
                return response.data
        except Exception as exc:
            logger.error("Supabase query error on rules (%s). Using mock rules.", exc)

    rules = list(_mock_db.rules.values())
    if active_only:
        rules = [r for r in rules if r.get("is_active", True)]
    return sorted(rules, key=lambda r: r.get("rule_code", ""))


def create_or_update_rule(rule_data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update a compliance rule definition."""
    data = dict(rule_data)
    data.setdefault("id", str(uuid.uuid4()))
    now = _get_utc_now_iso()
    data.setdefault("created_at", now)
    data["updated_at"] = now
    data.setdefault("is_active", True)

    client = get_supabase_client()
    if client is not None:
        try:
            response = client.table("rules").upsert(data, on_conflict="rule_code").execute()
            if response.data:
                return response.data[0]
        except Exception as exc:
            logger.error("Supabase upsert error on rules (%s). Falling back to mock store.", exc)

    rule_code = data.get("rule_code")
    if rule_code:
        _mock_db.rules[rule_code] = data
    return data


# ==============================================================================
# Helper Functions: Compliance Results
# ==============================================================================

def save_compliance_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Store compliance verdicts for a scan.

    Args:
        results: List of compliance evaluation result dictionaries.

    Returns:
        List of saved compliance results.
    """
    now = _get_utc_now_iso()
    prepared_results = []
    for r in results:
        item = dict(r)
        item.setdefault("id", str(uuid.uuid4()))
        item.setdefault("created_at", now)
        item.setdefault("updated_at", now)
        prepared_results.append(item)

    client = get_supabase_client()
    if client is not None and prepared_results:
        try:
            response = client.table("compliance_results").insert(prepared_results).execute()
            if response.data:
                return response.data
        except Exception as exc:
            logger.error("Supabase insert error on compliance_results (%s). Falling back to mock store.", exc)

    for item in prepared_results:
        _mock_db.compliance_results[item["id"]] = item
    return prepared_results


def get_compliance_results(scan_id: str) -> List[Dict[str, Any]]:
    """Retrieve all compliance evaluation results for a scan ID."""
    client = get_supabase_client()
    if client is not None:
        try:
            response = client.table("compliance_results").select("*").eq("scan_id", scan_id).order("created_at").execute()
            if response.data:
                return response.data
        except Exception as exc:
            logger.error("Supabase query error on compliance_results (%s). Checking mock store.", exc)

    results = [
        res for res in _mock_db.compliance_results.values()
        if res.get("scan_id") == scan_id
    ]
    return sorted(results, key=lambda x: x.get("created_at", ""))


# ==============================================================================
# Helper Functions: Storage Uploads
# ==============================================================================

def upload_file_to_storage(
    bucket_name: str,
    file_bytes: bytes,
    destination_path: str,
    content_type: str = "application/octet-stream",
) -> Dict[str, Any]:
    """Upload a file to Supabase Storage or mock storage.

    Args:
        bucket_name: Storage bucket name ('product-images' or 'inspection-reports').
        file_bytes: Binary contents of file.
        destination_path: Destination filename/path inside the bucket.
        content_type: MIME type of the uploaded file.

    Returns:
        Dictionary with 'path', 'url', and 'bucket'.
    """
    client = get_supabase_client()
    if client is not None:
        try:
            client.storage.from_(bucket_name).upload(
                path=destination_path,
                file=file_bytes,
                file_options={"content-type": content_type, "upsert": "true"},
            )
            public_url = client.storage.from_(bucket_name).get_public_url(destination_path)
            return {
                "bucket": bucket_name,
                "path": destination_path,
                "url": public_url,
                "offline": False,
            }
        except Exception as exc:
            logger.error(
                "Supabase storage upload error in %s (%s). Storing in mock storage.",
                bucket_name,
                exc,
            )

    # Offline / Mock storage
    if bucket_name not in _mock_db.storage:
        _mock_db.storage[bucket_name] = {}
    _mock_db.storage[bucket_name][destination_path] = file_bytes
    mock_url = f"mock://{bucket_name}/{destination_path}"
    return {
        "bucket": bucket_name,
        "path": destination_path,
        "url": mock_url,
        "offline": True,
    }


def get_file_public_url(bucket_name: str, destination_path: str) -> str:
    """Get the public URL for an uploaded file."""
    client = get_supabase_client()
    if client is not None:
        try:
            return client.storage.from_(bucket_name).get_public_url(destination_path)
        except Exception as exc:
            logger.error("Supabase storage get_public_url error (%s).", exc)

    return f"mock://{bucket_name}/{destination_path}"
