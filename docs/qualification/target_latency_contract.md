# Target deployment latency evidence contract

The existing command is `python -m evaluation.production_latency_qualification --target-output <new-directory> [--source-root <governed-source-root>]`, run from the repository on the designated deployment host. It executes three isolated processes, each with a cold warm-up followed by a fresh warm repetition, using the retained frozen semantic cohort. Do not run workstation tuning again.

This command measures perception and downstream shadow work. Its `target_qualification.json` deliberately does not claim a complete production path SLA. A configured deployment executor must additionally measure the complete production page path and publish `deployment_latency.local.json` under the qualification directory, with a sealed job receipt containing its byte hash. Missing deployment services remain NOT_AVAILABLE.

`target_latency_evidence` validates this JSON contract:

- `scope` and `profile.scope`: `COMPLETE_PRODUCTION_PAGE_PATH`.
- `configuration_sha256`: governed `cdp_services.pipeline_configuration_sha256`; `deployment_id`: approved deployment ID; `run_id`: actual run identifier.
- `baseline_sha256`: `content_digest` of the retained `evaluation_results/production_closure/latency/qualification.local.json`.
- `profile.experiments`: existing benchmark page/semantic record format, a first `COLD_FIRST_PASS` and at least three `WARM_STEADY_STATE` runs. Every run must contain the entire frozen cohort in order, fresh OCR, unchanged semantic fingerprints, positive measured memory, and `full_claim_context_available: true`.
- `latency.P50`, `P95`, `P99`: nearest-rank percentiles of page `stages.total_ms`; `throughput_pages_per_second`: page count divided by summed page milliseconds, multiplied by 1000. The validator recomputes these and requires median warm P95 <=5000 ms.
- `runtime`: actual `host_id`, `cpu_model`, `logical_cpus`, `execution_provider`, `runtime_version`, `os`, and `gpu_model` (use the explicit string `NONE` for a CPU deployment).
- `ub04_canaries`: exactly three records with governed page IDs, `strict_family: UB04`, confirmed identity, canonical localization invoked, `critical_safety: PASS`, and `semantic_sha256` matching `cdp_services.ub04_canary_fingerprints` for that page. These must be measured observations. The retained 12-page benchmark has no UB04 pages, so its comparison alone cannot establish 3/3 canaries.
- `evidence_sha256`: `content_digest` of the complete payload excluding this seal field. A content seal checks integrity, while the configured deployment and pinned executor provide provenance.

Do not supply invented fingerprints, runtime characteristics, human labels, endpoints, or target measurements. The JSON contract is validated evidence, not permission to accelerate or alter extraction semantics. Shadow-only evidence cannot pass the complete production path gate.

The built-in raw/final executor can be configured with argv `[absolute_python_executable, absolute_repository/evaluation/deployment_control_executor.py]`; it resolves repository imports from its own path. Its configuration must explicitly name the governed qualification services and secret environment variables. `OPERATIONAL_PREFLIGHT`, `OPERATIONAL`, and `TARGET_LATENCY` require their own explicitly configured deployment executors; the raw/final executor does not simulate those tests.
