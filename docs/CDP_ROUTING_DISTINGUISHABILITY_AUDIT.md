# Routing Distinguishability Audit

Status: **human review required; not yet passed**. Automated predictions are not substitutes for knowledgeable reviewers.

The 120 hard confusers must be independently reviewed at four disclosure levels: 224×224 thumbnail, full-resolution page, page plus OCR text, and page plus bundle context. Each record captures truth taxonomy, frozen visual prediction, deterministic prediction, confusion family, human distinguishability, semantic/structural context requirements, and the minimum sufficient disclosure level.

Expected high-risk pairs are UB04/custom institutional, CMS1500/custom professional, UB04/itemized bill, custom structured claim/EOB, invoice/itemized bill, and correspondence/clinical note. The latter distinctions are frequently semantic, document-context, or business-metadata decisions. If agreement requires OCR or bundle context, thumbnail-only routing is declared insufficient. No model training or threshold tuning may use this audit corpus.
