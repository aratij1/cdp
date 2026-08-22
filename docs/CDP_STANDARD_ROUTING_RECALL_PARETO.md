# CDP Standard Routing Recall Pareto

The first ROUTING_DEV_V3 run safely rejected promotion: CMS recall 0%, UB
recall 75%, zero false standard routes, P95 450 ms. The dominant class was
`PARTIAL_PHRASE / GEOMETRY_NOT_USED`: Tesseract returned label words as
separate geometry records, while weighted evidence matched one record at a
time. Flattened diagnostics could see the phrases but canonical evidence could
not score them.

Bounded ordered-token aggregation now joins at most five adjacent OCR records,
rejects windows spanning more than 120 pixels vertically, and retains union
geometry. The second run has no standard false negatives: CMS 60/60 and UB
60/60. The machine-readable per-document evidence and any future misses are in
`evaluation_results/ROUTING_DEV_V3/benchmark.json`.
