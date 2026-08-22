# CDP vNext Migration Guide

## Phase 2 evidence schema

1. Back up PostgreSQL and record the current application version.
2. Apply `deploy/postgres/migrations/002_vnext_page_evidence.sql` before new workers start.
3. Deploy document-preparation, page-detection, then standard-extraction workers.
4. Verify new rows populate `pages.image_quality`; registration evidence is nullable by design
   because anchor/grid/rescale-only routes did not execute geometric registration.
5. Roll back application workers first. The nullable JSONB columns may remain during rollback;
   removing them would destroy audit evidence and is intentionally not automated.

Fresh local databases continue to use SQLAlchemy metadata creation. Existing PostgreSQL databases
require the migration because `create_all` does not alter existing tables.

## Phase 5 review governance

Apply `deploy/postgres/migrations/003_hitl_governance.sql` before the Phase 5 review API. Grant the
application database role `SELECT, INSERT` on `review_audit_events`, never `UPDATE` or `DELETE`.
Review task versions begin at zero; old clients may omit `expected_version` temporarily, while new
clients should claim tasks and submit the returned version with every decision.
