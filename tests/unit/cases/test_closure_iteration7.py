"""Iteration 7 fail-closed contracts, with synthetic data only."""

import asyncio
from datetime import UTC, datetime

import pytest

from evaluation.production_evidence_readiness import deterministic_adapter_overhead
from packages.claim_evidence.authoritative_snapshot import MatchStatus
from packages.claim_evidence.configuration import AuthorityConfiguration, ProviderType
from packages.claim_evidence.enablement import LookupResult, SourceResult, SourceStatus
from packages.claim_evidence.lookup_runtime import (
    BoundedAuthorityClient,
    LookupPolicy,
    independent_lookups,
)
from packages.claim_evidence.source_review import ReviewStatus
from packages.claim_intelligence.enablement import ClaimRequirements
from packages.claim_intelligence.review_scenario import reviewed_scenario


@pytest.mark.parametrize("provider", list(ProviderType))
def test_reference_configuration_never_activates_authority(provider):
    config = AuthorityConfiguration(provider, "v1")
    assert config.status == "NOT_AVAILABLE" and not config.source_reference_supplied
    assert not config.production_authority
    configured = AuthorityConfiguration(provider, "v1", snapshot_reference="governed-registry-name")
    assert configured.source_reference_supplied and configured.status == "NOT_AVAILABLE"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"endpoint_reference": "https://example.invalid/api"},
        {"credential_reference_name": "secret with whitespace"},
        {"endpoint_reference": "one", "snapshot_reference": "two"},
        {"timeout_ms": 0},
        {"cache_ttl_seconds": -1},
    ],
)
def test_configuration_rejects_inline_values_and_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        AuthorityConfiguration(ProviderType.MEMBER, "v1", **kwargs)


@pytest.mark.parametrize(
    "status,available,expected",
    [
        (SourceStatus.AVAILABLE_UNVERIFIED, False, "FILE_PRESENT"),
        (SourceStatus.AVAILABLE_UNVERIFIED, True, "VERIFICATION_AVAILABLE"),
        (SourceStatus.VERIFIED, True, "VALUE_VERIFIED"),
        (SourceStatus.CONFLICT, True, "CONFLICT"),
        (SourceStatus.UNREADABLE, True, "UNREADABLE"),
        (SourceStatus.NOT_AVAILABLE, False, "NOT_AVAILABLE"),
    ],
)
def test_source_evidence_dimensions(status, available, expected):
    result = SourceResult(status, "TEST", datetime.now(UTC), verification_available=available)
    assert result.evidence_state == expected
    assert not result.production_authority and not result.release_truth
    assert not result.resolves_source_review


@pytest.mark.parametrize(
    "status,unlocked",
    [
        (ReviewStatus.NOT_REVIEWED, 0),
        (ReviewStatus.CONFIRMED_VALUE, 1),
        (ReviewStatus.CONFIRMED_CONFLICT, 0),
        (ReviewStatus.CONFIRMED_UNREADABLE, 0),
    ],
)
def test_scenario_uses_supplied_review_state(status, unlocked):
    claims = (ClaimRequirements("synthetic", 0, frozenset({"SOURCE_REVIEW"})),)
    result = reviewed_scenario(claims, frozenset({"SOURCE_REVIEW"}), {"synthetic": (status,)})
    assert result["potentially_stp_capable_claims"] == unlocked
    assert result["achieved_production_stp"] is None


def test_one_confirmed_field_cannot_clear_another_conflict_or_missing_review():
    claims = (ClaimRequirements("synthetic", 0, frozenset({"SOURCE_REVIEW"})),)
    for states in [(), (ReviewStatus.CONFIRMED_VALUE, ReviewStatus.CONFIRMED_CONFLICT)]:
        assert reviewed_scenario(claims, frozenset(), {"synthetic": states})["potential_stp"] == 0
    with pytest.raises(ValueError):
        reviewed_scenario(claims, frozenset(), {"outside": (ReviewStatus.CONFIRMED_VALUE,)})


def test_nested_lists_ordering_parallel_and_cache_isolation():
    async def scenario():
        calls = []

        async def transport(**query):
            calls.append(query)
            return LookupResult(
                MatchStatus.MATCH,
                "synthetic",
                datetime.now(UTC),
                "TEST",
                provenance_ids=("synthetic:record",),
            )

        policy = LookupPolicy(ttl_seconds=60)
        one = BoundedAuthorityClient("one", transport, policy=policy)
        two = BoundedAuthorityClient("two", transport, policy=policy)
        query = {"nested": {"a": [1, {"b": 2}], "z": 3}}
        first = await independent_lookups({"one": (one, query), "two": (two, query)})
        assert all(not v.cache_hit for v in first.values()) and len(calls) == 2
        assert (await one.lookup(nested={"z": 3, "a": [1, {"b": 2}]})).cache_hit
        assert not (await one.lookup(nested={"z": 3, "a": [{"b": 2}, 1]})).cache_hit
        assert not (await one.lookup(nested={"z": 3, "a": (1, {"b": 2})})).cache_hit
        assert (await two.lookup(**query)).cache_hit

    asyncio.run(scenario())


def test_nested_list_mutation_during_lookup_does_not_change_snapshot():
    async def scenario():
        entered, resume = asyncio.Event(), asyncio.Event()
        observed = []

        async def transport(**query):
            entered.set()
            await resume.wait()
            observed.append(query)
            return LookupResult(
                MatchStatus.MATCH,
                "synthetic",
                datetime.now(UTC),
                "TEST",
                provenance_ids=("synthetic:record",),
            )

        client = BoundedAuthorityClient("one", transport, policy=LookupPolicy(ttl_seconds=60))
        value = [{"x": [1, 2]}]
        task = asyncio.create_task(client.lookup(value=value))
        await entered.wait()
        value[0]["x"].reverse()
        value.append(3)
        resume.set()
        await task
        assert observed == [{"value": [{"x": [1, 2]}]}]
        assert (await client.lookup(value=[{"x": [1, 2]}])).cache_hit
        assert not (await client.lookup(value=value)).cache_hit

    asyncio.run(scenario())


def test_adapter_double_proves_concurrency_without_network_claim():
    report = asyncio.run(deterministic_adapter_overhead())
    assert report["all_entered_before_completion"] and report["all_results_match"]
    assert report["production_network_ms"] is None


def test_prediction_freeze_complete_immutable_and_not_truth(tmp_path):
    from packages.real_data_evaluation.prediction_freeze import freeze_predictions

    path = tmp_path / "evaluator_only.json"
    args = dict(  # noqa: C408
        cohort={"page": "package"},
        configuration_sha256="a" * 64,
        source_sha256={"page": "b" * 64},
        predictions=[
            {
                "page_id": "page",
                "package_id": "package",
                "fields": {},
                "execution_status": "EXECUTED",
            }
        ],
    )
    first = freeze_predictions(path, **args)
    assert first == freeze_predictions(path, **args)
    assert not first["reviewer_visible"]
    args["predictions"][0]["fields"] = {"synthetic_field": "synthetic value"}
    with pytest.raises(ValueError, match="FROZEN_PREDICTIONS_CHANGED"):
        freeze_predictions(path, **args)
    args["predictions"] = []
    with pytest.raises(ValueError, match="INCOMPLETE_PREDICTION_COHORT"):
        freeze_predictions(path, **args)


def test_parallel_queue_has_explicit_bound_and_immutable_context():
    async def scenario():
        entered, resume = asyncio.Event(), asyncio.Event()
        active = peak = 0
        observed = []

        async def transport(**query):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            entered.set()
            await resume.wait()
            observed.append(query["value"])
            active -= 1
            return LookupResult(
                MatchStatus.MATCH,
                "synthetic",
                datetime.now(UTC),
                "TEST",
                provenance_ids=("synthetic:record",),
            )

        client = BoundedAuthorityClient("one", transport)
        queries = {str(i): (client, {"value": [i]}) for i in range(6)}
        pending = asyncio.create_task(independent_lookups(queries, max_concurrent=2))
        await entered.wait()
        for _, query in queries.values():
            query["value"].append(99)
        resume.set()
        results = await pending
        assert peak == 2 and len(results) == 6
        assert sorted(observed) == [[i] for i in range(6)]

    asyncio.run(scenario())
