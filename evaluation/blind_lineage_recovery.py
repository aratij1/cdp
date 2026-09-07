"""Recover blind source lineage without inferring claim identity or reading predictions."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from PIL import Image

from evaluation.claim_inventory import build_inventory
from packages.real_data_evaluation.blind_workflow import content_digest

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = [
    "review_page_alias",
    "source_hash_alias",
    "package_alias",
    "source_file_alias",
    "frame/page number",
    "suggested document boundary if evidenced",
    "claim_alias_to_fill",
    "membership_status",
    "owner_confirmation",
    "notes",
]


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recover(
    sources: list[dict], bindings: list[dict], lineage: dict, membership: dict | None = None
) -> tuple[list[dict], dict, dict]:
    """Only the existing governed contract can establish an exact claim relationship."""
    by_page = {b["source_page_id"]: b for b in bindings}
    if len(by_page) != len(bindings) or len({s["page_id"] for s in sources}) != len(sources):
        raise ValueError("DUPLICATE_PAGE_BINDING")
    assets: dict[str, list[dict]] = {}
    for asset in lineage.get("assets", []):
        assets.setdefault(asset.get("sha256", ""), []).append(asset)
    inventory = build_inventory(membership or {}, bindings)
    exact = {
        p
        for claim in inventory["claims"]
        if claim["membership_status"] == "EXACT"
        for p in claim["page_ids_sha256"]
    }
    aliases: dict[str, dict[str, str]] = {}

    def alias(kind: str, value: str) -> str:
        table = aliases.setdefault(kind, {})
        if value not in table:
            table[value] = f"{kind}-{len(table) + 1:04d}"
        return table[value]

    rows, lookup = [], []
    recovered_source = 0
    for source in sorted(sources, key=lambda s: s["page_id"]):
        binding = by_page.get(source["page_id"], {})
        if (
            binding.get("state") != "EXACT"
            or binding.get("source_asset_sha256") != source["source_asset_sha256"]
            or binding.get("package_id") != source["package_id"]
            or binding.get("source_page_index") != source["frame_index"]
            or binding.get("rendered_page_sha256") != source["rendered_page_sha256"]
            or binding.get("cdp_page_sha256") != source["rendered_page_sha256"]
        ):
            raise ValueError("SOURCE_BINDING_SEAL_MISMATCH")
        candidates = assets.get(source["source_asset_sha256"], [])
        matches = [
            a
            for a in candidates
            if a.get("relative_path")
            and source["source_asset_path"]
            .replace("\\", "/")
            .lower()
            .endswith("/" + a["relative_path"].replace("\\", "/").lower().lstrip("/"))
        ]
        frame_count = matches[0].get("frame_count") if len(matches) == 1 else None
        witnessed = isinstance(frame_count, int) and 0 <= source["frame_index"] < frame_count
        recovered_source += int(witnessed)
        file_alias = alias("file", source["source_asset_path"])
        page_alias = alias("page", source["page_id"])
        status = "EXACT" if content_digest(source["page_id"]) in exact else "UNBOUND"
        row = dict(
            zip(
                COLUMNS,
                [
                    page_alias,
                    alias("hash", source["source_asset_sha256"]),
                    alias("package", source["package_id"]),
                    file_alias,
                    source["frame_index"] + 1,
                    f"{file_alias}: frames 1-{frame_count}; source container only"
                    if witnessed
                    else "",
                    "",
                    status,
                    "",
                    "Claim boundary requires governed confirmation; do not infer from file or package.",
                ],
            )
        )
        if status != "EXACT":
            rows.append(row)
        lookup.append(
            {
                "review_page_alias": page_alias,
                "source": source,
                "lineage_assets": matches,
                "binding": binding,
            }
        )
    report = {
        "schema_version": 1,
        "scope": "BLIND_150_SOURCE_LINEAGE_ONLY",
        "pages": len(sources),
        "source_assets": len(aliases.get("hash", {})),
        "packages": len(aliases.get("package", {})),
        "source_container_lineage_recovered_pages": recovered_source,
        "automatically_recovered_claim_membership_pages": len(sources) - len(rows),
        "owner_confirmation_required_pages": len(rows),
        "still_unbound_pages": len(rows),
        "claims_inferred": False,
        "predictions_read": False,
        "reviews_modified": False,
        "document_boundary_scope": "SOURCE_CONTAINER_NOT_CLAIM_BOUNDARY",
    }
    return (
        rows,
        {
            "aliases": {k: {v: raw for raw, v in vals.items()} for k, vals in aliases.items()},
            "pages": lookup,
        },
        report,
    )


def build(root: Path = ROOT) -> dict:
    private = root / "evaluation_results/qualification_closure"
    cohort = root / "evaluation_results/cdp2/active_learning_blind_manifest.json"
    sources_path = private / "blind_source_views.local.json"
    binding_path = private / "source_page_bindings.local.json"
    sealed = {p: _sha(p) for p in (cohort, sources_path, binding_path)}
    sources = _read(sources_path)
    manifest = _read(cohort)
    binding = _read(binding_path)
    if binding.get("blind_manifest_sha256") != sealed[cohort]:
        raise ValueError("COHORT_SEAL_MISMATCH")
    expected = {(p["page_id"], p["package_id"]) for p in manifest["pages"]}
    if (
        len(sources) != 150
        or len(expected) != 150
        or expected != {(p["page_id"], p["package_id"]) for p in sources}
    ):
        raise ValueError("FROZEN_COHORT_SCOPE_MISMATCH")
    checked = set()
    for source in sources:
        path = Path(source["source_asset_path"])
        if path not in checked:
            if _sha(path) != source["source_asset_sha256"]:
                raise ValueError("SOURCE_HASH_MISMATCH")
            checked.add(path)
        with Image.open(path) as img:
            if not 0 <= source["frame_index"] < getattr(img, "n_frames", 1):
                raise ValueError("SOURCE_FRAME_MISSING")
    lineage_path = root / "evaluation_results/closure1000/page_lineage.json"
    membership_path = private / "claim_membership.local.json"
    rows, lookup, report = recover(
        sources,
        binding["bindings"],
        _read(lineage_path),
        _read(membership_path) if membership_path.exists() else {},
    )
    # Search source metadata only; inspect no extraction, prediction, truth or review records.
    hits, inspected, skipped = [], 0, 0
    hashes = {s["source_asset_sha256"] for s in sources}
    for base in (root / "evaluation_results", root / "evaluation_data"):
        for path in sorted(base.rglob("*.json")):
            relative = path.relative_to(root).as_posix()
            if any(
                word in relative.lower()
                for word in (
                    "prediction",
                    "truth",
                    "review",
                    "annotation",
                    "blind_lineage",
                    "real_release",
                )
            ):
                continue
            if not any(
                word in path.name.lower()
                for word in ("manifest", "inventory", "lineage", "binding")
            ):
                continue
            if path.stat().st_size > 20_000_000:
                skipped += 1
                continue
            try:
                value = _read(path)
            except (ValueError, UnicodeError):
                skipped += 1
                continue
            inspected += 1
            encoded = json.dumps(value)
            matches = sum(h in encoded for h in hashes)
            if matches:
                hits.append(
                    {
                        "artifact_sha256": _sha(path),
                        "matching_source_hashes": matches,
                        "explicit_governed_claim_map": isinstance(value, dict)
                        and value.get("governed") is True
                        and isinstance(value.get("claims"), dict),
                    }
                )
    report.update(
        {
            "cohort_manifest_sha256": sealed[cohort],
            "source_lineage_sha256": _sha(lineage_path),
            "source_metadata_files_inspected": inspected,
            "source_metadata_files_skipped": skipped,
            "matching_metadata_artifacts": hits,
            "search_limitation": "Bounded local JSON source metadata; hash matches establish provenance, not claim authority.",
        }
    )
    if any(_sha(p) != digest for p, digest in sealed.items()):
        raise ValueError("INPUT_CHANGED_DURING_RECOVERY")
    output = root / "evaluation_results/real_release"
    output.mkdir(parents=True, exist_ok=True)
    with (output / "150_cohort_missing_membership.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (private / "blind_lineage_alias_lookup.local.json").write_text(
        json.dumps(lookup, indent=2) + "\n", encoding="utf-8"
    )
    (output / "blind_lineage_recovery_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
