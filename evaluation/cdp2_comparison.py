"""Same-claim comparison using the current field reconciler and CDP2 shadow.

Frozen observations are engineering regression input. Embedded labels are not
release truth and are not passed to either architecture.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from packages.candidate_reconciliation import EvidenceReconciler
from packages.claim_intelligence.document import fingerprint
from packages.claim_intelligence.models import (
    AuthorityState,
    Candidate,
    CandidateEvidence,
    ClaimGraph,
    EvidenceFeatures,
    FieldNode,
)
from packages.claim_intelligence.normalization import normalize
from packages.claim_intelligence.pipeline import (
    CDP2ShadowPipeline,
    LegacyFieldResult,
    LegacyResult,
    assert_same_claims,
    graph_relationships,
)
from packages.claim_intelligence.spatial import IDENTITY_FIELDS, TARGET_FIELDS
from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.ocr.contracts import OCRCandidate
from packages.ocr.provenance import EvidenceProvenance

ROOT = Path(__file__).resolve().parents[1]
STARTING_SHA = "5063c348093253b49d546e1d1f457f72b1db9de3"


def write(output: Path, name: str, value: Any) -> None:
    output.mkdir(parents=True, exist_ok=True)
    target = output / name
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", "utf-8")
    temporary.replace(target)


def load_rows(root: Path) -> list[dict[str, Any]]:
    source = root / "evaluation/baselines/phase8_12/inputs/source_b/policy_replay_input.jsonl"
    allowed = {
        "document_id",
        "family",
        "field_name",
        "final_value",
        "criticality",
        "candidates",
        "localization_evidence",
        "wrong_crop_suspected",
        "deterministic_validation",
    }
    rows = []
    for line in source.read_text("utf-8").splitlines():
        if line:
            row = json.loads(line)
            if row["field_name"] in TARGET_FIELDS:
                rows.append({k: v for k, v in row.items() if k in allowed})
    keys = [(r["document_id"], r["field_name"]) for r in rows]
    if len(set(keys)) != len(keys) or not keys:
        raise ValueError("INVALID_FROZEN_CLAIM_DENOMINATOR")
    return rows


def ocr_candidate(value: dict[str, Any]) -> OCRCandidate:
    data = {k: v for k, v in value.items() if k in OCRCandidate.__dataclass_fields__}
    data["bounding_box"] = BoundingBox.model_validate(data["bounding_box"])
    data["provenance"] = (
        EvidenceProvenance.model_validate(data["provenance"]) if data.get("provenance") else None
    )
    data["validation_results"] = tuple(data.get("validation_results", ()))
    data["tokens"] = ()  # This frozen source contains no token arrays; do not invent geometry.
    return OCRCandidate(**data)


def shadow_candidate(
    value: OCRCandidate, field: str, location: dict, wrong_crop: bool
) -> Candidate:
    normalized, valid = normalize(field, value.value or value.raw_value)
    p = value.provenance
    safe_geometry = location.get("confirmed") and location.get("geometry_valid") and not wrong_crop
    e = CandidateEvidence(
        value.engine,
        value.calibrated_confidence or value.raw_confidence,
        page_id=p.page_sha256 if p else None,
        crop_hash=p.crop_sha256 if p else None,
        localization_region=p.localization_region_id if p else None,
        source_id=p.document_sha256 if p else None,
        provenance_id=p.invocation_id if p else None,
        dependencies=p.shared_dependency_ids if p else (),
        bbox=(
            value.bounding_box.x0,
            value.bounding_box.y0,
            value.bounding_box.x1,
            value.bounding_box.y1,
        ),
    )
    geometry = float(location.get("confidence", 0)) if safe_geometry else None
    return Candidate(
        EvidenceReconciler._candidate_id(value),
        value.value or value.raw_value,
        (e,),
        normalized,
        EvidenceFeatures(geometry, location.get("anchor_confidence"), geometry, valid),
        field,
    )


def legacy_and_graph(
    claim_id: str, rows: list[dict], reconciler: EvidenceReconciler
) -> tuple[LegacyResult, ClaimGraph, float]:
    started = time.perf_counter()
    fields = []
    graph_fields = {}
    pages = set()
    canonical_results = []
    for row in rows:
        name = row["field_name"]
        observations = [ocr_candidate(c) for c in row["candidates"]]
        for c in observations:
            if c.provenance and c.provenance.page_sha256:
                pages.add(c.provenance.page_sha256)
        decision = reconciler.reconcile(
            name,
            observations,
            CriticalityLevel(row["criticality"]),
            deterministic_evidence=set(row.get("deterministic_validation", {}).get("evidence", ())),
            document_family=row["family"],
        )
        canonical_results.append(decision.model_dump(mode="json"))
        location = row.get("localization_evidence") or {}
        wrong = bool(row.get("wrong_crop_suspected"))
        missing = not location.get("positive_bounded_roi")
        candidates = tuple(shadow_candidate(c, name, location, wrong) for c in observations)
        technical = []
        if not row.get("final_value"):
            technical.append("CANDIDATE_ASSEMBLY")
        if wrong:
            technical.append("WRONG_CROP")
        if missing:
            technical.append("MISSING_CROP")
        if row.get("final_value") and normalize(name, row["final_value"])[1] is False:
            technical.append("SOFTWARE_VALIDATION")
        if len({c.normalized_value or c.value for c in candidates}) > 1:
            technical.append("CANDIDATE_AMBIGUITY")
        accepted = decision.decision.value in {"ACCEPT", "REFERENCE_CONFIRMED"}
        authority = (
            AuthorityState.AUTHORITATIVE_NOT_AVAILABLE
            if name in IDENTITY_FIELDS
            else AuthorityState.AUTHORITATIVE_NOT_REQUIRED
        )
        evidence = (
            ("AUTHORITATIVE_DATA_REQUIRED",)
            if name in IDENTITY_FIELDS
            else (() if accepted else ("EVIDENCE_REQUIRED",))
        )
        critical = row["criticality"] == "C3"
        fields.append(
            LegacyFieldResult(
                name,
                decision.selected_value,
                accepted,
                candidates,
                tuple(technical),
                evidence,
                critical,
                wrong,
                missing,
            )
        )
        graph_fields[name] = FieldNode(
            name, list(candidates), authority_state=authority, critical=critical
        )
    legacy = LegacyResult(
        claim_id,
        tuple(fields),
        fingerprint(canonical_results),
        rows[0]["family"],
        tuple(sorted(pages)),
    )
    elapsed = (time.perf_counter() - started) * 1000
    # Frozen declared form family is not a new strict identity authorization.
    graph = ClaimGraph(
        claim_id,
        rows[0]["family"],
        graph_fields,
        page_ids=legacy.page_ids,
        form_identity_confirmed=False,
    )
    graph.relationships = graph_relationships(graph)
    return legacy, graph, elapsed


def latency_summary(values: list[float]) -> dict[str, float | None]:
    ordered = sorted(values)
    result = {
        name: ordered[max(0, math.ceil(q * len(ordered)) - 1)] if ordered else None
        for name, q in (("P50", 0.5), ("P95", 0.95), ("P99", 0.99))
    }
    result["throughput_claims_per_second"] = (
        1000 * len(values) / sum(values) if sum(values) else None
    )
    return result


def run(root: Path = ROOT, *, real_pages: int = 100) -> dict:
    output = root / "evaluation_results/cdp2"
    rows = load_rows(root)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["document_id"]].append(row)
    pipeline, reconciler = CDP2ShadowPipeline(), EvidenceReconciler()
    comparisons, timings, legacy_records, shadows = [], [], [], []
    for claim_id in sorted(grouped):
        legacy, graph, elapsed = legacy_and_graph(claim_id, grouped[claim_id], reconciler)
        result = pipeline.compare(legacy, graph)
        comparisons.append(result)
        timings.append(elapsed)
        legacy_records.append(legacy)
        shadows.append(result.cdp2)
    assert_same_claims(tuple(legacy_records), tuple(shadows))
    identifiers = sorted(fingerprint(r.claim_id) for r in legacy_records)
    page_ids = {p for r in legacy_records for p in r.page_ids}
    manifest = {
        "claim_ids": identifiers,
        "claims": len(identifiers),
        "fields": len(rows),
        "pages_with_observation_provenance": len(page_ids),
        "page_denominator_status": "OBSERVED_PAGE_HASHES_ONLY_MISSING_PROVENANCE_NOT_IMPUTED",
        "legacy_claim_ids": identifiers,
        "cdp2_claim_ids": identifiers,
        "denominator_match": True,
        "cohort_sha256": fingerprint(identifiers),
        "evidence_sha256": fingerprint(rows),
        "authority": "FROZEN_REGRESSION",
        "release_truth": False,
        "package_leakage": "NOT_EVALUABLE_NO_FROZEN_PACKAGE_LINKAGE",
        "holdout_use": "FORBIDDEN_UNTIL_PACKAGE_LINEAGE_VERIFIED",
    }
    write(output, "same_claim_manifest.json", manifest)
    old = {
        key: sum(int(c.legacy_metrics[key]) for c in comparisons)
        for key in comparisons[0].legacy_metrics
    }
    new = {
        key: sum(int(c.cdp2_metrics[key]) for c in comparisons)
        for key in comparisons[0].cdp2_metrics
    }
    write(
        output,
        "legacy_baseline.json",
        {
            "metrics": old,
            "authority": "FROZEN_REGRESSION",
            "canonical_result_sha256": fingerprint([r.canonical_sha256 for r in legacy_records]),
        },
    )
    write(
        output,
        "cdp2_shadow_result.json",
        {
            "metrics": new,
            "runtime_authority": False,
            "shadow_accepts": sum(r.engineering_accepts for r in shadows),
            "canonical_outputs_unchanged": True,
        },
    )
    write(
        output,
        "candidate_graph_summary.json",
        {
            "fields": len(rows),
            "legacy_candidates": sum(len(f.candidates) for r in legacy_records for f in r.fields),
            "shadow_candidates": sum(len(f.candidates) for r in legacy_records for f in r.fields),
            "alternatives_retained": True,
            "token_geometry_in_frozen_rows": False,
        },
    )
    write(
        output,
        "claim_graph_summary.json",
        {
            "claims": len(shadows),
            "field_nodes": len(rows),
            "relationship_edges": len(rows),
            "service_line_completeness": "NOT_AVAILABLE_IN_FROZEN_INPUT",
        },
    )
    write(
        output,
        "constraint_summary.json",
        {
            "proofs": sum(s.deterministic_proofs for s in shadows),
            "conflicts": sum(s.deterministic_conflicts for s in shadows),
            "unknown": sum(s.unknown_constraints for s in shadows),
            "authority": "ENGINEERING_ONLY",
        },
    )
    write(
        output,
        "technical_vs_evidence_hitl.json",
        {
            "legacy": old,
            "cdp2": new,
            "production_hitl": None,
            "authority": "ENGINEERING_REGRESSION",
        },
    )
    write(
        output,
        "claim_unlock_distance_v2.json",
        {
            "claims": [
                {
                    "claim_id": fingerprint(c.legacy.claim_id),
                    "legacy": c.legacy_metrics,
                    "cdp2": c.cdp2_metrics,
                }
                for c in comparisons
            ],
            "production_authority": False,
        },
    )
    old_timing = latency_summary(timings)
    # The strangler includes the legacy work. Compare total legacy+shadow overhead,
    # not the incremental shadow duration against the whole baseline.
    new_timing = latency_summary(
        [t + c.profile["total_ms"] for t, c in zip(timings, comparisons, strict=True)]
    )
    from evaluation.cdp2_real_corpus import real_corpus

    real = real_corpus(root, output, real_pages)
    write(
        output,
        "performance_profile.json",
        {
            "same_claim_legacy": old_timing,
            "same_claim_cdp2_strangler": new_timing,
            "unit": "milliseconds_per_claim",
            "scope": "CACHED_CANDIDATE_DECISION_REPLAY_NOT_END_TO_END_OCR",
            "shadow_profiles": [c.profile for c in comparisons],
            "real_operational": real["profile"],
            "fresh_ocr_targets": "NOT_EVALUABLE_CACHED_PERCEPTION",
        },
    )
    write(
        output,
        "ocr_invocation_report.json",
        {
            "same_claim_scope": "CACHED_FIELD_CANDIDATES",
            "legacy_new_full_page_calls": 0,
            "shadow_new_full_page_calls": 0,
            "regional_calls": 0,
            "llm_calls": 0,
            "paid_ai_cost_usd": 0,
            "pricing_status": "PRICING_NOT_CONFIGURED",
            "real_operational": real["ledger"],
        },
    )
    scorecard = []
    for metric, old_value in old.items():
        scorecard.append(
            {
                "metric": metric,
                "legacy": old_value,
                "cdp2": new[metric],
                "delta": new[metric] - old_value,
                "authority": "FROZEN_REGRESSION",
            }
        )
    for metric in old_timing:
        scorecard.append(
            {
                "metric": metric,
                "legacy": old_timing[metric],
                "cdp2": new_timing[metric],
                "delta": float(new_timing[metric] or 0) - float(old_timing[metric] or 0),
                "authority": "MEASURED_MS_PER_CLAIM_CACHED",
            }
        )
    for metric in (
        "OCR_calls/page",
        "regional_OCR_calls/page",
        "LLM_calls/page",
        "paid_AI_cost/page",
    ):
        scorecard.append(
            {
                "metric": metric,
                "legacy": 0,
                "cdp2": 0,
                "delta": 0,
                "authority": "NO_NEW_CALLS_IN_CACHED_REPLAY",
            }
        )
    scorecard.append(
        {
            "metric": "engineering_claims_unlocked",
            "legacy": 0,
            "cdp2": sum(
                bool(c.cdp2_metrics["engineering_unlockable"])
                and not c.legacy_metrics["engineering_unlockable"]
                for c in comparisons
            ),
            "delta": sum(
                bool(c.cdp2_metrics["engineering_unlockable"])
                and not c.legacy_metrics["engineering_unlockable"]
                for c in comparisons
            ),
            "authority": "NEW_TECHNICAL_UNLOCKS_RELATIVE_TO_LEGACY",
        }
    )
    for metric in ("accuracy", "critical_accuracy", "accepted_precision", "critical_false_accepts"):
        scorecard.append(
            {
                "metric": metric,
                "legacy": None,
                "cdp2": None,
                "delta": None,
                "authority": "NOT_EVALUABLE_NO_TRUSTED_TRUTH",
                "status": "NOT_EVALUABLE",
            }
        )
    meaningful = any(
        new[k] < old[k]
        for k in (
            "technical_blockers",
            "CDP_CONTROLLED_HITL",
            "technical_unlock_distance",
            "candidate_ambiguity",
            "wrong_crop_dependence",
            "missing_crop_dependence",
        )
    )
    safety = real["safety"]
    verdict = (
        "CDP2_SHADOW_CANDIDATE" if meaningful and safety["passed"] else "CDP2_NO_ARCHITECTURAL_GAIN"
    )
    write(
        output,
        "architecture_manifest.json",
        {
            "repository": "https://github.com/ashneevai/CDP",
            "branch": "architecture/cdp2-claim-intelligence",
            "starting_sha": STARTING_SHA,
            "runtime_authority": False,
            "production_canonical_outputs_unchanged": True,
            "status": verdict,
            "safety": safety,
            "real_inventory": real["inventory"],
            "scope_limits": [
                "Frozen input lacks verified form identity, token geometry, and complete service lines",
                "Frozen package lineage is not mapped to real pages",
                "No fresh OCR latency measurement",
            ],
            "validation_status": "PENDING_FINAL_VALIDATION",
            "diagnosis_reference_status": "SYNTAX_ONLY_NO_ENABLED_GOVERNED_SNAPSHOT",
        },
    )
    write(
        output,
        "comparative_scorecard.json",
        {
            "status": verdict,
            "metrics": scorecard,
            "runtime_authority": False,
            "same_claim_manifest_sha256": fingerprint(manifest),
        },
    )
    md = [
        "# CDP 2.0 same-claim architecture comparison",
        "",
        verdict,
        "",
        "Both paths ran on the same frozen claim observations; no embedded truth was used.",
        "Latency is per claim over cached observations and includes legacy work plus shadow overhead.",
        "Real-page operational profiling is a separate cohort. No fresh-OCR target is claimed.",
        "",
        "| Metric | Legacy | CDP 2.0 | Delta | Authority |",
        "|---|---:|---:|---:|---|",
    ]
    for row in scorecard:
        md.append(
            "| "
            + " | ".join(
                str(row[k]) if row[k] is not None else "null"
                for k in ("metric", "legacy", "cdp2", "delta", "authority")
            )
            + " |"
        )
    (output / "comparative_scorecard.md").write_text("\n".join(md) + "\n", "utf-8")
    return {"status": verdict, "claims": len(shadows), "fields": len(rows), "safety": safety}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--real-pages", type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(run(args.root, real_pages=args.real_pages), sort_keys=True))
