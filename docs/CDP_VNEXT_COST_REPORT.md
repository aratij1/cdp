# CDP vNext Cost Qualification

Qualification date: 2026-08-21  
Status: **NOT TESTED**

The local performance harness prints an illustrative value of `$0.00585/page`, based on an assumed
field routing mix and old `REGIONAL_PADDLEOCR` labels. It is not metered consumption and must not be
used for budgeting or a vNext business case.

Production qualification requires metered CPU/memory time, actual review minutes, current contracted
Vertex/AWS prices, retry and error rates, storage/egress, and cost distributions by document family.
No live RapidOCR, Gemini, Textract, Docling, or human-review cost run was performed in this environment.
