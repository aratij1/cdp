import json
from pathlib import Path

from PIL import Image

from evaluation.phase8_5_claim_unlock import run
from packages.claim_decision import ClaimDecisionContext, ClaimDecisionService
from packages.claim_evidence import ClaimEvidenceBuilder
from packages.criticality import CriticalityLevel
from packages.deterministic_evidence import DeterministicEvidenceService
from packages.domain.common import BoundingBox
from packages.evidence import (
    EvidencePolicy,
    FieldEvidenceBundle,
    StructuralLocalizationEvidence,
    StructuralLocalizationType,
)
from packages.evidence_decision import (
    DecisionContext,
    EvidenceDecisionService,
    FieldDecision,
    FieldDisposition,
    NextAction,
)
from packages.field_localization import FieldDefinitionRegistry, FieldLocator
from packages.ocr.contracts import OCRCandidate
from packages.page_observation import PageObservationService
from workers.page_detection.text_extraction import TextLine

ROOT = Path(__file__).resolve().parents[3]


class CountingOCR:
    model_version = "fixture-v1"

    def __init__(self, lines):
        self.lines = lines
        self.calls = 0

    def extract(self, _image):
        self.calls += 1
        return self.lines


def candidate(value="12-3456789"):
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine="rapidocr_full_page",
        model_name="RapidOCR-ONNX",
        model_version="fixture-v1",
        preprocessing_variant="page-observation",
        raw_confidence=0.99,
        calibrated_confidence=None,
        bounding_box=BoundingBox(
            x0=700, y0=100, x1=850, y1=130, image_width=1000, image_height=1200
        ),
        latency_ms=1,
    )


def test_federal_tax_no_uses_canonical_observation_and_anchor_locator():
    ocr = CountingOCR(
        [
            TextLine("FEDERAL TAX NO", 700, 100, 870, 125, 0.99),
            TextLine("12-3456789", 705, 145, 825, 170, 0.99),
        ]
    )
    observation = PageObservationService(ocr, preprocessing_version="fixture-v1").observe(
        "ub-tax", Image.new("RGB", (1000, 1200), "white")
    )
    definition = FieldDefinitionRegistry.load(ROOT / "config/field_definitions/ub04_v1.yaml").get(
        "UB04", "federal_tax_no"
    )
    location = FieldLocator().locate(observation, definition)

    assert ocr.calls == 1
    assert definition.datatype == "TAX_IDENTIFIER"
    assert definition.blocking is True
    assert location.method.value == "ANCHOR_RELATIVE"
    assert location.bbox is not None


def test_tax_syntax_is_canonical_deterministic_e4_without_digit_repair():
    service = DeterministicEvidenceService()
    valid = service.evaluate("federal_tax_no", "12-3456789")
    invalid = service.evaluate("federal_tax_no", "12-345678X")
    assert valid.passed
    assert "TAX_IDENTIFIER_SYNTAX_VALID" in valid.evidence
    assert not invalid.passed
    assert invalid.failure_reasons == ["INVALID_TAX_IDENTIFIER"]


def test_federal_tax_no_cannot_bypass_evidence_decision_service():
    policy = EvidencePolicy.load(ROOT / "config/evidence_policies_phase8_4_balanced.yaml")
    decision = EvidenceDecisionService(evidence_policy=policy).decide(
        DecisionContext(
            field_name="federal_tax_no",
            document_family="UB04",
            criticality=CriticalityLevel.C2,
            required=True,
            blocks_stp=True,
            candidates=[candidate()],
            deterministic_evidence={"FORMAT_VALID", "TAX_IDENTIFIER_SYNTAX_VALID"},
            deterministic_evidence_version="fixture-v1",
            hard_validation_passed=True,
            structural_localization=StructuralLocalizationEvidence(
                evidence_type=StructuralLocalizationType.ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED,
                confidence=0.99,
                confirmed=True,
                reason_codes=("BOUNDED_ALIAS_MATCH", "OBSERVED_VALUE_TOKEN_GEOMETRY"),
                source="DYNAMIC_GEOMETRY:ANCHOR_RELATIVE",
            ),
        )
    )
    assert decision.disposition not in {
        FieldDisposition.AUTO_ACCEPTED,
        FieldDisposition.REFERENCE_CONFIRMED,
    }
    assert decision.blocks_stp is True


def test_cms_member_id_critical_acceptance_requires_approved_independent_evidence():
    policy = EvidencePolicy.load(ROOT / "config/evidence_policies_phase8_4_balanced.yaml")
    decision = EvidenceDecisionService(evidence_policy=policy).decide(
        DecisionContext(
            field_name="member_id",
            document_family="CMS1500",
            criticality=CriticalityLevel.C3,
            required=True,
            blocks_stp=True,
            candidates=[candidate("ABC-12345")],
            deterministic_evidence={"FORMAT_VALID"},
            deterministic_evidence_version="fixture-v1",
            hard_validation_passed=True,
            structural_localization=StructuralLocalizationEvidence(
                evidence_type=StructuralLocalizationType.ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED,
                confidence=0.99,
                confirmed=True,
                reason_codes=("BOUNDED_ALIAS_MATCH", "OBSERVED_VALUE_TOKEN_GEOMETRY"),
                source="DYNAMIC_GEOMETRY:ANCHOR_RELATIVE",
            ),
        )
    )
    assert decision.disposition not in {
        FieldDisposition.AUTO_ACCEPTED,
        FieldDisposition.REFERENCE_CONFIRMED,
    }
    assert "E2" in decision.missing_evidence


def test_unresolved_field_blocks_stp_only_when_explicitly_configured_on_decision():
    service = ClaimDecisionService.load()

    def unresolved(blocks_stp):
        return FieldDecision(
            field_name="federal_tax_no",
            disposition=FieldDisposition.HUMAN_REVIEW_REQUIRED,
            calibrated_probability=0.0,
            next_action=NextAction.HUMAN_REVIEW,
            policy_version="fixture-v1",
            criticality=CriticalityLevel.C2,
            required=True,
            blocks_stp=blocks_stp,
            requires_review_when_unresolved=True,
            evidence_bundle=FieldEvidenceBundle(field_name="federal_tax_no"),
        )

    blocked = service.decide(
        ClaimDecisionContext(
            claim_id="blocked",
            document_family="UB04",
            field_decisions=[unresolved(True)],
            enforce_configured_required_fields=False,
        )
    )
    nonblocking = service.decide(
        ClaimDecisionContext(
            claim_id="nonblocking",
            document_family="UB04",
            field_decisions=[unresolved(False)],
            enforce_configured_required_fields=False,
        )
    )
    assert blocked.blocking_unresolved_fields == ["federal_tax_no"]
    assert not blocked.stp_eligible
    assert nonblocking.blocking_unresolved_fields == []
    assert nonblocking.stp_eligible


def test_financial_reconciliation_persists_fact_and_never_changes_total():
    total = "150.00"
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-1",
        document_family="CMS1500",
        claim_values={"total_charge": total},
        service_lines=[{"charge_amount": "100.00"}, {"charge_amount": "50.00"}],
    )
    item = next(i for i in result.evidence_items if i.evidence_type == "CLAIM_TOTAL_CONFIRMED")
    assert item.value == total
    assert item.metadata["reported_total"] == total
    assert item.metadata["computed_total"] == total
    assert item.metadata["difference"] == "0.00"
    assert item.metadata["line_count"] == 2
    assert item.metadata["result"] == "PASS"


def test_financial_contradiction_is_not_emitted_as_supporting_e6():
    result = ClaimEvidenceBuilder.load().build(
        claim_id="claim-2",
        document_family="CMS1500",
        claim_values={"total_charge": "150.00"},
        service_lines=[{"charge_amount": "99.00"}],
    )
    assert "CLAIM_TOTAL_RECONCILED" not in {i.evidence_type for i in result.evidence_items}
    contradiction = next(
        i for i in result.contradictions if i.evidence_type == "CLAIM_TOTAL_CONTRADICTION"
    )
    assert contradiction.metadata["result"] == "CONTRADICTION"


def test_phase8_5_replay_is_ocr_free_and_preserves_zero_false_accepts(tmp_path):
    source = (ROOT / "evaluation/phase8_5_claim_unlock.py").read_text("utf-8")
    assert "PageObservationService" not in source
    assert "RapidOCR" not in source
    result = run(tmp_path)
    assert result["baseline"]["ocr_reruns"] == 0
    assert result["decision"]["critical_false_accepts"] == 0
    assert result["decision"]["total_false_accepts"] == 0
    assert json.loads((tmp_path / "decision.json").read_text("utf-8"))["decision"] == "NO_PROMOTION"
