# Router V4 targeted remediation plan

`ROUTING_DEV_V4_REMEDIATION_01` contains 200 independent PHI-free reproductions across ten anchor, geometry, UB table/header, custom and non-claim buckets using PIL/Tahoma and separately resampled OpenCV pipelines. It does not copy A/B/C/D pixels.

Experiments are isolated. REM-01 evaluates only content-bound geometry; REM-02 evaluates only token-group anchors on original V4 geometry. Neither meets the development promotion gate, so both remain disabled, REM-03 is blocked, and frozen A/B/C/D are not rerun.

