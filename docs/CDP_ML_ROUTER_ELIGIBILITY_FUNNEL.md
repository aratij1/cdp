# ML eligibility funnel

Calibration-derived thresholds plus deterministic corroboration produced:

- A-trained → B: CMS eligibility 20%, UB 100%, structured 22.22%, non-claim 0%.
- B-trained → A: CMS eligibility 62.5%, UB 80%, structured 14.29%, non-claim 83.33%.

Worst-source CMS/UB eligibility is 20%/80%, below the required 90%. CMS/UB false eligibility and dual eligibility were zero. Existing final scoring was unchanged, so no final-routing recovery occurred. Per the stop rule, further ML tuning is rejected; scoring/ranking and feature sufficiency are separate next bottlenecks.

