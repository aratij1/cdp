# Router V4 design and governance

Router V4 is a separately versioned, development-only router. It does not modify frozen Router V3 and is disabled by default.

It combines three independent evidence families for standards: normalized visual structure, semantic anchors, and spatial relationships. Its PHI-safe descriptors include line histograms, grid and box density maps, region occupancy, repeated service-table rows, connected-component distributions, and edge projections. Semantic identity is a bonus rather than a requirement.

`UNKNOWN_STRUCTURED` remains a first-class route. Custom structure uses explicit component evidence for label/value density, alignment, boxes, tables, repeated rows, dates, identifiers, currency, healthcare concepts, and spatial regularity. `NON_CLAIM` requires both positive negative-document evidence and low claim evidence. Ambiguity falls safely to `UNKNOWN_UNSTRUCTURED`.

All current score weights are recorded in `config/document_routing_v4.yaml`, calibrated only against new V4 development partitions. The observed 500-document representative corpus is explicitly excluded. Runtime promotion is forbidden until all four source partitions and a newly sourced independent holdout pass.

