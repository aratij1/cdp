# Phase 7A.12 LOSO Report

Status: **BLOCKED_BY_QUALIFIED_CORPUS**. No LOSO rotation was run and all routing metrics remain `null`.

When eligible, the runner calls `DocumentRoutingDecisionService` in evaluation-only mode for each held-out source and reports top-level, standard/non-standard, CMS/UB nomination and verification, processing route, false-standard authorization, safe fallback, cost-weighted routing, exact subtype, and P50/P95/P99 latency. Classification and nomination are one atomic deterministic-baseline stage and are reported as such; verification and route resolution are separately timed.

Promotion uses worst-source values. A failed held-out source may be diagnosed, but it may not be used for tuning; reproductions belong in a separate V2 development extension.
