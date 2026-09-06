from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from packages.validation_rules.npi import is_valid_npi

from .models import Candidate, ClaimGraph
from .normalization import calendar_date, money
from .provenance import complete, corroborated_alternatives


@dataclass(frozen=True)
class ConsistencyResult:
    rule_id: str
    verdict: str
    field_name: str
    candidate_id: str | None = None
    reason: str | None = None
    authority: str | None = None


class ClaimConsistencyEngine:
    """Deterministic engineering constraints. UNKNOWN is never counted as proof."""

    _decimal = staticmethod(money)
    _date = staticmethod(calendar_date)

    def total_charge(self, claim: ClaimGraph) -> list[ConsistencyResult]:
        field = claim.field("total_charge")
        if (
            not field
            or not field.candidates
            or not claim.service_lines_complete
            or not claim.service_lines
        ):
            return []
        ids = [line.line_id for line in claim.service_lines]
        regions = []
        charges = []
        for line in claim.service_lines:
            if (
                not line.readable
                or not line.sign_unambiguous
                or line.currency != "USD"
                or not line.evidence
                or not all(complete(e) for e in line.evidence)
            ):
                return []
            amount = money(line.charge) if line.charge is not None else None
            if amount is None:
                return []
            charges.append(amount)
            e = line.evidence[0]
            regions.append((e.source_id, e.page_id, e.localization_region))
        if not all(ids) or len(set(ids)) != len(ids) or len(set(regions)) != len(regions):
            return []
        if len({line.evidence[0].crop_hash for line in claim.service_lines}) != len(
            claim.service_lines
        ):
            return []
        with localcontext() as ctx:
            ctx.prec = max(len(str(v)) for v in charges) + len(str(len(charges))) + 8
            expected = sum(charges, Decimal("0.00"))
        results = []
        for candidate in field.candidates:
            amount = money(candidate.value)
            eligible = bool(candidate.evidence) and all(complete(e) for e in candidate.evidence)
            if amount is None or not eligible:
                results.append(
                    ConsistencyResult(
                        "TOTAL_CHARGE_EQUALS_SERVICE_LINE_SUM",
                        "UNKNOWN",
                        field.name,
                        candidate.candidate_id,
                        "MISSING_PREREQUISITE",
                    )
                )
                continue
            verdict = "PROOF" if amount == expected else "CONFLICT"
            results.append(
                ConsistencyResult(
                    "TOTAL_CHARGE_EQUALS_SERVICE_LINE_SUM",
                    verdict,
                    field.name,
                    candidate.candidate_id,
                    "EXACT_DECIMAL_COMPARISON",
                    "ARITHMETIC_EXACT" if verdict == "PROOF" else None,
                )
            )
        return results

    def service_dates(self, claim: ClaimGraph) -> list[ConsistencyResult]:
        start, end = calendar_date(claim.statement_start), calendar_date(claim.statement_end)
        observations: list[tuple[str | None, str | None]] = [
            (None, line.service_date) for line in claim.service_lines
        ]
        field = claim.field("service_date")
        if field:
            observations += [(c.candidate_id, c.value) for c in field.candidates]
        results = []
        for candidate_id, value in observations:
            parsed = calendar_date(value)
            verdict, reason = "UNKNOWN", "STATEMENT_PERIOD_UNAVAILABLE"
            if parsed is None:
                verdict, reason = (
                    "CONFLICT" if value else "UNKNOWN",
                    "INVALID_OR_MISSING_CALENDAR_DATE",
                )
            elif start is not None and end is not None:
                verdict = "PROOF" if start <= parsed <= end and start <= end else "CONFLICT"
                reason = "STATEMENT_PERIOD_CHECK"
            if claim.admission_constraints_applicable and parsed:
                admission, discharge = (
                    calendar_date(claim.admission_date),
                    calendar_date(claim.discharge_date),
                )
                if admission is None or discharge is None:
                    if verdict != "CONFLICT":
                        verdict, reason = "UNKNOWN", "ADMISSION_CONTEXT_INCOMPLETE"
                elif not admission <= parsed <= discharge:
                    verdict, reason = "CONFLICT", "APPLICABLE_ADMISSION_PERIOD_CONFLICT"
            results.append(
                ConsistencyResult(
                    "SERVICE_DATE_WITHIN_STATEMENT_PERIOD",
                    verdict,
                    "service_date",
                    candidate_id,
                    reason,
                    "CROSS_FIELD_EXACT" if verdict == "PROOF" else None,
                )
            )
        return results

    def dob(self, claim: ClaimGraph, maximum_age: int = 130) -> list[ConsistencyResult]:
        field = claim.field("patient_dob") or claim.field("patient_DOB")
        if field is None:
            return []
        dates = [calendar_date(line.service_date) for line in claim.service_lines]
        date_field = claim.field("service_date")
        if not dates and date_field:
            dates = [calendar_date(c.value) for c in date_field.candidates]
        valid = [d for d in dates if d is not None]
        first = min(valid) if valid else None
        statement = calendar_date(claim.statement_start)
        results = []
        for candidate in field.candidates:
            birth = calendar_date(candidate.value)
            verdict, reason = "UNKNOWN", "CHRONOLOGY_CONTEXT_INCOMPLETE"
            if birth is None:
                verdict, reason = "CONFLICT", "INVALID_CALENDAR_DATE"
            elif (first and birth >= first) or (statement and birth >= statement):
                verdict, reason = "CONFLICT", "DOB_NOT_BEFORE_CLAIM_DATES"
            elif first and all(d is not None for d in dates):
                age = (
                    first.year - birth.year - ((first.month, first.day) < (birth.month, birth.day))
                )
                verdict, reason = (
                    ("UNKNOWN", "UNUSUAL_AGE_REQUIRES_REVIEW")
                    if age > maximum_age
                    else ("PROOF", "VALID_CALENDAR_AND_CHRONOLOGY")
                )
            results.append(
                ConsistencyResult(
                    "DOB_TEMPORAL_VALIDATION",
                    verdict,
                    field.name,
                    candidate.candidate_id,
                    reason,
                    "CROSS_FIELD_EXACT" if verdict == "PROOF" else None,
                )
            )
        return results

    def relationships(self, claim: ClaimGraph) -> list[ConsistencyResult]:
        results = []
        for line in claim.service_lines:
            if line.diagnosis_pointer:
                verdict = (
                    "UNKNOWN"
                    if not claim.diagnosis_positions
                    else (
                        "PROOF"
                        if line.diagnosis_pointer in claim.diagnosis_positions
                        else "CONFLICT"
                    )
                )
                results.append(
                    ConsistencyResult(
                        "DIAGNOSIS_POINTER_REFERENCE",
                        verdict,
                        "diagnosis_pointer",
                        reason="DIAGNOSIS_POSITION_CHECK",
                    )
                )
        field = claim.field("provider_npi")
        if field:
            results.extend(
                ConsistencyResult(
                    "NPI_CHECKSUM",
                    "PROOF" if is_valid_npi(c.value) else "CONFLICT",
                    field.name,
                    c.candidate_id,
                    "NPI_FORMAT_CHECK",
                    "DETERMINISTIC_EXACT" if is_valid_npi(c.value) else None,
                )
                for c in field.candidates
            )
        if claim.patient_is_subscriber is True:
            patient, insured = claim.field("patient_name"), claim.field("insured_name")
            # Equality is usable only for explicit SELF and unambiguous observations.
            if patient and insured and len(patient.candidates) == len(insured.candidates) == 1:
                a, b = patient.candidates[0], insured.candidates[0]
                results.append(
                    ConsistencyResult(
                        "EXPLICIT_SELF_RELATIONSHIP",
                        "PROOF" if a.value == b.value else "CONFLICT",
                        "insured_name",
                        b.candidate_id,
                        "EXPLICIT_RELATIONSHIP_CHECK",
                    )
                )
        return results

    def evaluate(self, claim: ClaimGraph) -> list[ConsistencyResult]:
        repeated = [
            ConsistencyResult(
                "REPEATED_INDEPENDENT_EXACT",
                "PROOF",
                name,
                c.candidate_id,
                "INDEPENDENT_OBSERVATIONS",
                "INDEPENDENT_SOURCE_EXACT",
            )
            for name, node in claim.fields.items()
            for c in node.candidates
            if corroborated_alternatives(c, node.candidates)
        ]
        return [
            *self.total_charge(claim),
            *self.service_dates(claim),
            *self.dob(claim),
            *self.relationships(claim),
            *repeated,
        ]


def proof_candidate_ids(results: list[ConsistencyResult], field_name: str) -> set[str]:
    return {
        r.candidate_id
        for r in results
        if r.verdict == "PROOF" and r.field_name == field_name and r.candidate_id is not None
    }


def rank_candidates(candidates: list[Candidate], proof_ids: set[str]) -> list[Candidate]:
    return sorted(
        candidates,
        key=lambda c: (
            c.candidate_id not in proof_ids,
            c.features.format_valid is False,
            -(c.features.geometry_confidence or 0),
            -max((e.confidence or 0 for e in c.evidence), default=0),
            c.candidate_id,
        ),
    )
