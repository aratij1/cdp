# CDP Phase 8.2 Throughput

Each run used all 100 unique pages, uncached OCR results, and warm process-long-lived models.

- 1 worker(s): 5.64 pages/min, efficiency 100.00%, P95 15.66s, peak 0.93 GiB
- 2 worker(s): 5.62 pages/min, efficiency 49.79%, P95 30.29s, peak 1.39 GiB
- 4 worker(s): 4.84 pages/min, efficiency 21.43%, P95 74.25s, peak 1.92 GiB
- 8 worker(s): 4.39 pages/min, efficiency 9.72%, P95 168.35s, peak 2.70 GiB

Same-host 15K target: FAIL; same-host 50K target: FAIL. Horizontally isolated worker design: 2 nodes for 15K/day and 7 nodes for 50K/day before burst headroom; both fleet design targets pass by measured sizing.
