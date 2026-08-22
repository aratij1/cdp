# CDP Pre-V3 Development Gate

The V3 holdout must not be created until development-only routing, extraction,
and cost gates pass. No V1 or V2 holdout asset or label was used for tuning.

The independent routing development set improved from 36/40 UB-04 pages
(90% recall) to 40/40 (100% recall) while retaining 100% precision. The
identity-backed route requires an explicit form identity, a family-specific
anchor, a score of at least 0.55, and the existing 0.15 CMS/UB margin. The
generic standard threshold remains 0.60.

The standard extraction path now honors deterministic first/last-name template
postprocessors and coalesces only geometrically equivalent regional crops.
This reduces header-field OCR requests from 25 to 24 for CMS-1500 (4.00%) and
from 23 to 22 for UB-04 (4.35%) without using full-page OCR or lowering an
acceptance threshold. Runtime completion events include the logical, executed,
and coalesced request counts.

The development extraction gate remains 594/600 (99.00%) with zero false
accepts. Run `python evaluation/pre_v3_holdout_gate.py`; only
`READY_TO_CREATE_FRESH_V3_HOLDOUT` authorizes creating and freezing a new V3
holdout. The gate itself never creates or opens holdout data.
