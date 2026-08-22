# CDP V2 Routing Pareto

Frozen 200-document baseline; no recovery changes are included.

| Truth | CMS | UB | Structured | Unstructured | Non-claim |
|---|---:|---:|---:|---:|---:|
| CMS-1500 | 55 | 0 | 0 | 11 | 3 |
| UB-04 | 0 | 0 | 0 | 80 | 0 |
| Custom claim | 0 | 0 | 6 | 18 | 0 |
| Attachment | 0 | 0 | 0 | 13 | 4 |
| Non-claim | 0 | 0 | 0 | 5 | 5 |

| Route | Precision | Recall | F1 |
|---|---:|---:|---:|
| CMS-1500 | 100% | 79.71% | 88.71% |
| UB-04 | n/a | 0% | 0% |
| Unknown structured | 100% | 25% | 40% |
| Unknown unstructured | 10.24% | 76.47% | 18.06% |
| Non-claim | 41.67% | 50% | 45.45% |

The router made no false standard-form assignments, preserving safety. The
Pareto is dominated by 80 UB-04 pages falling to unstructured, followed by 18
custom claims falling to unstructured and 14 missed CMS pages. Unknown fallback
was 66.5%. UB recognition is the first recovery target.
