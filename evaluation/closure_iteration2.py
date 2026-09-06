"""Source-bound frozen replay; references enter scoring only, never extraction."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.cdp2_comparison import legacy_and_graph, write
from evaluation.closure_bottlenecks import decompose
from packages.candidate_reconciliation import EvidenceReconciler
from packages.claim_intelligence.discovery import NoncanonicalDiscovery, select_recovery
from packages.claim_intelligence.document import DocumentPage, Token, fingerprint
from packages.claim_intelligence.normalization import comparison_key, normalize
from packages.claim_intelligence.pipeline import CDP2ShadowPipeline
from packages.claim_intelligence.spatial import TARGET_FIELDS

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "evaluation/baselines/phase8_12/inputs/source_b/policy_replay_input.jsonl"
OBS = ROOT / "evaluation_results/phase8_8c/source_b/observations"


def run(name: str) -> dict:
    source = [json.loads(line) for line in INPUT.read_text().splitlines() if line]
    if len(source) != 200 or len({(r["document_id"], r["field_name"]) for r in source}) != 200:
        raise ValueError("FROZEN_200_FIELD_DENOMINATOR_REQUIRED")
    groups = defaultdict(list)
    for row in source:
        groups[row["document_id"]].append(row)
    extractor = NoncanonicalDiscovery()
    baseline, candidate, roots, review, claims = [], [], [], [], []
    evidence_hashes = []
    canonical_hashes = []
    for claim, rows in sorted(groups.items()):
        observation = json.loads((OBS / f"{claim}.json").read_text())
        page_hashes = {c["provenance"]["page_sha256"] for r in rows for c in r["candidates"]}
        if observation["page_id"] != claim or page_hashes != {observation["page_sha256"]}:
            raise ValueError("FROZEN_OBSERVATION_BINDING_MISMATCH")
        invocation = fingerprint(observation)
        evidence_hashes.append(invocation)
        tokens = tuple(
            Token(
                t["text"],
                t["text"],
                tuple(t["bbox"]),
                t["confidence"],
                observation["ocr_model_version"],
                claim,
                fingerprint(t["bbox"]),
                invocation,
                observation["page_sha256"],
                observation["page_sha256"],
            )
            for t in observation["ocr_tokens"]
        )
        # Literal discovery is independent of form templates. This adapter carries no
        # strict identity authorization and never enters canonical localization.
        page = DocumentPage(
            claim,
            claim,
            "OTHER_CLAIM_FORM",
            "NOT_VERIFIED",
            observation["width"],
            observation["height"],
            observation["image_quality"]["quality_bucket"],
            tokens,
        )
        regions: list[dict] = []
        discoveries = extractor.extract(page, regions)
        inputs = [
            {k: v for k, v in r.items() if k not in {"truth", "exact", "cross_field_evidence"}}
            for r in rows
        ]
        legacy, graph, _ = legacy_and_graph(claim, inputs, EvidenceReconciler())
        canonical_hashes.append(legacy.canonical_sha256)
        comparison = CDP2ShadowPipeline().compare(legacy, graph)
        fields = {f.field_name: f for f in legacy.fields}
        technical = sum(len(f.technical_blockers) for f in legacy.fields)
        claims.append(
            {
                "claim_id": fingerprint(claim),
                "technical_distance": technical,
                "technical_distance_after": comparison.cdp2_metrics["technical_unlock_distance"],
                "technical_review_after": comparison.cdp2_metrics["CDP_CONTROLLED_HITL"],
                "evidence_blockers": sum(len(f.evidence_blockers) for f in legacy.fields),
                "engineering_unlockable_after": comparison.cdp2_metrics["engineering_unlockable"],
                "production_unlockable_after": False,
                "technical_fields": [f.field_name for f in legacy.fields if f.technical_blockers],
            }
        )
        for row in rows:
            field = row["field_name"]
            old = fields[field]
            top = normalize(field, old.canonical_value or "")[0]
            values = list(dict.fromkeys(c.normalized_value or c.value for c in old.candidates))
            if top in values:
                values.remove(top)
                values.insert(0, top)
            recovered = list(
                dict.fromkeys(
                    c.normalized_value or c.value for c in discoveries.candidates.get(field, [])
                )
            )
            new = list(dict.fromkeys([*values, *recovered]))[:5]
            selected_top = top
            selected, ranking_reasons = select_recovery(
                field,
                discoveries.candidates.get(field, []),
                existing_value=top,
                wrong_crop=old.wrong_crop,
                missing_crop=old.missing_crop,
            )
            if selected is not None:
                selected_top = selected.normalized_value or selected.value
                new.remove(selected_top)
                new.insert(0, selected_top)
            base = {
                "claim_id": claim,
                "field": field,
                "form": row["family"],
                "quality": page.quality_band,
                "ranking_reasons": list(ranking_reasons),
                "criticality": row["criticality"],
                "authority": "FROZEN_REGRESSION",
                "truth": row["truth"],
                "candidates": values,
                "top1": top,
                "accepted": old.accepted,
                "authority_blocked": "AUTHORITATIVE_DATA_REQUIRED" in old.evidence_blockers,
                "external_evidence_blocked": "EVIDENCE_REQUIRED" in old.evidence_blockers,
            }
            baseline.append(base)
            candidate.append({**base, "candidates": new, "top1": selected_top})
            expected = normalize(field, row["truth"])[0]
            if expected not in values:
                in_token = any(normalize(field, t.text)[0] == expected for t in tokens)
                name_field = field in {"patient_name", "insured_name", "provider_name"}
                key = comparison_key(field, expected)
                representation_mismatch = name_field and key in {
                    comparison_key(field, v) for v in values
                }
                merged_token = name_field and any(
                    comparison_key(field, t.text) == key for t in tokens
                )
                region = (row.get("localization_evidence") or {}).get("field_bbox")
                field_crop_corruption = bool(in_token and region and not old.wrong_crop and any(
                    normalize(field,t.text)[0] == expected
                    and region[0] <= (t.bbox[0]+t.bbox[2])/2 <= region[2]
                    and region[1] <= (t.bbox[1]+t.bbox[3])/2 <= region[3]
                    for t in tokens))
                cause = (
                    "REFERENCE_MISMATCH"
                    if representation_mismatch
                    else "OCR_CHARACTER_CORRUPTION"
                    if field_crop_corruption
                    else "SPATIAL_WINDOW_MISS"
                    if in_token
                    else "TOKEN_MERGE_ERROR"
                    if merged_token
                    else "UNKNOWN"
                )
                roots.append(
                    {
                        "claim_id": fingerprint(claim),
                        "field": field,
                        "form": row["family"],
                        "quality": page.quality_band,
                        "criticality": row["criticality"],
                        "primary_root_cause": cause,
                        "reference_present_in_source_token": in_token,
                        "recovered": expected in new,
                        "governed_recovered": key in {comparison_key(field, v) for v in new},
                        "claim_unlock_impact": 1 / max(1, technical),
                        "source_limitation_proven": False,
                    }
                )
            if old.technical_blockers:
                equivalent = len({comparison_key(field,c.normalized_value or c.value) for c in old.candidates}) == 1 and all(c.features.format_valid is True for c in old.candidates)
                remaining = [b for b in old.technical_blockers if not (b == "CANDIDATE_AMBIGUITY" and equivalent)]
                category = ("candidate missing" if "CANDIDATE_ASSEMBLY" in remaining else
                            "validation" if "SOFTWARE_VALIDATION" in remaining else
                            "candidate ranking" if "CANDIDATE_AMBIGUITY" in remaining else
                            "technical evidence" if remaining else
                            "external authority" if "AUTHORITATIVE_DATA_REQUIRED" in old.evidence_blockers else "source evidence")
                review.append(
                    {
                        "claim_id": fingerprint(claim),
                        "field": field,
                        "technical": list(old.technical_blockers),
                        "remaining_technical": remaining,
                        "review_category": category,
                        "historical_130_field_scope": field in TARGET_FIELDS,
                        "evidence": list(old.evidence_blockers),
                    }
                )

    def governed(items):
        return decompose(
            [
                {
                    **r,
                    "truth": comparison_key(r["field"], r["truth"]),
                    "candidates": [comparison_key(r["field"], v) for v in r["candidates"]],
                    "top1": comparison_key(r["field"], r["top1"]),
                }
                for r in items
            ],
            scope="ENGINEERING",
        )

    clusters = defaultdict(list)
    for root in roots:
        clusters[(root["primary_root_cause"], root["field"])].append(root)
    priorities = []
    for (cause, field), members in clusters.items():
        fixability = 0.25 if cause == "UNKNOWN" else 1.0
        impact = sum(m["claim_unlock_impact"] for m in members) / len(members)
        criticality = max({"C3":3,"C2":2,"C1":1}.get(m["criticality"],1) for m in members)
        priorities.append({"root_cause":cause,"field":field,"blocker_count":len(members),
                           "claim_unlock_impact":impact,"criticality_weight":criticality,
                           "software_fixability_weight":fixability,
                           "priority_score":len(members)*impact*criticality*fixability})
    report = {
        "root_cause_priority": sorted(priorities,key=lambda r:(-r["priority_score"],r["field"],r["root_cause"])),
        "comparison_policy": "EXACT_NORMALIZED_AND_EXISTING_GOVERNED_NAME_AGREEMENT_SEPARATELY",
        "governed_baseline": governed(baseline),
        "governed_candidate": governed(candidate),
        "authority": "FROZEN_REGRESSION",
        "production_authority": False,
        "canonical_outputs_sha256": fingerprint(canonical_hashes),
        "cohort_sha256": fingerprint([(r["document_id"], r["field_name"]) for r in source]),
        "evidence_sha256": fingerprint(evidence_hashes),
        "baseline": decompose(baseline, scope="ENGINEERING"),
        "candidate": decompose(candidate, scope="ENGINEERING"),
        "missing_candidate_root_causes": roots,
        "review_fields": review,
        "ranking_decisions": [
            {
                "claim_id": fingerprint(r["claim_id"]),
                "field": r["field"],
                "reasons": r["ranking_reasons"],
            }
            for r in baseline
        ],
        "claim_distances": claims,
        "root_cause_counts": dict(Counter(r["primary_root_cause"] for r in roots)),
        "technical_blockers": sum(c["technical_distance"] for c in claims),
        "engineering_claims_unlocked": sum(c["technical_distance_after"] == 0 for c in claims),
        "technical_blockers_after": sum(c["technical_distance_after"] for c in claims),
        "technical_review_after": sum(c["technical_review_after"] for c in claims),
        "release_status": "NOT_EVALUABLE_WITHOUT_TRUSTED_TRUTH",
    }
    write(ROOT / "evaluation_results/closure/iteration2", name + ".json", report)
    print(json.dumps({k: report[k]["summary"] for k in ("baseline", "candidate")}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="source_discovery")
    args = parser.parse_args()
    run(args.name)
