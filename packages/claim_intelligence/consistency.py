from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from .models import Candidate, ClaimGraph


@dataclass(frozen=True)
class ConsistencyResult:
    rule_id: str
    verdict: str
    field_name: str
    candidate_id: str | None = None
    reason: str | None = None


class ClaimConsistencyEngine:
    """Generate deterministic claim-level engineering evidence.

    These proofs are not release truth by themselves. They are intended to rank
    or eliminate candidates in the shadow path while preserving fail-closed
    production governance.
    """

    @staticmethod
    def _decimal(value: str) -> Decimal | None:
        try:
            return Decimal(value.replace(",", "").replace("$", "").strip())
        except (InvalidOperation, AttributeError):
            return None

    @staticmethod
    def _date(value: str | None) -> date | None:
        if not value:
            return None
        normalized = value.strip().replace("/", "-")
        formats = ("%Y-%m-%d", "%m-%d-%Y", "%m-%d-%y")
        from datetime import datetime

        for fmt in formats:
            try:
                return datetime.strptime(normalized, fmt).date()
            except ValueError:
                continue
        return None

    def total_charge(self, claim: ClaimGraph) -> list[ConsistencyResult]:
        field = claim.field("total_charge")
        if field is None or not field.candidates or not claim.service_lines:
            return []
        charges: list[Decimal] = []
        for line in claim.service_lines:
            if line.charge is None:
                return []
            parsed = self._decimal(line.charge)
            if parsed is None or parsed < 0:
                return []
            charges.append(parsed)
        expected = sum(charges, Decimal("0"))
        results: list[ConsistencyResult] = []
        for candidate in field.candidates:
            parsed = self._decimal(candidate.value)
            if parsed is None:
                continue
            verdict = "PROOF" if parsed == expected else "CONFLICT"
            results.append(
                ConsistencyResult(
                    rule_id="TOTAL_CHARGE_EQUALS_SERVICE_LINE_SUM",
                    verdict=verdict,
                    field_name="total_charge",
                    candidate_id=candidate.candidate_id,
                    reason=f"service_line_sum={expected}",
                )
            )
        return results

    def service_dates(self, claim: ClaimGraph) -> list[ConsistencyResult]:
        start = self._date(claim.statement_start)
        end = self._date(claim.statement_end)
        if start is None or end is None or start > end:
            return []
        results: list[ConsistencyResult] = []
        for line in claim.service_lines:
            parsed = self._date(line.service_date)
            if parsed is None:
                continue
            verdict = "PROOF" if start <= parsed <= end else "CONFLICT"
            results.append(
                ConsistencyResult(
                    rule_id="SERVICE_DATE_WITHIN_STATEMENT_PERIOD",
                    verdict=verdict,
                    field_name="service_date",
                    reason=f"line_id={line.line_id}",
                )
            )
        return results

    def dob(self, claim: ClaimGraph) -> list[ConsistencyResult]:
        field = claim.field("patient_dob") or claim.field("patient_DOB")
        if field is None:
            return []
        service_dates = [self._date(line.service_date) for line in claim.service_lines]
        service_dates = [value for value in service_dates if value is not None]
        first_service = min(service_dates) if service_dates else None
        results: list[ConsistencyResult] = []
        for candidate in field.candidates:
            parsed = self._date(candidate.value)
            if parsed is None:
                results.append(
                    ConsistencyResult(
                        rule_id="DOB_TEMPORAL_VALIDATION",
                        verdict="CONFLICT",
                        field_name=field.name,
                        candidate_id=candidate.candidate_id,
                        reason="invalid_calendar_date",
                    )
                )
                continue
            if first_service is not None and parsed >= first_service:
                verdict = "CONFLICT"
                reason = "dob_not_before_service"
            else:
                verdict = "PROOF"
                reason = "valid_calendar_and_chronology"
            results.append(
                ConsistencyResult(
                    rule_id="DOB_TEMPORAL_VALIDATION",
                    verdict=verdict,
                    field_name=field.name,
                    candidate_id=candidate.candidate_id,
                    reason=reason,
                )
            )
        return results

    def evaluate(self, claim: ClaimGraph) -> list[ConsistencyResult]:
        return [*self.total_charge(claim), *self.service_dates(claim), *self.dob(claim)]


def proof_candidate_ids(results: list[ConsistencyResult], field_name: str) -> set[str]:
    return {
        result.candidate_id
        for result in results
        if result.verdict == "PROOF"
        and result.field_name == field_name
        and result.candidate_id is not None
    }


def rank_candidates(candidates: list[Candidate], proof_ids: set[str]) -> list[Candidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.candidate_id not in proof_ids,
            -max(
                (evidence.confidence or 0.0 for evidence in candidate.evidence),
                default=0.0,
            ),
            candidate.candidate_id,
        ),
    )
