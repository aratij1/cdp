# Standard-Form Verification Design

CMS and UB use separate deterministic verifiers. Visual probability and title OCR are deliberately excluded from authorization. Each verifier needs at least three independent evidence classes, mandatory family-specific structure/spatial evidence, and no contradictions.

CMS evidence covers page geometry, patient/insured relationship, claim and diagnosis layout, professional service grid, provider/billing placement, high-value anchors, relative geometry, and optional registration. UB evidence covers institutional grid, type-of-bill and statement regions, payer/provider placement, revenue/service region, HCPCS-charge relationship, diagnosis region, repeated rows, anchors, geometry, and optional registration.

Only `VERIFIED` sets `eligible_for_fixed_extractor=true`. Missing evidence, `NOT_VERIFIED`, and `AMBIGUOUS` fail closed to structured layout or safe unknown. The standard extraction consumer repeats this check before processing an event.
