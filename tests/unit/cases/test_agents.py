from __future__ import annotations

from uuid import uuid4

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.human_review_api.db.models import Base, ReviewAuditORM, ReviewTaskORM
from apps.human_review_api.db.repository import ReviewTaskRepository
from packages.agents.context import AgentContext, WorkflowState
from packages.agents.implementations import (
    ClaimReconciliationAgent,
    DocumentIntelligenceAgent,
    DocumentQualityAgent,
    EvidenceReconciliationAgent,
    ExtractionValidationAgent,
    GovernanceAuditAgent,
    HITLCommunicationAgent,
    IdentityResolutionAgent,
)
from packages.agents.orchestrator import ClaimsOrchestrator


def create_readable_document_image() -> Image.Image:
    """Helper to construct a high-contrast mock document image to pass quality audits."""
    img = Image.new("RGB", (400, 400), color="white")
    draw = ImageDraw.Draw(img)
    
    # Draw fine high-contrast grid lines every 15px to optimize brightness and Laplacian variance
    for i in range(0, 400, 15):
        draw.line([(i, 0), (i, 400)], fill="black", width=1)
        draw.line([(0, i), (400, i)], fill="black", width=1)
        
    # Draw mock text to simulate a claim header
    draw.text((10, 10), "CMS-1500 HEALTH INSURANCE CLAIM FORM", fill="black")
    draw.text((10, 50), "PHYSICIAN OR SUPPLIER INFORMATION", fill="black")
    return img


@pytest.fixture(name="db_session")
def fixture_db_session():
    # Setup in-memory sqlite engine and schema for real DB testing
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.mark.asyncio
async def test_agent_context_and_state_defaults():
    ctx = AgentContext()
    assert ctx.current_state == WorkflowState.INGESTED
    assert len(ctx.results) == 0
    assert len(ctx.errors) == 0


@pytest.mark.asyncio
async def test_document_intelligence_real_routing():
    # Provide a readable mock image
    img = create_readable_document_image()
    ctx = AgentContext(document_id=uuid4())
    ctx.metadata["document_image"] = img
    
    agent = DocumentIntelligenceAgent()
    updated_ctx = await agent.run(ctx)
    res = updated_ctx.get_result("Document Intelligence")
    
    assert res is not None
    # Real MultiSignalRouter loads the router and routes to classified types.
    # An unrecognized mock image will correctly route to UNKNOWN_UNSTRUCTURED, which is is_standard_form=False
    assert "classified_type" in res
    assert res["is_standard_form"] is False


@pytest.mark.asyncio
async def test_document_quality_real_assessment():
    img = create_readable_document_image()
    ctx = AgentContext(document_id=uuid4())
    ctx.metadata["document_image"] = img
    
    agent = DocumentQualityAgent()
    updated_ctx = await agent.run(ctx)
    res = updated_ctx.get_result("Document Quality & Localization")
    
    assert res is not None
    # High-contrast image will easily score above 0.50 threshold
    assert res["quality_score"] >= 0.50
    assert res["is_blurry"] is False
    assert res["deskew_required"] is False


@pytest.mark.asyncio
async def test_extraction_validation_real_luhn_algorithm():
    # Test valid NPI check-digit code (Luhn checksum passes)
    ctx1 = AgentContext()
    ctx1.metadata["extracted_fields"] = {
        "billing_provider_npi": "1234567893",
        "total_charge": "120.00"
    }
    agent = ExtractionValidationAgent()
    res_ctx1 = await agent.run(ctx1)
    res1 = res_ctx1.get_result("Extraction & Validation")
    assert len(res1["validation_errors"]) == 0

    # Test invalid NPI code (Luhn checksum fails)
    ctx2 = AgentContext()
    ctx2.metadata["extracted_fields"] = {
        "billing_provider_npi": "1234567890",
        "total_charge": "120.00"
    }
    res_ctx2 = await agent.run(ctx2)
    res2 = res_ctx2.get_result("Extraction & Validation")
    assert len(res2["validation_errors"]) > 0
    assert "fails the NPI check-digit algorithm" in res2["validation_errors"][0]


@pytest.mark.asyncio
async def test_identity_resolution_real_matcher():
    ctx = AgentContext()
    ctx.metadata["extracted_fields"] = {
        "billing_provider_npi": "1234567893",
        "patient_name": "DOE, JOHN"
    }
    agent = IdentityResolutionAgent()
    updated_ctx = await agent.run(ctx)
    res = updated_ctx.get_result("Identity Resolution")
    
    assert res is not None
    assert res["resolved_provider"]["provider_npi"] == "1234567893"
    assert res["resolved_provider"]["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_evidence_reconciliation_real_builder():
    ctx = AgentContext()
    ctx.metadata["extracted_fields"] = {
        "total_charge": "500.00",
        "billing_provider_npi": "1234567893"
    }
    agent = EvidenceReconciliationAgent()
    updated_ctx = await agent.run(ctx)
    res = updated_ctx.get_result("Evidence Reconciliation")
    
    assert res is not None
    assert "evidence_package" in res
    assert res["evidence_package"]["evidence_items_count"] > 0


@pytest.mark.asyncio
async def test_claim_reconciliation_real_check():
    ctx = AgentContext()
    ctx.metadata["extracted_fields"] = {
        "total_charge": "250.00"
    }
    agent = ClaimReconciliationAgent()
    updated_ctx = await agent.run(ctx)
    res = updated_ctx.get_result("Claim Reconciliation")
    
    assert res is not None
    # ClaimReconciliationAgent correctly falls back to metadata extracted fields
    assert res["reported_total"] == "250.00"
    assert res["reconciliation_status"] == "MATCHED"


@pytest.mark.asyncio
async def test_governance_tamper_evident_db_persistence(db_session):
    ctx = AgentContext(workflow_id=uuid4())
    ctx.metadata["db_session"] = db_session
    ctx.metadata["audit_record_factory"] = ReviewAuditORM
    ctx.set_result("test_agent_1", {"key1": "value1"})
    
    agent = GovernanceAuditAgent()
    updated_ctx = await agent.run(ctx)
    
    # Assert signature computation
    audit_res = updated_ctx.get_result("Governance & Audit")
    assert "tamper_evident_sha256" in audit_res
    
    # Assert database persistence
    db_record = db_session.query(ReviewAuditORM).filter_by(task_id=ctx.workflow_id).first()
    assert db_record is not None
    assert db_record.decision_hash == audit_res["tamper_evident_sha256"]
    assert db_record.actor == "agent:governance"


@pytest.mark.asyncio
async def test_hitl_escalation_and_db_persistence(db_session):
    # Set validation errors so HITL review is triggered
    ctx = AgentContext(workflow_id=uuid4(), claim_id=uuid4(), document_id=uuid4())
    ctx.metadata["db_session"] = db_session
    ctx.metadata["review_task_repository"] = ReviewTaskRepository(db_session)
    ctx.metadata["field_id"] = uuid4()
    ctx.set_result("Extraction & Validation", {
        "validation_errors": ["NPI fails the algorithm check"]
    })
    
    agent = HITLCommunicationAgent()
    updated_ctx = await agent.run(ctx)
    res = updated_ctx.get_result("HITL & Communication")
    
    assert res["hitl_required"] is True
    assert res["status"] == "WAITING_REVIEWER"
    
    # Assert persistent review task record was saved in DB
    db_task = db_session.query(ReviewTaskORM).filter_by(document_id=ctx.document_id).first()
    assert db_task is not None
    assert db_task.status == "OPEN"
    assert "NPI fails the algorithm check" in db_task.validation_errors


@pytest.mark.asyncio
async def test_claims_orchestrator_complete_run():
    orchestrator = ClaimsOrchestrator()
    ctx = AgentContext(claim_id=uuid4())

    # Supply realistic valid document image and valid extraction fields to orchestrate auto-approval
    img = create_readable_document_image()
    ctx.metadata["document_image"] = img
    ctx.metadata["extracted_fields"] = {
        "billing_provider_npi": "1234567893",
        "total_charge": "482.00",
        "patient_name": "DOE, JOHN"
    }

    final_ctx = await orchestrator.execute_workflow(ctx)
    
    # Verify successfully reached final state
    assert final_ctx.current_state == WorkflowState.APPROVED
    
    # Check that key agents executed and saved structural findings
    assert "Intake Orchestrator" in final_ctx.results
    assert "Document Intelligence" in final_ctx.results
    assert "Extraction & Validation" in final_ctx.results
    assert "Governance & Audit" in final_ctx.results
    assert "HITL & Communication" in final_ctx.results
