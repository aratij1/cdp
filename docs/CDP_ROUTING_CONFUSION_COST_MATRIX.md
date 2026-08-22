# Routing Confusion Cost Matrix

| Error | Risk score | Consequence |
|---|---:|---|
| Non-standard document authorized for CMS/UB fixed extraction | 100 | unsafe field interpretation |
| CMS authorized as UB or UB authorized as CMS | 80 | wrong fixed schema |
| Structured routed as unstructured, or reverse | 40 | accuracy/cost degradation |
| EOB vs invoice/itemized bill with same structured route | 5 | subtype error without processing error |
| Correct subtype and processing route | 0 | none |

Evaluation reports exact subtype accuracy separately from `PROCESSING_ROUTE_ACCURACY`, `FALSE_STANDARD_AUTHORIZATION_RATE`, abstention, accuracy among non-abstained, and mean `ROUTING_RISK_SCORE`.
