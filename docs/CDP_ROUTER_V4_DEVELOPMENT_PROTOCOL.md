# Router V4 multi-source development protocol

Each page manifest must record `source_family`, `renderer_family`, and `degradation_family`.

- V4-A Standard: canonical assets with varied scale, DPI, margins, population, line thickness, clipping, and service rows.
- V4-B Standard Alternate: independent renderer, fonts, rasterization, dimensions, and scan simulation; no shared A renderer.
- V4-C Custom Negative: custom claims and adversarial non-claims containing healthcare vocabulary.
- V4-D Degradation: clean, office scan, fax, photocopy, low/high DPI, low contrast, JPEG, noise, skew, rotation, perspective, clipping, fading, illumination, and header/footer loss.

Reports must show each partition and degradation separately. Promotion uses worst-source and worst-family gates, never an aggregate that can hide collapse. Representative V2 remains diagnosis-only. A new holdout must be independently sourced and remain inaccessible until the development implementation and configuration are frozen.
