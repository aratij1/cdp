"""Regional extraction for standard (CMS-1500/UB-04) forms: OCR is run
ONLY on the template's configured field/service-line regions -- never a
whole-page OCR pass. This is the Phase 2 acceptance criterion ("Standard
CMS and UB forms use template-region OCR first") and it's structural, not
just a convention: `StandardFormExtractionService` never calls
`TextExtractor.extract`, only `TextExtractor.extract_region`.

Callers are expected to have already aligned the candidate page to the
template's reference frame (`workers.page_detection.template_alignment`)
before calling `extract` -- field regions are defined in that reference
coordinate space.
"""

from __future__ import annotations

from packages.domain.claim import ServiceLine
from packages.domain.common import BoundingBox
from packages.domain.enums import ExtractionMethod, ValidationStatus
from packages.domain.extraction import ExtractedField
from packages.templates.models import FieldRegion, Template
from workers.page_detection.text_extraction import TextExtractor
from workers.standard_form_extraction.field_processors import normalize
from workers.table_extraction import UB04ServiceLineEngine, UB04Token

REGION_PADDING_PX = 4


def _region_text(extractor: TextExtractor, image, region: FieldRegion | tuple) -> tuple[str, float]:
    """Returns (joined text, mean per-line OCR confidence -- 0.0 if the
    region has no lines), matching the averaging approach already used by
    `workers.retry.retry_service._combine_lines`."""
    x0, y0, x1, y1 = (
        (region.x0, region.y0, region.x1, region.y1) if isinstance(region, FieldRegion) else region
    )
    padding = region.padding_px if isinstance(region, FieldRegion) else REGION_PADDING_PX
    width, height = image.size
    x0 = max(0, x0 - padding)
    y0 = max(0, y0 - padding)
    x1 = min(width, x1 + padding)
    y1 = min(height, y1 + padding)
    lines = extractor.extract_region(image, x0, y0, x1, y1)
    ordered = sorted(lines, key=lambda l: (l.y0, l.x0))
    text = " ".join(line.text for line in ordered)
    confidence = sum(line.confidence for line in ordered) / len(ordered) if ordered else 0.0
    return text, confidence


def _make_field(
    template: Template,
    field_name: str,
    field_type: str,
    raw_text: str,
    confidence: float,
    region_x0: int,
    region_y0: int,
    region_x1: int,
    region_y1: int,
    page_number: int,
    image_width: int,
    image_height: int,
    extraction_method: ExtractionMethod = ExtractionMethod.REGIONAL_PADDLEOCR,
) -> ExtractedField:
    normalized_value, ok = normalize(field_type, raw_text)
    if not (normalized_value or "").strip():
        confidence = 0.0
        ok = False
    return ExtractedField(
        field_name=field_name,
        raw_value=raw_text,
        normalized_value=normalized_value,
        confidence=confidence,
        page_number=page_number,
        bounding_box=BoundingBox(
            x0=region_x0,
            y0=region_y0,
            x1=region_x1,
            y1=region_y1,
            image_width=image_width,
            image_height=image_height,
        ),
        extraction_method=extraction_method,
        template_version=f"{template.template_id}@{template.version}",
        validation_status=ValidationStatus.PENDING if ok else ValidationStatus.INVALID,
        validation_reasons=[]
        if ok
        else [
            "required_or_unvalidated_blank"
            if not (normalized_value or "").strip()
            else "normalization_failed"
        ],
    )


class StandardFormExtractionService:
    def __init__(self, text_extractor: TextExtractor) -> None:
        self._text_extractor = text_extractor

    def extract_fields(
        self,
        image,
        template: Template,
        page_number: int,
        crop_boxes_by_field: dict[str, tuple[tuple[int, int, int, int], ...]] | None = None,
    ) -> list[ExtractedField]:
        width, height = (
            template.reference_dimensions.width_px,
            template.reference_dimensions.height_px,
        )
        fields = []
        method = (
            ExtractionMethod.REGIONAL_RAPIDOCR
            if getattr(self._text_extractor, "engine_name", "") == "rapidocr"
            else ExtractionMethod.REGIONAL_PADDLEOCR
        )
        for region in template.field_regions:
            variants = (crop_boxes_by_field or {}).get(region.field_name)
            disagreement = False
            if variants and len(variants) > 1:
                readings = [_region_text(self._text_extractor, image, box) for box in variants]
                populated = [(text.strip(), score) for text, score in readings if text.strip()]
                values = {text.casefold() for text, _ in populated}
                disagreement = len(values) > 1
                raw_text, confidence = max(populated, key=lambda item: item[1]) if populated else ("", 0.0)
            else:
                raw_text, confidence = _region_text(self._text_extractor, image, region)
            fields.append(
                _make_field(
                    template,
                    region.field_name,
                    region.field_type,
                    raw_text,
                    confidence,
                    region.x0,
                    region.y0,
                    region.x1,
                    region.y1,
                    page_number,
                    width,
                    height,
                    method,
                )
            )
            field = fields[-1]
            field.model_name = getattr(self._text_extractor, "model_name", None)
            field.model_version = getattr(self._text_extractor, "model_version", None)
            if disagreement:
                field.validation_status = ValidationStatus.NEEDS_REVIEW
                field.validation_reasons.append("multi_crop_disagreement")
        return fields

    def extract_ub04_service_lines(
        self,
        image,
        template: Template,
        page_number: int,
        *,
        registration_confidence: float,
        claim_total=None,
    ):
        """Run the structural FL42-FL48 engine on one registered table crop."""
        table = template.service_line_region
        if table is None:
            return [], None
        text_lines = self._text_extractor.extract_region(
            image, table.table_x0, table.table_y0, table.table_x1, table.table_y1
        )
        tokens = [
            UB04Token(
                text=line.text,
                bbox=(line.x0, line.y0, line.x1, line.y1),
                confidence=line.confidence,
            )
            for line in text_lines
        ]
        result = UB04ServiceLineEngine().reconstruct(
            tokens,
            registration_confidence=registration_confidence,
            claim_total=claim_total,
        )
        width, height = template.reference_dimensions.width_px, template.reference_dimensions.height_px
        type_by_name = {
            "revenue_code": "code", "description": "text",
            "hcpcs_rate_hipps_code": "code", "service_date": "date",
            "service_units": "number", "total_charges": "currency",
            "non_covered_charges": "currency",
        }
        lines = []
        for reconstructed in result.lines:
            values = {
                "revenue_code": reconstructed.revenue_code,
                "description": reconstructed.description,
                "hcpcs_rate_hipps_code": reconstructed.hcpcs,
                "service_date": reconstructed.service_date,
                "service_units": reconstructed.units,
                "total_charges": reconstructed.charge,
                "non_covered_charges": reconstructed.non_covered_charge,
            }
            row_y0 = int(table.table_y0 + (reconstructed.line_number - 1) * table.row_height_px)
            fields = []
            for column in table.columns:
                raw = "" if values.get(column.field_name) is None else str(values[column.field_name])
                field = _make_field(
                    template, column.field_name, type_by_name.get(column.field_name, column.field_type),
                    raw, reconstructed.mean_confidence, column.x0, row_y0,
                    column.x1, row_y0 + table.row_height_px, page_number, width, height,
                )
                if reconstructed.validation_errors or not reconstructed.automatically_eligible:
                    field.validation_status = ValidationStatus.NEEDS_REVIEW
                    field.validation_reasons.extend(result.reason_codes + reconstructed.validation_errors)
                fields.append(field)
            line = ServiceLine(
                line_number=reconstructed.line_number,
                service_date_from=reconstructed.service_date,
                units=reconstructed.units,
                charge_amount=reconstructed.charge,
                revenue_code=reconstructed.revenue_code,
                hcpcs_code=reconstructed.hcpcs,
                non_covered_charge_amount=reconstructed.non_covered_charge,
                fields=fields,
            )
            lines.append(line)
        return lines, result

    def extract_service_lines(
        self, image, template: Template, page_number: int
    ) -> list[ServiceLine]:
        table = template.service_line_region
        if table is None:
            return []
        width, height = (
            template.reference_dimensions.width_px,
            template.reference_dimensions.height_px,
        )

        lines: list[ServiceLine] = []
        method = (
            ExtractionMethod.REGIONAL_RAPIDOCR
            if getattr(self._text_extractor, "engine_name", "") == "rapidocr"
            else ExtractionMethod.REGIONAL_PADDLEOCR
        )
        for row_index in range(table.max_rows):
            row_y0 = table.table_y0 + row_index * table.row_height_px
            row_y1 = min(row_y0 + table.row_height_px, table.table_y1)

            row_fields: list[ExtractedField] = []
            for column in table.columns:
                raw_text, confidence = _region_text(
                    self._text_extractor, image, (column.x0, row_y0, column.x1, row_y1)
                )
                row_fields.append(
                    _make_field(
                        template,
                        column.field_name,
                        column.field_type,
                        raw_text,
                        confidence,
                        column.x0,
                        row_y0,
                        column.x1,
                        row_y1,
                        page_number,
                        width,
                        height,
                        method,
                    )
                )

            if _row_is_blank(row_fields):
                break  # service lines are contiguous from the top; stop at the first empty row

            line = ServiceLine(line_number=row_index + 1, fields=row_fields)
            _populate_service_line_shortcuts(line)
            lines.append(line)

        return lines


def _row_is_blank(fields: list[ExtractedField]) -> bool:
    return all(not f.raw_value.strip() for f in fields)


def _populate_service_line_shortcuts(line: ServiceLine) -> None:
    """Copy commonly-needed values onto ServiceLine's typed shortcut
    attributes (Phase 3 validation reads these directly rather than
    re-searching `line.fields` by name every time)."""
    by_name = {f.field_name: f for f in line.fields}
    if (f := by_name.get("procedure_code")) or (f := by_name.get("cpt_hcpcs")):
        line.procedure_code = f.normalized_value
    if f := by_name.get("place_of_service"):
        line.place_of_service = f.normalized_value
    if f := by_name.get("revenue_code"):
        line.revenue_code = f.normalized_value
    if (f := by_name.get("modifier")) and f.normalized_value:
        line.modifiers = [f.normalized_value]
    if (f := by_name.get("diagnosis_pointer")) and f.normalized_value:
        line.diagnosis_pointers = list(f.normalized_value.replace(" ", ""))
    for charge_field in ("charges", "total_charges"):
        if (f := by_name.get(charge_field)) and f.normalized_value:
            from decimal import Decimal, InvalidOperation

            try:
                line.charge_amount = Decimal(f.normalized_value)
            except InvalidOperation:
                pass
    if (f := by_name.get("units")) and f.normalized_value:
        from decimal import Decimal, InvalidOperation

        try:
            line.units = Decimal(f.normalized_value)
        except InvalidOperation:
            pass
    for date_field in ("date_from", "service_date"):
        if (f := by_name.get(date_field)) and f.normalized_value:
            from datetime import date

            line.service_date_from = date.fromisoformat(f.normalized_value)
    if (f := by_name.get("date_to")) and f.normalized_value:
        from datetime import date

        line.service_date_to = date.fromisoformat(f.normalized_value)
