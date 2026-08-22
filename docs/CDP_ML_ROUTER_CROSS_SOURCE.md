# ML router cross-source comparison

| Model | Train → test | Accuracy | CMS recall | UB recall | Structured recall | Non-claim recall | P95 inference |
|---|---|---:|---:|---:|---:|---:|---:|
| LightGBM | A → B | 74.19% | 80% | 100% | 100% | 0% | 0.34 ms |
| LightGBM | B → A | 73.08% | 100% | 100% | 14.29% | 83.33% | 0.33 ms |
| XGBoost | A → B | 87.10% | 100% | 100% | 55.56% | 100% | 4.44 ms |
| XGBoost | B → A | 53.85% | 100% | 100% | 0% | 16.67% | 4.51 ms |

XGBoost has a severe source-direction collapse. LightGBM is faster and more stable, but also fails non-claim/structured generalization. Decision: LightGBM is the diagnostic winner; no model is promotable.

