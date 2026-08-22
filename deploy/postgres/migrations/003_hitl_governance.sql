-- Phase 5: optimistic review concurrency and append-only audit evidence.
ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS review_audit_events (
    audit_id UUID PRIMARY KEY,
    task_id UUID NOT NULL,
    document_id UUID NOT NULL,
    field_name VARCHAR(128) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    task_version INTEGER NOT NULL,
    decision_hash VARCHAR(64),
    reason_code VARCHAR(128) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_review_audit_task_id ON review_audit_events(task_id);
CREATE INDEX IF NOT EXISTS ix_review_audit_document_id ON review_audit_events(document_id);

-- Database role used by the application must receive INSERT/SELECT only on
-- review_audit_events. UPDATE/DELETE are intentionally omitted.
