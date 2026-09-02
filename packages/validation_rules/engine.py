"""Deterministic validation engine: dispatches each extracted field to the
rule its threshold config names (`config/validation/*.yaml`), checks its
confidence against a criticality-aware threshold, and reconciles
service-line charges against the claim total. Never a single
document-level confidence score -- every check is field-scoped and
produces its own `ValidationResult`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from packages.domain.claim import Claim, ServiceLine
from packages.domain.enums import FieldCriticality, ValidationStatus
from packages.domain.extraction import ExtractedField
from packages.domain.validation import ValidationResult
from packages.templates.models import Template
from packages.validation_rules.cpt_hcpcs import (
    is_valid_hcpcs_syntax,
    is_valid_modifier_syntax,
)
from packages.validation_rules.dates import check_not_future
from packages.validation_rules.icd10 import is_valid_icd10_syntax
from packages.validation_rules.npi import is_valid_npi
from packages.validation_rules.numeric import check_non_negative_currency, check_positive_units
from packages.validation_rules.reconciliation import check_service_line_total_matches_claim_total
from packages.validation_rules.required_fields import find_missing_required_fields
from packages.validation_rules.thresholds import ThresholdRegistry


class ValidationEngine:
    def __init__(self, threshold_registry: ThresholdRegistry) -> None:
        self._thresholds = threshold_registry

    def validate_claim(self, claim: Claim, template: Template | None) -> list[ValidationResult]:
        results: list[ValidationResult] = []

        required_fields = template.required_fields if template else []
        for name in find_missing_required_fields(required_fields, claim.header_fields):
            results.append(
                ValidationResult(
                    claim_id=claim.claim_id,
                    field_name=name,
                    rule_name="required_field",
                    criticality=self._criticality(name),
                    status=ValidationStatus.INVALID,
                    message="required field is missing or empty",
                )
            )

        for field in claim.header_fields:
            results.extend(self._validate_field(claim, field))

        for line in claim.service_lines:
            results.extend(self._validate_service_line(claim, line))

        results.append(self._reconciliation_result(claim))
        return results

    def _criticality(self, field_name: str) -> FieldCriticality:
        threshold = self._thresholds.get(field_name)
        return threshold.criticality if threshold else FieldCriticality.NON_CRITICAL

    def _confidence_result(self, claim: Claim, field: ExtractedField) -> ValidationResult | None:
        criticality = self._criticality(field.field_name)
        if self._thresholds.meets_threshold(field.field_name, field.confidence, criticality):
            return None
        min_conf = self._thresholds.min_confidence_for(field.field_name, criticality)
        return ValidationResult(
            claim_id=claim.claim_id,
            field_id=field.field_id,
            field_name=field.field_name,
            rule_name="confidence_threshold",
            criticality=criticality,
            status=ValidationStatus.NEEDS_REVIEW,
            message=f"confidence {field.confidence:.2f} below required {min_conf:.2f}",
        )

    def _validate_field(self, claim: Claim, field: ExtractedField) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        if (confidence_result := self._confidence_result(claim, field)) is not None:
            results.append(confidence_result)

        threshold = self._thresholds.get(field.field_name)
        rule = threshold.rule if threshold else None
        value = field.normalized_value
        if not rule or not value:
            return results

        criticality = self._criticality(field.field_name)
        ok, message = self._evaluate_rule(rule, value)
        results.append(
            ValidationResult(
                claim_id=claim.claim_id,
                field_id=field.field_id,
                field_name=field.field_name,
                rule_name=rule,
                criticality=criticality,
                status=ValidationStatus.VALID if ok else ValidationStatus.INVALID,
                message=message,
            )
        )
        return results

    def _evaluate_rule(self, rule: str, value: str) -> tuple[bool, str | None]:
        if rule == "npi_luhn_checksum":
            ok = is_valid_npi(value)
            return ok, None if ok else f"'{value}' fails the NPI check-digit algorithm"
        if rule == "icd10_syntax":
            codes = value.split()
            ok = bool(codes) and all(is_valid_icd10_syntax(c) for c in codes)
            return ok, None if ok else f"'{value}' contains a syntactically invalid ICD-10 code"
        if rule == "cpt_hcpcs_syntax":
            ok = is_valid_hcpcs_syntax(value)
            return ok, None if ok else f"'{value}' is not a valid CPT/HCPCS code"
        if rule == "modifier_syntax":
            ok = is_valid_modifier_syntax(value)
            return ok, None if ok else f"'{value}' is not a valid 2-character modifier"
        if rule == "tax_id_syntax":
            ok = value.isdigit() and len(value) == 9
            return ok, None if ok else f"'{value}' is not a 9-digit tax ID"
        if rule == "non_negative_currency":
            return self._check_currency(value)
        if rule == "date_not_future":
            return self._check_date_not_future(value)
        return True, None

    def _check_currency(self, value: str) -> tuple[bool, str | None]:
        try:
            result = check_non_negative_currency(Decimal(value))
        except InvalidOperation:
            return False, f"'{value}' is not a valid currency amount"
        return result.ok, result.reason

    def _check_date_not_future(self, value: str) -> tuple[bool, str | None]:
        try:
            result = check_not_future(date.fromisoformat(value))
        except ValueError:
            return False, f"'{value}' is not a valid ISO date"
        return result.ok, result.reason

    def _validate_service_line(self, claim: Claim, line: ServiceLine) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        if line.procedure_code and not is_valid_hcpcs_syntax(line.procedure_code):
            results.append(
                ValidationResult(
                    claim_id=claim.claim_id,
                    field_name=f"service_line[{line.line_number}].procedure_code",
                    rule_name="cpt_hcpcs_syntax",
                    criticality=FieldCriticality.CRITICAL,
                    status=ValidationStatus.INVALID,
                    message=f"'{line.procedure_code}' is not a valid CPT/HCPCS code",
                )
            )
        for modifier in line.modifiers:
            if not is_valid_modifier_syntax(modifier):
                results.append(
                    ValidationResult(
                        claim_id=claim.claim_id,
                        field_name=f"service_line[{line.line_number}].modifier",
                        rule_name="modifier_syntax",
                        criticality=FieldCriticality.NON_CRITICAL,
                        status=ValidationStatus.INVALID,
                        message=f"'{modifier}' is not a valid modifier",
                    )
                )
        if line.charge_amount is not None:
            check = check_non_negative_currency(line.charge_amount)
            if not check.ok:
                results.append(
                    ValidationResult(
                        claim_id=claim.claim_id,
                        field_name=f"service_line[{line.line_number}].charge_amount",
                        rule_name="non_negative_currency",
                        criticality=FieldCriticality.CRITICAL,
                        status=ValidationStatus.INVALID,
                        message=check.reason,
                    )
                )
        if line.units is not None:
            check = check_positive_units(line.units)
            if not check.ok:
                results.append(
                    ValidationResult(
                        claim_id=claim.claim_id,
                        field_name=f"service_line[{line.line_number}].units",
                        rule_name="positive_units",
                        criticality=FieldCriticality.NON_CRITICAL,
                        status=ValidationStatus.INVALID,
                        message=check.reason,
                    )
                )
        return results

    def _reconciliation_result(self, claim: Claim) -> ValidationResult:
        recon = check_service_line_total_matches_claim_total(claim)
        return ValidationResult(
            claim_id=claim.claim_id,
            field_name="total_charge",
            rule_name="service_line_total_reconciliation",
            criticality=FieldCriticality.CRITICAL,
            status=ValidationStatus.VALID if recon.ok else ValidationStatus.INVALID,
            message=recon.reason,
        )
