# Routing Dataset Leakage Report

`ROUTING_TAXONOMY_CORPUS_V1` is not yet populated; therefore its leakage gate is **NOT PASSED**. The manifest contract records SHA256, optional perceptual hash, source family, renderer family, layout/template lineage, origin type, acquisition channel, organization, and degradation family.

Exact duplicates, PHI, incomplete lineage, and source/template groups crossing splits are reported as failures. Primary evaluation uses leave-one-source-family-out rotation, never random-page splitting. Near-duplicate perceptual/layout review remains a required corpus-build step before training.
