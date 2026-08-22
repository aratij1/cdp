# Routing Experiment History

| Component | Governed result | Runtime | Rejection reason |
|---|---|---|---|
| Router V3 | FAILED_GENERALIZATION | disabled by default | development performance did not generalize |
| Router V4 | NEEDS_MORE_DATA / NOT_ELIGIBLE | disabled | cross-source gates failed |
| LightGBM eligibility V1 | REJECT | disabled | eligibility/generalization gates failed |
| XGBoost eligibility V1 | REJECT | disabled | eligibility/generalization gates failed |
| Visual Router V1 | REJECT | disabled | hard-confuser false-standard rate 53.33% |
| Visual Contradiction V1 | REJECT | disabled | best false-standard rate remained 23.33% |

No routing candidate exists. External holdout and shadow are blocked, Phase 7B extraction is paused, and production Router V4 is unchanged. Immutable experiment JSON contains git SHA, config/dataset/model hashes, feature versions, metrics, and rejection reasons where an artifact existed. `config/router_lifecycle.json` is the fail-closed lifecycle authority; rejected components are evaluation artifacts only.
