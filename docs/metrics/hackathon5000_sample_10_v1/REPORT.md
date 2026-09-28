# Hackathon-5000 sample-10 PRODUCT report

**Corpus:** [Hackathon - 5000 Claims.zip](https://drive.google.com/file/d/1ohv3muiEChPU6pqR0sj7ansqUYq7odIY) (`DEVELOPMENT_DATASET_HACKATHON_5000_V1`)  
**Selection:** nested stratified 10 from sample_1000 (A6 / B2 / C1 / D1) — seed **20260925** — `selected_documents.txt`  
**Profile:** **PRODUCT** (`run_manifest.json`) — gpt-4o crop + Azure DI charge + TrOCR DOB + conflict agent ON  
**Ledger:** `evaluation_results/hackathon5000_sample_10_v1/`  
**Prior FAST archive:** `evaluation_results/hackathon5000_sample_10_v1_fast/` (not gate-eligible)

## Product gate (claim-page)

| Metric | Value | Target | Status |
|---|---|---|---|
| Claim-page STP | **100%** (7/7) | ≥ 97% | **PASS** (n=10; noisy) |
| Field HITL | **0** | FA=0 prefer | OK |
| HITL / REG | 0 / 3 | REG excluded from STP denom | |
| Run profile | PRODUCT | require_product_profile | OK |

## Disposition

| Disposition | Count | Rate |
|---|---|---|
| TRUE_STP | 7 | 70% of all / **100% of claim pages** |
| HITL | 0 | 0% |
| REGISTRATION_FAILED | 3 | 30% |

## Why overall STP looked “dipped”

1. **FAST (pre-keys)** on the same 10: claim-page STP **2/7 = 40%** (5 HITL) — cloud residuals OFF. That was the real dip.
2. **PRODUCT (keys restored)** recovered to **7/7 = 100%** claim-page STP with **0 HITL**.
3. **3 REG** are mailroom/separator pages (not claim ink) — excluded from claim-page STP by design:
   - `Group B/M0473JFJ.005` — `DOCUMENT_SEPARATOR` (`MAILROOM_OR_FAX_NO_CLAIM_INK`)
   - `Group C/M046UJGA.001` — `UNIQUE_ID_COVER` separator
   - `Group D/M047KJG4.001` — `FAX_PATCH` / unknown page
4. **n=10** over-weights B/C/D (40% of sample vs ~32% in the 1000). REG rate looks worse than sample-200 (19%) but claim-page STP is the gate metric.

## FAST vs PRODUCT (same docs)

| Profile | Claim-page STP | HITL | REG |
|---|---|---|---|
| FAST (archived) | 2/7 (40%) | 5 | 3 |
| PRODUCT | **7/7 (100%)** | **0** | 3 |

## Reproduce

```bash
python3 -u scripts/run_hackathon5000_sample_10.py --product --fresh
```
