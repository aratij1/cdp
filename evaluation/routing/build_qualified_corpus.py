"""Build the qualified manifest from governed metadata and an external asset index."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from packages.document_taxonomy.corpus_v1 import (QualifiedRoutingCorpusManifest,
    RoutingTaxonomyPageRecord, SourceLineageRecord)
from .qualify_corpus import qualify, write_reports

QUALIFIED_CORPUS_BUILDER_VERSION = "routing-taxonomy-qualified-builder-v1.0.0"


def _dhash(image: Image.Image) -> str:
    pixels = list(image.convert("L").resize((9, 8)).getdata())
    bits = [pixels[row * 9 + column] > pixels[row * 9 + column + 1]
            for row in range(8) for column in range(8)]
    return f"{sum(int(bit) << index for index, bit in enumerate(bits)):016x}"


def build(metadata_path: Path, asset_index_path: Path, asset_root: Path,
          manifest_output: Path, report_output: Path, markdown_output: Path) -> dict:
    metadata = json.loads(metadata_path.read_text("utf-8"))
    asset_index = json.loads(asset_index_path.read_text("utf-8"))
    pages = []
    asset_failures = {}
    for raw in metadata["pages"]:
        page_id = raw["page_id"]
        asset_id = raw["asset_id"]
        relative = asset_index.get(asset_id)
        reasons = []
        try:
            data = (asset_root / relative).read_bytes() if relative else b""
            with Image.open(asset_root / relative) as image:
                image.load()
                observed_phash = _dhash(image)
            if hashlib.sha256(data).hexdigest() != raw["file_sha256"]: reasons.append("SHA256_MISMATCH")
            if observed_phash != raw["perceptual_hash"]: reasons.append("PERCEPTUAL_HASH_MISMATCH")
        except Exception:
            reasons.append("IMAGE_UNREADABLE")
        if reasons: asset_failures[page_id] = reasons
        pages.append(RoutingTaxonomyPageRecord.model_validate({key: value for key, value in raw.items()
                                                               if key != "asset_id"}))
    manifest = QualifiedRoutingCorpusManifest(
        sources=tuple(SourceLineageRecord.model_validate(row) for row in metadata["sources"]),
        pages=tuple(pages), minimum_pages=metadata.get("minimum_pages", 1000),
        minimum_sources_per_priority_class=metadata.get("minimum_sources_per_priority_class", 3),
        double_review_minimum_rate=metadata.get("double_review_minimum_rate", .10))
    report = qualify(manifest)
    if asset_failures:
        report["asset_failures"] = asset_failures
        report["corpus_reasons"].append("ASSET_INTEGRITY_FAILURES_PRESENT")
        report["qualified"] = report["loso_allowed"] = report["freeze_allowed"] = False
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.write_text(manifest.model_dump_json(indent=2), "utf-8")
    write_reports(report, report_output, markdown_output)
    return {"builder_version": QUALIFIED_CORPUS_BUILDER_VERSION, "manifest": manifest,
            "qualification": report}
