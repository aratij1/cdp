# Routing Taxonomy to Processing Matrix

| Taxonomy condition | Verification | Processing route |
|---|---|---|
| CMS1500 candidate | VERIFIED CMS | CMS_STANDARD_EXTRACTOR |
| UB04 candidate | VERIFIED UB | UB_STANDARD_EXTRACTOR |
| Any standard candidate | NOT_VERIFIED or AMBIGUOUS; structured | LAYOUT_STRUCTURED_EXTRACTOR |
| Custom/other structured claim | not applicable | LAYOUT_STRUCTURED_EXTRACTOR |
| EOB, itemized bill, invoice, lab/structured support | not applicable | LAYOUT_STRUCTURED_EXTRACTOR |
| Clinical note/correspondence/unstructured support | not applicable | UNSTRUCTURED_EXTRACTOR |
| Non-claim | not applicable | STOP_NON_CLAIM |
| Unsafe uncertainty | not applicable | SAFE_UNKNOWN |

Nomination never appears in the final mapping without form verification.
