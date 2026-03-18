# Hermes FTP/SFTP Collector Config Spec

## 1. Purpose

This document defines the configuration contract for the Hermes FTP/SFTP collector.

The main rule is:

- `settings` = how Hermes connects to the remote system
- `recipe` = what Hermes collects and how it selects files
- `runtime_policy` = how Hermes retries, limits, and recovers during execution

These three layers must not be collapsed into one flat config.

## 2. Why This Separation Matters

FTP/SFTP collection has two very different concerns:

1. Connection and transport concerns
   - host
   - port
   - auth
   - TLS / SSH
   - passive mode

2. Collection logic concerns
   - which folders to traverse
   - whether traversal is recursive
   - which files match
   - how to exclude partial files
   - what to do after collection

Operators change collection logic frequently. Connection details change less often.

Therefore:

- connection belongs to `settings`
- collection logic belongs to `recipe`
- retry / backoff / concurrency belongs to `runtime_policy`

## 3. Config Layers

### 3.1 Settings

Settings are instance-level and usually reusable across multiple recipes.

Typical fields:

- `protocol`
- `host`
- `port`
- `username`
- `password`
- `private_key_path`
- `private_key_passphrase`
- `passive_mode`
- `host_key_checking`

These fields describe where and how to connect.

### 3.2 Recipe

Recipe is versioned business configuration.

Typical fields:

- `remote_path`
- `recursive`
- `max_depth`
- `folder_pattern`
- `file_filter`
- `ordering`
- `discovery_mode`
- `batch_size`
- `completion_check`
- `post_action`
- `checksum_verification`

These fields describe what Hermes should collect.

### 3.3 Runtime Policy

Runtime policy describes execution behavior.

Typical fields:

- `poll_interval`
- `connection_timeout_seconds`
- `data_timeout_seconds`
- `max_concurrent_downloads`
- `retry_max_attempts`
- `retry_base_delay_seconds`
- `retry_max_delay_seconds`
- `circuit_breaker_threshold`
- `circuit_breaker_recovery_seconds`

These fields describe how Hermes should execute and recover.

## 4. Canonical FTP/SFTP Contract

### 4.1 Settings Schema

```json
{
  "protocol": "SFTP",
  "host": "sftp.vendor.example.com",
  "port": 22,
  "username": "collector",
  "password": "",
  "private_key_path": "/secrets/id_rsa",
  "private_key_passphrase": "",
  "passive_mode": true,
  "host_key_checking": true
}
```

Validation rules:

- `protocol` must be one of `FTP`, `FTPS`, `SFTP`
- `host` is required
- `username` is required
- `password` and `private_key_path` are mutually compatible, but `private_key_path` wins for SFTP
- `passive_mode` applies only to `FTP` / `FTPS`
- `host_key_checking` applies only to `SFTP`

### 4.2 Recipe Schema

```json
{
  "remote_path": "/data/incoming",
  "recursive": true,
  "max_depth": 3,
  "folder_pattern": {
    "enabled": true,
    "format": "yyyyMMdd",
    "lookback_days": 7,
    "timezone": "Asia/Seoul"
  },
  "file_filter": {
    "filename_regex": "sensor_.*\\.csv$",
    "path_regex": ".*/equipment_[A-Z]+/.*",
    "min_size_bytes": 100,
    "max_size_bytes": 0,
    "max_age_hours": 24,
    "exclude_patterns": [
      "\\.tmp$",
      "^\\.",
      "\\.bak$"
    ],
    "exclude_zero_byte": true
  },
  "ordering": "NEWEST_FIRST",
  "discovery_mode": "ALL_NEW",
  "batch_size": 100,
  "completion_check": {
    "strategy": "MARKER_FILE",
    "marker_suffix": ".done",
    "stable_seconds": 10
  },
  "post_action": {
    "action": "MOVE",
    "move_target": "/archive",
    "rename_suffix": ".processed",
    "conflict_resolution": "TIMESTAMP"
  },
  "checksum_verification": true
}
```

### 4.3 Runtime Policy Schema

```json
{
  "poll_interval": "5m",
  "connection_timeout_seconds": 30,
  "data_timeout_seconds": 60,
  "max_concurrent_downloads": 4,
  "retry_max_attempts": 5,
  "retry_base_delay_seconds": 2,
  "retry_max_delay_seconds": 300,
  "circuit_breaker_threshold": 5,
  "circuit_breaker_recovery_seconds": 300
}
```

## 5. Recipe Field Semantics

### 5.1 Traversal

- `remote_path`: root directory for scanning
- `recursive`: whether subdirectories are traversed
- `max_depth`:
  - `0` = root only
  - `1` = root + immediate children
  - `-1` = unlimited

### 5.2 Folder Pattern

`folder_pattern` is for date-oriented directory trees.

Supported use cases:

- `/data/20260318/`
- `/data/2026/03/18/`
- `/data/topicA/20260318/`

Recommended fields:

- `enabled`
- `format`
- `lookback_days`
- `timezone`

This is a collection rule, not a connection setting.

### 5.3 File Filter

`file_filter` determines which files are eligible.

Recommended fields:

- `filename_regex`
- `path_regex`
- `min_size_bytes`
- `max_size_bytes`
- `max_age_hours`
- `exclude_patterns`
- `exclude_zero_byte`

Rules:

- `filename_regex` applies to file name only
- `path_regex` applies to full remote path
- `exclude_patterns` are deny rules and win over positive matches
- `exclude_zero_byte` should default to `true`

### 5.4 Discovery Mode

Recommended enum:

- `ALL`
- `LATEST`
- `BATCH`
- `ALL_NEW`

Meanings:

- `ALL`: collect every matching file each poll
- `LATEST`: collect only the newest matching file
- `BATCH`: collect up to `batch_size`
- `ALL_NEW`: collect only unseen files according to persisted state

`ALL_NEW` is the default operational mode.

### 5.5 Completion Check

This prevents collecting files that are still being written.

Recommended strategies:

- `NONE`
- `MARKER_FILE`
- `SIZE_STABLE`

Notes:

- `MARKER_FILE` is best when upstream creates companion files like `.done`
- `SIZE_STABLE` is useful when marker files do not exist
- `NONE` is allowed but should be treated as lower integrity

### 5.6 Post Action

After successful collection, the collector may:

- `KEEP`
- `DELETE`
- `MOVE`
- `RENAME`

This belongs to the recipe because it is part of collection business behavior.

## 6. UI Contract

The Web UI must expose three sections for FTP/SFTP:

1. `Connection Settings`
2. `Collection Recipe`
3. `Runtime Policy`

Recommended tabs:

1. `Settings`
2. `Recipe`
3. `Advanced JSON`
4. `Preview / Test`

UI rules:

- schema-driven form should be the default
- raw JSON editor should exist for advanced users
- raw JSON and form view must edit the same underlying object
- `folder_pattern`, `file_filter`, `completion_check`, and `post_action` must be visible in the UI
- test connection must validate only `settings`
- preview must validate `settings + recipe`

## 7. Preview and Validation Requirements

The FTP/SFTP editor should support:

### 7.1 Test Connection

Checks:

- network reachability
- auth success
- TLS / SSH handshake
- host key validation
- passive mode compatibility

This uses `settings` only.

### 7.2 Preview Collection

Checks:

- path traversal
- folder pattern resolution
- regex matching
- exclusion rules
- completion check logic
- sample candidate files

This uses `settings + recipe`.

Preview output should show:

- scanned directories
- total discovered files
- matched files
- excluded files
- exclusion reason per file

## 8. Runtime Expectations

For FTP/SFTP to be operationally trustworthy, the runtime should support:

- persisted checkpointing
- dedup across restart
- retry with backoff
- completion checks
- post-action execution
- checksum verification
- secure SFTP host key validation
- FTPS TLS configuration

Current status in this repository:

- community example plugin expresses most of this contract
- test suite covers much of this contract
- current `.NET` monitor supports only a subset

## 9. Current Gap in Hermes

Current UI gap:

- the current UI mostly exposes connection-oriented fields
- recipe-level collection logic is underexposed

Current runtime gap:

- `.NET` `FtpSftpMonitor` currently handles a flatter config:
  - `base_path`
  - `recursive`
  - `path_filter_regex`
  - `file_filter_regex`
  - `sort_by`
  - `max_files_per_poll`
  - `min_age_seconds`

Missing or incomplete relative to this spec:

- `folder_pattern`
- `exclude_patterns`
- `exclude_zero_byte`
- `discovery_mode`
- `completion_check`
- `post_action`
- `checksum_verification`
- persisted dedup/checkpoint semantics

## 10. Recommended Next Work

### P0

- make Web UI render `settings_schema` and `input_schema` separately
- add raw JSON editor for recipe
- make preview return discovered vs excluded files with reasons

### P1

- extend `.NET` `FtpSftpMonitor` to support:
  - `folder_pattern`
  - `exclude_patterns`
  - `exclude_zero_byte`
  - `discovery_mode`
  - `completion_check`

### P2

- add `post_action`
- add `checksum_verification`
- add persisted checkpoint/dedup state

## 11. General Rule for Other Connectors

This split should apply beyond FTP/SFTP.

### Kafka Consumer

- `settings`: brokers, auth, security, group connectivity
- `recipe`: topics, filters, deserializer, selection rules, dedup key
- `runtime_policy`: poll interval, batch limits, retry, rebalance handling

### REST API Collector

- `settings`: base auth, common headers, network timeouts
- `recipe`: endpoint path, params/body template, pagination, records path, dedup logic
- `runtime_policy`: retry, poll cadence, concurrency

### DB Poller

- `settings`: connection string, provider, auth
- `recipe`: query/table, predicates, cursor/watermark, batch rules
- `runtime_policy`: polling cadence, retry, timeout

### Process Step

- `settings`: runtime/image/executor/resource class
- `recipe`: algorithm parameters, mapping rules, thresholds, transforms
- `runtime_policy`: timeout, retry, concurrency

### Export Step

- `settings`: destination connection/auth
- `recipe`: topic/table/path/template/mapping/write mode
- `runtime_policy`: retry, batch, idempotency

This is the standard Hermes config pattern.
