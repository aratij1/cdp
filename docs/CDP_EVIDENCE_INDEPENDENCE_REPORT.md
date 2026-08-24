# CDP Evidence Independence Report

Phase 8.8C replaces engine-name independence with explicit observation-lineage
classification. `EvidenceDependencyService` evaluates page representation, observation,
crop identity and overlap, localization, preprocessing, engine/model family,
registration transform, and parent-candidate lineage.

Relations are `INDEPENDENT`, `PARTIALLY_INDEPENDENT`, `CORRELATED`, and `UNKNOWN`.
Different OCR families are only one signal. A shared crop plus shared localization or
observation is correlated. Missing required lineage is unknown. Neither state qualifies
as policy E2 independent confirmation.

The fresh extraction plus unchanged Phase 8.8A A/B/C replay produced:

| Relation | Agreements | False agreements |
|---|---:|---:|
| Independent | 0 | 0 |
| Partially independent | 0 | 0 |
| Correlated | 0 | 0 |
| Unknown | 243 | not promoted |

The 243 unknown results are expected: the frozen replay records predate canonical
`EvidenceProvenance` and do not contain enough crop/representation lineage to infer
independence safely. New runtime candidates persist this lineage. Historical records
remain readable but never default to independent.

Because PaddleOCR was unavailable in the execution environment, frozen Paddle
observations were reused only when the freshly extracted crop SHA-256 matched exactly:
90 Source A, 90 Source B, and 89 Source C observations. One changed Source C crop
abstained. Exact pixel reuse is still `UNKNOWN`, never independent.

E2 remains one taxonomy class for compatibility, with structured types:
`OCR_AGREEMENT_CORRELATED`, `OCR_AGREEMENT_PARTIALLY_INDEPENDENT`,
`OCR_AGREEMENT_INDEPENDENT`, and `OCR_AGREEMENT_UNKNOWN_DEPENDENCY`.
Only the independent subtype is policy-eligible.
