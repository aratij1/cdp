from packages.ai_gateway.contracts import FieldResolutionResponse
from packages.ai_gateway.routing import EscalationContext, evidence_sufficient, next_provider
from packages.criticality import CriticalityLevel
from packages.docling_policy import DoclingRouteInput, should_run_docling


class Provider:
    def __init__(self, name):
        self.model_name = name


def test_model_cascade_selects_first_unattempted_and_honors_budget_sla():
    providers = [Provider("gemini-2.5-flash-lite"), Provider("gemini-2.5-flash")]
    context = EscalationContext(CriticalityLevel.C2, 0.1, 1.0, 5000)
    assert (
        next_provider(providers, {"gemini-2.5-flash-lite"}, context).model_name
        == "gemini-2.5-flash"
    )
    assert (
        next_provider(providers, set(), EscalationContext(CriticalityLevel.C2, 0.1, 0, 5000))
        is None
    )


def test_ai_confidence_never_short_circuits_c3_acceptance():
    response = FieldResolutionResponse(
        value="123",
        confidence=1.0,
        insufficient_evidence=False,
        provider="vertex",
        model="gemini",
        model_version="2.5",
    )
    assert not evidence_sufficient(response, EscalationContext(CriticalityLevel.C3, 0, 1, 1000))


def test_docling_runs_only_for_failed_tables_or_table_heavy_unstructured():
    assert not should_run_docling(DoclingRouteInput(True, False, False, True))
    assert should_run_docling(DoclingRouteInput(True, True, False, True))
    assert should_run_docling(DoclingRouteInput(False, False, True, False))
