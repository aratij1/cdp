# Visual Safety Development Report

Decision: **REJECT**.

`VISUAL_SAFETY_DEV_V1` contains 120 independent hard-confuser pages across all five route classes. It was not derived from frozen A/B/C/D. Both frozen visual models produced the same material result: VC-01 false-standard rate 53.33%; VC-02 through VC-05 reduced it only to 23.33%. At the best safety stage, CMS recall was 100%, UB 13.33%, UNKNOWN_STRUCTURED 80%, UNKNOWN_UNSTRUCTURED 100%, and NON_CLAIM 0%. Visual P95 was at most 21.71 ms and contradiction P95 below 0.05 ms.

The required false-standard ceiling is 0.5%, with CMS >=95%, UB >=98%, and the other families >=98%. No experiment passed. Frozen A/B/C/D were not rerun, no candidate was created, and production/default routing is unchanged.
