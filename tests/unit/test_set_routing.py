from redis_to_aerospike.config import AerospikeSetRoute
from redis_to_aerospike.set_routing import SetRouter, _aerospike_key_from_route


def test_first_route_wins():
    router = SetRouter(
        [
            AerospikeSetRoute("user:*", "users"),
            AerospikeSetRoute("user:admin:*", "admins"),
        ],
        "redis",
    )
    r1 = router.resolve("user:1")
    assert r1.set_name == "users"
    assert r1.key == "1"
    r2 = router.resolve("user:admin:1")
    assert r2.set_name == "users"
    assert r2.key == "admin:1"


def test_unmatched_key_uses_default_full_key():
    router = SetRouter([AerospikeSetRoute("cache:*", "cache")], "redis")
    r = router.resolve("other")
    assert r.set_name == "redis"
    assert r.key == "other"


def test_binary_key_uses_default_no_strip():
    router = SetRouter([AerospikeSetRoute("*", "all")], "redis")
    raw = b"\xff\xfe"
    r = router.resolve(raw)
    assert r.set_name == "redis"
    assert r.key is raw


def test_empty_routes_always_default():
    router = SetRouter([], "redis")
    r = router.resolve("user:1")
    assert r.set_name == "redis"
    assert r.key == "user:1"


def test_strip_suffix_pattern():
    router = SetRouter([AerospikeSetRoute("*-v1", "v1")], "redis")
    r = router.resolve("my-resource-v1")
    assert r.set_name == "v1"
    assert r.key == "my-resource"


def test_strip_middle_segment():
    router = SetRouter([AerospikeSetRoute("app:*:item", "items")], "redis")
    r = router.resolve("app:42:item")
    assert r.set_name == "items"
    assert r.key == "42"


def test_two_stars_pattern_keeps_full_key():
    assert _aerospike_key_from_route("a:x:y:b", "a:*:*:b") == "a:x:y:b"


def test_route_with_two_stars_matches_but_keeps_full_primary_key():
    router = SetRouter([AerospikeSetRoute("a:*:*:b", "box")], "redis")
    r = router.resolve("a:x:y:b")
    assert r.set_name == "box"
    assert r.key == "a:x:y:b"


def test_question_mark_pattern_keeps_full_key():
    assert _aerospike_key_from_route("user1", "user?") == "user1"


def test_exact_prefix_only_star_yields_suffix():
    assert _aerospike_key_from_route("sample:route:user:7", "sample:route:user:*") == "7"


def test_key_equal_prefix_only_keeps_full_key():
    """Matching ``foo*`` with key ``foo`` would yield empty body; keep original."""
    assert _aerospike_key_from_route("foo", "foo*") == "foo"
