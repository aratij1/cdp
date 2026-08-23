# Routing Corpus Duplicate and Qualification Report

Status: **NOT RUN — CORPUS UNAVAILABLE**.

The Phase 7A.11 toolchain checks exact SHA256 duplicates, 64-bit perceptual-hash distance, layout fingerprint collisions, base-asset lineage, renderer/template lineage, and cross-declared-source clones. Related degradation variants must share the same base asset and source family and cannot cross a LOSO boundary.

No existing local dataset has all required source-independence, PHI, usage/license, asset-integrity, and independent-review attestations. Therefore no assets were admitted and no misleading duplicate counts are reported. `qualify_corpus.py` generates this report from a supplied qualified manifest before corpus freeze.
