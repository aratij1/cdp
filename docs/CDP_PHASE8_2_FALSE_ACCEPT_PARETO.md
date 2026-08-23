# CDP Phase 8.2 False-Accept Pareto

Phase 8.1 extraction-proxy cases: 9. All are retained in `false_accept_records.json` with remediation status. Final canonical false accepts: 0 (0.00%); safe rejections: 41; accepted precision: 100.00%.

Root causes: `{"ID_ACCEPTANCE_TOO_WEAK": 1, "LOCALIZATION_FALSE_POSITIVE": 3, "NAME_ACCEPTANCE_TOO_WEAK": 5}`. Critical false accepts are zero. Wrong final values remain counted as extraction errors and are never reclassified away.
