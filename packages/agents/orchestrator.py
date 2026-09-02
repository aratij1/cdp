from __future__ import annotations

import logging
from uuid import UUID
from typing import Any, Dict, List, Optional
from packages.agents.context import AgentContext, WorkflowState
from packages.agents.base import BaseAgent
from packages.agents.implementations import (
    IntakeOrchestratorAgent,
    DocumentIntelligenceAgent,
    DocumentQualityAgent,
    ExtractionValidationAgent,
    IdentityResolutionAgent,
    PolicyCoverageAgent,
    EvidenceReconciliationAgent,
    UnderwritingRiskAgent,
    PricingRatingAgent,
    ClaimCodingClinicalAgent,
    ClaimReconciliationAgent,
    FraudAnomalyAgent,
    UnderwritingDecisionAgent,
    ClaimDecisionAgent,
    GovernanceAuditAgent,
    HITLCommunicationAgent,
)

logger = logging.getLogger(__name__)


class ClaimsOrchestrator:
    """Central state machine controlling workflow execution, routing, and transitions."""

    def __init__(self) -> None:
        # Construct and register the 16 standard agents
        self.agents: Dict[str, BaseAgent] = {
            "intake": IntakeOrchestratorAgent(),
            "doc_intel": DocumentIntelligenceAgent(),
            "doc_quality": DocumentQualityAgent(),
            "extraction": ExtractionValidationAgent(),
            "identity": IdentityResolutionAgent(),
            "policy": PolicyCoverageAgent(),
            "evidence": EvidenceReconciliationAgent(),
            "risk": UnderwritingRiskAgent(),
            "pricing": PricingRatingAgent(),
            "coding": ClaimCodingClinicalAgent(),
            "reconciliation": ClaimReconciliationAgent(),
            "fraud": FraudAnomalyAgent(),
            "underwriting_decision": UnderwritingDecisionAgent(),
            "claim_decision": ClaimDecisionAgent(),
            "governance": GovernanceAuditAgent(),
            "hitl": HITLCommunicationAgent(),
        }

        # Sequential mapping of workflow states to their primary executing agent
        self.state_routing: Dict[WorkflowState, List[str]] = {
            WorkflowState.INGESTED: ["intake"],
            WorkflowState.DOCUMENT_PROCESSING: ["doc_intel", "doc_quality"],
            WorkflowState.EXTRACTING: ["extraction"],
            WorkflowState.VALIDATING: ["extraction"],
            WorkflowState.IDENTITY_RESOLUTION: ["identity"],
            WorkflowState.COVERAGE_CHECK: ["policy"],
            WorkflowState.EVIDENCE_RECONCILIATION: ["evidence"],
            WorkflowState.RISK_ASSESSMENT: ["risk"],
            WorkflowState.CODING: ["coding"],
            WorkflowState.RECONCILIATION: ["reconciliation"],
            WorkflowState.FRAUD_CHECK: ["fraud"],
            WorkflowState.DECISION: ["underwriting_decision", "claim_decision"],
            WorkflowState.HITL_REVIEW: ["hitl"],
        }

    async def execute_workflow(self, context: AgentContext) -> AgentContext:
        """Runs the claims pipeline step-by-step through valid state transitions with retry logic."""
        logger.info(f"Starting ClaimsOrchestrator execution for workflow: {context.workflow_id}")

        # List of states to visit in a standard, successful run
        pipeline_sequence = [
            WorkflowState.INGESTED,
            WorkflowState.DOCUMENT_PROCESSING,
            WorkflowState.EXTRACTING,
            WorkflowState.VALIDATING,
            WorkflowState.IDENTITY_RESOLUTION,
            WorkflowState.COVERAGE_CHECK,
            WorkflowState.EVIDENCE_RECONCILIATION,
            WorkflowState.RISK_ASSESSMENT,
            WorkflowState.CODING,
            WorkflowState.RECONCILIATION,
            WorkflowState.FRAUD_CHECK,
            WorkflowState.DECISION,
            WorkflowState.HITL_REVIEW,
        ]

        for target_state in pipeline_sequence:
            # Transition state
            context.current_state = target_state
            agent_keys = self.state_routing.get(target_state, [])

            for key in agent_keys:
                agent = self.agents.get(key)
                if not agent:
                    continue

                # Run agent with retry handling (circuit breaker style)
                attempt = 0
                max_attempts = 3
                success = False

                while attempt < max_attempts and not success:
                    attempt += 1
                    try:
                        logger.info(f"Invoking {agent.name} (Attempt {attempt}/{max_attempts})")
                        await agent.run(context)
                        
                        # Check if agent execution set any error in the context
                        if agent.name in context.errors:
                            raise RuntimeError(context.errors[agent.name])
                        
                        success = True
                    except Exception as err:
                        logger.warning(f"{agent.name} execution failed: {err}")
                        if attempt >= max_attempts:
                            context.set_error(agent.name, f"Execution failed after {max_attempts} attempts: {err}")
                            context.current_state = WorkflowState.FAILED
                            return context

            # Run Governance & Audit agent after every transition to record audit signatures
            audit_agent = self.agents["governance"]
            await audit_agent.run(context)

        # Dynamic terminal state outcome logic
        hitl_res = context.get_result("HITL & Communication")
        if hitl_res and hitl_res.get("hitl_required", False):
            context.current_state = WorkflowState.HITL_REVIEW
        else:
            decision_res = context.get_result("Claim Decision")
            if decision_res and decision_res.get("recommended_adjudication") == "AUTO_APPROVE":
                context.current_state = WorkflowState.APPROVED
            else:
                context.current_state = WorkflowState.COMPLETED

        logger.info(f"Workflow {context.workflow_id} executed successfully. Final state: {context.current_state}")
        return context
