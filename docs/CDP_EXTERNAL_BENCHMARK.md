# CDP External Benchmark

Status: `BLOCKED_EXTERNAL_CREDENTIALS`.

Provider selected: AWS Textract `DetectDocumentText`, used only as a benchmark oracle on PHI-free synthetic field crops. The repository already has a normalized Textract provider and a page-cost assumption of $0.0015. No AWS credential variables are available in the audit environment, and `textract_enabled` remains false. Azure OpenAI evaluation variables are not Azure Document Intelligence credentials and were not repurposed.

`evaluation/architecture_reset_external_benchmark.py` is a credential-gated harness. It:

1. selects difficult non-locked validation failures whose expected value is present in the CDP crop;
2. adds deterministic correct controls;
3. exports a manifest without making a network call;
4. requires the explicit acknowledgement `CDP_EXTERNAL_BENCHMARK_ACK=AWS_TEXTRACT_COST_AND_DATA_APPROVED` before invoking AWS;
5. records overall and critical-field accuracy, CDP/external wins, both-wrong cases, provider latency, and actual estimated cost;
6. never feeds external output into runtime decisions, tuning, or the locked holdout.

The current field-crop harness isolates OCR quality. UB table comparison additionally requires a page-level `AnalyzeDocument(TABLES)` run and row mapping; it is explicitly blocked with the provider execution rather than inferred from field OCR. Until authorized credentials and an explicit external-processing acknowledgement exist, provider pages, accuracy, critical accuracy, table accuracy, cost, and latency are reported as unavailable rather than fabricated.
