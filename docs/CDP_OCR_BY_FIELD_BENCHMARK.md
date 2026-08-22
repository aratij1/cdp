# CDP OCR by Field Benchmark

> Synthetic correct-crop benchmark; not production accuracy.

| Field | Engine | Evaluated | Exact | Accuracy | CER | Mean latency | OCR accuracy given correct crop |
|---|---|---:|---:|---:|---:|---:|---:|
| `insured_id_number` | paddleocr | 60 | 59 | 98.33% | 0.17% | 361.5 ms | 98.33% |
| `insured_id_number` | rapidocr | 60 | 60 | 100.00% | 0.00% | 1886.6 ms | 100.00% |
| `insured_id_number` | tesseract | 60 | 2 | 3.33% | 10.00% | 604.7 ms | 3.33% |
