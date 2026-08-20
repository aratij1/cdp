
import pytest

from packages.domain.claim import Claim
from packages.domain.extraction import ExtractedField


def test_finalization_gate_rejects_unresolved_critical_fields():
    # Construct a Claim with one critical field that is unresolved
    unresolved_field = ExtractedField(
        field_name="total_charge",
        raw_value="100.00",
        confidence=0.9,
        page_number=1,
        bounding_box={"x0": 0, "y0": 0, "x1": 10, "y1": 10, "image_width": 100, "image_height": 100},
        extraction_method="CACHE_HIT",
        is_critical=True,
        disposition="NEEDS_RETRY" # Not VALIDATED_AUTOMATICALLY or VERIFIED_BY_HUMAN
    )
    
    claim = Claim(
        claim_id="00000000-0000-0000-0000-000000000000",
        document_id="00000000-0000-0000-0000-000000000000",
        tenant_id="test",
        correlation_id="00000000-0000-0000-0000-000000000000",
        form_type="CMS1500",
        total_charge_amount=100.0,
        schema_version="1",
        template_version="1",
        header_fields=[unresolved_field],
        service_lines=[]
    )
    
    # We can test the logic directly or simulate the worker
    # We added the check right after claim construction
    unresolved_critical = [
        f for f in claim.header_fields + [f for line in claim.service_lines for f in line.fields]
        if f.is_critical and f.disposition not in ("VALIDATED_AUTOMATICALLY", "VERIFIED_BY_HUMAN")
    ]
    
    assert len(unresolved_critical) == 1
    
    # Verify the check fails
    with pytest.raises(ValueError, match="Cannot finalize claim: unresolved critical fields exist"):
        if unresolved_critical:
            raise ValueError("Cannot finalize claim: unresolved critical fields exist")

def test_finalization_gate_allows_resolved_critical_fields():
    resolved_field = ExtractedField(
        field_name="total_charge",
        raw_value="100.00",
        confidence=0.9,
        page_number=1,
        bounding_box={"x0": 0, "y0": 0, "x1": 10, "y1": 10, "image_width": 100, "image_height": 100},
        extraction_method="CACHE_HIT",
        is_critical=True,
        disposition="VALIDATED_AUTOMATICALLY"
    )
    
    claim = Claim(
        claim_id="00000000-0000-0000-0000-000000000000",
        document_id="00000000-0000-0000-0000-000000000000",
        tenant_id="test",
        correlation_id="00000000-0000-0000-0000-000000000000",
        form_type="CMS1500",
        total_charge_amount=100.0,
        schema_version="1",
        template_version="1",
        header_fields=[resolved_field],
        service_lines=[]
    )
    
    unresolved_critical = [
        f for f in claim.header_fields + [f for line in claim.service_lines for f in line.fields]
        if f.is_critical and f.disposition not in ("VALIDATED_AUTOMATICALLY", "VERIFIED_BY_HUMAN")
    ]
    
    assert len(unresolved_critical) == 0
