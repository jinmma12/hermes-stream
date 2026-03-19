# Test Integrity Gap Report

Generated: 2026-03-19

## 1. Migration Safety

| Test | Status | Description |
|---|---|---|
| table_exists_in_schema | PASS | stage_runtime_states table present after create_all |
| unique_constraint_activation_step | PASS | Duplicate (activation, step) handled idempotently |
| fk_cascade_on_activation_delete | PASS | Deleting activation cascades to runtime states |
| activate_pipeline_creates_runtime_states | PASS | RUNNING states for enabled steps on activation |
| coexistence_with_work_items | PASS | Runtime states coexist with existing work items |

**Gap**: No real Alembic migration runner in test. Schema validated via ORM `create_all` only. Production deploy should verify `002_add_stage_runtime_states.sql` independently.

## 2. Runtime Parity (Python vs .NET)

### Passing Parity

| Fixture | Path Tests | Status |
|---|---|---|
| flat_csv_pickup | 4 paths | PASS |
| recursive_equipment_tree | 4 paths | PASS |
| exclude_patterns | 4 paths | PASS |
| depth_limited | 3 paths | PASS |

### Known .NET Gaps (xfail)

| Feature | Python | .NET | Status |
|---|---|---|---|
| exclude_patterns | Supported | Not implemented | xfail |
| Persisted checkpoint (ALL_NEW dedup) | In-memory set | In-memory _seenFiles | xfail |
| completion_check (MARKER_FILE, SIZE_STABLE) | Supported | Not implemented | xfail |
| post_action (MOVE/DELETE/RENAME) | Supported | Not implemented | xfail |
| Kafka consumer duplicate handling | Not tested | Not tested | xfail |
| DB writer UPSERT idempotency | Not tested | Not tested | xfail |

## 3. Restart / Failover / Chaos

| Test | Status | Description |
|---|---|---|
| stage_stop_state_lost_on_new_activation | PASS | Fresh activation = fresh RUNNING states |
| backlog_from_old_activation_not_visible | PASS | New activation starts with zero queues |
| backlog_survives_within_same_activation | PASS | Stop/resume cycles preserve backlog |
| double_stop_is_idempotent | PASS | No error on repeated stop |
| double_resume_is_idempotent | PASS | No error on repeated resume |
| cluster_failover_preserves_stage_stop | xfail | Requires .NET engine cluster support |
| reprocess_interrupted_mid_execution | xfail | Requires crash recovery in orchestrator |

## 4. Operator-Facing Risks

### Must be documented for operators:

1. **Restart resets stage stop**: When a pipeline is deactivated and reactivated, all stage stops are cleared. Operators must re-stop stages manually after reactivation.

2. **ALL_NEW depends on process memory**: Both Python and .NET collectors track seen files in memory. Process restart causes re-collection of all matching files. **No persistent dedup exists yet.**

3. **Queue counts are per-activation**: Queue summary is scoped to the current activation. Old activation's backlog is not carried forward.

4. **.NET runtime is thinner than Python reference**: The Python reference layer has more features (exclude_patterns, completion_check, post_action). Operators should verify .NET behavior separately.

5. **DB migration must be run manually**: The `002_add_stage_runtime_states.sql` must be applied to production databases before the new stage lifecycle features can be used.

## 5. Summary

| Category | Passing | xfail | Total |
|---|---|---|---|
| Migration safety | 5 | 0 | 5 |
| Runtime parity | 4 (+6 xfail) | 6 | 10 |
| Restart/chaos | 5 (+2 xfail) | 2 | 7 |
| **Total** | **14** | **8** | **22** |
