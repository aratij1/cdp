# Router V4 cross-source report

Router `4.0-dev` was run unchanged over 736 pages with one OCR call per page.

| Source | CMS precision / recall | UB precision / recall | Custom recall | Non-claim recall | P95 ms |
|---|---:|---:|---:|---:|---:|
| V4-A | 100% / 18.10% | 100% / 9.52% | n/a | n/a | 1,779 |
| V4-B | 100% / 80.95% | n/a / 0% | n/a | n/a | 1,872 |
| V4-C | n/a | n/a | 5.71% | 0% | 3,064 |
| V4-D | 100% / 70.59% | 100% / 10.29% | n/a | n/a | 2,553 |

Attachment accuracy was 100%; false standard routes were zero. Every source and performance gate failed. Decision: `NEEDS_MORE_DATA`. A/B/C/D are now observed development regressions and cannot become untouched validation sets.

