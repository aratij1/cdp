"""Strangler boundary: read canonical results, return a separate shadow result."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from packages.domain.claim import Claim

from .discovery import DiscoveryResult, NoncanonicalDiscovery
from .document import DocumentPage, fingerprint
from .models import (
    AuthorityState,
    Candidate,
    CandidateEvidence,
    ClaimGraph,
    EvidenceFeatures,
    FieldNode,
    ServiceLine,
)
from .normalization import money, normalize
from .shadow import CDP2ShadowEngine, ShadowClaimResult
from .spatial import IDENTITY_FIELDS, SpatialCandidateExtractor, merge_candidates
from .telemetry import PerformanceProfile


@dataclass(frozen=True)
class LegacyFieldResult:
    field_name: str
    canonical_value: str | None
    accepted: bool
    candidates: tuple[Candidate, ...]
    technical_blockers: tuple[str, ...] = ()
    evidence_blockers: tuple[str, ...] = ()
    critical: bool = False
    wrong_crop: bool = False
    missing_crop: bool = False


@dataclass(frozen=True)
class LegacyResult:
    claim_id: str
    fields: tuple[LegacyFieldResult, ...]
    canonical_sha256: str
    form_type: str
    page_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShadowComparison:
    legacy: LegacyResult
    cdp2: ShadowClaimResult
    legacy_metrics: dict[str, int | bool]
    cdp2_metrics: dict[str, int | bool]
    profile: dict[str, Any]
    discovery_candidates: tuple[DiscoveryResult, ...] = ()
    runtime_authority: bool = field(default=False, init=False)


def unlock(technical: int, evidence: int, critical: int) -> dict[str, int | bool]:
    if min(technical, evidence, critical) < 0:
        raise ValueError("NEGATIVE_BLOCKERS")
    return {
        "technical_blockers": technical,
        "evidence_blockers": evidence,
        "critical_blockers": critical,
        "technical_unlock_distance": technical,
        "production_unlock_distance": technical + evidence,
        "engineering_unlockable": technical == 0,
        "production_unlockable": False,
        "CDP_CONTROLLED_HITL": technical,
        "technical_hitl": technical,
        "evidence_hitl": evidence,
        "total_hitl": technical + evidence,
    }


def assert_same_claims(
    legacy: tuple[LegacyResult, ...], shadow: tuple[ShadowClaimResult, ...]
) -> None:
    left, right = [r.claim_id for r in legacy], [r.claim_id for r in shadow]
    if (
        len(left) != len(set(left))
        or len(right) != len(set(right))
        or sorted(left) != sorted(right)
    ):
        raise ValueError("SAME_CLAIM_DENOMINATOR_MISMATCH")
    fields = {r.claim_id: sorted(f.field_name for f in r.fields) for r in legacy}
    if any(fields[r.claim_id] != sorted(f.field_name for f in r.fields) for r in shadow):
        raise ValueError("SAME_FIELD_DENOMINATOR_MISMATCH")


class CDP2ShadowPipeline:
    def __init__(self) -> None:
        self.spatial = SpatialCandidateExtractor()
        self.discovery = NoncanonicalDiscovery()
        self.engine = CDP2ShadowEngine()

    def compare(
        self, legacy: LegacyResult, graph: ClaimGraph, pages: tuple[DocumentPage, ...] = ()
    ) -> ShadowComparison:
        if legacy.claim_id != graph.claim_id or {f.field_name for f in legacy.fields} != set(
            graph.fields
        ):
            raise ValueError("SAME_CLAIM_OR_FIELD_MISMATCH")
        if pages and (
            set(graph.page_ids) != {p.page_id for p in pages}
            or any(p.package_id != graph.package_id for p in pages)
        ):
            raise ValueError("CLAIM_PAGE_PACKAGE_MISMATCH")
        before = fingerprint(legacy)
        profile = PerformanceProfile()
        with profile.measure("claim_graph_ms"):
            working = copy.deepcopy(graph)
        with profile.measure("spatial_reasoning_ms"):
            observed = [self.spatial.extract(page) for page in pages]
            discoveries = tuple(
                self.discovery.extract(page)
                for page in pages
                if page.form_type == "OTHER_CLAIM_FORM"
            )
        with profile.measure("candidate_assembly_ms"):
            for spatial_result in observed:
                for name, candidates in spatial_result.items():
                    if name in working.fields:
                        working.fields[name].candidates = merge_candidates(
                            [*working.fields[name].candidates, *candidates]
                        )
        shadow = self.engine.evaluate(working, profile)
        assert_same_claims((legacy,), (shadow,))
        technical = sum(len(f.technical_blockers) for f in legacy.fields)
        evidence = sum(len(f.evidence_blockers) for f in legacy.fields)
        critical = sum(
            f.critical and bool(f.technical_blockers or f.evidence_blockers) for f in legacy.fields
        )
        old = unlock(technical, evidence, critical)
        old["CDP_CONTROLLED_HITL"] = old["technical_hitl"] = sum(
            bool(f.technical_blockers) for f in legacy.fields
        )
        old["evidence_hitl"] = sum(bool(f.evidence_blockers) for f in legacy.fields)
        old["total_hitl"] = sum(
            bool(f.evidence_blockers or f.technical_blockers) for f in legacy.fields
        )
        old["candidate_ambiguity"] = sum(
            max(0, len({c.normalized_value or c.value for c in f.candidates}) - 1)
            for f in legacy.fields
        )
        old["wrong_crop_dependence"] = sum(f.wrong_crop for f in legacy.fields)
        old["missing_crop_dependence"] = sum(f.missing_crop for f in legacy.fields)
        by_name = {f.field_name: f for f in shadow.fields}
        remaining = wrong = missing = new_critical = technical_fields = total_fields = 0
        for f in legacy.fields:
            result = by_name[f.field_name]
            selected = next(
                (
                    c
                    for c in working.fields[f.field_name].candidates
                    if c.candidate_id == result.proposed_candidate_id
                ),
                None,
            )
            # Crop blockers require a supported spatial alternative, not reuse of a bad crop.
            spatial = selected is not None and all(
                e.source == "SPATIAL_EXTRACTION" for e in selected.evidence
            )
            resolved = result.decision.extraction_supported
            blockers = [
                b
                for b in f.technical_blockers
                if not (
                    resolved and (b not in {"WRONG_CROP", "MISSING_CROP", "EMPTY_CROP"} or spatial)
                )
            ]
            remaining += len(blockers)
            technical_fields += bool(blockers)
            total_fields += bool(blockers or f.evidence_blockers)
            wrong += f.wrong_crop and not (resolved and spatial)
            missing += f.missing_crop and not (resolved and spatial)
            new_critical += f.critical and bool(blockers or f.evidence_blockers)
        # Contradictions without a represented field remain claim-level evidence blockers.
        global_conflicts = [
            r
            for r in self.engine.consistency.evaluate(working)
            if r.verdict == "CONFLICT" and r.field_name not in working.fields
        ]
        new = unlock(
            remaining, evidence + len(global_conflicts), new_critical + len(global_conflicts)
        )
        new["CDP_CONTROLLED_HITL"] = new["technical_hitl"] = technical_fields
        new["evidence_hitl"] = old["evidence_hitl"]
        new["total_hitl"] = total_fields
        new["candidate_ambiguity"] = sum(
            max(0, len({c.normalized_value or c.value for c in n.candidates}) - 1)
            for n in working.fields.values()
        )
        new["wrong_crop_dependence"], new["missing_crop_dependence"] = wrong, missing
        with profile.measure("serialization_ms"):
            fingerprint(shadow)
        if before != fingerprint(legacy):
            raise RuntimeError("LEGACY_RESULT_MUTATED")
        return ShadowComparison(
            legacy, shadow, old, new, profile.diagnostics(), discovery_candidates=discoveries
        )


def canonical_adapter(
    claim: Claim, pages: tuple[DocumentPage, ...], *, service_lines_complete: bool = False
) -> tuple[LegacyResult, ClaimGraph]:
    fields = {}
    legacy_fields = []
    scoped_fields = [(f.field_name, f) for f in claim.header_fields]
    scoped_fields += [
        (f"{f.field_name}@{line.line_id}", f) for line in claim.service_lines for f in line.fields
    ]
    for key, f in scoped_fields:
        if key in fields:
            raise ValueError("REPEATED_FIELD_REQUIRES_SERVICE_LINE_SCOPING")
        candidates = []
        for evidence in f.candidates:
            p = evidence.provenance
            value, valid = normalize(f.field_name, evidence.raw_text)
            candidates.append(
                Candidate(
                    str(evidence.evidence_id),
                    evidence.raw_text,
                    (
                        CandidateEvidence(
                            str(evidence.source),
                            evidence.confidence,
                            page_id=p.page_sha256 if p else None,
                            crop_hash=p.crop_sha256 if p else None,
                            localization_region=p.localization_region_id if p else None,
                            source_id=p.document_sha256 if p else None,
                            provenance_id=p.invocation_id if p else None,
                            dependencies=p.shared_dependency_ids if p else (),
                        ),
                    ),
                    value,
                    EvidenceFeatures(format_valid=valid),
                    f.field_name,
                )
            )
        accepted = f.disposition in {
            "AUTO_ACCEPTED",
            "REFERENCE_CONFIRMED",
            "HUMAN_CONFIRMED",
            "ACCEPT",
        }
        authority = (
            AuthorityState.AUTHORITATIVE_NOT_AVAILABLE
            if f.field_name in IDENTITY_FIELDS
            else AuthorityState.AUTHORITATIVE_NOT_REQUIRED
        )
        # Unverified external reference metadata never upgrades authority here.
        if f.reference_evidence and f.reference_evidence.get("conflict") is True:
            authority = AuthorityState.AUTHORITATIVE_CONFLICT
        fields[key] = FieldNode(key, candidates, authority_state=authority, critical=f.is_critical)
        technical = ("EXTRACTION_FAILED",) if not f.raw_value else ()
        evidence_blockers = (
            ("AUTHORITATIVE_DATA_REQUIRED",)
            if authority != AuthorityState.AUTHORITATIVE_NOT_REQUIRED
            else (() if accepted else ("EVIDENCE_REQUIRED",))
        )
        legacy_fields.append(
            LegacyFieldResult(
                key,
                f.normalized_value or f.raw_value,
                accepted,
                tuple(candidates),
                technical,
                evidence_blockers,
                f.is_critical,
            )
        )
    line_evidence = {}
    for line in claim.service_lines:
        observations = []
        for source_field in line.fields:
            if source_field.field_name not in {
                "charge",
                "charge_amount",
                "line_charge",
                "service_line_charge",
                "charges",
            }:
                continue
            for observed in source_field.candidates:
                if money(observed.raw_text) != line.charge_amount:
                    continue
                lineage = observed.provenance
                observations.append(
                    CandidateEvidence(
                        str(observed.source),
                        observed.confidence,
                        page_id=lineage.page_sha256 if lineage else None,
                        crop_hash=lineage.crop_sha256 if lineage else None,
                        localization_region=lineage.localization_region_id if lineage else None,
                        source_id=lineage.document_sha256 if lineage else None,
                        provenance_id=lineage.invocation_id if lineage else None,
                        dependencies=lineage.shared_dependency_ids if lineage else (),
                    )
                )
        line_evidence[line.line_id] = tuple(observations)
    graph = ClaimGraph(
        str(claim.claim_id),
        claim.form_type.value,
        fields,
        service_lines=[
            ServiceLine(
                str(line.line_id),
                str(line.service_date_from) if line.service_date_from else None,
                line.procedure_code,
                line.diagnosis_pointers[0] if len(line.diagnosis_pointers) == 1 else None,
                str(line.charge_amount) if line.charge_amount is not None else None,
                evidence=line_evidence[line.line_id],
            )
            for line in claim.service_lines
        ],
        service_lines_complete=service_lines_complete,
        statement_start=str(claim.statement_period_from) if claim.statement_period_from else None,
        statement_end=str(claim.statement_period_to) if claim.statement_period_to else None,
        form_identity_confirmed=bool(pages) and all(p.canonical_identity_confirmed for p in pages),
        package_id=pages[0].package_id if pages else None,
        page_ids=tuple(p.page_id for p in pages),
        diagnosis_positions=tuple(claim.diagnosis_codes_by_position),
    )
    graph.relationships = graph_relationships(graph)
    return LegacyResult(
        str(claim.claim_id),
        tuple(legacy_fields),
        fingerprint(claim.model_dump(mode="json")),
        graph.form_type,
        graph.page_ids,
    ), graph


def graph_relationships(graph: ClaimGraph) -> tuple[tuple[str, str, str], ...]:
    owner = {
        "patient_name": "Patient",
        "patient_dob": "Patient",
        "member_id": "Patient",
        "insured_name": "Subscriber",
        "subscriber_id": "Subscriber",
        "provider_name": "Provider",
        "provider_npi": "Provider",
        "principal_diagnosis": "Claim",
        "total_charge": "Claim",
    }
    edges = [(owner.get(name, "Claim"), "has_field", name) for name in sorted(graph.fields)]
    edges.extend(("Claim", "has_service_line", line.line_id) for line in graph.service_lines)
    return tuple(edges)


@dataclass(frozen=True)
class ShadowFailure:
    error_code: str
    runtime_authority: bool = field(default=False, init=False)
    status: str = "SHADOW_FAILED_CANONICAL_UNCHANGED"


def run_after_legacy(
    run_legacy: Callable[[], Claim],
    pages: tuple[DocumentPage, ...],
    *,
    service_lines_complete: bool = False,
) -> tuple[Claim, ShadowComparison | ShadowFailure]:
    canonical = run_legacy()
    before = canonical.model_dump(mode="json")
    try:
        legacy, graph = canonical_adapter(
            canonical, pages, service_lines_complete=service_lines_complete
        )
        comparison: ShadowComparison | ShadowFailure = CDP2ShadowPipeline().compare(
            legacy, graph, pages
        )
    except Exception as exc:  # noqa: BLE001 -- isolate all shadow failures from canonical delivery
        # Shadow errors are observable but never interrupt canonical delivery.
        # Exception messages can contain PHI; expose only the exception class.
        comparison = ShadowFailure(type(exc).__name__)
    if canonical.model_dump(mode="json") != before:
        raise RuntimeError("CANONICAL_OUTPUT_MUTATED")
    return canonical, comparison
