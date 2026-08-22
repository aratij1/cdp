# CDP OCR by Field Benchmark

> Synthetic correct-crop benchmark; not production accuracy.

| Field | Engine | Evaluated | Exact | Accuracy | CER | Mean latency | OCR accuracy given correct crop |
|---|---|---:|---:|---:|---:|---:|---:|
| `federal_tax_no` | paddleocr | 60 | 45 | 75.00% | 2.78% | 526.7 ms | 75.00% |
| `patient_dob` | paddleocr | 120 | 105 | 87.50% | 10.94% | 215.6 ms | 87.50% |
| `patient_name` | paddleocr | 120 | 102 | 85.00% | 8.39% | 931.2 ms | 85.00% |
| `principal_diagnosis` | paddleocr | 60 | 45 | 75.00% | 90.00% | 490.2 ms | 75.00% |
| `provider_npi` | paddleocr | 60 | 60 | 100.00% | 0.00% | 236.2 ms | 100.00% |
| `total_charge` | paddleocr | 60 | 59 | 98.33% | 0.33% | 272.0 ms | 98.33% |
| `type_of_bill` | paddleocr | 60 | 45 | 75.00% | 25.00% | 446.3 ms | 75.00% |
