"""Health/quota tests use fake clocks and never contact providers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from shopassist.llm_gateway.config import Limits
from shopassist.llm_gateway.errors import ErrorCategory, ReasonCode
from shopassist.llm_gateway.health import ProviderHealthManager, retry_after_deadline
from shopassist.llm_gateway.quota import ProviderQuotaManager, QuotaReservation
from shopassist.llm_gateway.schemas import GatewayUsage


def health(*, cooldown=10.0):
    now = [100.0]
    manager = ProviderHealthManager(default_cooldown_s=cooldown, cooldown_cap_s=900, clock=lambda: now[0])
    return manager, now


def test_retry_after_delta_and_http_date_convert_to_monotonic_once():
    now_utc = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    assert retry_after_deadline("30", now_utc=now_utc, now_mono=100) == 130
    date = (now_utc + timedelta(seconds=45)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert retry_after_deadline(date, now_utc=now_utc, now_mono=100) == 145
    assert retry_after_deadline("9999", now_utc=now_utc, now_mono=100) == 10099
    for malformed in (None, "-1", "NaN", "nonsense", True):
        assert retry_after_deadline(malformed, now_utc=now_utc, now_mono=100) is None


def test_transient_failure_enters_cooldown_and_route_is_skipped():
    manager, now = health(cooldown=10)
    lease = manager.reserve("openrouter-profile", "route-primary", "phase12.recommendation.v1")
    assert not isinstance(lease, ReasonCode)
    manager.record_failure(lease, ErrorCategory.RATE_LIMITED, retry_after_deadline_mono=125)
    assert manager.snapshot("openrouter-profile").status == "cooldown"
    assert manager.snapshot("openrouter-profile").cooldown_remaining_s == 25
    assert manager.reserve("openrouter-profile", "route-backup", "phase12.recommendation.v1") == ReasonCode.COOLDOWN
    assert manager.reserve("groq-profile", "route-backup", "phase12.recommendation.v1") is not None
    now[0] = 125
    recovered = manager.reserve("openrouter-profile", "route-backup", "phase12.recommendation.v1")
    assert not isinstance(recovered, ReasonCode)


def test_half_open_allows_one_probe_and_release_returns_probe_slot():
    manager, now = health(cooldown=2)
    lease = manager.reserve("p", "r", "s")
    manager.record_failure(lease, ErrorCategory.NETWORK_ERROR)
    now[0] = 102
    first = manager.reserve("p", "r", "s")
    assert not isinstance(first, ReasonCode)
    assert first.profile_probe and first.route_probe
    assert manager.reserve("p", "r", "s") == ReasonCode.COOLDOWN
    manager.release(first)
    retry = manager.reserve("p", "r", "s")
    assert not isinstance(retry, ReasonCode)
    manager.record_success(retry)
    assert manager.snapshot("p").status == "active"
    assert manager.snapshot("p").consecutive_failures == 0


def test_half_open_probe_reservation_is_atomic_across_threads():
    manager, now = health(cooldown=1)
    lease = manager.reserve("p", "r", "s")
    manager.record_failure(lease, ErrorCategory.NETWORK_ERROR)
    now[0] = 101
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: manager.reserve("p", "r", "s"), range(12)))
    assert sum(not isinstance(item, ReasonCode) for item in results) == 1
    assert results.count(ReasonCode.COOLDOWN) == 11


def test_backoff_is_exponential_and_capped_and_auth_blocks_profile():
    manager, now = health(cooldown=3)
    for expected in (3, 6, 12):
        lease = manager.reserve("p", "r", "s")
        manager.record_failure(lease, ErrorCategory.PROVIDER_UNAVAILABLE)
        assert manager.snapshot("p").cooldown_remaining_s == expected
        now[0] += expected
    lease = manager.reserve("p", "r", "s")
    manager.record_failure(lease, ErrorCategory.AUTHENTICATION)
    assert manager.snapshot("p").blocked_reason == ReasonCode.AUTHENTICATION
    assert manager.reserve("p", "backup", "s") == ReasonCode.AUTHENTICATION


def test_route_schema_failure_is_scoped_to_compatibility_route():
    manager, _ = health()
    lease = manager.reserve("profile", "route-a", "schema-a")
    manager.record_failure(lease, ErrorCategory.INCOMPATIBLE_ROUTE)
    assert manager.snapshot("profile").status == "active"
    assert manager.snapshot("profile", "route-a", "schema-a").status == "blocked"
    assert manager.reserve("profile", "route-a", "schema-a") == ReasonCode.INCOMPATIBLE_ROUTE
    assert not isinstance(manager.reserve("profile", "route-a", "schema-b"), ReasonCode)


def test_invalid_output_cools_only_route_schema_and_recovers():
    manager, now = health(cooldown=4)
    lease = manager.reserve("profile", "route-a", "schema-a")
    manager.record_failure(lease, ErrorCategory.INVALID_OUTPUT)
    assert manager.snapshot("profile").status == "active"
    assert manager.snapshot("profile", "route-a", "schema-a").status == "cooldown"
    assert manager.reserve("profile", "route-a", "schema-a") == ReasonCode.COOLDOWN
    assert not isinstance(manager.reserve("profile", "route-a", "schema-b"), ReasonCode)
    now[0] += 4
    probe = manager.reserve("profile", "route-a", "schema-a")
    assert not isinstance(probe, ReasonCode)
    manager.record_success(probe)
    assert manager.snapshot("profile", "route-a", "schema-a").status == "active"


def test_stale_success_does_not_clear_newer_cooldown_generation():
    manager, _ = health()
    old = manager.reserve("p", "r", "s")
    concurrent = manager.reserve("p", "r", "s")
    manager.record_failure(concurrent, ErrorCategory.NETWORK_ERROR)
    manager.record_success(old)
    assert manager.snapshot("p").status == "cooldown"


def quota(*, seconds=0.0, day=datetime(2026, 11, 25, tzinfo=timezone.utc)):
    mono = [seconds]
    utc = [day]
    return ProviderQuotaManager(monotonic=lambda: mono[0], utc_now=lambda: utc[0]), mono, utc


def test_request_rate_rolling_window_and_pre_dispatch_release():
    manager, now, _ = quota()
    limits = Limits(requests_per_minute=1)
    reservation = manager.reserve("provider-profile", limits)
    assert isinstance(reservation, QuotaReservation)
    assert manager.reserve("provider-profile", limits) == ReasonCode.QUOTA_EXHAUSTED
    assert manager.release(reservation)
    assert isinstance(manager.reserve("provider-profile", limits), QuotaReservation)
    first = manager.reserve("other", limits)
    assert manager.mark_dispatched(first)
    assert manager.reserve("other", limits) == ReasonCode.QUOTA_EXHAUSTED
    now[0] += 60
    assert isinstance(manager.reserve("other", limits), QuotaReservation)


def test_daily_token_and_cost_caps_require_bounded_estimates_and_settle_actual():
    manager, _, _ = quota()
    limits = Limits(tokens_per_day=100, cost_per_day_usd=1.0)
    assert manager.reserve("p", limits) == ReasonCode.QUOTA_EXHAUSTED
    assert manager.reserve("p", limits, estimated_max_tokens=50) == ReasonCode.QUOTA_EXHAUSTED
    reservation = manager.reserve("p", limits, estimated_max_tokens=50,
                                  estimated_max_cost_usd=Decimal("0.50"))
    assert manager.mark_dispatched(reservation)
    assert manager.release(reservation, usage=GatewayUsage(input_tokens=40, output_tokens=30,
                                                           total_tokens=70, estimated_cost_usd=Decimal("0.7")))
    assert not manager.release(reservation)
    assert manager.snapshot("p")["tokens_used_today"] == 70
    assert manager.snapshot("p")["cost_used_today_usd"] == "0.7"
    assert manager.reserve("p", limits, estimated_max_tokens=31,
                           estimated_max_cost_usd=Decimal("0.1")) == ReasonCode.QUOTA_EXHAUSTED


def test_unknown_usage_keeps_full_reservation_until_utc_day_rollover():
    manager, _, utc = quota()
    limits = Limits(tokens_per_day=100)
    reservation = manager.reserve("p", limits, estimated_max_tokens=60)
    manager.mark_dispatched(reservation)
    manager.release(reservation, usage=GatewayUsage())
    assert manager.reserve("p", limits, estimated_max_tokens=41) == ReasonCode.QUOTA_EXHAUSTED
    utc[0] += timedelta(days=1)
    assert isinstance(manager.reserve("p", limits, estimated_max_tokens=100), QuotaReservation)


def test_rolling_request_limit_survives_utc_midnight():
    manager, mono, utc = quota(day=datetime(2026, 11, 25, 23, 59, 50, tzinfo=timezone.utc))
    limits = Limits(requests_per_minute=1)
    reservation = manager.reserve("p", limits)
    assert manager.mark_dispatched(reservation)
    manager.release(reservation)
    utc[0] += timedelta(seconds=15)
    assert manager.reserve("p", limits) == ReasonCode.QUOTA_EXHAUSTED
    mono[0] += 60
    assert isinstance(manager.reserve("p", limits), QuotaReservation)


def test_concurrency_reservation_is_atomic_across_threads():
    manager, _, _ = quota()
    limits = Limits(max_in_flight=1)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: manager.reserve("p", limits), range(12)))
    assert sum(isinstance(item, QuotaReservation) for item in results) == 1
    assert results.count(ReasonCode.CAPACITY_EXHAUSTED) == 11


def test_dispatched_reservation_counts_even_when_provider_usage_is_unknown():
    manager, _, _ = quota()
    limits = Limits(tokens_per_day=10)
    reservation = manager.reserve("p", limits, estimated_max_tokens=8)
    manager.mark_dispatched(reservation)
    manager.release(reservation, usage=None)
    assert manager.snapshot("p")["tokens_used_today"] == 8

