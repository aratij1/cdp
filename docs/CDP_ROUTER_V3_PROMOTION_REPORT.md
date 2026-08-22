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

All development gates pass. `ENABLE_ROUTER_V3` remains false by default;
enable it for a controlled runtime promotion while retaining V2 rollback.
The next authorized phase is route-specific extraction recovery, followed by a
fresh frozen V3 production holdout.
