"""Region-scoped semantic escalation for ambiguous Bundle-D evidence."""

from __future__ import annotations

import io
from hashlib import sha256
from uuid import uuid4

from PIL import Image

from packages.ai_gateway import SelectiveResolutionCoordinator
from packages.ai_gateway.contracts import FieldResolutionRequest
from packages.domain.common import BoundingBox
from packages.ocr.contracts import OCRCandidate
from packages.policy_engine import PolicyAction

from .models import CanonicalLayoutCandidate


ROUTES = {
    "AI_CHEAP": PolicyAction.GEMINI_CHEAP,
    "AI_STANDARD": PolicyAction.GEMINI_STANDARD,
    "AI_ADVANCED": PolicyAction.GEMINI_ADVANCED,
}


class BundleDRegionEscalator:
    """Calls the central gateway with one bounded region and returns E7 only."""

    def __init__(self, coordinator: SelectiveResolutionCoordinator) -> None:
        self._coordinator = coordinator

    async def resolve(
        self, *, route: str, tenant_id: str, document_id: str,
        field_name: str, expected_type: str, page: Image.Image,
        region: BoundingBox, label: str,
        candidates: list[CanonicalLayoutCandidate], contains_phi: bool = True,
        allowed_pattern: str | None = None, remaining_sla_ms: int | None = None,
        estimated_cost_usd: float = 0,
    ) -> OCRCandidate:
        if route not in ROUTES:
            raise ValueError(f"unsupported Bundle-D AI route: {route}")
        crop = page.crop((region.x0, region.y0, region.x1, region.y1))
        buffer = io.BytesIO(); crop.save(buffer, format="PNG"); payload = buffer.getvalue()
        request = FieldResolutionRequest(
            request_id=str(uuid4()), tenant_id=tenant_id, document_id=document_id,
            field_name=field_name, expected_type=expected_type,
            crop_bytes=payload, crop_sha256=sha256(payload).hexdigest(),
            scope="FIELD_CROP", allowed_pattern=allowed_pattern,
            nearby_label=label,
            ocr_candidates=[candidate.value for candidate in candidates[:10]],
            validation_errors=["AMBIGUOUS_LAYOUT_LINK"],
            contains_phi=contains_phi, remaining_sla_ms=remaining_sla_ms,
        )
        result = await self._coordinator.resolve(
            ROUTES[route], request, estimated_cost_usd=estimated_cost_usd,
        )
        auxiliary = result.candidate
        # This is deliberately an OCRCandidate with no acceptance authority.
        # EvidenceDecisionService remains the only disposition owner.
        return OCRCandidate(
            value=auxiliary.value, raw_value=auxiliary.value or "",
            engine=auxiliary.source, model_name=auxiliary.model,
            model_version=auxiliary.model_version,
            preprocessing_variant="bundle_d_ambiguous_region",
            raw_confidence=auxiliary.confidence, calibrated_confidence=None,
            bounding_box=region, latency_ms=0,
            validation_results=auxiliary.validation_results + ("E7_AUXILIARY_ONLY",),
            evidence_reference=f"ai_gateway:{route}",
            actual_cost_usd=auxiliary.actual_cost_usd,
        )
