# CDP Phase 8.8C Generalization

Decision: **NEEDS_MORE_DATA**. The safety gates pass, but coverage and raw-accuracy
recovery gates do not. The locked external holdout was not opened.

| Metric | Phase 8.8A baseline | Phase 8.8C unchanged replay | Gate |
|---|---:|---:|---:|
| Worst critical accuracy | 86.61% | 86.61% | >=95% |
| Worst accepted precision | 94.44% | 100.00% | >=99.5% |
| Critical false accepts | 2 | 0 | 0 |
| Worst-source STP | 0.00% | 0.00% | >=30% |
| Average STP | 2.38% | 0.00% | >=40% |
| Worst field HITL | 22.86% | 90.71% | <=15% |
| Cloud calls / cost | 0 / $0 | 0 / $0 | 0 / $0 |

Source A/B/C accepted precision is 100%. Field HITL is 90.71%, 90.00%, and
90.71%, respectively; claim STP is 0% on every source. Fresh P95 latency is
15.64s, 14.35s, and 16.71s. Average fully loaded cost is $0.38429/page
(worst $0.38512/page), driven by modeled HITL; cloud cost remains $0.

Unchanged validation raw accuracy is 79.29% overall: CMS 80.95%, UB 77.25%, and
critical fields 88.10% overall (worst source 86.61%). Expected-value-in-region is
25.24%, localization correctness is 24.76%, and OCR accuracy given a correct region
is 53.77%. UB row detection recall remains 100%; worst exact-row accuracy is 57.14%
and worst column-cell accuracy is 75.40%.

The dominant remaining defect is source-sensitive localization plus absence of
provenance in the frozen secondary-candidate records. The next evidence capture must
run all local candidate engines through the new provenance path so dependency-aware
E2 can be measured; it must not be an easier or value-tuned dataset.
