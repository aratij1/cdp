# CDP Phase 8.10 — Correct Localization, Wrong Extraction

After span recovery, 46 of the 60 residual errors occur despite expected-value
containment. The main populations are:

| Field | Correctly localized | Accuracy given containment | Wrong |
| --- | ---: | ---: | ---: |
| patient_name | 41 | 53.66% | 19 |
| insured_name | 19 | 63.16% | 7 |
| relationship | 21 | 71.43% | 6 |
| provider_name | 41 | 87.80% | 5 |
| member_id | 42 | 95.24% | 2 |
| diagnosis | 20 | 95.00% | 1 |
| total_charge | 38 | 97.37% | 1 |
| principal_diagnosis | 18 | 94.44% | 1 |

Dates, NPIs, CPT/HCPCS, service dates, and type-of-bill reach 100% extraction
accuracy when containment is correct. Compressed names remain the largest defect;
the local engines often observe two names as one token, and truth-blind rules
cannot safely infer the missing boundary in arbitrary identities.

Artifact: `correct_localization_wrong_extraction.json/csv`.
