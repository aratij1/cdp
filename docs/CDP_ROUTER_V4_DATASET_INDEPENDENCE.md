# Router V4 dataset independence

The development run contains 736 PHI-free pages: A 210, B 210, C 180, and D 136. V4-B uses OpenCV/Hershey rendering, different dimensions and rasterization from V4-A's PIL/TrueType pipeline. All documents carry hashes, truth, quality, source, renderer, generator, degradation, and creation metadata.

The leakage audit passed with no cross-partition exact duplicate or perceptual near-duplicate. No legacy images were found under the configured evaluation-result locations, so similarity against unavailable legacy pixels is **not established**. No production-representative image was copied into these generators.

