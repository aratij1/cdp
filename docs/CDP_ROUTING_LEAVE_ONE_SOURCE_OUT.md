# Leave-One-Source-Out Routing Evaluation

The evaluator groups by `source_family`; it does not random-split pages. Each rotation reports top-level per-class recall, worst top-level recall, standard precision/recall, CMS and UB nomination precision/recall, CMS and UB verification recall, exact subtype accuracy, processing-route accuracy, false/CMS/UB standard authorization, standard-to-standard misroute, abstention, and P50/P95 latency.

Promotion is based on worst source. The evaluator exists, but `ROUTING_TAXONOMY_CORPUS_V1` has not met its 1,000–2,000 page, PHI-free, multi-source data gate; therefore no development metrics or candidate are claimed.

Safe standard fallback is reported separately: a truth CMS/UB page is correctly nominated, is not verified, and safely reaches `LAYOUT_STRUCTURED_EXTRACTOR`. This is an efficiency loss, not a routing safety failure. Any fixed route without matching `VERIFIED` family evidence is separately counted as unverified fixed authorization.
