"""Synthetic authority/source contracts: no real values or release truth."""

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from packages.claim_evidence.authoritative_snapshot import MatchStatus
from packages.claim_evidence.enablement import (
    IdentityAuthorityProvider,
    LookupResult,
    MemberAuthorityProvider,
    SourceBinding,
    SourceEvidenceProvider,
    SourceStatus,
)
from packages.claim_evidence.lookup_runtime import (
    BoundedAuthorityClient,
    LookupPolicy,
    independent_lookups,
)
from packages.claim_evidence.source_review import (
    ReviewStatus,
    SourceReviewProvider,
    SourceReviewRecord,
    review_digest,
)


def source(tmp_path, status=ReviewStatus.CONFIRMED_VALUE):
    path = tmp_path / "source.txt"
    path.write_bytes(b"synthetic source only")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    binding = SourceBinding("pkg", "page", "attach", path, sha, "boundary", ("region",))
    record = SourceReviewRecord(
        "pkg",
        "page",
        "attach",
        sha,
        "region",
        "test_field",
        status,
        "record",
        "reviewer",
        "policy",
        datetime.now(UTC),
        "synthetic" if status == ReviewStatus.CONFIRMED_VALUE else None,
    )
    query = {
        "package_id": "pkg",
        "page_id": "page",
        "attachment_id": "attach",
        "field_name": "test_field",
        "region_provenance_id": "region",
    }
    return binding, record, query


def reviews(record, **kwargs):
    return SourceReviewProvider(
        (record,),
        expected_sha256=review_digest((record,)),
        authorized_reviewers=frozenset({"reviewer"}),
        policy_id="policy",
        **kwargs,
    )


@pytest.mark.parametrize(
    "status,expected",
    [
        (ReviewStatus.CONFIRMED_VALUE, SourceStatus.VERIFIED),
        (ReviewStatus.CONFIRMED_UNREADABLE, SourceStatus.UNREADABLE),
        (ReviewStatus.CONFIRMED_CONFLICT, SourceStatus.CONFLICT),
        (ReviewStatus.NOT_REVIEWED, SourceStatus.AVAILABLE_UNVERIFIED),
    ],
)
def test_source_review_outcomes_are_scoped_and_never_automatic_acceptance(
    tmp_path, status, expected
):
    binding, record, query = source(tmp_path, status)
    result = SourceEvidenceProvider((binding,), reviews=reviews(record)).lookup(**query)
    assert result.status == expected and result.provenance_ids
    assert not result.release_truth and not result.production_authority
    assert not result.resolves_source_review  # Existing acceptance path still required.
    assert (
        SourceEvidenceProvider((binding,)).lookup(**query).status
        == SourceStatus.AVAILABLE_UNVERIFIED
    )


@pytest.mark.parametrize(
    "change",
    [
        {"reviewer_id": "unauthorized"},
        {"policy_id": "other"},
        {"source_sha256": "wrong"},
        {"field_name": "different"},
        {"region_provenance_id": "different"},
        {"reviewed_at": datetime.now(UTC) + timedelta(days=1)},
        {"confirmed_value": None},
    ],
)
def test_bad_review_never_verifies(tmp_path, change):
    binding, record, query = source(tmp_path)
    record = replace(record, **change)
    result = SourceEvidenceProvider((binding,), reviews=reviews(record)).lookup(**query)
    assert result.status == SourceStatus.AVAILABLE_UNVERIFIED


def test_pin_duplicate_and_changed_source_fail_closed(tmp_path):
    binding, record, query = source(tmp_path)
    provider = reviews(record)
    provider.expected_sha256 = "wrong"
    assert (
        SourceEvidenceProvider((binding,), reviews=provider).lookup(**query).status
        == SourceStatus.AVAILABLE_UNVERIFIED
    )
    provider = reviews(record)
    provider.records = (record, record)
    provider.expected_sha256 = review_digest(provider.records)
    assert (
        SourceEvidenceProvider((binding,), reviews=provider).lookup(**query).status
        == SourceStatus.AVAILABLE_UNVERIFIED
    )
    binding.path.write_bytes(b"changed")
    assert (
        SourceEvidenceProvider((binding,), reviews=reviews(record)).lookup(**query).status
        == SourceStatus.CONFLICT
    )


def test_unconfigured_results_have_attempt_not_record_provenance():
    result = MemberAuthorityProvider().lookup(
        member_id="", payer="", service_date=None, patient_name="", dob=""
    )
    assert result.reason == "PROVIDER_NOT_CONFIGURED" and result.provenance_ids
    assert all(p.startswith("LOOKUP_ATTEMPT:") for p in result.provenance_ids)
    source_result = SourceEvidenceProvider().lookup(package_id="", page_id="", attachment_id="")
    assert source_result.provenance_ids and not source_result.release_truth
    insured = IdentityAuthorityProvider().lookup(
        member_id="", payer="", person_role="insured", name="", dob="", service_date=None
    )
    assert insured.reason == "PROVIDER_NOT_CONFIGURED"


def test_runtime_independent_failure_does_not_crash_and_timeout_is_bounded():
    async def scenario():
        entered = asyncio.Event()

        async def slow(**query):
            entered.set()
            await asyncio.sleep(100)

        async def good(**query):
            await entered.wait()
            return LookupResult(
                MatchStatus.MATCH,
                "synthetic",
                datetime.now(UTC),
                "TEST",
                provenance_ids=("synthetic:record",),
            )

        result = await independent_lookups(
            {
                "slow": (
                    BoundedAuthorityClient("slow", slow, policy=LookupPolicy(timeout_ms=20)),
                    {},
                ),
                "good": (BoundedAuthorityClient("good", good), {}),
            }
        )
        assert result["slow"].result.reason == "LOOKUP_TIMEOUT"
        assert result["good"].result.status == MatchStatus.MATCH
        assert result["slow"].elapsed_ms < 1000

    asyncio.run(scenario())


def test_cache_scope_ttl_rate_and_budget_are_enforced():
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

        client = BoundedAuthorityClient(
            "test",
            transport,
            policy=LookupPolicy(
                ttl_seconds=0.01,
                max_requests_per_minute=2,
                cost_usd_per_lookup=Decimal(".01"),
                budget_usd=Decimal(".02"),
            ),
        )
        first = await client.lookup(payer="a")
        cached = await client.lookup(payer="a")
        assert not first.cache_hit and cached.cache_hit and cached.configured_cost_usd == 0
        assert not (await client.lookup(payer="b")).cache_hit
        await asyncio.sleep(0.02)
        assert (await client.lookup(payer="a")).result.reason == "RATE_LIMITED"
        assert len(calls) == 2
        unknown = BoundedAuthorityClient(
            "test", transport, policy=LookupPolicy(budget_usd=Decimal(1))
        )
        assert (await unknown.lookup()).result.reason == "PRICING_NOT_CONFIGURED"
        budget = BoundedAuthorityClient(
            "test",
            transport,
            policy=LookupPolicy(cost_usd_per_lookup=Decimal(".01"), budget_usd=Decimal(0)),
        )
        assert (await budget.lookup()).result.reason == "LOOKUP_BUDGET_EXCEEDED"

    asyncio.run(scenario())


def test_exceptions_and_invalid_context_are_sanitized():
    async def scenario():
        async def broken(**query):
            raise RuntimeError("sensitive exception must not be logged")

        client = BoundedAuthorityClient("test", broken)
        result = await client.lookup()
        assert result.result.reason == "LOOKUP_FAILED"
        assert (await client.lookup(value=object())).result.reason == "INVALID_REQUEST_CONTEXT"
        assert (
            await BoundedAuthorityClient("absent").lookup()
        ).result.reason == "PROVIDER_NOT_CONFIGURED"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "policy", [{"timeout_ms": 0}, {"ttl_seconds": float("inf")}, {"budget_usd": Decimal("NaN")}]
)
def test_invalid_runtime_policy_rejected(policy):
    with pytest.raises(ValueError):
        LookupPolicy(**policy)


def test_attempt_provenance_cannot_establish_match_or_enter_cache():
    async def scenario():
        async def transport(**query):
            return LookupResult(MatchStatus.MATCH, "synthetic", datetime.now(UTC), "TEST")

        client = BoundedAuthorityClient("test", transport, policy=LookupPolicy(ttl_seconds=60))
        result = await client.lookup()
        assert result.result.status == MatchStatus.NOT_AVAILABLE
        assert result.result.reason == "INVALID_PROVIDER_RESULT"
        assert not result.cache_hit

    asyncio.run(scenario())


def test_cache_context_types_cannot_collide():
    from datetime import date

    async def scenario():
        async def transport(**query):
            return LookupResult(
                MatchStatus.MATCH,
                "synthetic",
                datetime.now(UTC),
                "TEST",
                provenance_ids=("synthetic:record",),
            )

        client = BoundedAuthorityClient("test", transport, policy=LookupPolicy(ttl_seconds=60))
        assert not (await client.lookup(on=date(2020, 1, 1))).cache_hit
        assert not (await client.lookup(on={"__service_date__": "2020-01-01"})).cache_hit
        assert (await client.lookup(on=date(2020, 1, 1))).cache_hit
        assert (await client.lookup(on=float("nan"))).result.reason == "INVALID_REQUEST_CONTEXT"

    asyncio.run(scenario())


def test_selective_source_review_path_uses_actual_combinations():
    from evaluation.production_evidence_readiness import selective_review_path
    from packages.claim_intelligence.enablement import ClaimRequirements

    claims = (
        ClaimRequirements("a", 0, frozenset({"MEMBER_AUTHORITY"})),
        ClaimRequirements("b", 0, frozenset({"MEMBER_AUTHORITY", "SOURCE_REVIEW"})),
        ClaimRequirements("c", 1, frozenset({"MEMBER_AUTHORITY", "SOURCE_REVIEW"})),
        ClaimRequirements("d", 0, frozenset({"MEMBER_AUTHORITY", "REAL_CONFLICT"})),
    )
    core = frozenset({"MEMBER_AUTHORITY"})
    result = selective_review_path(claims, core, 0.5)
    assert result["additional_review_claims_required"] == 1
    assert result["potential_stp"] == 0.5
    assert not selective_review_path(claims, core, 0.8)["target_reachable"]
    assert result["achieved_production_stp"] is None


def test_identity_projection_rejects_attempt_only_match():
    from packages.claim_intelligence.enablement import identity_review_state
    from packages.claim_intelligence.models import AuthorityState, FieldNode

    node = FieldNode("member_id")
    result = LookupResult(MatchStatus.MATCH, "synthetic", datetime.now(UTC), "TEST")
    report = identity_review_state(node, result, authority_required=True)
    assert report["authority_state"] == "AUTHORITATIVE_NOT_AVAILABLE"
    assert report["production_decision"] == "REVIEW_REQUIRED"
    node.authority_state = AuthorityState.AUTHORITATIVE_CONFLICT
    result = replace(result, provenance_ids=("synthetic:record",))
    assert (
        identity_review_state(node, result, authority_required=True)["authority_state"]
        == "AUTHORITATIVE_CONFLICT"
    )


def test_review_values_do_not_appear_in_default_repr(tmp_path):
    _, record, _ = source(tmp_path)
    assert "synthetic" not in repr(record)


def test_failed_attempts_consume_configured_budget_without_exposing_exception():
    async def scenario():
        async def broken(**query):
            raise RuntimeError("synthetic sensitive detail")

        client = BoundedAuthorityClient(
            "test",
            broken,
            policy=LookupPolicy(cost_usd_per_lookup=Decimal(".01"), budget_usd=Decimal(".01")),
        )
        first = await client.lookup()
        assert first.configured_cost_usd == Decimal(".01")
        assert first.result.reason == "LOOKUP_FAILED"
        assert (await client.lookup()).result.reason == "LOOKUP_BUDGET_EXCEEDED"

    asyncio.run(scenario())


def test_nested_request_context_is_snapshotted_before_transport_await():
    async def scenario():
        entered, resume = asyncio.Event(), asyncio.Event()
        observed = []

        async def transport(**query):
            entered.set()
            await resume.wait()
            observed.append(query["context"]["scope"])
            return LookupResult(
                MatchStatus.MATCH,
                "synthetic",
                datetime.now(UTC),
                "TEST",
                provenance_ids=("synthetic:record",),
            )

        client = BoundedAuthorityClient("test", transport, policy=LookupPolicy(ttl_seconds=60))
        context = {"scope": "first"}
        pending = asyncio.create_task(client.lookup(context=context))
        await entered.wait()
        context["scope"] = "second"
        resume.set()
        await pending
        assert observed == ["first"]
        assert (await client.lookup(context={"scope": "first"})).cache_hit

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "provenance", [(" LOOKUP_ATTEMPT:x",), ("SOURCE_REVIEW_ATTEMPT:x",), ("",), "not-a-tuple"]
)
def test_attempt_namespaces_and_malformed_provenance_are_not_records(provenance):
    result = LookupResult(
        MatchStatus.MATCH, "synthetic", datetime.now(UTC), "TEST", provenance_ids=provenance
    )
    assert not result.has_record_provenance


@pytest.mark.parametrize(
    "settings",
    [
        {"timeout_ms": 1.5},
        {"max_requests_per_minute": True},
        {"max_cache_entries": float("nan")},
        {"cost_usd_per_lookup": 0.01},
    ],
)
def test_runtime_limits_require_integer_bounds_and_decimal_cost(settings):
    with pytest.raises(ValueError):
        LookupPolicy(**settings)
