# Public-Spec Synthetic Benchmark

## Dataset

Generated 120 deterministic, non-PHI claim-like pages: 60 CMS-1500 and 60 UB-04. Field structure is derived from public CMS/NUCC completion guidance, while all artwork and values are generated locally. Every page is visibly marked `SYNTHETIC` and `NOT A REAL CLAIM`.

The corpus covers clean, fax, low-contrast, rotation, skew, cropped-edge, poor-DPI, and handwriting-style variants. It includes 600 labeled field crops and SHA-256 inventories. It is useful for regression and robustness testing but is explicitly not a production holdout.

## Local Tesseract results

- Overall exact match: 224/600 (37.33%).
- CMS-1500: 140/240 (58.33%).
- UB-04: 84/360 (23.33%).
- Clean scans: 65.00%.
- Low contrast: 65.00%.
- Rotation: 0.00%.
- Cropped edges: 3.33%.
- P95 call latency: 268.50 ms.
- Mean call latency: 204.85 ms.

All candidates were marked `accepted=false`; therefore the synthetic run introduced no automatic false accepts. The low result mainly exposes registration/crop sensitivity and printed-label contamination, particularly for UB-04. It must not replace the independently sourced holdout required for production promotion.
