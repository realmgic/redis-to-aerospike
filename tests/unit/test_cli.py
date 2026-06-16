"""Smoke tests for the CLI wiring and exit codes."""

import pytest

import redis_to_aerospike.cli as cli
from redis_to_aerospike.aerospike_sink import AerospikeServerInfo
from redis_to_aerospike.config import MigrationConfig
from redis_to_aerospike.stats import MigrationStats


def test_parse_args_defaults():
    # Config flags use argparse.SUPPRESS, so an empty CLI yields an empty
    # namespace and the defaults come from the dataclasses via build_config().
    config = cli.build_config(cli.parse_args([]))
    assert config.redis.host == "localhost"
    assert config.aerospike.hosts == [("localhost", 3000)]
    assert config.workers == 8
    assert config.hash_strategy.value == "map_bin"
    assert config.ttl_overflow_policy.value == "reject"


def test_build_config_maps_ttl_overflow_flags():
    args = cli.parse_args(["--max-ttl", "1000", "--ttl-overflow-policy", "clamp"])
    config = cli.build_config(args)
    assert config.aerospike.max_ttl == 1000
    assert config.ttl_overflow_policy.value == "clamp"


def test_build_config_maps_args():
    args = cli.parse_args(
        [
            "--workers", "3",
            "--scan-batch", "50",
            "--hash-strategy", "field_bins",
            "--aerospike-namespace", "ns",
            "--value-bin", "v",
            "--redis-port", "6380",
        ]
    )
    config = cli.build_config(args)
    assert config.workers == 3
    assert config.scan_batch == 50
    assert config.hash_strategy.value == "field_bins"
    assert config.aerospike.namespace == "ns"
    assert config.aerospike.value_bin == "v"
    assert config.redis.port == 6380


def test_build_config_maps_rate_limit_flags():
    args = cli.parse_args(["--scan-rate-limit", "1000", "--write-rate-limit", "250.5"])
    config = cli.build_config(args)
    assert config.scan_rate_limit == 1000
    assert config.write_rate_limit == 250.5


def test_render_preview_shows_rate_limits():
    config = cli.build_config(cli.parse_args(["--write-rate-limit", "500"]))
    preview = cli.render_preview(config, {"keys": 1}, None)
    assert "scan rate   : unlimited" in preview
    assert "write rate  : 500/s" in preview


def test_build_config_maps_write_batch_size_flag():
    config = cli.build_config(cli.parse_args(["--write-batch-size", "250"]))
    assert config.write_batch_size == 250


def test_render_preview_shows_write_batch():
    single = cli.render_preview(cli.build_config(cli.parse_args([])), {"keys": 1}, None)
    assert "write batch : single" in single
    batched = cli.render_preview(
        cli.build_config(cli.parse_args(["--write-batch-size", "100"])), {"keys": 1}, None
    )
    assert "write batch : 100 records" in batched


def test_parse_args_progress_and_dry_run_defaults():
    args = cli.parse_args([])
    assert args.dry_run is False
    assert cli.build_config(args).progress_interval == MigrationConfig.progress_interval


def _write_yaml(tmp_path, data):
    yaml = pytest.importorskip("yaml")
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return str(path)


def test_build_config_loads_yaml_file(tmp_path):
    path = _write_yaml(
        tmp_path,
        {
            "aerospike": {"namespace": "from_yaml", "username": "admin", "tls_enable": True},
            "workers": 3,
        },
    )
    config = cli.build_config(cli.parse_args(["--config", path]))
    assert config.aerospike.namespace == "from_yaml"
    assert config.aerospike.username == "admin"
    assert config.aerospike.tls_enable is True
    assert config.workers == 3


def test_explicit_cli_flag_overrides_yaml(tmp_path):
    path = _write_yaml(tmp_path, {"aerospike": {"namespace": "from_yaml"}, "workers": 3})
    config = cli.build_config(
        cli.parse_args(["--config", path, "--aerospike-namespace", "from_cli", "--workers", "9"])
    )
    # Explicit flags win; untouched YAML values are kept.
    assert config.aerospike.namespace == "from_cli"
    assert config.workers == 9


def test_yaml_value_kept_when_no_cli_override(tmp_path):
    path = _write_yaml(tmp_path, {"redis": {"host": "yamlhost", "port": 6390}})
    config = cli.build_config(cli.parse_args(["--config", path]))
    assert config.redis.host == "yamlhost"
    assert config.redis.port == 6390


def test_redis_flags_map_and_override_yaml(tmp_path):
    path = _write_yaml(tmp_path, {"redis": {"username": "from_yaml", "cluster": False}})
    config = cli.build_config(
        cli.parse_args(
            [
                "--config", path,
                "--redis-username", "from_cli",
                "--redis-cluster",
                "--redis-ssl",
                "--redis-socket-timeout", "2.5",
            ]
        )
    )
    assert config.redis.username == "from_cli"
    assert config.redis.cluster is True
    assert config.redis.ssl is True
    assert config.redis.socket_timeout == 2.5


class _FakeSource:
    def __init__(self, *args, **kwargs):
        pass

    def ping(self):
        return True

    def server_info(self):
        return {"keys": 3, "expires": 1, "used_memory_human": "1M", "redis_version": "7.2"}

    def close(self):
        pass


class _FailPingSource(_FakeSource):
    def ping(self):
        raise ConnectionError("no redis")


class _FakeSink:
    def __init__(self, *args, **kwargs):
        pass

    def connect(self):
        return self

    def server_info(self):
        return None

    def close(self):
        pass


def _fake_migrator(stats):
    class _FakeMigrator:
        ran = False

        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            type(self).ran = True
            return stats

    return _FakeMigrator


def test_main_returns_2_when_redis_unreachable(monkeypatch):
    monkeypatch.setattr(cli, "RedisSource", _FailPingSource)
    monkeypatch.setattr(cli, "AerospikeSink", _FakeSink)
    assert cli.main([]) == 2


def test_main_returns_1_when_errors(monkeypatch):
    stats = MigrationStats()
    stats.record_error("write:Boom")
    monkeypatch.setattr(cli, "RedisSource", _FakeSource)
    monkeypatch.setattr(cli, "AerospikeSink", _FakeSink)
    monkeypatch.setattr(cli, "Migrator", _fake_migrator(stats))
    assert cli.main([]) == 1


def test_main_returns_0_on_success(monkeypatch):
    stats = MigrationStats()
    stats.record_migrated()
    monkeypatch.setattr(cli, "RedisSource", _FakeSource)
    monkeypatch.setattr(cli, "AerospikeSink", _FakeSink)
    monkeypatch.setattr(cli, "Migrator", _fake_migrator(stats))
    assert cli.main([]) == 0


def test_dry_run_skips_migration(monkeypatch):
    migrator = _fake_migrator(MigrationStats())
    monkeypatch.setattr(cli, "RedisSource", _FakeSource)
    monkeypatch.setattr(cli, "AerospikeSink", _FakeSink)
    monkeypatch.setattr(cli, "Migrator", migrator)

    assert cli.main(["--dry-run"]) == 0
    assert migrator.ran is False


def test_render_preview_includes_source_target_and_estimate():
    config = cli.build_config(cli.parse_args(["--redis-match", "user:*"]))
    redis_info = {"keys": 100, "expires": 5, "used_memory_human": "2M", "redis_version": "7.2"}
    aero_info = AerospikeServerInfo(
        namespace="test", nsup_period=120, max_record_size=1048576, stop_writes_pct=90
    )

    preview = cli.render_preview(config, redis_info, aero_info)

    assert "migration preview" in preview
    assert "localhost:6379" in preview
    assert "namespace   : test" in preview
    assert "SCAN filter" in preview
    assert "nsup-period : 120" in preview
    assert "max-record-size : 1048576" in preview
    # Non-"*" match makes the estimate an upper bound.
    assert "<= 100" in preview and "user:*" in preview


def test_render_preview_exact_estimate_for_match_all():
    config = cli.build_config(cli.parse_args([]))
    preview = cli.render_preview(config, {"keys": 42}, None)
    assert "estimated keys : 42" in preview


def test_redis_key_pattern_alias_without_redis_match():
    config = cli.build_config(cli.parse_args(["--redis-key-pattern", "x:*"]))
    assert config.redis.scan_match == "x:*"


def test_redis_match_overrides_redis_key_pattern():
    config = cli.build_config(
        cli.parse_args(["--redis-key-pattern", "a:*", "--redis-match", "b:*"])
    )
    assert config.redis.scan_match == "b:*"


def test_set_route_flags_append_to_config():
    config = cli.build_config(
        cli.parse_args(
            [
                "--set-route",
                "user:*=users",
                "--set-route",
                "cache:*=caches",
            ]
        )
    )
    assert len(config.aerospike.set_routes) == 2
    assert config.aerospike.set_routes[0].pattern == "user:*"
    assert config.aerospike.set_routes[0].destination == "users"
    assert config.aerospike.set_routes[1].destination == "caches"


def test_render_preview_lists_set_routes():
    config = cli.build_config(cli.parse_args(["--set-route", "a:*=A"]))
    preview = cli.render_preview(config, {"keys": 1}, None)
    assert "set (default)" in preview
    assert "set route 1" in preview
    assert "a:* -> A" in preview


def test_apply_server_info_warns_when_nsup_disabled(caplog):
    config = cli.build_config(cli.parse_args([]))
    info = AerospikeServerInfo(namespace="test", nsup_period=0)

    with caplog.at_level("WARNING", logger="redis_to_aerospike.cli"):
        cli.apply_server_info(config, info)

    assert any("nsup-period=0" in r.message for r in caplog.records)


def test_apply_server_info_aligns_max_record_size():
    config = cli.build_config(cli.parse_args([]))
    config.aerospike.max_record_size = 8 * 1024 * 1024
    info = AerospikeServerInfo(namespace="test", nsup_period=120, max_record_size=1024)

    cli.apply_server_info(config, info)

    assert config.aerospike.max_record_size == 1024


def test_apply_server_info_keeps_default_when_server_unknown():
    config = cli.build_config(cli.parse_args([]))
    original = config.aerospike.max_record_size
    cli.apply_server_info(config, AerospikeServerInfo(namespace="test", max_record_size=0))
    assert config.aerospike.max_record_size == original
