# ML router feature importance

Across both LightGBM directions, the leading features were UB structure, UB service-table score, structured score, OCR token/character counts, CMS structure, grid density, and horizontal/vertical line density. This explains UB's deterministic collapse: useful institutional evidence exists but rigid conjunctions and raw score scaling do not use it effectively.

No raw OCR text or identifiers are features. SHAP was not promoted because the development sample is insufficient and the development gate already failed; compact inference explanations use governed global importance until a larger independent corpus exists.

