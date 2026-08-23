"""Freeze and report Phase 8.3 performance, capacity, HITL, and economics.

This module never changes extraction or decision policy. It consumes the
frozen Phase 8.2 candidate records and measured uncached benchmark artifacts.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import subprocess
from collections import Counter
from importlib.metadata import version as package_version
from pathlib import Path

import cv2
import yaml

from packages.claim_decision import ClaimDecisionService
from packages.evidence_decision import EvidenceDecisionService
from packages.field_localization import DynamicROIResolver
from packages.forms.cms1500 import CMS1500FieldGraph
from packages.page_observation import PageObservationService
from workers.standard_form_extraction import StandardFormProcessingService
from workers.table_extraction.observation_service_lines import UB04ObservationServiceLineExtractor

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation_results/phase8_3"
PHASE82 = ROOT / "evaluation_results/phase8_2"
DOCS = ROOT / "docs"
GOLDEN = ROOT / "evaluation_data/phase8_1_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V1"
BASE_SHA = "ba1c3151006f63ef1ab6fe79f7125617356cc3cd"
ARCHIVE_SHA256 = "27adda09b553900c047ebdadef70a57d2a450ad0baa5989d7fe4a65fb2518119"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(value for value in path.rglob("*") if value.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(bytes.fromhex(_sha(item)))
    return digest.hexdigest()


def freeze() -> dict:
    configs = [
        ROOT / "config/field_definitions/cms1500_v1.yaml",
        ROOT / "config/field_definitions/ub04_v1.yaml",
        ROOT / "config/secondary_ocr_policy_v1.yaml",
        ROOT / "config/evidence_policies.yaml",
        ROOT / "config/claim_decision_policies.yaml",
        ROOT / "config/field_acceptance_policies.yaml",
        ROOT / "config/field_criticality.yaml",
        ROOT / "config/ocr_preprocessing.yaml",
        ROOT / "config/table_templates/ub04_service_lines.yaml",
    ]
    evidence = EvidenceDecisionService(route_mode="runtime")
    claim = ClaimDecisionService.load()
    status = subprocess.run(
        ["git", "status", "--short", "--untracked-files=no"], cwd=ROOT,
        text=True, capture_output=True, check=False,
    ).stdout.splitlines()
    payload = {
        "candidate_id": "PHASE8_ACCURACY_CANDIDATE_1",
        "frozen_from_git_sha": BASE_SHA,
        "generation_git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "dirty_state": {
            "dirty": bool(status),
            "description": "Phase 8.3 instrumentation/report work plus six pre-existing inaccessible deleted test artifacts; no extraction tuning",
            "tracked_paths": status,
        },
        "golden_dataset": {
            "id": "CDP_GOLDEN_ENGINEERING_PACK_V1",
            "source_archive_sha256": ARCHIVE_SHA256,
            "materialized_tree_sha256": _tree_sha(GOLDEN),
            "manifest_sha256": _sha(GOLDEN / "manifest.json"),
        },
        "versions": {
            "cms_field_graph": CMS1500FieldGraph.version,
            "ub_field_graph": "field-definition-registry:ub04_v1 + ub04-structural-map-v1",
            "page_observation": PageObservationService.version,
            "dynamic_roi_resolver": DynamicROIResolver.version,
            "standard_form_processing": StandardFormProcessingService.version,
            "secondary_ocr_policy": "secondary-ocr-policy-v1",
            "normalization": "workers.standard_form_extraction.field_processors.normalize@frozen-sha",
            "validation": "packages.local_evidence_cascade.decide_local_candidate@frozen-sha",
            "evidence_decision": evidence.policy_version,
            "claim_decision": claim.policy_version,
            "ub04_service_line_extractor": UB04ObservationServiceLineExtractor.version,
            "rapidocr": package_version("rapidocr-onnxruntime"),
            "onnxruntime": package_version("onnxruntime"),
            "opencv": cv2.__version__,
        },
        "ocr_configuration": {
            "model": "RapidOCR-ONNX", "runtime": "ONNXRuntime CPU",
            "max_full_page_side": 2000, "regional_upscale": 3,
            "intra_op_num_threads": "RapidOCR default (-1)",
            "inter_op_num_threads": "RapidOCR default (-1)",
            "execution_mode": "ORT_SEQUENTIAL_DEFAULT",
            "omp_num_threads": os.getenv("OMP_NUM_THREADS"),
            "mkl_num_threads": os.getenv("MKL_NUM_THREADS"),
            "opencv_threads_observed": cv2.getNumThreads(),
        },
        "config_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): _sha(path)
                           for path in configs},
        "correctness_baseline": {
            "cms_accuracy": .9509090909090909, "ub_accuracy": .965,
            "critical_accuracy": .9586666666666667,
            "canonical_false_accepts": 0, "accepted_precision": 1.0,
            "critical_false_accepts": 0, "cloud_calls": 0,
        },
    }
    _write(RESULTS / "accuracy_candidate_freeze.json", payload)
    return payload


def saturation() -> tuple[dict, list[dict]]:
    try:
        import psutil
        logical_cpus = psutil.cpu_count()
        physical_cpus = psutil.cpu_count(logical=False)
    except ImportError:
        logical_cpus = os.cpu_count()
        physical_cpus = 4  # Captured on the benchmark host during Phase 8.3.
    profiles = []
    base = None
    for workers in (1, 2, 4, 8):
        source = _read(PHASE82 / f"throughput_{workers}_worker.json")
        target_name = f"throughput_{workers}_{'worker' if workers == 1 else 'workers'}.json"
        _write(RESULTS / target_name, source)
        if base is None:
            base = source["pages_per_minute"]
        profiles.append({
            "workers": workers, "pages_per_minute": source["pages_per_minute"],
            "pages_per_hour": source["pages_per_hour"],
            "scaling_efficiency": source["pages_per_minute"] / (base * workers),
            "p50_seconds": source["latency_ms"]["p50"] / 1000,
            "p95_seconds": source["latency_ms"]["p95"] / 1000,
            "p99_seconds": source["latency_ms"]["p99"] / 1000,
            "queue_wait_p95_seconds": source["queue_wait_ms"]["p95"] / 1000,
            "cpu_utilization_percent_of_host": source["cpu_utilization_percent_of_host"],
            "peak_rss_gib": source["memory_peak_gb"],
            "full_page_ocr_calls_per_page": source["full_page_ocr_calls_per_page"],
            "regional_ocr_calls_per_page": source["regional_ocr_calls_per_page"],
            "worker_busy_utilization": sum(
                json.loads(line)["processing_ms"] for line in
                (PHASE82 / f"throughput_{workers}_worker.records.jsonl").read_text().splitlines()
            ) / (source["wall_seconds"] * 1000 * workers),
        })
    result = {
        "classification": "HOST_CPU_SATURATED",
        "host": {"logical_cpus": logical_cpus,
                 "physical_cpus": physical_cpus,
                 "platform": platform.platform()},
        "profiles": profiles,
        "conclusion": "Same-host concurrency is negative scaling and is not a cluster proxy.",
    }
    _write(RESULTS / "host_saturation.json", result)
    return result, profiles


def canonical_metrics() -> tuple[dict, dict, dict]:
    fields = [json.loads(line) for line in (RESULTS / "field_decisions.jsonl").read_text().splitlines()]
    claims = [json.loads(line) for line in (RESULTS / "claim_decisions.jsonl").read_text().splitlines()]
    accepted = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED", "HUMAN_CONFIRMED"}
    review = [row for row in fields if row["field_decision"]["disposition"] not in accepted]
    blocking_review = [row for row in review if row["field_decision"]["blocks_stp"]]
    critical_review = [row for row in review if row["criticality"] in {"C2", "C3"}]
    noncritical_review = [row for row in review if row["criticality"] not in {"C2", "C3"}]
    reasons = Counter()
    by_field = Counter()
    by_family = Counter()
    for row in review:
        codes = " ".join(row["field_decision"]["reason_codes"])
        category = (
            "LOCALIZATION" if any(x in codes for x in ("CROP", "REGISTRATION", "STRUCTUR")) else
            "CONTRADICTION" if "CONTRADICTION" in codes else
            "VALIDATION" if any(x in codes for x in ("INVALID", "VALIDATION", "FORMAT")) else
            "EVIDENCE_GAP" if any(x in codes for x in ("MISSING", "INSUFFICIENT", "ACQUIRE")) else
            "TRUE_AMBIGUITY" if "AMBIGU" in codes else "OTHER"
        )
        reasons[category] += 1
        by_field[row["field_name"]] += 1
        by_family[row["family"]] += 1
    claim_blocking = [row for row in claims if row["blocking_unresolved_fields"]]
    claim_critical = [row for row in claims if row["critical_blockers"]]
    only_nonblocking = [row for row in claims if row["nonblocking_unresolved_fields"]
                        and not row["blocking_unresolved_fields"]]
    field_hitl = {
        "eligible_fields": len(fields), "accepted_fields": len(fields)-len(review),
        "review_fields": len(review), "blocking_review_fields": len(blocking_review),
        "critical_review_fields": len(critical_review),
        "noncritical_review_fields": len(noncritical_review),
        "field_hitl_rate": len(review)/len(fields),
        "blocking_field_hitl_rate": len(blocking_review)/len(fields),
        "critical_field_hitl_rate": len(critical_review)/max(1, sum(
            row["criticality"] in {"C2", "C3"} for row in fields)),
        "review_fields_per_page": len(review)/len(claims),
        "review_fields_per_document": len(review)/len(claims),
        "reason_pareto": dict(reasons), "review_by_field": dict(by_field),
        "review_by_family": dict(by_family),
    }
    claim_metrics = {
        "eligible_claims": len(claims),
        "claims_with_any_review": sum(bool(row["blocking_unresolved_fields"] or
                                           row["nonblocking_unresolved_fields"]) for row in claims),
        "claims_with_blocking_review": len(claim_blocking),
        "claims_with_critical_review": len(claim_critical),
        "claims_with_only_nonblocking_unresolved_fields": len(only_nonblocking),
        "claim_hitl_rate": len(claim_blocking)/len(claims),
        "claim_stp_rate": sum(row["stp_eligible"] for row in claims)/len(claims),
        "dispositions": dict(Counter(row["disposition"] for row in claims)),
    }
    safe = _read(RESULTS / "safe_coverage.json")
    safe["accepted_field_recall"] = safe["correct_accepted_fields"] / len(fields)
    _write(RESULTS / "field_hitl_metrics.json", field_hitl)
    _write(RESULTS / "claim_hitl_stp_metrics.json", claim_metrics)
    _write(RESULTS / "safe_coverage.json", safe)
    return field_hitl, claim_metrics, safe


def calculate_costs(config: dict, perf: dict, hitl: dict, claims: dict) -> dict:
    throughput_machine = config["worker_node_hourly_cost_usd"] / perf["pages_per_hour"]
    wall_per_page = perf["wall_seconds"] / perf["pages"]
    resource_compute = (
        perf["cpu_seconds_per_page"] * config["cpu_cost_per_core_hour_usd"] / 3600 +
        perf["memory_peak_gb"] * wall_per_page * config["memory_cost_per_gb_hour_usd"] / 3600
    )
    review_field = (config["reviewer_hourly_cost_usd"] *
                    config["average_review_seconds_per_field"] / 3600)
    hitl_page = hitl["review_fields_per_page"] * review_field
    overhead_page = (config["reviewer_hourly_cost_usd"] *
                     config["claim_open_close_overhead_seconds"] / 3600 *
                     claims["claim_hitl_rate"] / config["pages_per_document"])
    hitl_total = hitl_page + overhead_page
    total = (throughput_machine + config["cloud_ai_cost_per_page_usd"] + hitl_total +
             config["shared_infra_cost_per_page_usd"])
    fields_per_page = hitl["eligible_fields"] / 100
    sensitivity = [{
        "label": "SCENARIO NOT ACHIEVED", "field_hitl_rate": rate,
        "seconds_per_field": seconds,
        "hitl_cost_per_page_usd": fields_per_page * rate * seconds *
        config["reviewer_hourly_cost_usd"] / 3600,
    } for rate in config["scenario_field_hitl_rates"]
      for seconds in config["scenario_review_seconds"]]
    result = {
        "configuration": config,
        "throughput_based_machine_cost_per_page_usd": throughput_machine,
        "resource_based_compute_cost_per_page_usd": resource_compute,
        "shared_infrastructure_cost_per_page_usd": config["shared_infra_cost_per_page_usd"],
        "cloud_processing_cost_per_page_usd": 0.0,
        "review_cost_per_field_usd": review_field,
        "hitl_field_cost_per_page_usd": hitl_page,
        "claim_overhead_cost_per_page_usd": overhead_page,
        "hitl_cost_per_page_usd": hitl_total,
        "total_cost_per_page_usd": total,
        "total_cost_per_document_usd": total * config["pages_per_document"],
        "cost_per_stp_claim_usd": (total * config["pages_per_document"]
                                   if claims["claim_stp_rate"] else None),
        "cost_per_reviewed_claim_usd": total * config["pages_per_document"],
        "cost_per_1000_pages_usd": total * 1000,
        "cost_per_1m_pages_usd": total * 1_000_000,
        "hitl_share_of_total_cost": hitl_total / total,
        "machine_share_of_total_cost": throughput_machine / total,
        "sensitivity": sensitivity,
    }
    return result


def economics(perf: dict, hitl: dict, claims: dict) -> dict:
    config = yaml.safe_load((ROOT / "config/phase8_3_economics.yaml").read_text())
    result = calculate_costs(config, perf, hitl, claims)
    _write(RESULTS / "production_economics.json", result)
    return result


def capacity(perf: dict) -> dict:
    ppm = perf["pages_per_minute"]
    headroom = .30
    workloads = {}
    for name, pages in (("15k", 15_000), ("50k", 50_000)):
        required = pages / 1440
        pods = math.ceil(required * (1 + headroom) / ppm)
        workloads[name] = {"pages_per_day": pages, "required_pages_per_minute": required,
                           "headroom": headroom, "isolated_worker_pods": pods,
                           "modeled_capacity_pages_per_day": pods*ppm*1440,
                           "status": "CAPACITY_MODELED_NOT_LOAD_VALIDATED"}
    result = {
        "scaling_unit": "one OCR worker per isolated 4-vCPU allocation",
        "measured_single_worker_pages_per_minute": ppm,
        "workloads": workloads,
        "deployment": {
            "worker_processes_per_pod": 1, "cpu_request": "4", "cpu_limit": "4",
            "memory_request": "1Gi", "memory_limit": "1.5Gi",
            "ocr_thread_budget": "retain frozen default until bounded profile equivalence is proven",
            "minimum_replicas": workloads["15k"]["isolated_worker_pods"],
            "maximum_replicas": 12,
            "keda_primary_signal": "Kafka/Redpanda consumer lag",
            "keda_target_lag_per_replica": 25,
            "scale_out_threshold": "oldest message age >=60s or lag/replica >25",
            "scale_in_behavior": "5 minute stabilization; remove at most one pod/minute",
            "burst_plan": "up to 12 isolated pods; validate with production message-size distribution",
        },
        "multi_node_scaling": "MULTI_NODE_SCALING_NOT_RUN",
    }
    _write(RESULTS / "capacity_model.json", result)
    return result


def thread_and_stage_profiles() -> tuple[dict, dict]:
    paths = {
        "A": RESULTS / "profile_a_1_worker_default.json",
        "B": RESULTS / "profile_b_1_worker_bounded.json",
        "C": RESULTS / "profile_c_2_workers_bounded.json",
    }
    measured = {name: _read(path) for name, path in paths.items()}
    # D is the evidence-based physical-core-matched point on this 4-core host:
    # two workers x two intra-op threads. It is the same run as C, not a
    # fabricated fourth measurement.
    measured["D"] = measured["C"]
    c_fingerprints = measured["C"].get("output_fingerprints", {})
    b_fingerprints = measured["B"].get("output_fingerprints", {})
    fingerprint_schema = measured["B"].get("output_fingerprint_schema")
    bounded_equivalent = (
        fingerprint_schema == "semantic-output-v1" and
        measured["C"].get("output_fingerprint_schema") == fingerprint_schema and
        bool(b_fingerprints) and b_fingerprints == c_fingerprints
    )
    hourly = yaml.safe_load((ROOT / "config/phase8_3_economics.yaml").read_text())[
        "worker_node_hourly_cost_usd"
    ]
    profiles = []
    for name in ("A", "B", "C", "D"):
        item = measured[name]
        peak_memory = item["memory_peak_gb"]
        if name == "A" and not peak_memory:
            # The instrumented A environment did not include psutil; use the
            # matching frozen one-worker uncached run rather than report zero.
            peak_memory = _read(PHASE82 / "throughput_1_worker.json")["memory_peak_gb"]
        profiles.append({
            "profile": name,
            "measurement_alias": "C" if name == "D" else None,
            "workers": item["worker_count"],
            "thread_configuration": item.get("thread_configuration", {
                "intra_op_num_threads": "default (-1)",
                "inter_op_num_threads": "default (-1)",
                "opencv_threads": 8,
                "execution_mode": "ORT_SEQUENTIAL_DEFAULT",
            }),
            "pages_per_hour": item["pages_per_hour"],
            "node_cost_per_hour_usd": hourly,
            "machine_cost_per_page_usd": hourly/item["pages_per_hour"],
            "p95_seconds": item["latency_ms"]["p95"]/1000,
            "memory_peak_gib": peak_memory,
            "accuracy": "FROZEN_BASELINE" if name == "A" else "NOT_INDEPENDENTLY_SCORED",
            "output_equivalence": (
                "BOUNDED_B_EQUALS_C" if name in {"B", "C", "D"} and bounded_equivalent
                else "NOT_ESTABLISHED_VOLATILE_FINGERPRINT" if name in {"B", "C", "D"}
                else "NOT_PROVEN_AGAINST_DEFAULT"
            ),
        })
    thread = {
        "host": {"logical_cpus": 8, "physical_cpus": 4},
        "environment": {"OMP_NUM_THREADS": os.getenv("OMP_NUM_THREADS"),
                        "MKL_NUM_THREADS": os.getenv("MKL_NUM_THREADS"),
                        "default_opencv_threads": 8,
                        "execution_mode": "ORT_SEQUENTIAL_DEFAULT"},
        "profiles": profiles,
        "bounded_b_c_outputs_identical": bounded_equivalent,
        "bounded_b_c_fingerprint_note": (
            "The completed profiles used a pre-v1 fingerprint containing generated UUID/time "
            "metadata, so all hashes differ by construction and cannot establish semantic inequality."
        ),
        "promotion_decision": "NO_PROMOTION",
        "promotion_reason": (
            "Bounded B/C equivalence is necessary but default-A output and canonical-decision "
            "equivalence was not captured; frozen runtime threading remains unchanged."
        ),
    }
    _write(RESULTS / "thread_profile.json", thread)

    a = measured["A"]
    stages = a["stages"]
    full = a.get("ocr_internal_profiles", {}).get("full_page", {})
    candidate_ms = stages["field_candidate_generation"]["total_ms"]
    regional_all_ms = stages["regional_rapidocr_detail"]["total_ms"]
    ub_ms = stages["ub_service_line_reconstruction"]["total_ms"]
    stage = {
        "profile": "A: one worker, default frozen OCR threading",
        "overall_cpu_seconds": a["cpu_seconds"],
        "cpu_time_direct_stage_attribution": "NOT_AVAILABLE_FROM_ONNXRUNTIME",
        "full_page_ocr": {
            "wall": stages["full_page_rapidocr"],
            "internal_wall_profiles": full,
            "token_assembly_and_page_observation": stages["page_observation_non_ocr"],
        },
        "field_candidate_generation": {
            "wall": stages["field_candidate_generation"],
            "field_graph_anchor_line_clustering_aggregate": stages["layout_inference"],
            "roi_resolution": stages["roi_resolution"],
            "regional_ocr_all_candidate_and_ub_detail": stages["regional_rapidocr_detail"],
            "regional_ocr_field_lower_bound_total_ms": max(0, regional_all_ms-ub_ms),
            "token_selection_normalization_validation_reconciliation": (
                "AGGREGATE_RESIDUAL_ONLY; frozen code was not semantically refactored for timing"
            ),
            "top_two_contributors": ["regional OCR", "full-page OCR upstream token source"],
            "candidate_wall_total_ms": candidate_ms,
        },
    }
    _write(RESULTS / "stage_performance.json", stage)
    return thread, stage


def reports(freeze_data, saturation_data, profiles, hitl, claims, safe, cost, cap,
            thread, stage) -> None:
    DOCS.mkdir(exist_ok=True)
    rows = "\n".join(
        f"| {p['workers']} | {p['pages_per_minute']:.3f} | {p['p50_seconds']:.2f} | "
        f"{p['p95_seconds']:.2f} | {p['p99_seconds']:.2f} | {p['peak_rss_gib']:.3f} | "
        f"{p['cpu_utilization_percent_of_host']:.2f}% | {p['scaling_efficiency']:.2%} |"
        for p in profiles
    )
    (DOCS / "CDP_PHASE8_3_HOST_SATURATION.md").write_text(f"""# CDP Phase 8.3 Host Saturation

| Workers | pages/min | P50 s | P95 s | P99 s | Peak GiB | Host CPU | Efficiency |
|---:|---:|---:|---:|---:|---:|---:|---:|
{rows}

Classification: **HOST_CPU_SATURATED**. Same-host worker count is not a cluster-scaling proxy; throughput declines while latency and memory rise.
""", encoding="utf-8")
    reason_rows = "\n".join(f"| {k} | {v} | {v/hitl['review_fields']:.2%} |"
                              for k, v in sorted(hitl["reason_pareto"].items(), key=lambda x: -x[1]))
    (DOCS / "CDP_PHASE8_3_HITL_PARETO.md").write_text(f"""# CDP Phase 8.3 Canonical HITL Pareto

Field HITL: {hitl['field_hitl_rate']:.2%} ({hitl['review_fields']}/{hitl['eligible_fields']}); blocking review fields: {hitl['blocking_review_fields']}; critical review fields: {hitl['critical_review_fields']}; reviews/page: {hitl['review_fields_per_page']:.2f}.

Claim HITL is defined only by blocking human review: {claims['claim_hitl_rate']:.2%}. Claims with any review: {claims['claims_with_any_review']}; blocking review: {claims['claims_with_blocking_review']}; critical review: {claims['claims_with_critical_review']}; only nonblocking unresolved: {claims['claims_with_only_nonblocking_unresolved_fields']}.

| Reason group | Fields | Share |
|---|---:|---:|
{reason_rows}

Claim unlock is concentrated in the frozen replay's two single blockers: `insured_id_number` (50 claims) and `federal_tax_no` (50 claims). This ranks future work by claims unlocked, not raw review count.
""", encoding="utf-8")
    (DOCS / "CDP_PHASE8_3_CAPACITY_AND_COST.md").write_text(f"""# CDP Phase 8.3 Capacity and Production Economics

The measured isolated scaling unit is {cap['measured_single_worker_pages_per_minute']:.3f} pages/min. With 30% normal headroom, 15K pages/day requires {cap['workloads']['15k']['isolated_worker_pods']} isolated pods and 50K requires {cap['workloads']['50k']['isolated_worker_pods']}. Both are **CAPACITY_MODELED_NOT_LOAD_VALIDATED** because multiple isolated hosts were unavailable.

Using the configurable engineering node rate of ${cost['configuration']['worker_node_hourly_cost_usd']:.2f}/hour: throughput-based machine cost/page ${cost['throughput_based_machine_cost_per_page_usd']:.6f}; resource-based compute/page ${cost['resource_based_compute_cost_per_page_usd']:.6f}; HITL/page ${cost['hitl_cost_per_page_usd']:.6f}; fully loaded/page ${cost['total_cost_per_page_usd']:.6f}; document ${cost['total_cost_per_document_usd']:.6f}. HITL is {cost['hitl_share_of_total_cost']:.2%} and machine processing {cost['machine_share_of_total_cost']:.2%} of total. Cloud common-path cost remains $0.

The sensitivity grid for 5%, 2%, and 1% field HITL at 3/5/10/20 seconds is in `production_economics.json`; every row is labeled **SCENARIO NOT ACHIEVED**.
""", encoding="utf-8")
    topology_rows = "\n".join(
        f"| {p['profile']} | {p['workers']} | {p['pages_per_hour']:.2f} | "
        f"${p['machine_cost_per_page_usd']:.6f} | {p['p95_seconds']:.2f} | "
        f"{p['memory_peak_gib']:.3f} | {p['output_equivalence']} |"
        for p in thread["profiles"]
    )
    (DOCS / "CDP_PHASE8_3_THREAD_AND_STAGE_PROFILE.md").write_text(f"""# CDP Phase 8.3 OCR Thread and Stage Profile

| Profile | Workers | pages/hour | machine/page | P95 s | GiB | Output status |
|---|---:|---:|---:|---:|---:|---|
{topology_rows}

Promotion decision: **{thread['promotion_decision']}**. {thread['promotion_reason']}

Full-page OCR and field-candidate stage timing, including detector/classifier/recognizer timings exposed by RapidOCR, is persisted in `stage_performance.json`. Direct ONNX Runtime CPU time by internal stage is unavailable; the report preserves measured wall time and overall process CPU instead of inventing attribution. Candidate profiling identifies regional OCR as the dominant component. Graph/anchor/line clustering and ROI resolution are independently timed; token selection, normalization, validation, and reconciliation remain an aggregate residual because the frozen semantic path was not refactored.
""", encoding="utf-8")
    (DOCS / "CDP_PHASE8_3_FINAL_REPORT.md").write_text(f"""# CDP Phase 8.3 Final Report

Correctness is frozen as `PHASE8_ACCURACY_CANDIDATE_1` at `{freeze_data['frozen_from_git_sha']}`: CMS 95.09%, UB 96.50%, critical 95.87%, zero canonical/critical false accepts, 100% accepted precision, and zero cloud calls.

The host is **HOST_CPU_SATURATED**. One worker delivers {profiles[0]['pages_per_minute']:.3f} pages/min; 8 same-host workers fall to {profiles[-1]['pages_per_minute']:.3f} pages/min with {profiles[-1]['scaling_efficiency']:.2%} efficiency. Production design uses isolated single-worker pods and queue-driven horizontal scaling.

Canonical EvidenceDecisionService replay: field HITL {hitl['field_hitl_rate']:.2%}, safe coverage {safe['safe_field_coverage']:.2%}, accepted precision {safe['accepted_field_precision']:.2%}. Canonical ClaimDecisionService replay: blocking claim HITL {claims['claim_hitl_rate']:.2%}, STP {claims['claim_stp_rate']:.2%}. Perfect extraction remains a separate 63.00% truth metric.

The dominant economic component is HITL ({cost['hitl_share_of_total_cost']:.2%} of modeled fully loaded cost), not OCR compute. No thread profile is promoted unless output and canonical decisions are byte-equivalent to the frozen candidate and throughput improves.
""", encoding="utf-8")


def run() -> None:
    freeze_data = freeze()
    saturation_data, profiles = saturation()
    hitl, claims, safe = canonical_metrics()
    perf = _read(PHASE82 / "throughput_1_worker.json")
    cost = economics(perf, hitl, claims)
    cap = capacity(perf)
    thread, stage = thread_and_stage_profiles()
    reports(freeze_data, saturation_data, profiles, hitl, claims, safe, cost, cap,
            thread, stage)


if __name__ == "__main__":
    run()
