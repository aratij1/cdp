# Router Latency Shift Report

Development P95 was 492 ms and the observed representative P95 was 4.44 s.
The frozen V3 observation retained only total routing time, so attributing that
delta to a particular stage would be speculation. RouterObservation schema 1.0
now records decode, image features, structure, template, sparse/full-page OCR,
anchor, geometry, fallback, decision and total time plus OCR calls, regions,
cache, retry and fallback counts. V4 benchmarks must populate these fields.

The input parity audit already identifies heterogeneous raster/DPI and runtime
preparation as differences. Latency optimization is deferred until V4 stage
observations provide measured attribution.
