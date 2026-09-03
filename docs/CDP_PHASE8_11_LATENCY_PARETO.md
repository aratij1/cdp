# Phase 8.11 Stage Latency Pareto

Measured on an uncached eight-page, single-worker refresh.

| stage | samples | p50 | p95 | max |
|---|---|---|---|---|
| field_candidate_generation | 8 | 6229.836999991676 | 9221.308400010457 | 9221.308400010457 |
| full_page_observation | 8 | 4767.980299977353 | 7036.794599989662 | 7036.794599989662 |
| ub_service_line_reconstruction | 3 | 866.2820000026841 | 4695.636100019328 | 4695.636100019328 |
| layout_inference | 8 | 78.19840000593103 | 117.90939999627881 | 117.90939999627881 |
| roi_resolution | 8 | 0.13890000991523266 | 0.26199998683296144 | 0.26199998683296144 |
| page_observation | 8 | 0.000400003045797348 | 0.0005999754648655653 | 0.0005999754648655653 |

Dominant P95 stage: field_candidate_generation.
