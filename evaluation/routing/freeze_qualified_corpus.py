"""Freeze an immutable qualified corpus manifest before LOSO begins."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from packages.document_taxonomy.corpus_v1 import QualifiedRoutingCorpusManifest
from packages.document_taxonomy.taxonomy import DocumentTaxonomyV1
from packages.processing_routes.contracts import PROCESSING_ROUTE_CONTRACT_VERSION
from .qualify_corpus import qualify


def freeze(manifest: QualifiedRoutingCorpusManifest, output: Path) -> dict:
    qualification = qualify(manifest)
    if not qualification["qualified"]:
        raise ValueError(f"CORPUS_QUALIFICATION_FAILED:{qualification['corpus_reasons']}")
    record = {"freeze_id": "ROUTING_TAXONOMY_CORPUS_V1_FREEZE",
              "created_at": datetime.now(timezone.utc).isoformat(), **manifest.hashes(),
              "taxonomy_version": DocumentTaxonomyV1.version,
              "processing_route_contract_version": PROCESSING_ROUTE_CONTRACT_VERSION,
              "page_count": len(manifest.pages), "source_count": len(manifest.sources),
              "immutable_after_loso_start": True, "loso_started": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), "utf-8")
    return record
