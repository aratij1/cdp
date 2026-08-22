# CDP Router V3 Promotion Report

ROUTING_DEV_V3 contains 210 newly generated synthetic development documents:
60 CMS, 60 UB, 30 custom structured, 20 attachments, 20 adversarial structured
negatives and 20 non-claims across clean, fax, skew, low-contrast and clipped
conditions. It is explicitly prohibited as a holdout.

| Gate | Result |
|---|---:|
| CMS precision / recall | 100% / 100% |
| UB precision / recall | 100% / 100% |
| Unknown structured recall | 100% |
| Non-claim accuracy | 100% |
| False standard routes | 0 / 210 |
| P50 / P95 | 378 ms / 492 ms |
| OCR calls/document | 1.0 |

All development gates passed, but the later previously observed representative
regression measured only 14% routing accuracy. Router V3 is therefore
`FAILED_GENERALIZATION`, `NOT_ELIGIBLE`, disabled by default, and restricted to
evaluation. It must not be represented as production-ready. Phase 7B is paused
while separately versioned Router V4 generalization work proceeds.
