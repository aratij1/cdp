# ML router latency and size

LightGBM P95 inference was 0.33–0.34 ms; XGBoost was 4.44–4.51 ms. All artifacts were 0.17–0.21 MB, CPU-only and single-thread configured. Python-tracked inference memory remained below 121 KB in these runs. Both meet the isolated inference target; LightGBM is materially cheaper.

No total routing benchmark or 1/2/4-thread scalability promotion run was performed because the eligibility development gate failed. Runtime/default routing never loaded a model.

