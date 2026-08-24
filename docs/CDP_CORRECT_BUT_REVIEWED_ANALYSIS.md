# CDP Correct-but-Reviewed Analysis

Of 600 field decisions, 52 are accepted and 548 are reviewed/escalated. The reviewed population decomposes without overlap as follows:

| Review outcome | Count | Share of reviewed |
| --- | ---: | ---: |
| Correct but reviewed | 482 | 87.96% |
| Wrong and reviewed | 29 | 5.29% |
| Missing and reviewed | 35 | 6.39% |
| True ambiguity | 2 | 0.36% |

The two true-ambiguity cases carry `CONFLICT_MARGIN_TOO_SMALL`; both are incorrect provider-name candidates. “Wrong and reviewed” excludes those two so the categories sum exactly to 548.

Correct-but-reviewed is primarily missing independent evidence, not extraction uncertainty. Frequent reasons include `MISSING_E2_INDEPENDENT_CONFIRMATION`, `MISSING_E4_DETERMINISTIC_VALIDATION`, and `MISSING_E6_CROSS_FIELD_CONFIRMATION`. Provider NPI and federal tax number are especially clear: all evaluated values are correct but all remain reviewed because the required independent/reference evidence is unavailable.

This is a legitimate evidence gap under the frozen semantics. It must not be relabeled as true ambiguity and must not be solved by lowering confidence or evidence thresholds. The result also explains the economics: field HITL is 91.33%, claim HITL is 100%, and claim STP is 0% even though raw field accuracy is 89.05%.
