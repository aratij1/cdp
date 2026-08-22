-- Phase 7: field-level decision evidence and reproducibility metadata.
ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS review_reason_codes JSONB NOT NULL DEFAULT '[]';
ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS candidate_evidence JSONB NOT NULL DEFAULT '[]';
ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS reference_evidence JSONB NOT NULL DEFAULT '[]';
ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS registration_evidence JSONB NOT NULL DEFAULT '{}';
ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS system_recommendation VARCHAR(1024);
ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS evidence_versions JSONB NOT NULL DEFAULT '{}';

COMMENT ON COLUMN review_tasks.evidence_versions IS
  'Template, registration, OCR, preprocessing, validation, reference, calibration and routing versions used for the decision.';
