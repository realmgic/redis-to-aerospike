# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This repository is a **reference example**; version bumps track **revision history**
for installs and issue reports, not a formal product release cadence.

## [Unreleased]

### Changed

- **Breaking:** PyPI distribution renamed from `redis-to-aerospike` to `redis2aerospike`; the installed CLI is now `redis2aerospike` (replacing `redis-to-aerospike`).

## [0.1.0] - 2026-06-18

### Added

- CLI tool `redis-to-aerospike` to migrate Redis (or Valkey / wire-compatible) data into Aerospike using native Aerospike types.
- Pluggable converters for Redis strings, hashes, lists, sets, and sorted sets, with TTL handling and unsupported-type skips.
- Multi-threaded producer/consumer pipeline (`SCAN` → bounded queue → workers).
- YAML, CLI, and environment-variable configuration; set routes for per-pattern Aerospike sets and key shaping.
- Redis standalone and Cluster, TLS/mTLS, ACL auth, URLs; Aerospike multi-host, Enterprise auth, TLS/mTLS, timeouts.
- Rate limits, batch writes, record-exists policies, hash strategies, TTL overflow policies, dry-run preview, and migration summary with exit codes.
