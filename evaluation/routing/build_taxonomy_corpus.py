"""Validate and freeze operator-supplied PHI-free corpus metadata; generates no synthetic pages."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from packages.document_taxonomy.corpus import CorpusRecord, RoutingCorpusManifest

CORPUS_BUILDER_VERSION = "routing-taxonomy-corpus-builder-v1.0.0"


def build(metadata_path: Path, image_root: Path, output_path: Path) -> dict:
    source = json.loads(metadata_path.read_text("utf-8"))
    records = tuple(CorpusRecord.model_validate({key: value for key, value in row.items()
                                                 if key != "relative_image_path"})
                    for row in source["records"])
    manifest = RoutingCorpusManifest(corpus_id="ROUTING_TAXONOMY_CORPUS_V1", records=records)
    unreadable = []
    for row in source["records"]:
        image_path = image_root / row["relative_image_path"]
        try:
            with Image.open(image_path) as image:
                image.verify()
        except Exception:
            unreadable.append(row["document_id"])
    result = {
        "corpus_id": manifest.corpus_id,
        "corpus_builder_version": CORPUS_BUILDER_VERSION,
        "taxonomy_version": manifest.taxonomy_version,
        "dataset_hash": manifest.dataset_hash(),
        "record_count": len(records),
        "class_counts": manifest.class_counts(),
        "representation_gaps": manifest.representation_gaps(),
        "quality_failures": {**manifest.quality_failures(),
                             **{document_id: ["IMAGE_UNREADABLE"] for document_id in unreadable}},
        "primary_split_policy": "LEAVE_ONE_SOURCE_FAMILY_OUT",
        "training_eligible": not unreadable and not manifest.quality_failures()
                             and not manifest.representation_gaps() and len(records) >= 1000,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), "utf-8")
    return result
