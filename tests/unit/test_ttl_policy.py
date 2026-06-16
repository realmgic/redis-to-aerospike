"""Tests for the configurable TTL max-ttl overflow policy."""

import logging

import pytest

from redis_to_aerospike.config import DEFAULT_MAX_TTL_S, TtlOverflowPolicy
from redis_to_aerospike.converters import StringConverter, TtlPolicy, TtlTooLongError
from redis_to_aerospike.models import TTL_NEVER_EXPIRE, RedisRecord

# One second past the 10-year default max-ttl, expressed in milliseconds.
OVER_LIMIT_MS = (DEFAULT_MAX_TTL_S + 1) * 1000


def rec(ttl_ms):
    return RedisRecord(key="k", type="string", value=b"v", ttl_ms=ttl_ms)


# --- TtlPolicy.to_ttl -------------------------------------------------------

def test_none_is_never_expire():
    assert TtlPolicy().to_ttl(None) == TTL_NEVER_EXPIRE


def test_under_limit_passes_through():
    assert TtlPolicy().to_ttl(5_000) == 5


def test_exactly_at_limit_is_allowed():
    assert TtlPolicy().to_ttl(DEFAULT_MAX_TTL_S * 1000) == DEFAULT_MAX_TTL_S


def test_default_policy_rejects_over_limit():
    policy = TtlPolicy()
    assert policy.mode is TtlOverflowPolicy.REJECT
    with pytest.raises(TtlTooLongError):
        policy.to_ttl(OVER_LIMIT_MS)


def test_clamp_returns_exactly_max_ttl():
    policy = TtlPolicy(mode=TtlOverflowPolicy.CLAMP)
    assert policy.to_ttl(OVER_LIMIT_MS) == DEFAULT_MAX_TTL_S


def test_never_expire_converts_overflow():
    policy = TtlPolicy(mode=TtlOverflowPolicy.NEVER_EXPIRE)
    assert policy.to_ttl(OVER_LIMIT_MS) == TTL_NEVER_EXPIRE


def test_string_mode_is_accepted():
    # CLI / env supply plain strings; the policy normalizes them.
    assert TtlPolicy(mode="clamp").mode is TtlOverflowPolicy.CLAMP


def test_zero_max_ttl_disables_the_check():
    policy = TtlPolicy(mode=TtlOverflowPolicy.REJECT, max_ttl_s=0)
    # No boundary -> the huge TTL is only clamped below the reserved sentinels.
    assert policy.to_ttl(OVER_LIMIT_MS) <= 0xFFFFFFFC


def test_custom_max_ttl_boundary():
    policy = TtlPolicy(mode=TtlOverflowPolicy.CLAMP, max_ttl_s=100)
    assert policy.to_ttl(150_000) == 100
    assert policy.to_ttl(90_000) == 90


# --- warn-once behavior -----------------------------------------------------

def test_reject_warns_once_per_run(caplog):
    policy = TtlPolicy(mode=TtlOverflowPolicy.REJECT)
    with caplog.at_level(logging.WARNING, logger="redis_to_aerospike.converters.base"):
        for _ in range(5):
            with pytest.raises(TtlTooLongError):
                policy.to_ttl(OVER_LIMIT_MS)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "reject" in warnings[0].getMessage().lower()


def test_clamp_warns_once_per_run(caplog):
    policy = TtlPolicy(mode=TtlOverflowPolicy.CLAMP)
    with caplog.at_level(logging.WARNING, logger="redis_to_aerospike.converters.base"):
        for _ in range(5):
            policy.to_ttl(OVER_LIMIT_MS)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "clamp" in warnings[0].getMessage().lower()


def test_never_expire_warns_once_per_run(caplog):
    policy = TtlPolicy(mode=TtlOverflowPolicy.NEVER_EXPIRE)
    with caplog.at_level(logging.WARNING, logger="redis_to_aerospike.converters.base"):
        for _ in range(3):
            policy.to_ttl(OVER_LIMIT_MS)
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


# --- wiring through a converter --------------------------------------------

def test_converter_rejects_overflow_by_default():
    with pytest.raises(TtlTooLongError):
        StringConverter("value").convert(rec(OVER_LIMIT_MS))


def test_converter_clamps_when_configured():
    converter = StringConverter("value", TtlPolicy(mode=TtlOverflowPolicy.CLAMP))
    out = converter.convert(rec(OVER_LIMIT_MS))
    assert out.ttl_s == DEFAULT_MAX_TTL_S
