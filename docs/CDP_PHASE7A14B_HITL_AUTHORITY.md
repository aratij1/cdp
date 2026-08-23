# CDP Phase 7A.14B HITL Authority



```json
{
  "canonical_authority": "CANONICAL_POST_EVIDENCE_DECISION_V1",
  "authoritative_event_builder": "packages.human_review_authority.CanonicalHITLAuthority",
  "application_layer_authority_count": 1,
  "extraction_worker_authoritative_hitl_events_before": "ONE_PER_REVIEW_SUGGESTED_FIELD",
  "extraction_worker_authoritative_hitl_events_after": 0,
  "validation_worker_authoritative_hitl_events_after": 0,
  "retry_post_evidence_authority": true,
  "field_task_idempotency": "UUID5_DOCUMENT_FIELD_AND_REPOSITORY_EXISTENCE_GUARD",
  "replay_contract_test": "PASS_MAX_ONE_TASK"
}
```
