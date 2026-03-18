# Hermes Stream: Claude E2E and Ops Consulting Notes

## 1. System Concept

Hermes is aiming at a non-developer-first data pipeline platform:

- users register source parameters and collection settings through the web UI
- the system materializes those settings into versioned recipes and pipeline instances
- the engine collects, processes, exports, and tracks each work item end-to-end
- operators must be able to preview, validate, activate, monitor, and reprocess without code

The strongest product value in this repo is:

- web-based parameter registration
- per-item provenance
- recipe versioning and reprocessing
- lightweight alternative to NiFi/Airbyte-style operations

## 2. What Matters Most for E2E

The highest-value tests are not isolated unit tests. They are operator-flow tests:

1. create a definition
2. configure an instance in the UI
3. validate connection and preview data
4. activate a pipeline
5. ingest real or mocked source data
6. verify process/export/provenance
7. simulate failure
8. recover or reprocess

If these pass, the product concept is credible.

## 3. High-Priority E2E Scenario Matrix

### P0: Core operator flows

1. `FTP/SFTP -> Process -> DB Writer`
   - create pipeline from UI/API
   - test connection succeeds
   - preview shows remote files
   - activation starts monitoring
   - new file creates work item
   - processor runs with saved recipe snapshot
   - DB writer persists result
   - provenance shows collect/process/export stages

2. `REST API -> Process -> Webhook`
   - auth header, query params, pagination
   - preview sample response
   - export retries on 5xx

3. `File Watcher -> Process -> S3 Upload`
   - completion check prevents partial-file pickup
   - export metadata includes original source and checksum

4. `Kafka -> Process -> DB/S3 dual export`
   - at-least-once semantics
   - idempotent export behavior
   - duplicate message handling

5. `Reprocess from failed stage`
   - collect succeeds
   - process fails
   - operator changes recipe
   - reprocess starts from process stage
   - new execution snapshot is stored

### P1: configuration and governance flows

6. `Recipe version publish / compare / rollback`
7. `Activate / deactivate / activate again`
8. `Secret-bound parameters` such as passwords and keys
9. `Pipeline clone` across environments with different secrets
10. `Definition update` without breaking existing instances

### P1: cluster and reliability flows

11. coordinator failover during active polling
12. worker crash during export
13. retry exhaustion -> DLQ
14. backpressure pause/resume
15. network partition between API and engine

## 4. Edge Cases Claude Should Cover

### FTP/SFTP collection

1. wrong host, wrong port, wrong credentials
2. FTPS TLS handshake failure
3. SFTP host key mismatch
4. SFTP key-based auth with passphrase
5. passive mode blocked by firewall
6. active/passive fallback behavior
7. huge directory listing: 10k+ files
8. recursive folders with date hierarchy
9. zero-byte file
10. file renamed between list and download
11. file grows during download
12. file deleted after discovery
13. marker-file completion check missing
14. size-stable check false positive
15. unicode filenames and non-UTF8 names
16. clock skew affecting `latest` selection
17. restart after partial download
18. duplicate detection after restart

### API / DB / Kafka collection

1. pagination token expires
2. API 429 with retry-after
3. schema drift in payload
4. DB query timeout or long transaction
5. incremental cursor reset
6. Kafka rebalance during processing
7. poison message loops

### Process and export

1. plugin timeout
2. plugin crash with partial output
3. invalid recipe schema vs runtime config mismatch
4. export succeeds after process retry
5. export partially succeeds to multiple sinks
6. exactly-once is impossible; verify idempotent design instead

### UI / operator behavior

1. invalid parameter combinations blocked before activation
2. preview result differs from actual runtime schema
3. hidden advanced options retain stale values
4. form reset loses secrets or draft state
5. concurrent edits cause stale recipe publish

## 5. Operational Risks Seen in Current Repo

### 5.1 Python reference layer is still richer than the .NET target layer

Observed pattern:

- Python test corpus is large
- `.NET` is supposed to be the production engine
- some resilience features exist in Python plugin examples and tests, but not yet clearly in native `.NET` execution paths

Risk:

- the UI and tests may imply capabilities that the actual engine does not yet enforce

### 5.2 `EngineClient` stub mode can hide missing integration

`backend/vessel/engine_client.py` falls back to stub mode when gRPC or generated stubs are missing.

Risk:

- UI/API happy-path demos may pass while the real engine is disconnected
- operators may think activation/reprocess worked when it only returned a stub response

Recommended test:

- fail startup or mark health `degraded` when production mode still uses stub transport

### 5.3 Native `.NET` FTP/SFTP monitor is operationally thinner than the design

Current `engine/src/Hermes.Engine/Services/Monitors/FtpSftpMonitor.cs` shows:

- in-memory `_seenFiles`
- simple regex and age filtering
- no persisted cursor/state
- no explicit retry or circuit breaker
- no completion check
- no checksum verification
- no post-collection move/delete/rename
- no visible host-key verification for SFTP
- no key-based auth flow
- no explicit FTPS TLS configuration path

Risk:

- restart duplicates
- cluster duplicates across workers
- incomplete file pickup
- weaker security posture than the UI/design suggests

### 5.4 Dedupe appears process-local

`_seenFiles` is memory-local to one monitor instance.

Risk:

- process restart re-collects files
- active/standby failover re-collects files
- multi-node cluster can double-collect without a shared checkpoint or idempotency key

Recommended fix direction:

- persist discovery checkpoints in DB
- use per-source dedup keys based on path + size + mtime + checksum where appropriate

### 5.5 Definition/UI promises may outrun runtime support

The docs and UI describe:

- marker-file completion
- size-stable checks
- advanced post-collection actions
- FTPS/SFTP variants
- cluster-safe monitoring

Risk:

- operator-configurable options exist before native engine behavior is complete
- this is worse than missing features because it creates false confidence

## 6. Recommended Test Additions

### Add real-service integration tests

Use docker-compose or TestContainers for:

1. real FTP server
2. real SFTP server
3. PostgreSQL
4. Kafka
5. optional MinIO for S3 export

Mock-heavy tests are useful, but they do not expose:

- TLS issues
- auth negotiation issues
- path encoding issues
- server-specific directory listing quirks
- connection reuse and timeout behavior

### Add a plugin acceptance harness

Every collector/exporter plugin should pass:

1. `spec/config schema`
2. `test connection`
3. `preview/discover`
4. `collect/read`
5. `failure reporting`
6. `idempotent retry behavior`

### Add long-running soak tests

12-24 hour scenarios for:

1. repeated polling with no leaks
2. reconnect after transient outages
3. circuit breaker open/half-open/close
4. backlog growth and recovery

### Add cluster fault-injection tests

1. coordinator dies during activation
2. worker dies after collect, before export
3. duplicate assignment after lease timeout
4. DB connection drop during checkpoint save
5. network partition and rejoin

## 7. Suggested Files Claude Can Add Next

1. `backend/tests/e2e/test_operator_pipeline_flow.py`
2. `backend/tests/e2e/test_reprocess_from_failed_stage.py`
3. `backend/tests/e2e/test_activation_failover.py`
4. `backend/tests/e2e/test_stub_mode_rejected_in_production.py`
5. `engine/tests/Hermes.Engine.Tests/Monitors/FtpSftpMonitorStateTests.cs`
6. `engine/tests/Hermes.Engine.Tests/Monitors/FtpSftpMonitorSecurityTests.cs`
7. `engine/tests/Hermes.Engine.Tests/Cluster/CheckpointFailoverTests.cs`
8. `deploy/docker-compose.e2e.yml`

## 8. Immediate Priority for Claude

1. make runtime capability match the UI for FTP/SFTP safety features
2. persist monitor checkpoint/dedup state outside process memory
3. block or loudly expose `stub mode` in non-dev environments
4. add real-service E2E tests before expanding more UI options
5. validate failover and reprocess semantics before cluster claims are expanded
