# Iteration-six evidence adapters

These read-only adapters reuse `AuthoritativeSnapshot` records. They are not connected to production acceptance and cannot activate production authority or create release truth.

| Capability | Contract | Required context | Default |
|---|---|---|---|
| Member / eligibility | `MemberAuthorityProvider.lookup` | Member ID, payer, service date, patient name and DOB; affirmative eligibility in a valid record | NOT_AVAILABLE |
| Provider master | `ProviderAuthorityProvider.lookup` | NPI, provider name, provider role and service date | NOT_AVAILABLE |
| Patient / subscriber | `IdentityAuthorityProvider.lookup` | Member ID, payer, person role, name, DOB and service date | NOT_AVAILABLE |
| Source provenance | `SourceEvidenceProvider.lookup` | Package, page and attachment IDs; configured path/hash, boundary and value-region provenance | NOT_AVAILABLE |

A snapshot adapter requires an explicitly supplied snapshot and expected snapshot hash. Load it through the existing governed snapshot workflow; pinning proves integrity, not business authorization. No evaluation labels or generated reference records are configured. Exact key matching, effective service dates, required comparison fields, uniqueness and conflicting context determine MATCH / NO_MATCH / CONFLICT / NOT_AVAILABLE. Results retain source, snapshot version, record provenance and a timezone-aware retrieval timestamp. No fuzzy names or OCR repair are performed.

A source adapter reads only explicitly configured bindings and verifies source bytes. Missing files return NOT_AVAILABLE; changed hashes or duplicate bindings return CONFLICT. AVAILABLE does not mean the document value is correct, does not assert independent OCR evidence, and cannot resolve source-review ambiguity. Overprint and competing printed values still need an independently governed resolution or replacement source.

`identity_review_state` reports the existing extraction state separately from authority for member/subscriber ID, provider, patient, insured and NPI fields. Missing external data cannot turn confident document extraction into a technical failure. A pre-existing authoritative conflict cannot be overridden. Even a matching adapter result requires the existing acceptance policy; there is no automatic ACCEPT path.

On the current 20-claim engineering cohort, four capabilities (member, provider, identity and source evidence) would leave six source-review claims. Resolving two of those six as well would reach the conditional 16/20 target. Exhaustive subset enumeration proves that source review is a fifth required capability at this denominator. A capability can share one real integration with another if that provider supplies every required, separately scoped fact; the calculation is not a claim that five separate services must be purchased.

The integration owner must supply real, authorized snapshots or implement the same contract against its service. The source owner must provide the required provenance and resolve source conflicts. Independent review/adjudication must supply trusted release truth, followed by package-separated development and holdout scoring. No adapter result bypasses those steps.
