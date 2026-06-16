import pytest

from redis_to_aerospike.config import HashStrategy
from redis_to_aerospike.converters import (
    HashConverter,
    ListConverter,
    SetConverter,
    StringConverter,
    ZSetConverter,
    coerce_scalar,
    to_aerospike_ttl,
)
from redis_to_aerospike.models import TTL_NEVER_EXPIRE, BinWritePolicy, RedisRecord


def rec(rtype, value, ttl_ms=None, key="k"):
    return RedisRecord(key=key, type=rtype, value=value, ttl_ms=ttl_ms)


# --- coerce_scalar ---------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        (b"123", 123),
        (b"-7", -7),
        (b"0", 0),
        (b"007", "007"),          # leading zeros stay a string (no silent change)
        (b"1.5", 1.5),
        (b"-2.0e3", -2000.0),
        (b"hello", "hello"),
        (b"  12 ", "  12 "),       # whitespace -> not numeric
        ("already-str", "already-str"),
        (42, 42),
    ],
)
def test_coerce_scalar(raw, expected):
    assert coerce_scalar(raw) == expected


def test_coerce_scalar_keeps_binary_blob():
    blob = b"\xff\xfe\x00"
    assert coerce_scalar(blob) == blob


# --- ttl -------------------------------------------------------------------

def test_ttl_none_is_never_expire():
    assert to_aerospike_ttl(None) == TTL_NEVER_EXPIRE


def test_ttl_rounds_up_to_at_least_one_second():
    assert to_aerospike_ttl(1) == 1
    assert to_aerospike_ttl(1500) == 2
    assert to_aerospike_ttl(5000) == 5


def test_ttl_clamped_below_reserved_sentinels():
    # An absurdly large Redis TTL must not collide with Aerospike's reserved
    # sentinel range (0xFFFFFFFD..0xFFFFFFFF).
    huge_ms = (0xFFFFFFFF + 1000) * 1000
    result = to_aerospike_ttl(huge_ms)
    assert result <= 0xFFFFFFFC


# --- string ----------------------------------------------------------------

def test_string_converter_coerces_and_sets_ttl():
    out = StringConverter("value").convert(rec("string", b"123", ttl_ms=3000))
    assert out.bins == {"value": 123}
    assert out.ttl_s == 3
    assert out.key == "k"


# --- hash ------------------------------------------------------------------

def test_hash_map_bin_strategy():
    out = HashConverter("value", HashStrategy.MAP_BIN).convert(
        rec("hash", {b"f1": b"1", b"name": b"alice"})
    )
    assert out.bins == {"value": {"f1": 1, "name": "alice"}}


def test_hash_field_bins_strategy():
    out = HashConverter("value", HashStrategy.FIELD_BINS).convert(
        rec("hash", {b"age": b"30", b"city": b"NYC"})
    )
    assert out.bins == {"age": 30, "city": "NYC"}


def test_hash_field_bins_rejects_long_field_names():
    with pytest.raises(ValueError):
        HashConverter("value", HashStrategy.FIELD_BINS).convert(
            rec("hash", {b"this_field_name_is_way_too_long": b"1"})
        )


def test_hash_empty():
    out = HashConverter("value", HashStrategy.MAP_BIN).convert(rec("hash", {}))
    assert out.bins == {"value": {}}


# --- list ------------------------------------------------------------------

def test_list_preserves_order_and_coerces():
    out = ListConverter("value").convert(rec("list", [b"a", b"1", b"2.5"]))
    assert out.bins == {"value": ["a", 1, 2.5]}


def test_list_empty():
    assert ListConverter("value").convert(rec("list", [])).bins == {"value": []}


# --- set -------------------------------------------------------------------

def test_set_converts_to_unique_sorted_list_with_policy():
    out = SetConverter("value").convert(rec("set", {b"b", b"a", b"a", b"c"}))
    assert out.bins == {"value": ["a", "b", "c"]}
    assert out.policy_for("value") is BinWritePolicy.UNIQUE_LIST


def test_set_empty():
    out = SetConverter("value").convert(rec("set", set()))
    assert out.bins == {"value": []}
    assert out.policy_for("value") is BinWritePolicy.UNIQUE_LIST


def test_set_numeric_members_are_not_collapsed():
    # "1" and "1.0" would collide if coerced to numbers; they must stay distinct.
    out = SetConverter("value").convert(rec("set", {b"1", b"1.0"}))
    assert sorted(out.bins["value"]) == ["1", "1.0"]
    assert all(isinstance(m, str) for m in out.bins["value"])


def test_set_preserves_binary_members_as_bytes():
    blob = b"\xff\x00"
    out = SetConverter("value").convert(rec("set", {blob}))
    assert out.bins["value"] == [blob]


# --- zset ------------------------------------------------------------------

def test_zset_to_member_score_map():
    out = ZSetConverter("value").convert(
        rec("zset", [(b"alice", 1.0), (b"bob", 2.5)])
    )
    assert out.bins == {"value": {"alice": 1.0, "bob": 2.5}}


def test_zset_empty():
    assert ZSetConverter("value").convert(rec("zset", [])).bins == {"value": {}}


def test_zset_float_like_members_stay_string_keys():
    # A float member would be an illegal Aerospike map key; "1" and "1.0" must
    # also remain distinct keys rather than collapsing.
    out = ZSetConverter("value").convert(rec("zset", [(b"1", 10.0), (b"1.0", 20.0)]))
    assert out.bins["value"] == {"1": 10.0, "1.0": 20.0}
    assert all(isinstance(k, str) for k in out.bins["value"])


def test_zset_non_finite_scores_stored_as_string():
    out = ZSetConverter("value").convert(
        rec("zset", [(b"hi", float("inf")), (b"lo", float("-inf"))])
    )
    assert out.bins["value"] == {"hi": "inf", "lo": "-inf"}


def test_zset_preserves_binary_member_key():
    blob = b"\xff\x00"
    out = ZSetConverter("value").convert(rec("zset", [(blob, 1.0)]))
    assert out.bins["value"] == {blob: 1.0}
