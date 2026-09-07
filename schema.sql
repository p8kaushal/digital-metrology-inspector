-- ==============================================================================
-- Digital Metrology Inspector (SIH26034)
-- Database Schema for Supabase (PostgreSQL)
--
-- Tables:
--   1. products
--   2. scans
--   3. extracted_fields
--   4. rules
--   5. compliance_results
--   6. storage buckets setup & security policies
-- ==============================================================================

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==============================================================================
-- 1. PRODUCTS TABLE
-- Stores metadata of packaged commodities inspected or cataloged.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    brand TEXT,
    category TEXT,
    barcode TEXT,
    net_quantity_declared TEXT,
    mrp_declared NUMERIC(10, 2),
    manufacturer_name TEXT,
    manufacturer_address TEXT,
    consumer_care TEXT,
    country_of_origin TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);
CREATE INDEX IF NOT EXISTS idx_products_created_at ON products(created_at DESC);

-- ==============================================================================
-- 2. SCANS TABLE
-- Logs individual inspection runs with front/back label images and coin calibration.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS scans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    front_image_url TEXT,
    back_image_url TEXT,
    front_coin_detected BOOLEAN DEFAULT false,
    front_coin_diameter_px NUMERIC(10, 2),
    front_calibration_ratio NUMERIC(10, 4), -- pixels per mm (diameter_px / 21.9)
    back_coin_detected BOOLEAN DEFAULT false,
    back_coin_diameter_px NUMERIC(10, 2),
    back_calibration_ratio NUMERIC(10, 4),  -- pixels per mm (diameter_px / 21.9)
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'uploaded', 'processing', 'processed', 'completed', 'failed')),
    dimensions JSONB DEFAULT '{}'::jsonb,
    report_url TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_scans_product_id ON scans(product_id);
CREATE INDEX IF NOT EXISTS idx_scans_status ON scans(status);
CREATE INDEX IF NOT EXISTS idx_scans_created_at ON scans(created_at DESC);

-- ==============================================================================
-- 3. EXTRACTED_FIELDS TABLE
-- Stores OCR extracted text, bounding boxes, and measured font sizes per label side.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS extracted_fields (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    side TEXT NOT NULL CHECK (side IN ('front', 'back', 'consolidated')),
    field_name TEXT NOT NULL,
    raw_text TEXT,
    parsed_value TEXT,
    bounding_box JSONB,
    font_height_px NUMERIC(10, 2),
    font_height_mm NUMERIC(10, 2),
    confidence NUMERIC(5, 4),
    is_rule7_compliant BOOLEAN,
    is_corrected BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_extracted_fields_scan_id ON extracted_fields(scan_id);
CREATE INDEX IF NOT EXISTS idx_extracted_fields_field_name ON extracted_fields(field_name);
CREATE INDEX IF NOT EXISTS idx_extracted_fields_side ON extracted_fields(side);
CREATE INDEX IF NOT EXISTS idx_extracted_fields_is_corrected ON extracted_fields(is_corrected);

-- ==============================================================================
-- 4. RULES TABLE
-- Structured Legal Metrology (Packaged Commodities) Rules, 2011 configurations.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_code TEXT NOT NULL UNIQUE,
    rule_name TEXT NOT NULL,
    legal_reference TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    severity TEXT NOT NULL DEFAULT 'HIGH' CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_rules_rule_code ON rules(rule_code);
CREATE INDEX IF NOT EXISTS idx_rules_category ON rules(category);
CREATE INDEX IF NOT EXISTS idx_rules_is_active ON rules(is_active);

-- ==============================================================================
-- 5. COMPLIANCE_RESULTS TABLE
-- Evaluation verdicts against Legal Metrology Rules for each scan.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS compliance_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    rule_id UUID REFERENCES rules(id) ON DELETE SET NULL,
    rule_code TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL', 'WARNING', 'MANUAL_REVIEW')),
    severity TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    message TEXT NOT NULL,
    details JSONB DEFAULT '{}'::jsonb,
    measured_font_height_mm NUMERIC(10, 2),
    required_min_font_height_mm NUMERIC(10, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_compliance_results_scan_id ON compliance_results(scan_id);
CREATE INDEX IF NOT EXISTS idx_compliance_results_rule_id ON compliance_results(rule_id);
CREATE INDEX IF NOT EXISTS idx_compliance_results_status ON compliance_results(status);
CREATE INDEX IF NOT EXISTS idx_compliance_results_rule_code ON compliance_results(rule_code);

-- ==============================================================================
-- 6. AUTOMATIC UPDATED_AT TRIGGER
-- Updates updated_at column automatically on row modifications.
-- ==============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_products_updated_at ON products;
CREATE TRIGGER trg_products_updated_at
    BEFORE UPDATE ON products
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_scans_updated_at ON scans;
CREATE TRIGGER trg_scans_updated_at
    BEFORE UPDATE ON scans
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_extracted_fields_updated_at ON extracted_fields;
CREATE TRIGGER trg_extracted_fields_updated_at
    BEFORE UPDATE ON extracted_fields
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_rules_updated_at ON rules;
CREATE TRIGGER trg_rules_updated_at
    BEFORE UPDATE ON rules
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_compliance_results_updated_at ON compliance_results;
CREATE TRIGGER trg_compliance_results_updated_at
    BEFORE UPDATE ON compliance_results
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==============================================================================
-- 7. SUPABASE STORAGE BUCKETS SETUP
-- Creates storage buckets for product images and inspection reports.
-- ==============================================================================
INSERT INTO storage.buckets (id, name, public)
VALUES 
    ('product-images', 'product-images', true),
    ('inspection-reports', 'inspection-reports', true)
ON CONFLICT (id) DO NOTHING;

-- Storage Policies for Public / Authenticated Access
DO $$
BEGIN
    -- Allow public read access to product-images
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE schemaname = 'storage' AND tablename = 'objects' AND policyname = 'Public Access for Product Images'
    ) THEN
        CREATE POLICY "Public Access for Product Images"
        ON storage.objects FOR SELECT
        USING (bucket_id = 'product-images');
    END IF;

    -- Allow insert access to product-images
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE schemaname = 'storage' AND tablename = 'objects' AND policyname = 'Allow Uploads for Product Images'
    ) THEN
        CREATE POLICY "Allow Uploads for Product Images"
        ON storage.objects FOR INSERT
        WITH CHECK (bucket_id = 'product-images');
    END IF;

    -- Allow public read access to inspection-reports
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE schemaname = 'storage' AND tablename = 'objects' AND policyname = 'Public Access for Inspection Reports'
    ) THEN
        CREATE POLICY "Public Access for Inspection Reports"
        ON storage.objects FOR SELECT
        USING (bucket_id = 'inspection-reports');
    END IF;

    -- Allow insert access to inspection-reports
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE schemaname = 'storage' AND tablename = 'objects' AND policyname = 'Allow Uploads for Inspection Reports'
    ) THEN
        CREATE POLICY "Allow Uploads for Inspection Reports"
        ON storage.objects FOR INSERT
        WITH CHECK (bucket_id = 'inspection-reports');
    END IF;
END $$;

-- ==============================================================================
-- 8. INITIAL LEGAL METROLOGY RULES SEED DATA
-- Default baseline rules under Legal Metrology (Packaged Commodities) Rules, 2011.
-- ==============================================================================
INSERT INTO rules (rule_code, rule_name, legal_reference, description, category, severity, parameters)
VALUES
    (
        'RULE_6_1_A',
        'Manufacturer / Packer / Importer Details',
        'Rule 6(1)(a) of Legal Metrology (Packaged Commodities) Rules, 2011',
        'The name and complete address of the manufacturer, or packer, or importer must be clearly declared on the package.',
        'mandatory_declaration',
        'CRITICAL',
        '{"required_field": "manufacturer_name", "address_required": true}'::jsonb
    ),
    (
        'RULE_6_1_B',
        'Generic or Common Name of Commodity',
        'Rule 6(1)(b) of Legal Metrology (Packaged Commodities) Rules, 2011',
        'The common or generic name of the commodity contained in the package must be stated.',
        'mandatory_declaration',
        'HIGH',
        '{"required_field": "generic_name"}'::jsonb
    ),
    (
        'RULE_6_1_C',
        'Net Quantity Declaration',
        'Rule 6(1)(c) of Legal Metrology (Packaged Commodities) Rules, 2011',
        'The net quantity in terms of standard unit of weight or measure must be declared.',
        'mandatory_declaration',
        'CRITICAL',
        '{"required_field": "net_quantity", "allowed_units": ["g", "kg", "ml", "l", "m", "cm", "u", "N"]}'::jsonb
    ),
    (
        'RULE_6_1_D',
        'Month and Year of Manufacture / Packaging / Import',
        'Rule 6(1)(d) of Legal Metrology (Packaged Commodities) Rules, 2011',
        'The month and year in which the commodity is manufactured or pre-packed or imported shall be declared.',
        'mandatory_declaration',
        'HIGH',
        '{"required_field": "mfg_date", "format_patterns": ["MM/YYYY", "MMM YYYY", "MM/YY"]}'::jsonb
    ),
    (
        'RULE_6_1_E',
        'Maximum Retail Price (MRP)',
        'Rule 6(1)(e) of Legal Metrology (Packaged Commodities) Rules, 2011',
        'The retail sale price of the package shall be clearly indicated as Maximum Retail Price (MRP) inclusive of all taxes.',
        'pricing',
        'CRITICAL',
        '{"required_field": "mrp", "must_include_tax_statement": true}'::jsonb
    ),
    (
        'RULE_6_1_F',
        'Consumer Care Contact Information',
        'Rule 6(1)(f) of Legal Metrology (Packaged Commodities) Rules, 2011',
        'The name, address, telephone number, and email address of the person/office to contact in case of consumer complaints.',
        'mandatory_declaration',
        'HIGH',
        '{"required_fields": ["phone", "email"], "contact_must_be_present": true}'::jsonb
    ),
    (
        'RULE_6_1_G',
        'Country of Origin',
        'Rule 6(1)(g) of Legal Metrology (Packaged Commodities) Rules, 2011',
        'For imported packages, the name of the country of origin or manufacture must be stated.',
        'mandatory_declaration',
        'MEDIUM',
        '{"required_field": "country_of_origin", "applies_to": "all_or_imported"}'::jsonb
    ),
    (
        'RULE_7_FONT_SIZE_NET_QTY',
        'Minimum Font Height for Net Quantity Declaration',
        'Rule 7 Table 1 of Legal Metrology (Packaged Commodities) Rules, 2011',
        'The minimum height of numerals and letters in the net quantity declaration must comply with Table 1 (typically 1.0mm to 6.0mm depending on package weight/volume).',
        'font_size',
        'HIGH',
        '{"min_height_mm_small": 1.0, "min_height_mm_medium": 2.0, "min_height_mm_large": 4.0}'::jsonb
    ),
    (
        'RULE_7_FONT_SIZE_GENERAL',
        'Minimum Font Height for General Mandatory Declarations',
        'Rule 7 of Legal Metrology (Packaged Commodities) Rules, 2011',
        'Mandatory declarations must not be smaller than the legally stipulated minimum height (normally 1.0mm for small packs, larger for larger packaging).',
        'font_size',
        'MEDIUM',
        '{"default_min_height_mm": 1.0}'::jsonb
    )
ON CONFLICT (rule_code) DO NOTHING;
