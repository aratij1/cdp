-- CDP vNext Phase 2: backward-compatible evidence columns.
-- Apply before deploying workers that persist image-quality/registration evidence.
ALTER TABLE pages
    ADD COLUMN IF NOT EXISTS image_quality JSONB;

ALTER TABLE page_classifications
    ADD COLUMN IF NOT EXISTS registration_evidence JSONB;
