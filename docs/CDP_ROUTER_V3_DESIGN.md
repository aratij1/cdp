# CDP Router V3 Design

Router V3 has two stages. Eligibility first accepts either identity plus a
specific supporting anchor and structure, or multiple high-discrimination
anchors plus correct normalized geometry, a strong form fingerprint and a
clear CMS/UB margin. Discrimination then ranks eligible standards alongside
structured, unstructured and non-claim routes.

Anchor classes carry weights 3.0, 2.0 and 0.5. Short labels never fuzzy-match.
Long and medium labels use length-aware bounds, with a small routing-only OCR
substitution map. Relative zones preserve resolution independence. Persisted
evidence includes exact/normalized/fuzzy counts, weighted coverage, boxes,
zone scores, structure, combinations, eligibility, scores, margin, reasons and
router version. The global 0.60 standard threshold was not reduced.
