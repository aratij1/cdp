ALTER TABLE extracted_fields
    ADD COLUMN IF NOT EXISTS reference_evidence JSONB NULL;

COMMENT ON COLUMN extracted_fields.reference_evidence IS
    'Immutable governed reference resolution, including source/version/match and contradiction provenance.';
