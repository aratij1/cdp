"""Value-free route accounting from saved worker events, without reference inputs."""
from __future__ import annotations

from collections import Counter
from typing import Any

from packages.templates.cms1500_boxes import BOXES
from workers.standard_form_extraction.recovery_eligibility import assess_raw

STAGES = (
    "FORM_IDENTITY", "PAGE_REGISTRATION", "CANONICAL_ROUTE", "CANONICAL_CROP_EMPTY",
    "CANONICAL_CROP_SUSPICIOUS", "RECOVERY_CLEAN", "RECOVERY_UNRESOLVED",
    "FIELD_ASSEMBLY", "NORMALIZATION", "FINAL_OUTPUT", "FALLBACK_RUNTIME_NOT_IMPLEMENTED",
)


def diagnose(execution: dict[str, Any]) -> dict[str, Any]:
    pages = []
    recovery: Counter[str] = Counter()
    scan_counts: Counter[str] = Counter()
    for claim in execution["claims"]:
        claim_pages = []
        for page in claim["pages"]:
            number = page["page_number"]
            requests = []
            completed = []
            fallbacks = []
            for event in claim["events"]:
                payload = event["envelope"]["payload"]
                if payload.get("page_number") != number and number not in payload.get("page_numbers", []):
                    continue
                if event["topic"] == "extraction.standard.requested":
                    requests.append(payload)
                elif event["topic"] == "extraction.completed":
                    completed.append(payload)
                elif event["topic"] == "extraction.unstructured.requested":
                    fallbacks.append(payload)
            identity = any(p.get("form_identity", {}).get("status") == "VERIFIED" for p in requests)
            registration = any((p.get("registration_evidence") or {}).get("accepted") is True for p in completed)
            fields = [f for f in claim["fields"] if f["page_number"] == number]
            canonical = registration and any(
                (c.get("provenance") or {}).get("localization_method") == "REGISTERED_CMS1500_VALUE_BOX"
                for f in fields for c in f.get("candidates", [])
            )
            statuses = []
            for field in fields:
                attempts: dict[str, dict] = {}
                for candidate in field.get("candidates", []):
                    provenance = candidate.get("provenance") or {}
                    if provenance.get("localization_method") != "REGISTERED_CMS1500_VALUE_BOX":
                        continue
                    attempts.setdefault(provenance["localization_region_id"], {})[
                        provenance.get("preprocessing_version")] = candidate
                for pair in attempts.values():
                    primary = pair.get("CANONICAL_PRIMARY") or pair.get("BOUNDED_MULTILINE_PRIMARY")
                    alternate = pair.get("BOUNDED_VALUE_RECOVERY")
                    if not primary:
                        continue
                    suspicious = assess_raw(field["field_name"], BOXES[field["field_name"]][1], primary["raw_text"]).eligible
                    if not suspicious:
                        recovery["clean_primary"] += 1
                    elif alternate:
                        if not alternate["raw_text"].strip():
                            recovery["blank_recovery"] += 1
                        elif assess_raw(field["field_name"], BOXES[field["field_name"]][1], alternate["raw_text"]).eligible:
                            recovery["both_suspicious"] += 1
                        else:
                            recovery["clean_recovery_selected"] += 1
                    else:
                        recovery["suspicious_without_alternative"] += 1
                if "RECOVERY_UNRESOLVED" in field.get("validation_reasons", []):
                    statuses.append("RECOVERY_UNRESOLVED")
                elif not field["raw_value"].strip():
                    statuses.append("CANONICAL_CROP_EMPTY")
                elif field.get("normalized_value") is None:
                    statuses.append("NORMALIZATION")
            first = (
                "FORM_IDENTITY" if not identity else
                "PAGE_REGISTRATION" if not registration else
                "CANONICAL_ROUTE" if not canonical else
                "FIELD_ASSEMBLY" if not fields else
                next((s for s in STAGES if s in statuses), "FINAL_OUTPUT")
            )
            row = {"identity_verified": identity, "registration_accepted": registration,
                   "canonical_entered": canonical, "fallback_requested": bool(fallbacks),
                   "fallback_runtime_unavailable": bool(fallbacks), "first_failing_stage": first,
                   "fallback_reason_codes": sorted({r for p in fallbacks for r in p.get("reason_codes", [])})}
            claim_pages.append(row)
            pages.append(row)
        for key in ("identity_verified", "registration_accepted", "canonical_entered",
                    "fallback_requested", "fallback_runtime_unavailable"):
            scan_counts[key] += any(p[key] for p in claim_pages)
    return {"scope": "FRESH_12_ENGINEERING_ONLY", "candidate_sha": execution["candidate_commit_sha"],
            "scan_count": len(execution["claims"]), "page_count": len(pages),
            "routing": dict(scan_counts), "pages": pages,
            "first_failing_stage_counts": dict(Counter(p["first_failing_stage"] for p in pages)),
            "recovery": {k: recovery[k] for k in ("clean_primary", "clean_recovery_selected",
                         "both_suspicious", "blank_recovery", "suspicious_without_alternative")},
            "recovery_counter_scope": "canonical field slots including empty optional slots"}
