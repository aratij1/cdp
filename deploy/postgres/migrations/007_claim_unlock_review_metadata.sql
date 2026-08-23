ALTER TABLE review_tasks
    ADD COLUMN IF NOT EXISTS claim_impact VARCHAR(128),
    ADD COLUMN IF NOT EXISTS blocks_stp BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS single_blocker_claim BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS blocking_field_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS claim_unlock_value DOUBLE PRECISION NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_review_tasks_claim_unlock_priority
    ON review_tasks (single_blocker_claim DESC, status, created_at);
