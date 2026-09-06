"""Optional closed-world observer. No novel values, labels, or authority."""

from packages.llm_adjudication.azure import AzureLLMPricingConfig

from .models import Candidate


def bounded_selection(response: str, candidates: tuple[Candidate, ...]) -> Candidate | None:
    if response == "NONE":
        return None
    if len({c.candidate_id for c in candidates}) != len(candidates):
        raise ValueError("DUPLICATE_CANDIDATE_ID")
    matches = [c for c in candidates if c.candidate_id == response]
    if len(matches) != 1:
        raise ValueError("LLM_NOVEL_CANDIDATE_REJECTED")
    return matches[0]


def pricing_status(pricing: AzureLLMPricingConfig | None = None) -> str:
    return (pricing or AzureLLMPricingConfig()).cost_status
