ALTER TABLE extracted_fields
    ADD COLUMN IF NOT EXISTS candidates JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN extracted_fields.candidates IS
    'Immutable OCR candidate evidence consumed by the canonical EvidenceDecisionService';
