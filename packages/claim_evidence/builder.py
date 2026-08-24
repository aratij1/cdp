from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import yaml

from packages.domain.common import DomainModel
from packages.evidence.models import EvidenceClass, EvidenceItem

DEFAULT_CLAIM_EVIDENCE_PATH = Path(__file__).resolve().parents[2] / "config" / "claim_evidence.yaml"


class ClaimEvidenceResult(DomainModel):
    evidence_items: list[EvidenceItem]
    contradictions: list[EvidenceItem]

    def evidence_types_for(self, field_name: str) -> set[str]:
        return {
            item.evidence_type
            for item in self.evidence_items
            if field_name in item.metadata.get("supported_fields", [])
        }


class ClaimFinancialReconciliationEvidence(DomainModel):
    """Truth-blind, non-mutating claim-total reconciliation fact."""

    reported_total: str
    computed_total: str
    difference: str
    tolerance: str
    line_count: int
    result: str
    reason: str


class ClaimEvidenceBuilder:
    """Build truth-blind, deterministic E6 evidence from claim relationships."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.version = str(config["version"])
        tolerance = config["financial_tolerance"]
        self.absolute_tolerance = Decimal(str(tolerance["absolute_usd"]))
        self.relative_tolerance = Decimal(str(tolerance["relative_fraction"]))

    @classmethod
    def load(
        cls,
        path: str | Path = DEFAULT_CLAIM_EVIDENCE_PATH,
    ) -> ClaimEvidenceBuilder:
        return cls(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def build(
        self,
        *,
        claim_id: str,
        document_family: str,
        claim_values: dict[str, object],
        service_lines: list[dict[str, object]] | None = None,
    ) -> ClaimEvidenceResult:
        evidence: list[EvidenceItem] = []
        contradictions: list[EvidenceItem] = []
        lines = service_lines or []

        self._financial(claim_id, claim_values, lines, evidence, contradictions)
        self._dates(claim_id, claim_values, lines, evidence, contradictions)
        self._member_identity(claim_id, claim_values, evidence, contradictions)
        self._provider_identity(claim_id, claim_values, evidence, contradictions)
        if document_family.upper() == "UB04":
            self._ub04_lines(claim_id, lines, evidence, contradictions)
        return ClaimEvidenceResult(
            evidence_items=evidence,
            contradictions=contradictions,
        )

    def _financial(self, claim_id, values, lines, evidence, contradictions) -> None:
        total = self._first_decimal(values, "total_charge", "total_charges", "claim_total")
        charges = [
            parsed
            for line in lines
            if (
                parsed := self._first_decimal(
                    line,
                    "charge_amount",
                    "charges",
                    "total_charges",
                    "service_line_charge",
                )
            )
            is not None
        ]
        if total is not None and charges:
            observed = sum(charges, Decimal(0))
            difference = abs(total - observed)
            target = max(abs(total), abs(observed), Decimal(1))
            tolerance = max(self.absolute_tolerance, target * self.relative_tolerance)
            supported = ["total_charge", "total_charges", "charges", "charge_amount"]
            passed = difference <= tolerance
            reconciliation = ClaimFinancialReconciliationEvidence(
                reported_total=str(total),
                computed_total=str(observed),
                difference=str(difference),
                tolerance=str(tolerance),
                line_count=len(charges),
                result="PASS" if passed else "CONTRADICTION",
                reason=(
                    "CLAIM_TOTAL_WITHIN_CONFIGURED_TOLERANCE"
                    if passed
                    else "CLAIM_TOTAL_OUTSIDE_CONFIGURED_TOLERANCE"
                ),
            )
            metadata = {
                "supported_fields": supported,
                "claim_total": str(total),
                "service_line_total": str(observed),
                **reconciliation.model_dump(mode="json"),
                "absolute_tolerance": str(self.absolute_tolerance),
                "relative_tolerance": str(self.relative_tolerance),
            }
            if passed:
                evidence.append(
                    self._item(
                        claim_id,
                        "CLAIM_TOTAL_CONFIRMED",
                        str(total),
                        metadata,
                    )
                )
            else:
                contradictions.append(
                    self._item(
                        claim_id,
                        "CLAIM_TOTAL_CONTRADICTION",
                        str(total),
                        metadata,
                    )
                )

        for index, line in enumerate(lines, start=1):
            units = self._first_decimal(line, "units")
            rate = self._first_decimal(line, "rate", "unit_rate")
            charge = self._first_decimal(
                line,
                "charge_amount",
                "charges",
                "total_charges",
                "service_line_charge",
            )
            if units is None or rate is None or charge is None:
                continue
            expected = units * rate
            difference = abs(expected - charge)
            target = max(abs(expected), abs(charge), Decimal(1))
            metadata = {
                "supported_fields": ["units", "rate", "unit_rate", "charges", "charge_amount"],
                "line_number": index,
                "computed_charge": str(expected),
                "observed_charge": str(charge),
                "difference": str(difference),
            }
            target_list = (
                evidence
                if difference
                <= max(
                    self.absolute_tolerance,
                    target * self.relative_tolerance,
                )
                else contradictions
            )
            evidence_type = (
                "SERVICE_LINE_RECONCILED"
                if target_list is evidence
                else "SERVICE_LINE_FINANCIAL_CONTRADICTION"
            )
            target_list.append(
                self._item(
                    claim_id,
                    evidence_type,
                    str(charge),
                    metadata,
                    discriminator=str(index),
                )
            )

    def _dates(self, claim_id, values, lines, evidence, contradictions) -> None:
        relationships = [
            ("statement_period_from", "statement_period_to"),
            ("service_date_from", "service_date_to"),
            ("admission_date", "discharge_date"),
        ]
        for start_name, end_name in relationships:
            start, end = self._date(values.get(start_name)), self._date(values.get(end_name))
            if start is None or end is None:
                continue
            metadata = {
                "supported_fields": [start_name, end_name],
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
            target = evidence if start <= end else contradictions
            evidence_type = (
                "DATE_RELATIONSHIP_CONFIRMED"
                if target is evidence
                else "DATE_RELATIONSHIP_CONTRADICTION"
            )
            target.append(
                self._item(
                    claim_id,
                    evidence_type,
                    f"{start.isoformat()}:{end.isoformat()}",
                    metadata,
                    discriminator=f"{start_name}:{end_name}",
                )
            )
        for index, line in enumerate(lines, start=1):
            start, end = (
                self._date(line.get("service_date_from")),
                self._date(line.get("service_date_to")),
            )
            if start is None or end is None:
                continue
            metadata = {
                "supported_fields": ["service_date_from", "service_date_to"],
                "line_number": index,
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
            target = evidence if start <= end else contradictions
            target.append(
                self._item(
                    claim_id,
                    "DATE_RELATIONSHIP_CONFIRMED"
                    if target is evidence
                    else "DATE_RELATIONSHIP_CONTRADICTION",
                    f"{start.isoformat()}:{end.isoformat()}",
                    metadata,
                    discriminator=f"line:{index}",
                )
            )

        patient_dob = self._date(values.get("patient_dob"))
        service_dates = [
            parsed
            for raw in (
                *self._values(values.get("service_date")),
                *(line.get("service_date") for line in lines),
                *(line.get("service_date_from") for line in lines),
                *(line.get("service_date_to") for line in lines),
            )
            if (parsed := self._date(raw)) is not None
        ]
        if patient_dob is not None and service_dates:
            metadata = {
                "supported_fields": ["patient_dob", "service_date"],
                "patient_dob": patient_dob.isoformat(),
                "earliest_service_date": min(service_dates).isoformat(),
                "latest_service_date": max(service_dates).isoformat(),
                "service_date_count": len(service_dates),
            }
            consistent = all(patient_dob <= item for item in service_dates)
            target = evidence if consistent else contradictions
            target.append(
                self._item(
                    claim_id,
                    "DOB_SERVICE_DATE_CONSISTENT"
                    if consistent
                    else "DOB_SERVICE_DATE_CONTRADICTION",
                    patient_dob.isoformat(),
                    metadata,
                    discriminator="patient_dob:service_dates",
                )
            )

    def _member_identity(self, claim_id, values, evidence, contradictions) -> None:
        repeated = self._values(values.get("insured_id_number"))
        repeated.extend(self._values(values.get("member_id")))
        repeated.extend(self._values(values.get("subscriber_id")))
        normalized = [self._identifier(item) for item in repeated if self._identifier(item)]
        if len(normalized) >= 2:
            metadata = {
                "supported_fields": ["insured_id_number", "member_id", "subscriber_id"],
                "occurrences": normalized,
            }
            target = evidence if len(set(normalized)) == 1 else contradictions
            target.append(
                self._item(
                    claim_id,
                    "MEMBER_IDENTITY_CONSISTENT"
                    if target is evidence
                    else "MEMBER_IDENTITY_CONTRADICTION",
                    normalized[0],
                    metadata,
                )
            )

        relationship = str(
            values.get("insured_relationship") or values.get("relationship") or ""
        ).upper()
        patient = self._name(values.get("patient_name"))
        insured = self._name(values.get("insured_name"))
        if relationship in {"SELF", "18"} and patient and insured:
            metadata = {
                "supported_fields": ["patient_name", "insured_name", "insured_relationship"],
                "relationship": relationship,
            }
            target = evidence if patient == insured else contradictions
            target.append(
                self._item(
                    claim_id,
                    "MEMBER_RELATIONSHIP_CONFIRMED"
                    if target is evidence
                    else "MEMBER_RELATIONSHIP_CONTRADICTION",
                    patient,
                    metadata,
                )
            )

    def _provider_identity(self, claim_id, values, evidence, contradictions) -> None:
        repeated = self._values(values.get("provider_npi"))
        normalized = [self._identifier(item) for item in repeated if self._identifier(item)]
        if len(normalized) < 2:
            return
        metadata = {
            "supported_fields": ["provider_npi"],
            "occurrences": normalized,
            "evidence_scope": "INTERNAL_NOT_AUTHORITY_REFERENCE",
        }
        target = evidence if len(set(normalized)) == 1 else contradictions
        target.append(
            self._item(
                claim_id,
                "PROVIDER_IDENTITY_CONSISTENT"
                if target is evidence
                else "PROVIDER_IDENTITY_CONTRADICTION",
                normalized[0],
                metadata,
            )
        )

    def _ub04_lines(self, claim_id, lines, evidence, contradictions) -> None:
        for index, line in enumerate(lines, start=1):
            revenue = self._identifier(line.get("revenue_code"))
            hcpcs = self._identifier(line.get("hcpcs_code") or line.get("procedure_code"))
            units = self._first_decimal(line, "units")
            charge = self._first_decimal(line, "charge_amount", "charges", "total_charges")
            present = [revenue, hcpcs, units, charge]
            if not any(value is not None and value != "" for value in present):
                continue
            coherent = (
                bool(re.fullmatch(r"\d{4}", revenue))
                and (not hcpcs or bool(re.fullmatch(r"[A-Z0-9]{5}", hcpcs)))
                and units is not None
                and units > 0
                and charge is not None
                and charge >= 0
            )
            metadata = {
                "supported_fields": [
                    "revenue_code",
                    "hcpcs_code",
                    "procedure_code",
                    "units",
                    "charges",
                    "charge_amount",
                ],
                "line_number": index,
                "revenue_code": revenue,
                "hcpcs_code": hcpcs,
                "units": str(units) if units is not None else None,
                "charge": str(charge) if charge is not None else None,
            }
            target = evidence if coherent else contradictions
            target.append(
                self._item(
                    claim_id,
                    "UB04_SERVICE_LINE_COHERENT" if coherent else "UB04_SERVICE_LINE_CONTRADICTION",
                    str(index),
                    metadata,
                    discriminator=str(index),
                )
            )

    def _item(self, claim_id, evidence_type, value, metadata, discriminator="") -> EvidenceItem:
        key = f"{self.version}|{claim_id}|{evidence_type}|{value}|{discriminator}"
        return EvidenceItem(
            evidence_id=uuid5(NAMESPACE_URL, key),
            evidence_class=EvidenceClass.E6,
            evidence_type=evidence_type,
            evidence_family="claim-cross-field",
            source="ClaimEvidenceBuilder",
            value=value,
            deterministic=True,
            independent=False,
            authoritative=False,
            version=self.version,
            metadata=metadata,
        )

    @staticmethod
    def _first_decimal(values: dict[str, object], *names: str) -> Decimal | None:
        for name in names:
            for value in ClaimEvidenceBuilder._values(values.get(name)):
                try:
                    cleaned = (
                        re.sub(r"[^0-9.()-]", "", str(value)).replace("(", "-").replace(")", "")
                    )
                    if cleaned:
                        return Decimal(cleaned)
                except (InvalidOperation, ValueError):
                    continue
        return None

    @staticmethod
    def _values(value: object) -> list[object]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    @staticmethod
    def _identifier(value: object) -> str:
        return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())

    @staticmethod
    def _name(value: object) -> str:
        return re.sub(r"[^A-Z]", "", str(value or "").upper())

    @staticmethod
    def _date(value: object) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m%d%Y", "%m%d%y", "%m/%d/%y"):
            try:
                return datetime.strptime(text, pattern).date()  # noqa: DTZ007
            except ValueError:
                continue
        return None
