# Rejected closure approaches

These experiments did not activate production authority. Keep denominators and comparison policies explicit before revisiting them.

| Approach | Cohort | Before | After | Reason rejected |
|---|---|---|---|---|
| Wider name discovery windows | Frozen 200 fields | 30 exact missing after offset fix | 30 | No incremental recall; reverted |
| Prefer every source-discovery alternative | Frozen 200 fields | Exact top-1 66% | 66% | No aggregate gain; not a safe universal ranking rule |
| Unconditional unique source preference | Frozen 200 fields | Governed selected-value correctness 166/200 under bounded recovery | 166/200 | No incremental gain; keep recovery limited to missing/wrong-crop extraction |
| Broad failure-driven regional OCR | 56 observed-label crops on frozen sources | 30 exact missing | 30 | Approximately 51.5 seconds OCR time, zero incremental exact candidates; implementation removed |
| Fresh full-page OCR on residual claims | Six hash-bound synthetic pages | Governed Recall@5 89.5% | 89.5% | Approximately 13 seconds OCR time, zero incremental recovery; not added to runtime |
| Expanded diagnosis discovery | Frozen 200 fields after numeric assembly fix | 29 exact missing | 29 | No incremental recall; reverted |
| Four threads with CPU arena | Same 12 real pages | Eight-thread three-run P95 median 6473.69 ms | Pilot P95 7041.30 ms | Slower pilot; no configuration promotion |
| Recognition batch 3, previous iteration | Same 12 real pages | Default batch P95 8993.47 ms | 9287.35 ms | Token evidence changed on 12 pages; candidates on two; strict identity on one |
| Recognition batch 12, previous iteration | Same 12 real pages | Default batch P95 8993.47 ms | 9927.01 ms | Token evidence changed on 11 pages; candidates on two |
| Twelve/sixteen threads, previous iteration | Frozen fresh-perception cohort | Eight-thread profile | Twelve-thread P95 23.32s; first two sixteen-thread pages 37.81s/40.00s | Runtime regression; sixteen-thread trial stopped |

The 31 original name ranking misses were a diagnostic comparison error: compact canonical names were compared against spaced reference strings. Reusing the existing governed name-agreement policy corrects that measurement; it is not a new extraction gain. Original exact-string and governed-comparison baselines remain separate.

None of these failures proves that the remaining technical ceiling has been reached.

Iteration 3: disabling ONNX intra/inter-op idle spinning (same models, eight threads, arena, batch size and 12 pages) produced P95 7038.80 ms versus the retained iteration-2 median 6473.69 ms. All five semantic checks were identical. The slower pilot was rejected; no runtime configuration change was retained. Two preliminary invocations failed to persist/initialize the experiment and are excluded from timing evidence.

Iteration 4: limiting OpenCV's pool from 16 threads to one while retaining eight ONNX threads, the same models, arena, batch and 12 pages produced P95 11769.77 ms. All five semantic checks were unchanged. The slower pilot was not promoted or added to runtime; it does not prove a latency ceiling. Three repetitions were not pursued for this failed pilot.
