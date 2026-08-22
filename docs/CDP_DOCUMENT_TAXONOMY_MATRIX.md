# Document Taxonomy V1 Decision Matrix

All fixed-template routes require separate form verification. Ambiguity always resolves to `SAFE_UNKNOWN`; it never authorizes CMS/UB extraction.

| Subtype | Business definition / positive evidence | Negative evidence and common confusers | Processing route | Context need |
|---|---|---|---|---|
| CMS1500 | Standard professional claim; patient/insured blocks, diagnosis pointers, professional service grid | Not custom professional, EOB, or claim summary | CMS fixed template after verification | structural + semantic |
| UB04 | Standard institutional claim; form locators, revenue codes, institutional service grid | Not custom institutional, itemized hospital bill, invoice, or EOB table | UB fixed template after verification | structural + semantic |
| CUSTOM_PROFESSIONAL | Professional claim semantics without verified CMS structure | CMS1500 is the primary visual confuser | layout structured | semantic |
| CUSTOM_INSTITUTIONAL | Institutional claim semantics without verified UB structure | UB04 and hospital bills are confusers | layout structured | semantic |
| OTHER_STRUCTURED_CLAIM | Claim requesting adjudication with other structured layout | EOB is retrospective, not a submitted claim | layout structured | semantic/business metadata |
| EOB | Adjudication/payment explanation | Custom claim or itemized bill | layout structured | semantic |
| ITEMIZED_BILL | Services/items and charges supporting a claim | UB04 and medical invoice | layout structured | semantic |
| MEDICAL_INVOICE | Provider request for payment | Itemized bill; distinction need not precede extraction | layout structured | semantic/business metadata |
| LAB_REPORT | Diagnostic laboratory results | Claim vocabulary may appear incidentally | layout structured | semantic |
| CLINICAL_NOTE | Narrative clinical record | Correspondence | layout unstructured | semantic/document context |
| CORRESPONDENCE | Claim/provider/member communication | Clinical note | layout unstructured | semantic/document context |
| OTHER_ATTACHMENT | Supporting material outside named support subtypes | Non-claim administrative material | layout unstructured | document context |
| COVER_PAGE | Transmission/bundle cover | Correspondence | stop | document context |
| DOCUMENT_SEPARATOR | Boundary sheet or barcode separator | Near-blank page | stop | structural/document context |
| ADMINISTRATIVE | Workflow/admin form not a claim or support | Generic structured claim | stop | semantic/business metadata |
| BLANK_OR_NEAR_BLANK | No meaningful content | Faded separator or damaged claim | stop | visual/full resolution |
| OTHER_NON_CLAIM | Other content outside claims workflow | Correspondence/support | stop | semantic |
| UNKNOWN | Evidence insufficient or inherently ambiguous | none—this is a safe outcome | safe unknown | any |
