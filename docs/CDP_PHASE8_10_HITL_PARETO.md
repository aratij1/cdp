# CDP Phase 8.10 — HITL Pareto

Field HITL is 91.33%; claim HITL is 100%. Review causes across the unchanged
engineering replay are:

| Cause | Fields |
| --- | ---: |
| Correct but reviewed | 465 |
| Validation/evidence conflict | 57 |
| Localization uncertainty | 24 |
| Wrong extraction with empty value | 2 |

The dominant opportunity is correct-but-reviewed, especially provider NPI,
federal tax number, patient DOB, member ID, total charge, and provider name.
This phase does not convert these by relaxing policy. New evidence must provide
measured independent/reference/cross-field support and claim unlock value.

Artifact: `hitl_pareto.json/csv`.
