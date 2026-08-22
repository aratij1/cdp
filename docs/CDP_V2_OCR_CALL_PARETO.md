# CDP V2 OCR Call Pareto

## Frozen baseline

| Engine | Calls | Share |
|---|---:|---:|
| RapidOCR regional | 1,375 | 90.46% |
| PaddleOCR full-page | 145 | 9.54% |

The 1,375 RapidOCR calls equal 25 configured regions across 55 CMS-routed
documents. OCR accounted for 11,699.95 seconds and dominated total latency.
The historical run did not persist crop hashes, so duplicate-crop and cache-hit
claims would be speculation and are intentionally omitted.

## Phase 7 instrumentation

Every future OCR call records document/page, route, field, engine, versioned
crop hash, preprocessing profile, attempt, reason, cache hit, latency, CPU, and
candidate presence. The content key is SHA-256 over crop bytes, engine, model
version, preprocessing version, and OCR configuration. Identical work within a
document lifecycle returns the original evidence rather than executing again.
