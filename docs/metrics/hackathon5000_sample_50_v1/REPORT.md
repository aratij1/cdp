# Hackathon-5000 sample-50 PRODUCT report

**Corpus:** [Hackathon - 5000 Claims.zip](https://drive.google.com/file/d/1ohv3muiEChPU6pqR0sj7ansqUYq7odIY) (`DEVELOPMENT_DATASET_HACKATHON_5000_V1`)  
**Selection:** nested stratified 50 from sample_1000, **excluding sample_10** — A34 / B9 / C4 / D3 — seed **20260925**  
**Profile:** **PRODUCT** (`run_manifest.json`) — gpt-4o crop + Azure DI charge + TrOCR DOB + conflict agent ON  
**Ledger:** `evaluation_results/hackathon5000_sample_50_v1/`  
**Gate artifact:** `product_gate.json`

## Product gate

| Metric | Value | Target | Status |
|---|---|---|---|
| Claim-page STP | **83.33%** (35/42) | ≥ 97% | **FAIL** |
| Accepted precision (GOLD) | FA=0 (GT missing; `--allow-incomplete-gt`) | 1.0 / FA=0 | SCORED |
| HITL / REG | 7 / 8 | REG excluded from STP denom | |
| Run profile | PRODUCT | require_product_profile | OK |
| Gate | **FAIL** | STP bar | |

Reasons: `RUN_PROFILE_OK:PRODUCT`, `CLAIM_PAGE_STP_BELOW_TARGET:0.8333<0.97`, `GT_MISSING_ALLOWED`.

Gap to 97%: need **+6** more claim-page AUTO (41/42) without FA.

Residual buckets (gate): `INK_ABSENT` 5 · `POLICY_HOLD` 2.

## Disposition

| Disposition | Count | Rate |
|---|---|---|
| TRUE_STP | 35 | 70% of all / **83.3% of claim pages** |
| HITL | 7 | 14% of all / 16.7% of claim pages |
| REGISTRATION_FAILED | 8 | 16% |

## Remaining HITL (claim pages)

| Claim | Critical blockers |
|---|---|
| `Group A/M0471JEH.045` | `patient_dob` |
| `Group A/M0472JB9.033` | `insured_id_number`, `patient_dob` |
| `Group A/M0473JAI.026` | `patient_dob` |
| `Group A/M0473JEP.033` | `patient_dob` |
| `Group A/M0477JJB.020` | `patient_dob` |
| `Group A/M047AJCY.030` | `insured_id_number`, `patient_dob`, `total_charge` |
| `Group D/M0472JDV.002` | `total_charge` |

DOB dominates (6/7 HITL). Charge-only residual on D `M0472JDV.002`.

## Latency

| | |
|---|---|
| Mean latency | **40.0 s/doc** |
| n | 50 |

## Vs sample-10 PRODUCT (same profile)

| Sample | Claim-page STP | HITL | REG |
|---|---|---|---|
| 10 (overlap-free prior) | 100% (7/7) | 0 | 3 |
| **50** | **83.3% (35/42)** | **7** | **8** |

n=10 was luckily clean on DOB; sample-50 surfaces handwriting DOB fail-closed volume.

## Reproduce

```bash
python3 -u scripts/run_hackathon5000_sample_50.py --product --fresh
python3 -u scripts/check_similar_sample_product_gate.py \
  --ledger-a evaluation_results/hackathon5000_sample_50_v1 \
  --allow-incomplete-gt \
  --write docs/metrics/hackathon5000_sample_50_v1/product_gate.json
```
