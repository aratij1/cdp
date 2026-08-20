import pytest

from packages.settings import Settings
from workers.vlm_fallback.factory import (
    AzureProductionConfigurationError,
    build_azure_review_adapter,
)


def test_production_azure_fails_closed_when_disabled():
    with pytest.raises(AzureProductionConfigurationError, match="disabled"):
        build_azure_review_adapter(Settings(_env_file=None, azure_ai_evaluation_enabled=False))


def test_production_azure_blocks_automatic_acceptance():
    settings = Settings(
        _env_file=None,
        azure_ai_evaluation_enabled=True,
        azure_openai_endpoint="https://example.openai.azure.com",
        azure_openai_api_key="secret",
        azure_ai_evaluation_deployment="gpt-4o",
        azure_openai_review_only=False,
    )
    with pytest.raises(AzureProductionConfigurationError, match="holdout"):
        build_azure_review_adapter(settings)


def test_production_azure_builds_only_in_review_mode():
    settings = Settings(
        _env_file=None,
        azure_ai_evaluation_enabled=True,
        azure_openai_endpoint="https://example.openai.azure.com",
        azure_openai_api_key="secret",
        azure_ai_evaluation_deployment="gpt-4o",
        azure_openai_review_only=True,
    )
    assert build_azure_review_adapter(settings) is not None
