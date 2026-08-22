"""Phase 4 immutable frontier freeze and row-level production-readiness artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluation_results" / "claim_stp_recovery" / "baseline"
OUTPUT = ROOT / "evaluation_results" / "production_readiness"
FRONTIER = OUTPUT / "evidence_frontier_v2"
ACCEPTED = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED", "HUMAN_CONFIRMED"}
ALLOWED_CLAIM_DISPOSITIONS = {
    "STP_SAFE", "STP_STANDARD", "FIELD_REVIEW_REQUIRED",
    "CLAIM_REVIEW_REQUIRED", "DOCUMENT_REJECTED",
}
FROZEN_CONFIGS = (
    "config/evidence_policies.yaml",
    "config/field_acceptance_policies.yaml",
    "config/claim_decision_policies.yaml",
    "config/claim_evidence.yaml",
    "config/ocr_field_routes.yaml",
    "config/field_criticality.yaml",
    "config/templates/cms1500_v02_12.yaml",
    "config/templates/ub04_v2014.yaml",
    "config/ocr_preprocessing.yaml",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _canonical_digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def freeze_evidence_frontier_v2(
    *, source: Path = SOURCE, output: Path = FRONTIER,
) -> dict:
    """Freeze the evaluated Phase 3 frontier exactly once."""
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(
            "EVIDENCE_FRONTIER_V2 is immutable; create a new frontier version"
        )
    source_manifest_path = source / "manifest.json"
    required = (
        source_manifest_path,
        source / "field_dispositions.json",
        source / "claim_dispositions.json",
        source / "metrics.json",
        source / "blocker_metrics.json",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing Phase 3 frontier artifacts: " + ", ".join(missing))

    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    extraction_manifest_path = (
        ROOT / "evaluation_results" / "evidence_optimization" /
        "extraction_baseline_v1" / "manifest.json"
    )
    extraction = json.loads(extraction_manifest_path.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=False)
    configs_dir = output / "configs"
    configs_dir.mkdir()
    config_hashes = {}
    for relative in FROZEN_CONFIGS:
        path = ROOT / relative
        if not path.is_file():
            continue
        target = configs_dir / relative.removeprefix("config/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        config_hashes[relative] = sha256(path)

    copied = {}
    for name in (
        "field_dispositions.json", "claim_dispositions.json",
        "metrics.json", "blocker_metrics.json",
    ):
        source_path, target = source / name, output / name
        shutil.copy2(source_path, target)
        copied[name] = sha256(target)

    routes = json.loads(json.dumps(
        yaml.safe_load((ROOT / "config" / "ocr_field_routes.yaml").read_text("utf-8")),
        default=lambda value: value.isoformat(),
    ))
    field_policy = yaml.safe_load((ROOT / "config" / "field_acceptance_policies.yaml").read_text("utf-8"))
    manifest = {
        "baseline_id": "EVIDENCE_FRONTIER_V2",
        "status": "FROZEN",
        "created_at": datetime.now(UTC).isoformat(),
        "qualification": "SYNTHETIC_EVALUATION_ONLY_NOT_PRODUCTION_AUTHORITY",
        "source_baseline": source_manifest["baseline_id"],
        "source_manifest_sha256": sha256(source_manifest_path),
        "git_sha": _git("rev-parse", "HEAD"),
        "working_tree_dirty": bool(_git("status", "--porcelain")),
        "dataset_version": source_manifest.get("dataset_version"),
        "dataset_hash": source_manifest.get("dataset_hash"),
        "dataset_contract_hash": source_manifest.get("dataset_contract_hash"),
        "renderer_version": extraction.get("renderer_version"),
        "template_versions": source_manifest.get("template_versions"),
        "roi_version": source_manifest.get("roi_version"),
        "ocr_provider_versions": source_manifest.get("ocr_provider_versions"),
        "field_specific_ocr_routes": routes,
        "confirmation_routes": {
            name: spec.get("confirmation_engine") or spec.get("confirmation")
            for name, spec in routes.get("ocr_routes", {}).items()
        },
        "evidence_taxonomy_version": "E1-E8-v1",
        "evidence_policy_version": source_manifest.get("field_evidence_policy_version"),
        "claim_policy_version": source_manifest.get("claim_decision_policy_version"),
        "criticality_metadata": {
            family: {
                name: spec.get("criticality", field_policy["default"]["criticality"])
                for name, spec in fields.items()
            }
            for family, fields in field_policy.get("forms", {}).items()
        },
        "blocks_stp_metadata": {
            family: {
                name: spec.get("blocks_stp", field_policy["default"]["blocks_stp"])
                for name, spec in fields.items()
            }
            for family, fields in field_policy.get("forms", {}).items()
        },
        "normalization_versions": {
            "extraction": extraction.get("normalization_version"),
            "evidence_agreement": source_manifest.get("normalization_version"),
        },
        "registration_version": source_manifest.get("registration_version"),
        "decision_service_versions": {
            "field": source_manifest.get("field_evidence_policy_version"),
            "claim": source_manifest.get("claim_decision_policy_version"),
        },
        "configuration_hashes": config_hashes,
        "artifact_hashes": copied,
        "synthetic_metrics": source_manifest["metrics"],
        "tuning_prohibition": (
            "No tuning against this frontier; create a new experiment branch and frontier version."
        ),
    }
    manifest["manifest_sha256"] = _canonical_digest(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def verify_frontier(path: Path = FRONTIER / "manifest.json") -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = payload.pop("manifest_sha256")
    if payload.get("status") != "FROZEN" or _canonical_digest(payload) != expected:
        raise ValueError("EVIDENCE_FRONTIER_V2 manifest integrity failure")
    for name, expected_hash in payload["artifact_hashes"].items():
        if sha256(path.parent / name) != expected_hash:
            raise ValueError(f"frozen frontier artifact integrity failure: {name}")
    return {**payload, "manifest_sha256": expected}


def write_claim_dispositions(
    *, frontier: Path = FRONTIER,
    output: Path = OUTPUT / "claim_dispositions.csv",
) -> list[dict]:
    field_rows = json.loads(
        (frontier / "field_dispositions.json").read_text(encoding="utf-8")
    )["rows"]
    claims_payload = json.loads(
        (frontier / "claim_dispositions.json").read_text(encoding="utf-8")
    )
    claim_rows = {
        row["claim_id"]: row for row in claims_payload.get("claims", [])
    }
    grouped = defaultdict(list)
    for row in field_rows:
        grouped[row["document_id"]].append(row)

    rows = []
    for claim_id, fields in sorted(grouped.items()):
        claim = claim_rows[claim_id]
        disposition = claim["disposition"]
        if disposition not in ALLOWED_CLAIM_DISPOSITIONS:
            raise ValueError(f"invalid canonical claim disposition: {disposition}")
        reviewed = [row for row in fields if row["final_disposition"] not in ACCEPTED]
        blocking = [row for row in reviewed if row["blocks_stp"]]
        nonblocking = [row for row in reviewed if not row["blocks_stp"]]
        critical = [row for row in reviewed if row["criticality"] in {"C2", "C3"}]
        accepted = [row for row in fields if row["final_disposition"] in ACCEPTED]
        false = [row for row in accepted if not row["candidate_correct"]]
        available = sorted({item for row in fields for item in row.get("evidence_available", [])})
        missing_evidence = sorted({item for row in reviewed for item in row.get("evidence_missing", [])})
        rows.append({
            "claim_id": claim_id,
            "document_family": fields[0]["document_family"],
            "total_fields": len(fields),
            "correct_fields": sum(bool(row["candidate_correct"]) for row in fields),
            "accepted_fields": len(accepted),
            "review_fields": len(reviewed),
            "blocking_review_fields": len(blocking),
            "non_blocking_review_fields": len(nonblocking),
            "critical_review_fields": len(critical),
            "claim_disposition": disposition,
            "STP_status": "STP" if claim["stp_eligible"] else "HITL",
            "field_safe_coverage": len(accepted) / len(fields),
            "available_evidence_classes": "|".join(available),
            "missing_evidence_classes": "|".join(missing_evidence),
            "claim_policy_id": claim["policy_id"],
            "claim_policy_version": claim["policy_version"],
            "false_accept_count": len(false),
            "critical_false_accept_count": sum(
                row["criticality"] in {"C2", "C3"} for row in false
            ),
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def _cheapest_safe_resolution(rows: list[dict]) -> str:
    actions = [row.get("next_action") for row in rows if row.get("next_action")]
    priority = (
        "PROPAGATE_EXISTING_EVIDENCE", "DETERMINISTIC_VALIDATION",
        "CROSS_FIELD_RECONCILIATION", "SECONDARY_OCR",
        "REFERENCE_LOOKUP", "HUMAN_REVIEW",
    )
    return next((action for action in priority if action in actions), "HUMAN_REVIEW")


def write_claim_blocker_pareto(
    *,
    frontier: Path = FRONTIER,
    output: Path = ROOT / "docs" / "CDP_CLAIM_STP_BLOCKER_PARETO.md",
) -> list[dict]:
    fields = json.loads(
        (frontier / "field_dispositions.json").read_text(encoding="utf-8")
    )["rows"]
    claims = json.loads(
        (frontier / "claim_dispositions.json").read_text(encoding="utf-8")
    )["claims"]
    claim_map = {row["claim_id"]: row for row in claims}
    non_stp = {row["claim_id"] for row in claims if not row["stp_eligible"]}
    routes = yaml.safe_load(
        (frontier / "configs" / "ocr_field_routes.yaml").read_text("utf-8")
    ).get("ocr_routes", {})
    grouped = defaultdict(list)
    for row in fields:
        if (
            row["document_id"] in non_stp
            and row["blocks_stp"]
            and row["final_disposition"] not in ACCEPTED
        ):
            grouped[(row["document_family"], row["field_name"])].append(row)

    result = []
    for (family, field_name), rows in grouped.items():
        claim_ids = {row["document_id"] for row in rows}
        single = {
            claim_id for claim_id in claim_ids
            if claim_map[claim_id]["blocking_unresolved_fields"] == [field_name]
        }
        route = routes.get(field_name, {})
        route_applies = (route.get("form") or route.get("document_family", "*")) in {"*", family}
        result.append({
            "field_name": field_name,
            "document_family": family,
            "claims_blocked": len(claim_ids),
            "percentage_of_non_stp_claims": len(claim_ids) / len(non_stp),
            "single_blocker_claims": len(single),
            "multi_blocker_claims": len(claim_ids - single),
            "claim_unlock_value": len(single),
            "available_evidence": sorted({
                item for row in rows for item in row.get("evidence_available", [])
            }),
            "missing_evidence": sorted({
                item for row in rows for item in row.get("evidence_missing", [])
            }),
            "current_policy": sorted({
                f"{row.get('current_evidence_policy')}@{row.get('policy_version')}"
                for row in rows
            }),
            "cheapest_safe_resolution": _cheapest_safe_resolution(rows),
            "production_route_status": (
                (route.get("status") or route.get("state", "DISABLED"))
                if route_applies else "DISABLED"
            ),
        })
    result.sort(
        key=lambda row: (row["claim_unlock_value"], row["claims_blocked"]),
        reverse=True,
    )
    lines = [
        "# CDP Claim STP Blocker Pareto", "",
        "> `EVIDENCE_FRONTIER_V2` synthetic evaluation only. Sorted by claim unlock value; evaluation-only routes are not runtime authority.", "",
        "| Field | Family | Claims blocked | % non-STP | Single blocker | Multi blocker | Claim unlock value | Available evidence | Missing evidence | Current policy | Cheapest safe resolution | Production route status |",
        "|---|---|---:|---:|---:|---:|---:|---|---|---|---|---|",
    ]
    for row in result:
        lines.append(
            f"| `{row['field_name']}` | {row['document_family']} | {row['claims_blocked']} | "
            f"{row['percentage_of_non_stp_claims']:.2%} | {row['single_blocker_claims']} | "
            f"{row['multi_blocker_claims']} | {row['claim_unlock_value']} | "
            f"{', '.join(row['available_evidence']) or 'none'} | "
            f"{', '.join(row['missing_evidence']) or 'none'} | "
            f"{', '.join(row['current_policy'])} | `{row['cheapest_safe_resolution']}` | "
            f"`{row['production_route_status']}` |"
        )
    lines.extend([
        "", "## Interpretation", "",
        f"There are {len(non_stp)} non-STP claims. Claim unlock value counts only claims where resolving this field alone would make the claim STP-eligible; multi-blocker claims receive no speculative unlock credit.",
        "", "No blocker was relabeled and no route was promoted by this analysis.",
    ])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUTPUT / "claim_blocker_pareto.json").write_text(
        json.dumps({"rows": result}, indent=2), encoding="utf-8",
    )
    return result


def main() -> int:
    if not (FRONTIER / "manifest.json").exists():
        freeze_evidence_frontier_v2()
    verify_frontier()
    rows = write_claim_dispositions()
    blockers = write_claim_blocker_pareto()
    print(json.dumps({
        "frontier": str(FRONTIER),
        "claim_rows": len(rows),
        "stp_claims": sum(row["STP_status"] == "STP" for row in rows),
        "false_accepts": sum(row["false_accept_count"] for row in rows),
        "blocker_rows": len(blockers),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
