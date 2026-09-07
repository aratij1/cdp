# Track B qualification

Track A remains frozen at `2a310ed51720b854cca99d361940eb929027e529`.

Read [INPUT_CONTRACT.md](INPUT_CONTRACT.md) for the exact owner, reviewer, and deployment input fields. The existing 150-page membership CSV is the only owner-editable membership file; the controller now ingests completed approvals automatically.

The live aggregate report is [CDP_TRACK_B_FINAL_QUALIFICATION.md](CDP_TRACK_B_FINAL_QUALIFICATION.md), with machine-readable results in `final_qualification.json`. Current hardening verification is recorded in `hardening_validation.json`; [HARDENING.md](HARDENING.md) describes the authority and recovery changes.

The existing controller and review UI remain authoritative. Missing external approvals, independent source reviews, deployment controls/access, and pricing cannot become measured qualification results.
