"""Adversarial and property-based tests for scalar coercion."""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from redis_to_aerospike.converters import coerce_scalar

INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1


# --- integer range ---------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        (str(INT64_MAX).encode(), INT64_MAX),
        (str(INT64_MIN).encode(), INT64_MIN),
        (str(INT64_MAX + 1).encode(), str(INT64_MAX + 1)),   # overflow -> string
        (str(INT64_MIN - 1).encode(), str(INT64_MIN - 1)),   # underflow -> string
        (b"99999999999999999999999999", "99999999999999999999999999"),
    ],
)
def test_int64_range_guard(raw, expected):
    assert coerce_scalar(raw) == expected


# --- non-finite floats -----------------------------------------------------

@pytest.mark.parametrize("raw", [b"1e400", b"-1e400"])
def test_overflowing_float_stays_string(raw):
    result = coerce_scalar(raw)
    assert isinstance(result, str)
    assert result == raw.decode()


@pytest.mark.parametrize("raw", [b"inf", b"-inf", b"nan", b"Infinity", b"NaN"])
def test_inf_nan_words_stay_string(raw):
    # These never match the numeric pattern, so they remain strings.
    result = coerce_scalar(raw)
    assert isinstance(result, str)


# --- ambiguous numeric-looking strings stay strings ------------------------

@pytest.mark.parametrize(
    "raw",
    [b"+5", b" 5", b"5 ", b"0x10", b"1_000", b"1,000", b"007", b"."],
)
def test_ambiguous_numeric_strings_kept(raw):
    result = coerce_scalar(raw)
    assert result == raw.decode()
    assert isinstance(result, str)


def test_empty_bytes_become_empty_string():
    assert coerce_scalar(b"") == ""


# --- property-based --------------------------------------------------------

@given(st.integers())
def test_integers_within_int64_roundtrip(n):
    result = coerce_scalar(str(n).encode())
    if INT64_MIN <= n <= INT64_MAX:
        assert result == n and isinstance(result, int)
    else:
        assert result == str(n) and isinstance(result, str)


@given(st.text())
def test_coercion_is_idempotent_on_text(text):
    once = coerce_scalar(text)
    twice = coerce_scalar(once)
    assert once == twice
    assert type(once) is type(twice)


@given(st.floats(allow_nan=False, allow_infinity=False, width=32))
def test_finite_floats_roundtrip(f):
    # Use the canonical repr so the parsed value matches exactly.
    result = coerce_scalar(repr(f).encode())
    assert isinstance(result, (int, float))
    assert math.isclose(float(result), f, rel_tol=1e-9, abs_tol=0.0) or result == f
