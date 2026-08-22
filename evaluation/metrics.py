"""Claims-specific accuracy, safety, review and fallback metrics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from evaluation.matcher import match_fields
from evaluation.normalizers import NormalizerRegistry
from evaluation.schemas import GroundTruthDataset, PredictionDataset


def _rate(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def character_error_rate(expected: str | None, actual: str | None) -> float:
    a, b = expected or "", actual or ""
    if not a:
        return 0.0 if not b else 1.0
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1] / len(a)


@dataclass
class Mismatch:
    document_id: str
    form_type: str
    field_name: str
    expected_value: str | None
    extracted_value: str | None
    normalized_value: str | None
    ocr_confidence: float | None
    validation_result: str
    extraction_method: str
    bounding_box: dict | None
    crop_reference: str | None
    failure_category: str


@dataclass
class EvaluationMetrics:
    field_count: int
    raw_exact_match_accuracy: float
    normalized_field_accuracy: float
    critical_field_accuracy: float
    character_error_rate: float
    missing_field_rate: float
    false_accept_rate: float
    critical_false_accept_rate: float
    false_review_rate: float
    perfect_claim_rate: float
    straight_through_processing_rate: float | None
    hitl_rate: float | None
    accuracy_before_fallback: float
    accuracy_after_fallback: float
    handwriting_accuracy: float
    printed_text_accuracy: float
    human_review_rate: float | None
    average_latency_ms_per_page: float
    average_cost_usd_per_page: float
    accuracy_after_stage: dict[str, float] = field(default_factory=dict)
    accuracy_by_field: dict[str, float] = field(default_factory=dict)
    accuracy_by_form_type: dict[str, float] = field(default_factory=dict)
    accuracy_by_extraction_method: dict[str, float] = field(default_factory=dict)
    accuracy_by_image_quality_bucket: dict[str, float] = field(default_factory=dict)
    mismatches: list[Mismatch] = field(default_factory=list)


def evaluate(
    truth: GroundTruthDataset,
    predictions: PredictionDataset,
    registry: NormalizerRegistry | None = None,
) -> EvaluationMetrics:
    registry = registry or NormalizerRegistry()
    pairs = match_fields(truth, predictions)
    raw_correct = normalized_correct = critical_correct = critical_count = missing = 0
    accepted = false_accepts = critical_accepted = critical_false_accepts = 0
    reviewed = false_reviews = 0
    before_correct = after_correct = 0
    handwriting_results: list[bool] = []
    printed_results: list[bool] = []
    stage_results: dict[str, list[bool]] = defaultdict(list)
    page_latency: dict[str, float] = defaultdict(float)
    page_cost: dict[str, float] = defaultdict(float)
    cer_total = 0.0
    grouped: dict[str, dict[str, list[bool]]] = {
        key: defaultdict(list) for key in ("field", "form", "method", "quality")
    }
    claim_results: dict[str, list[bool]] = defaultdict(list)
    claim_reviewed: dict[str, bool] = defaultdict(bool)
    mismatches: list[Mismatch] = []

    for pair in pairs:
        prediction = pair.prediction
        expected_raw = pair.truth.expected_raw
        expected_normalized = pair.truth.expected_normalized
        if expected_normalized is None:
            expected_normalized = registry.normalize(pair.truth.field_name, expected_raw)
        actual_raw = prediction.raw_value if prediction else None
        actual_normalized = prediction.normalized_value if prediction else None
        if actual_normalized is None:
            actual_normalized = registry.normalize(pair.truth.field_name, actual_raw)
        raw_ok = (expected_raw or "") == (actual_raw or "")
        normalized_ok = (expected_normalized or "") == (actual_normalized or "")
        raw_correct += raw_ok
        normalized_correct += normalized_ok
        missing += prediction is None or (actual_raw is None and actual_normalized is None)
        cer_total += character_error_rate(expected_raw, actual_raw)
        if pair.truth.critical:
            critical_count += 1
            critical_correct += normalized_ok
        method = prediction.extraction_method if prediction else "MISSING"
        grouped["field"][pair.truth.field_name].append(normalized_ok)
        grouped["form"][pair.document.form_type].append(normalized_ok)
        grouped["method"][method].append(normalized_ok)
        grouped["quality"][pair.document.image_quality_bucket].append(normalized_ok)
        claim_results[pair.document.document_id].append(normalized_ok)
        if prediction and prediction.accepted:
            accepted += 1
            false_accepts += not normalized_ok
            if pair.truth.critical:
                critical_accepted += 1
                critical_false_accepts += not normalized_ok
        if prediction and prediction.reviewed:
            reviewed += 1
            false_reviews += normalized_ok
            claim_reviewed[pair.document.document_id] = True
        if prediction and prediction.fallback_used:
            before = registry.normalize(pair.truth.field_name, prediction.before_fallback_value)
            before_correct += (expected_normalized or "") == (before or "")
        else:
            before_correct += normalized_ok
        after_correct += normalized_ok
        stage = (
            str(prediction.metadata.get("cascade_stage", prediction.extraction_method))
            if prediction else "MISSING"
        )
        stage_results[stage].append(normalized_ok)
        if prediction:
            page_latency[pair.document.document_id] += float(
                prediction.metadata.get("latency_ms", 0) or 0
            )
            page_cost[pair.document.document_id] += float(
                prediction.metadata.get("cost_usd", 0) or 0
            )
            if "trocr" in prediction.extraction_method.lower() or prediction.metadata.get(
                "writing_type"
            ) in {"HANDWRITTEN", "MIXED"}:
                handwriting_results.append(normalized_ok)
            else:
                printed_results.append(normalized_ok)
        if not normalized_ok:
            category = "MISSING" if prediction is None or actual_raw is None else (
                "FALSE_ACCEPT" if prediction.accepted else "MISMATCH"
            )
            bbox = prediction.bounding_box.model_dump() if prediction and prediction.bounding_box else None
            mismatches.append(Mismatch(
                pair.document.document_id, pair.document.form_type, pair.truth.field_name,
                expected_normalized, actual_raw, actual_normalized,
                prediction.confidence if prediction else None,
                prediction.validation_result if prediction else "NOT_EXTRACTED", method, bbox,
                prediction.crop_reference if prediction else None, category,
            ))

    total = len(pairs)
    claims = len(claim_results)
    perfect = sum(all(results) for results in claim_results.values())
    canonical_decisions = {
        document.document_id: document.claim_decision
        for document in predictions.documents
        if document.claim_decision is not None
    }
    canonical_complete = bool(claim_results) and all(
        document_id in canonical_decisions for document_id in claim_results
    )
    stp_rate = (
        _rate(sum(canonical_decisions[doc_id].stp_eligible for doc_id in claim_results), claims)
        if canonical_complete else None
    )
    hitl_rate = (1 - stp_rate) if stp_rate is not None else None
    return EvaluationMetrics(
        total, _rate(raw_correct, total), _rate(normalized_correct, total),
        _rate(critical_correct, critical_count), _rate(round(cer_total * 1_000_000), total * 1_000_000),
        _rate(missing, total), _rate(false_accepts, accepted),
        _rate(critical_false_accepts, critical_accepted), _rate(false_reviews, reviewed),
        _rate(perfect, claims), stp_rate, hitl_rate,
        _rate(before_correct, total), _rate(after_correct, total),
        _rate(sum(handwriting_results), len(handwriting_results)),
        _rate(sum(printed_results), len(printed_results)),
        hitl_rate,
        _rate(round(sum(page_latency.values())), claims),
        _rate(sum(page_cost.values()), claims),
        {stage: _rate(sum(values), len(values)) for stage, values in stage_results.items()},
        {key: _rate(sum(values), len(values)) for key, values in grouped["field"].items()},
        {key: _rate(sum(values), len(values)) for key, values in grouped["form"].items()},
        {key: _rate(sum(values), len(values)) for key, values in grouped["method"].items()},
        {key: _rate(sum(values), len(values)) for key, values in grouped["quality"].items()},
        mismatches,
    )
