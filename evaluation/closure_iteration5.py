"""Frozen-perception blocker replay; references score outputs but never enter policy."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import replace
from importlib.metadata import version
from statistics import median

from PIL import Image

from evaluation.cdp2_comparison import legacy_and_graph, write
from evaluation.closure_iteration2 import INPUT, OBS, ROOT
from evaluation.closure_iteration3 import external_categories
from evaluation.closure_performance_gate import compare_runs
from packages.candidate_reconciliation import EvidenceReconciler
from packages.claim_intelligence.blockers import SourceCondition
from packages.claim_intelligence.discovery import NoncanonicalDiscovery
from packages.claim_intelligence.document import DocumentPage, Token, fingerprint
from packages.claim_intelligence.normalization import comparison_key, normalize
from packages.claim_intelligence.pipeline import CDP2ShadowPipeline

OUT = ROOT / "evaluation_results/closure_iteration5"
BASE_SHA = "5903107f91c2f512b18bb4f7c9e4e2433918f151"
GIT = r"C:\Program Files\Git\cmd\git.exe"


def scenarios(claims: list[dict]) -> list[dict]:
    categories = {
        "MEMBER_AUTHORITY_REQUIRED",
        "PROVIDER_AUTHORITY_REQUIRED",
        "PATIENT_IDENTITY_AUTHORITY_REQUIRED",
        "SOURCE_EVIDENCE_REQUIRED",
    }
    choices = {
        "CURRENT_EVIDENCE": set(),
        "MEMBER_AUTHORITY_AVAILABLE": {"MEMBER_AUTHORITY_REQUIRED"},
        "PROVIDER_AUTHORITY_AVAILABLE": {"PROVIDER_AUTHORITY_REQUIRED"},
        "MEMBER_PLUS_PROVIDER": {"MEMBER_AUTHORITY_REQUIRED", "PROVIDER_AUTHORITY_REQUIRED"},
        "IDENTITY_AUTHORITY_AVAILABLE": {"PATIENT_IDENTITY_AUTHORITY_REQUIRED"},
        "SOURCE_EVIDENCE_AVAILABLE": {"SOURCE_EVIDENCE_REQUIRED"},
        "ALL_EXTERNAL_EVIDENCE_AVAILABLE": categories,
    }
    result = []
    for name, available in choices.items():
        capable = sum(c["technical_distance"] == 0 for c in claims)
        possible = sum(
            c["technical_distance"] == 0 and not (set(c["external_categories"]) - available)
            for c in claims
        )
        result.append(
            {
                "scenario": name,
                "claims": len(claims),
                "technically_capable_claims": capable,
                "potentially_stp_capable_claims": possible,
                "potential_stp_ceiling": possible / len(claims),
                "potential_claim_hitl_floor": 1 - possible / len(claims),
                "assumption": "INDEPENDENT_RELEASE_QUALIFICATION_ALSO_PASSES",
                "achieved": False,
                "production_qualified_claims_observed": 0,
            }
        )
    return result


def freeze() -> dict:
    paths = [
        ROOT / "packages/claim_intelligence" / f
        for f in ("discovery.py", "spatial.py", "document.py", "normalization.py")
    ]
    for folder in ("packages/ocr", "packages/document_routing", "packages/field_localization"):
        paths.extend((ROOT / folder).rglob("*.py"))
    paths.extend((ROOT / "config/field_definitions").glob("*.yaml"))
    paths.append(INPUT)
    hashes = {}
    for path in sorted(set(paths)):
        relative = path.relative_to(ROOT).as_posix()
        original = subprocess.check_output([GIT, "show", BASE_SHA + ":" + relative], cwd=ROOT)
        current = path.read_bytes()
        if original.replace(b"\r\n", b"\n") != current.replace(b"\r\n", b"\n"):
            raise ValueError("FROZEN_PERCEPTION_CHANGED:" + relative)
        hashes[relative] = hashlib.sha256(current).hexdigest()
    result = {
        "PERCEPTION_BASELINE_SHA": BASE_SHA,
        "component_hashes": hashes,
        "candidate_engine_version": BASE_SHA,
        "registration_version": "FROZEN_EXISTING_CONFIG_NO_REGISTRATION_RUN",
        "ocr_version": version("rapidocr-onnxruntime"),
        "candidate_recall_at_5": 0.945,
        "critical_c3_recall_at_5": 1.0,
    }
    write(OUT, "perception_baseline.json", result)
    return result


def run() -> dict:
    freeze()
    baseline = json.loads(
        (ROOT / "evaluation_results/closure/iteration2/iteration4_anchor_final.json").read_text()
    )
    current_scores = {(r["claim"], r["field"]): r for r in baseline["governed_candidate"]["fields"]}
    active = {
        (r["claim_id"], r["field"]): r["remaining_technical"] for r in baseline["review_fields"]
    }
    audits = json.loads((OUT / "source_inspections.local.json").read_text())
    audit_map = {(r["claim_id_hash"], r["field_name"]): r for r in audits}
    if len(audit_map) != len(audits):
        raise ValueError("DUPLICATE_SOURCE_INSPECTION")
    rows = [json.loads(line) for line in INPUT.read_text().splitlines() if line]
    if len(rows) != 200 or len({(r["document_id"], r["field_name"]) for r in rows}) != 200:
        raise ValueError("FROZEN_DENOMINATOR_CHANGED")
    groups = defaultdict(list)
    for row in rows:
        groups[row["document_id"]].append(row)
    pipeline = CDP2ShadowPipeline()
    traces, field_records, step_rows = [], [], defaultdict(list)
    claims: list[dict] = []
    canonical_hashes, inspected = [], set()
    observation_hashes = []
    selected_before = sum(r["top1_correct"] for r in current_scores.values())
    selected_after = selected_before
    for doc, original_rows in sorted(groups.items()):
        claim_hash = fingerprint(doc)
        observation = json.loads((OBS / (doc + ".json")).read_text())
        source_hash = observation["page_sha256"]
        asset = (
            ROOT
            / "evaluation_data/phase8_8_generalization/SOURCE_B"
            / ("cms" if "CMS" in doc else "ub")
            / (doc + ".png")
        )
        if hashlib.sha256(asset.read_bytes()).hexdigest() != source_hash:
            raise ValueError("SOURCE_IMAGE_CHANGED")
        invocation = fingerprint(observation)
        observation_hashes.append(invocation)
        tokens = tuple(
            Token(
                t["text"],
                t["text"],
                tuple(t["bbox"]),
                t["confidence"],
                observation["ocr_model_version"],
                doc,
                fingerprint(t["bbox"]),
                invocation,
                source_hash,
                source_hash,
            )
            for t in observation["ocr_tokens"]
        )
        page = DocumentPage(
            doc,
            doc,
            "OTHER_CLAIM_FORM",
            "NOT_VERIFIED",
            observation["width"],
            observation["height"],
            observation["image_quality"]["quality_bucket"],
            tokens,
        )
        discoveries = NoncanonicalDiscovery().extract(page)
        inputs = [
            {k: v for k, v in r.items() if k not in {"truth", "exact", "cross_field_evidence"}}
            for r in original_rows
        ]
        legacy, graph, _ = legacy_and_graph(doc, inputs, EvidenceReconciler())
        canonical_hashes.append(legacy.canonical_sha256)
        original_legacy = legacy
        before_hash = fingerprint(legacy)
        prior_assessment = pipeline.compare(legacy, graph)
        expected_distance = sum(
            len(active.get((claim_hash, f.field_name), ())) for f in legacy.fields
        )
        if prior_assessment.cdp2_metrics["technical_unlock_distance"] != expected_distance:
            raise ValueError("FROZEN_BLOCKER_BASELINE_CHANGED")
        # Preserve the already-governed iteration-four ambiguity correction exactly.
        legacy = replace(
            legacy,
            fields=tuple(
                replace(f, technical_blockers=tuple(active.get((claim_hash, f.field_name), ())))
                for f in legacy.fields
            ),
        )
        immutable = fingerprint(legacy)
        conditions = []
        for f in legacy.fields:
            key = claim_hash, f.field_name
            if key not in audit_map:
                continue
            record = audit_map[key]
            with Image.open(asset) as image:
                box = record["pixel_region"]
                if box[2] > image.width or box[3] > image.height:
                    raise ValueError("SOURCE_INSPECTION_REGION_OUT_OF_BOUNDS")
                actual = hashlib.sha256(image.crop(box).tobytes()).hexdigest()
                if actual != record["crop_pixel_sha256"]:
                    raise ValueError("SOURCE_INSPECTION_PIXELS_CHANGED")
            if record["release_truth"] is not False:
                raise ValueError("PIXEL_REVIEW_IS_NOT_RELEASE_TRUTH")
            conditions.append(
                SourceCondition(
                    f.field_name,
                    record["source_sha256"],
                    record["kind"],
                    record["inspection_id"],
                    tuple(record["pixel_region"]),
                )
            )
            inspected.add(key)
        stage_results = {}
        for stage, use_conditions, recover, validate in (
            ("BASELINE", False, False, False),
            ("SOURCE_OWNER_CORRECTION", True, False, False),
            ("ATOMIC_RECOVERY", True, True, False),
            ("FIELD_VALIDATION", True, True, True),
        ):
            results = pipeline.assess_document_blockers(
                legacy,
                discoveries,
                source_sha256=source_hash,
                source_conditions=tuple(conditions) if use_conditions else (),
                enable_recovery=recover,
                enable_validation=validate,
            )
            stage_results[stage] = results
            step_rows[stage].append(
                {
                    "technical": sum(len(r.technical) for r in results),
                    "review_fields": sum(bool(r.technical) for r in results),
                }
            )
        final = {r.field_name: r for r in stage_results["FIELD_VALIDATION"]}
        assert immutable == fingerprint(legacy)
        old_shadow = pipeline.compare(legacy, graph)
        shadow_fields = {r.field_name: r for r in old_shadow.cdp2.fields}
        consistency = pipeline.engine.consistency.evaluate(graph)
        external_categories_claim = set()
        for row in original_rows:
            name = row["field_name"]
            field = next(f for f in legacy.fields if f.field_name == name)
            result = final[name]
            score = current_scores[claim_hash, name]
            # Reference access starts here, after policy has completed.
            reference = comparison_key(name, row["truth"])
            actual_correct = score["top1_correct"]
            if result.document_value is not None:
                actual_correct = comparison_key(name, result.document_value) == reference
                if score["top1_correct"] and not actual_correct:
                    raise ValueError("DOCUMENT_RECOVERY_SELECTED_VALUE_REGRESSION")
                selected_after += int(actual_correct) - int(score["top1_correct"])
            external = external_categories(
                name, [b for b in result.external if b != "SOURCE_REVIEW_REQUIRED"]
            )
            if "SOURCE_REVIEW_REQUIRED" in result.external:
                external.append("SOURCE_EVIDENCE_REQUIRED")
            external = sorted(set(external))
            external_categories_claim.update(external)
            record = {
                "claim_id_hash": claim_hash,
                "field_name": name,
                "critical": field.critical,
                "technical": list(result.technical),
                "external": external,
                "reclassified": list(result.reclassified),
                "resolved": list(result.resolved),
                "reasons": list(result.reasons),
                "engineering_document_recovered": result.document_value is not None,
                "source_condition": audit_map.get((claim_hash, name), {}).get("kind"),
            }
            field_records.append(record)
            for index, blocker in enumerate(field.technical_blockers):
                moved = blocker in result.reclassified
                resolved = blocker in result.resolved
                root = (
                    "SOURCE_EVIDENCE_MISCLASSIFIED_TECHNICAL"
                    if moved
                    else "VALIDATION_DEFECT"
                    if resolved and blocker == "CANDIDATE_AMBIGUITY"
                    else "ACCEPTANCE_POLICY_DEFECT"
                    if resolved
                    else "PERCEPTION_MISSING_CANDIDATE"
                    if score["reference_rank"] is None
                    else "REAL_TECHNICAL_CONFLICT"
                )
                field_consistency = [c for c in consistency if c.field_name == name]
                traces.append(
                    {
                        "blocker_id": fingerprint((claim_hash, name, blocker, index)),
                        "claim_id_hash": claim_hash,
                        "field_name": name,
                        "form_type": row["family"],
                        "criticality": row["criticality"],
                        "source_sha256": source_hash,
                        "source_state": record["source_condition"] or "SOURCE_BOUND_UNADJUDICATED",
                        "ocr_token_count": len(tokens),
                        "candidate_count": score["candidate_count"],
                        "candidate_generation_state": "OBSERVED"
                        if score["candidate_count"]
                        else "ABSENT",
                        "reference_in_candidates": score["reference_rank"] is not None,
                        "reference_authority": "FROZEN_REGRESSION_ENGINEERING_ONLY",
                        "release_reference_in_candidates": None,
                        "ranking_state": "ABSTAIN_OR_DIFFERENT"
                        if not score["top1_correct"]
                        else "SELECTED_EQUIVALENT",
                        "selected_candidate_state": "DOCUMENT_RECOVERED_SHADOW"
                        if result.document_value
                        else "LEGACY_SELECTED"
                        if field.canonical_value
                        else "ABSTAINED",
                        "normalization_state": "NOT_SELECTED"
                        if field.canonical_value is None
                        else "VALID"
                        if normalize(name, field.canonical_value)[1] is True
                        else "INVALID"
                        if normalize(name, field.canonical_value)[1] is False
                        else "UNKNOWN_NOT_FAILURE",
                        "validation_state": list(result.reasons)
                        or list(shadow_fields[name].decision.reasons),
                        "claim_consistency_state": dict(
                            Counter(c.verdict for c in field_consistency)
                        ),
                        "evidence_state": list(result.external),
                        "authority_state": graph.fields[name].authority_state.value,
                        "acceptance_state": "PRODUCTION_UNCHANGED_REVIEW_REQUIREMENTS_RETAINED",
                        "acceptance_reason_codes": list(shadow_fields[name].decision.reasons),
                        "current_blocker_reason": blocker,
                        "corrected_root_cause": root,
                        "technical_or_external": "EXTERNAL"
                        if moved
                        else "RESOLVED"
                        if resolved
                        else "TECHNICAL",
                        "claim_unlock_impact": 1
                        / max(1, sum(len(f.technical_blockers) for f in legacy.fields)),
                        "final_blocker": "SOURCE_REVIEW_REQUIRED"
                        if moved
                        else None
                        if resolved
                        else blocker,
                        "canonical_result_mutated": False,
                    }
                )
        final_distance = sum(len(f.technical) for f in final.values())
        claims.append(
            {
                "claim_id_hash": claim_hash,
                "technical_distance": final_distance,
                "technical_stp_capable": final_distance == 0,
                "external_categories": sorted(external_categories_claim),
                "claim_release_qualification_gap": True,
                "production_unlockable": False,
                "production_unlock_distance": final_distance + len(external_categories_claim) + 1,
            }
        )
        assert fingerprint(original_legacy) == before_hash
    if inspected != set(audit_map) or len(traces) != 71:
        raise ValueError("BLOCKER_OR_INSPECTION_DENOMINATOR_MISMATCH")
    if fingerprint(observation_hashes) != baseline["evidence_sha256"]:
        raise ValueError("FROZEN_OCR_EVIDENCE_CHANGED")
    if fingerprint(canonical_hashes) != baseline["canonical_outputs_sha256"]:
        raise ValueError("CANONICAL_PRODUCTION_OUTPUT_CHANGED")
    write(OUT, "blocker_traces.local.json", traces)
    write(OUT, "field_dispositions.local.json", field_records)
    write(OUT, "claim_unlock_matrix.local.json", claims)
    steps = {
        name: {
            "technical_blockers": sum(r["technical"] for r in entries),
            "technical_review_fields": sum(r["review_fields"] for r in entries),
            "technically_clean_claims": sum(r["technical"] == 0 for r in entries),
        }
        for name, entries in step_rows.items()
    }
    root_counts = dict(Counter(r["corrected_root_cause"] for r in traces))
    outcomes = dict(Counter(r["technical_or_external"] for r in traces))
    technical = sum(len(r["technical"]) for r in field_records)
    technical_fields = sum(bool(r["technical"]) for r in field_records)
    external_fields = sum(bool(r["external"]) for r in field_records)
    union = sum(bool(r["technical"] or r["external"]) for r in field_records)
    clean = sum(c["technical_stp_capable"] for c in claims)
    external_claims = {
        k: sum(k in c["external_categories"] for c in claims)
        for k in sorted({k for c in claims for k in c["external_categories"]})
    }
    external_claims["MULTIPLE_REQUIREMENT_TYPES"] = sum(
        len(c["external_categories"]) > 1 for c in claims
    )
    summary = {
        "iteration": 5,
        "status": "BLOCKER_COLLAPSE_ACHIEVED"
        if technical <= 20 and clean >= 16
        else "CONTINUE_BOUNDED_CLOSURE",
        "authority": "ENGINEERING_FROZEN_COHORT_WITH_SOURCE_PIXEL_INSPECTIONS_NOT_RELEASE_TRUTH",
        "perception_baseline_sha": BASE_SHA,
        "perception_changed": False,
        "fields": 200,
        "claims": 20,
        "starting_blockers": 71,
        "technical_blockers": technical,
        "technical_review_fields": technical_fields,
        "technically_clean_claims": clean,
        "technical_stp_capability_rate": clean / 20,
        "blocker_outcomes": outcomes,
        "root_cause_counts": root_counts,
        "logical_steps": steps,
        "governed_candidate_recall_at_5": baseline["governed_candidate"]["summary"]["recall"][
            "R@5"
        ],
        "critical_c3_recall_at_5": 1.0,
        "critical_c3_fields": 30,
        "exact_missing_candidates": 22,
        "governed_missing_candidates": 11,
        "selected_correct_before": selected_before,
        "selected_correct_after": selected_after,
        "technical_hitl_rate": technical_fields / 200,
        "evidence_hitl_rate": external_fields / 200,
        "total_observed_hitl_rate": union / 200,
        "distance_distribution": dict(Counter(str(c["technical_distance"]) for c in claims)),
        "external_claim_blockers": external_claims,
        "source_inspection_fields": len(audits),
        "source_inspection_kinds": dict(Counter(r["kind"] for r in audits)),
        "new_ocr_calls": 0,
        "llm_calls": 0,
        "paid_ai_cost_usd": 0,
        "infrastructure_cost_usd": None,
        "p95_ms": 5581.23319997685,
        "latency_scope": "PRIOR_ITERATION3_FRESH_PERCEPTION_OBSERVATION_NOT_NEW_OR_COMPLETE_PRODUCTION_QUALIFICATION",
        "canonical_outputs_changed": False,
        "production_authority": False,
        "technical_ceiling_proven": False,
        "release_metrics": {
            k: {"value": None, "status": "NOT_EVALUABLE"}
            for k in (
                "accuracy",
                "critical_accuracy",
                "accepted_precision",
                "critical_false_accepts",
                "field_hitl",
                "claim_hitl",
                "stp",
            )
        },
    }
    technical_categories = {
        category: len(
            {
                (t["claim_id_hash"], t["field_name"])
                for t in traces
                if t["technical_or_external"] == "TECHNICAL"
                and t["corrected_root_cause"] == category
            }
        )
        for category in root_counts
    }
    clean_requirements = {
        k: sum(c["technical_stp_capable"] and k in c["external_categories"] for c in claims)
        for k in external_claims
        if k != "MULTIPLE_REQUIREMENT_TYPES"
    }
    summary["clean_claim_external_requirements"] = clean_requirements
    summary["external_field_requirement_counts"] = dict(
        Counter(k for f in field_records for k in f["external"])
    )
    summary["technical_hitl_categories"] = {
        "candidate_generation": technical_categories.get("PERCEPTION_MISSING_CANDIDATE", 0),
        "ranking": 0,
        "normalization": 0,
        "validation": 0,
        "claim_consistency": 0,
        "other_software_policy": 0,
        "technical_association_conflict": technical_categories.get("REAL_TECHNICAL_CONFLICT", 0),
    }
    summary["source_conflict_review_fields"] = sum(
        r["kind"] == "MULTIPLE_PRINTED_VALUES" for r in audits
    )
    summary["business_policy_review_fields"] = 0
    summary["accuracy_gain_from_reclassification"] = False
    latency_root = ROOT / "evaluation_results/closure/iteration5"
    repetitions = [
        json.loads((latency_root / f"repeat_{i}.json").read_text())["experiments"][0]
        for i in range(1, 4)
    ]
    previous_runtime = json.loads(
        (ROOT / "evaluation_results/closure/iteration3/repeat_3.json").read_text()
    )["experiments"][0]
    if any(len(r["pages"]) != 12 or r["new_full_page_calls"] != 12 for r in repetitions):
        raise ValueError("LATENCY_REPETITIONS_INCOMPLETE")
    semantic_gates = [compare_runs(previous_runtime, r) for r in repetitions]
    if not all(g["identical_semantics"] for g in semantic_gates):
        raise ValueError("FRESH_RUNTIME_SEMANTIC_REGRESSION")
    latency = {
        "scope": "FRESH_PERCEPTION_NOT_COMPLETE_PRODUCTION_CLAIM_PATH",
        "runs": [r["latency"] for r in repetitions],
        "median_p95_ms": median(r["latency"]["P95"] for r in repetitions),
        "median_p50_ms": median(r["latency"]["P50"] for r in repetitions),
        "median_p99_ms": median(r["latency"]["P99"] for r in repetitions),
        "cold_model_load_ms": [r["model_load_ms"] for r in repetitions],
        "max_sampled_rss_bytes": max(
            p["memory_rss_bytes"] for r in repetitions for p in r["pages"]
        ),
        "prior_three_run_median_p95_ms": 5581.23319997685,
        "configuration_changed": False,
        "semantics_identical": True,
        "target_met": all(g["identical_semantics"] for g in semantic_gates)
        and median(r["latency"]["P95"] for r in repetitions) <= 5000,
        "variance_cause": "NOT_ISOLATED",
        "full_page_ocr_calls": 36,
    }
    summary["latency_qualification"] = latency
    summary["p95_ms"] = latency["median_p95_ms"]
    summary["latency_scope"] = latency["scope"]
    summary["new_ocr_calls"] = 36
    summary["blocker_replay_new_ocr_calls"] = 0
    summary["latency_qualification_new_ocr_calls"] = 36
    write(OUT, "latency_qualification.json", latency)
    write(
        OUT,
        "best_architecture.json",
        {
            "status": "FROZEN_FOR_ENGINEERING_BLOCKER_QUALIFICATION",
            "perception_baseline_sha": BASE_SHA,
            "blocker_assessment_version": "stage-aware-blockers-v1",
            "production_authority": False,
            "perception_changed": False,
            "release_qualification": "NOT_EVALUABLE",
            "latency_target_met": latency["target_met"],
        },
    )
    artifacts = {
        "blocker_funnel.json": {
            "starting": 71,
            "primary_causes": root_counts,
            "outcomes": outcomes,
        },
        "blocker_root_cause_summary.json": root_counts,
        "blocker_reclassification_summary.json": {
            "reclassified_blockers": outcomes.get("EXTERNAL", 0),
            "authority_reclassified": 0,
            "source_review_reclassified": outcomes.get("EXTERNAL", 0),
            "accuracy_gain_claimed": False,
        },
        "validation_blockers.json": {
            "corrected": sum(r["corrected_root_cause"] == "VALIDATION_DEFECT" for r in traces)
        },
        "acceptance_blockers.json": {
            "downstream_document_acquisition_corrected": sum(
                r["corrected_root_cause"] == "ACCEPTANCE_POLICY_DEFECT" for r in traces
            ),
            "production_acceptance_policy_changed": False,
        },
        "technical_hitl_v2.json": {
            "fields": 200,
            "technical_fields": technical_fields,
            "external_fields": external_fields,
            "total_observed_fields": union,
            "production_measured": False,
            "residual_primary_cause_field_counts": {
                k: len(
                    {
                        (r["claim_id_hash"], r["field_name"])
                        for r in traces
                        if r["technical_or_external"] == "TECHNICAL"
                        and r["corrected_root_cause"] == k
                    }
                )
                for k in root_counts
            },
        },
        "claim_unlock_matrix.json": {
            "claims": 20,
            "technical_stp_capable": clean,
            "distance_distribution": summary["distance_distribution"],
        },
        "external_claim_blockers.json": external_claims,
        "scenario_stp_ceilings.json": scenarios(claims),
        "retained_changes.json": steps,
        "rejected_changes.json": {
            "new_perception_or_latency_experiments": 0,
            "global_threshold_changes": 0,
        },
        "comparative_scorecard.json": summary,
    }
    for name, data in artifacts.items():
        write(OUT, name, data)
    write(ROOT / "docs/closure", "iteration5_summary.json", summary)
    freeze()  # The entire run must leave perception untouched.
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
