# Test Integrity Gap Report

Updated: 2026-03-19

## 1. Migration Safety

### ORM-Level Tests (test_stage_runtime_states_migration.py)

| Test | Level | Status |
|---|---|---|
| table_exists_in_schema | ORM create_all | PASS |
| unique_constraint_idempotent | Service-level | PASS |
| fk_cascade_on_activation_delete | ORM cascade | PASS |
| activate_pipeline_creates_runtime_states | Service-level | PASS |
| coexistence_with_work_items | Integration | PASS |

### SQL-Level Tests (test_stage_runtime_states_migration_sql.py)

| Test | Level | Status |
|---|---|---|
| migration_sql_creates_table | Raw SQL DDL application | PASS |
| unique_constraint_rejects_duplicate_at_db_level | Raw SQL INSERT + IntegrityError | PASS |
| fk_rejects_orphan_state | Raw SQL FK enforcement | PASS |

**How it works**: Pre-migration schema (tables without stage_runtime_states) → apply migration SQL → verify constraints at DB level using raw INSERT statements.

**Remaining gap**: No Alembic runner. Migration SQL tested as raw DDL, not through a migration framework.

## 2. Runtime Parity

### Shared Corpus

`ftp_parity_corpus.json` contains 5 fixtures with 18 total path assertions:
- flat_csv_pickup (4 paths)
- recursive_equipment_tree (4 paths)
- depth_limited (3 paths, .NET gap)
- exclude_patterns (4 paths, .NET gap)
- root_only_json (3 paths)

### Python Reference Parity (test_ftp_runtime_parity.py)

| Fixture | Paths | Status | Level |
|---|---|---|---|
| flat_csv_pickup | 4 | PASS | Actual matching logic |
| recursive_equipment_tree | 4 | PASS | Actual matching logic |
| depth_limited | 3 | PASS | Actual matching logic |
| exclude_patterns | 4 | PASS | Actual matching logic |
| root_only_json | 3 | PASS | Actual matching logic |

### .NET Actual Parity (test_ftp_runtime_parity.py + FtpParityCorpusTests.cs)

| Fixture | Python | .NET (simulated) | .NET (xUnit) | Status |
|---|---|---|---|---|
| flat_csv_pickup | PASS | PASS | PASS (4 InlineData) | Actual parity |
| recursive_equipment_tree | PASS | PASS | PASS (4 InlineData) | Actual parity |
| root_only_json | PASS | PASS | PASS (3 InlineData) | Actual parity |
| depth_limited | PASS | N/A | Skip | .NET gap: no max_depth |
| exclude_patterns | PASS | N/A | Skip | .NET gap: no exclude_patterns |

### .NET Feature Gaps (xfail)

| Feature | Python | .NET | xfail test |
|---|---|---|---|
| max_depth | Supported | Not implemented | test_dotnet_gap_fixture[depth_limited] |
| exclude_patterns | Supported | Not implemented | test_dotnet_gap_fixture[exclude_patterns] |
| Persisted checkpoint | In-memory | In-memory | test_dotnet_persisted_checkpoint_parity |
| completion_check | Supported | Not implemented | test_dotnet_completion_check_parity |
| post_action | Supported | Not implemented | test_dotnet_post_action_parity |

## 3. Kafka Integrity Contracts (test_kafka_integrity_contracts.py)

| Contract | Status | Risk Level |
|---|---|---|
| Duplicate delivery handling | xfail | High — restart can re-deliver |
| Commit timing (after processing) | xfail | High — message loss risk |
| Poison message handling | xfail | Medium — consumer can loop |
| Producer delivery guarantee | xfail | Medium — silent loss possible |
| Rebalance handling | xfail | Medium — in-flight work risk |

All 5 contracts are xfail with explicit expected semantics documented.

## 4. DB Writer Integrity Contracts (test_db_writer_integrity_contracts.py)

| Contract | Status | Risk Level |
|---|---|---|
| UPSERT idempotency on conflict_key | xfail | High — retry double-insert |
| Retry after partial failure | xfail | High — partial batch risk |
| Write mode semantics (INSERT/UPSERT/MERGE) | xfail | Medium — undefined behavior |
| Failure observability and replayability | xfail | Medium — silent failures |
| Schema mismatch handling | xfail | Low — type coercion risk |

All 5 contracts are xfail with explicit expected semantics documented.

## 5. Restart / Chaos (test_stage_restart_semantics.py)

| Test | Status | Description |
|---|---|---|
| stage_stop_state_lost_on_new_activation | PASS | Fresh activation = fresh states |
| backlog_from_old_activation_not_visible | PASS | New activation = zero queues |
| backlog_survives_within_same_activation | PASS | Stop/resume preserves backlog |
| double_stop_is_idempotent | PASS | No error on repeated stop |
| double_resume_is_idempotent | PASS | No error on repeated resume |
| cluster_failover_preserves_stage_stop | xfail | Requires .NET engine |
| reprocess_interrupted_mid_execution | xfail | Requires crash recovery |

## 6. Summary

| Category | File | Pass | xfail | Total |
|---|---|---|---|---|
| Migration (ORM) | test_stage_runtime_states_migration.py | 5 | 0 | 5 |
| Migration (SQL) | test_stage_runtime_states_migration_sql.py | 3 | 0 | 3 |
| FTP Parity (Python) | test_ftp_runtime_parity.py | 8 | 5 | 13 |
| FTP Parity (.NET xUnit) | FtpParityCorpusTests.cs | 11 | 2 skip | 13 |
| Kafka Integrity | test_kafka_integrity_contracts.py | 0 | 5 | 5 |
| DB Writer Integrity | test_db_writer_integrity_contracts.py | 0 | 5 | 5 |
| Restart/Chaos | test_stage_restart_semantics.py | 5 | 2 | 7 |
| **Python Total** | | **21** | **17** | **38** |

## 7. Operator Risks

1. **Restart resets stage stop** — documented, tested, by design
2. **ALL_NEW depends on process memory** — both Python and .NET, no persistent dedup
3. **.NET runtime thinner than Python reference** — 5 documented feature gaps
4. **Kafka dedup/commit not guaranteed** — 5 unimplemented contracts
5. **DB writer retry safety unproven** — 5 unimplemented contracts
6. **Migration must be applied manually** — SQL verified but no Alembic
