# CDP vNext Load and Recovery Qualification

Qualification date: 2026-08-22  
Status: **LOCAL COMPONENT PASS; SYSTEM NOT TESTED**

The concurrent local OCR workload executed 240 synthetic field crops twice. At concurrency 1,
Tesseract sustained 5.31 fields/second with 219.38 ms P95 latency. At concurrency 4, it sustained
11.33 fields/second with 434.56 ms P95 latency. Both profiles completed with 0 execution errors.
The concurrency-4 profile passes the local component target derived from 50,000 pages/day and five
OCR-routed fields/page (2.9 fields/second required).

On the local real-file fixture (30 TIFF files, 67 pages), the isolated preparation stage measured
2.15 pages/second with 572.4 ms p95 latency; TIFF decode measured 89.85 pages/second and grid-signature
calculation measured 31.04 pages/second. The focused performance suite passed 3/3 tests.

This is not a full pipeline load test: the newest profile includes local Tesseract OCR but excludes
reconciliation, persistence, Kafka, external AI, and human review. Although 50,000 pages/day averages only 0.579 pages/second, the result does not prove
burst capacity, service-level latency, or sustainable throughput. Kubernetes/KEDA burst and soak,
backpressure, pod/node loss, dependency failure, backup restore, rollback, RTO, and RPO drills remain
`NOT TESTED` because no cluster or cloud environment was available.
