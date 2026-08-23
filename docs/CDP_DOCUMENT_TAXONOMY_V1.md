# Canonical Document Taxonomy V1

`DocumentTaxonomyV1` is business-semantic and versioned as `document-taxonomy-v1.0.0`. Top-level classes are CLAIM, CLAIM_SUPPORT, NON_CLAIM, and UNKNOWN. Claims divide into standard candidates (CMS1500/UB04) and non-standard professional, institutional, or other structured claims. Support and non-claim leaves follow the approved matrix.

`DocumentClassification` answers what the page is. It contains no extractor target. `BundleClassification` is separate so attachment pages retain their own page classifications. UNKNOWN is legitimate and safe. Exact support subtype is secondary when multiple classes share the same processing route.
