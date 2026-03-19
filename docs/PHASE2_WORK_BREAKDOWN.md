# Phase 2 Work Breakdown

> Scope source: `ROADMAP.md` Phase 2 Integrity Track
> Goal: move Hermes from "strong prototype" to "trustworthy single-node runtime"

---

## Phase 2 Objective

Phase 2 is not a feature expansion phase.
It is the phase where Hermes starts becoming safe to trust for internal operational use.

Primary outcome:

- runtime behavior matches product claims
- restart/replay/failure behavior becomes explicit
- core collect/process/export semantics stop depending on inference

---

## Workstream Summary

| ID | Workstream | Priority | Why it matters first |
|---|---|---|---|
| P2-1 | Runtime contract hardening | P0 | Operators must know whether the engine is real or stubbed |
| P2-2 | Checkpoint and dedup safety | P0 | Prevent silent duplicate collection after restart |
| P2-3 | Replay and snapshot correctness | P0 | Reprocess is a core differentiator |
| P2-4 | Failure classification framework | P1 | Retry/DLQ behavior must be predictable |
| P2-5 | Integrity-focused E2E and integration harness | P0 | Need proof, not just intent |
| P2-6 | UI/runtime trust alignment | P1 | UI must not promise unsupported behavior |

---

## Detailed Breakdown

## P2-1. Runtime Contract Hardening

### P2-1A. Stub mode visibility

| Item | Detail |
|---|---|
| Task | Prevent production mode from silently operating with `EngineClient` stub transport |
| Files | `backend/hermes/engine_client.py`, `backend/hermes/api/routes/system.py` |
| Output | explicit stub/degraded flags in health and system status |
| Validation | unit test + E2E contract test |
| Recommended owner | Claude |

Acceptance:

1. production mode cannot report healthy when engine is disconnected
2. stub mode is visible through API responses and logs
3. operator can distinguish CRUD API health from runtime engine health

### P2-1B. Runtime authority cleanup

| Item | Detail |
|---|---|
| Task | Make `.NET engine owns runtime` explicit in docs and service boundaries |
| Files | `README.md`, `CLAUDE.md`, `docs/ARCHITECTURE.md`, selected backend service comments |
| Output | reduced ambiguity between Python reference layer and .NET runtime |
| Validation | documentation review + no contradictory wording |
| Recommended owner | Codex |

Acceptance:

1. docs do not imply Python is the runtime source of truth
2. runtime responsibilities are listed clearly by layer

---

## P2-2. Checkpoint and Dedup Safety

### P2-2A. Dedup key contract

| Item | Detail |
|---|---|
| Task | Define dedup key strategy for File, FTP/SFTP, Kafka, REST API |
| Files | new design note + engine collector code + tests |
| Output | documented key format and collision assumptions |
| Validation | deterministic tests for identical and near-identical inputs |
| Recommended owner | Claude |

Acceptance:

1. same source item maps to same dedup identity
2. different source items do not collapse unexpectedly
3. dedup contract is documented per connector

### P2-2B. Persisted checkpoint storage

| Item | Detail |
|---|---|
| Task | Move collector progress state from process memory to persisted store |
| Files | engine monitor state, DB schema/repository, tests |
| Output | restart-safe monitor progress |
| Validation | restart simulation test |
| Recommended owner | Claude |

Acceptance:

1. restart does not blindly recollect accepted items
2. monitor progress survives process restart
3. state can be inspected or logged for debugging

### P2-2C. Restart safety tests

| Item | Detail |
|---|---|
| Task | Add tests proving no silent recollection after restart |
| Files | `backend/tests/e2e/`, `engine/tests/...` |
| Output | restart/recovery coverage for File, FTP/SFTP, Kafka |
| Validation | integration/E2E tests |
| Recommended owner | Codex for contracts, Claude for runtime-backed tests |

Acceptance:

1. restart scenarios are testable and repeatable
2. duplicate recollection becomes a failing test, not tribal knowledge

---

## P2-3. Replay and Snapshot Correctness

### P2-3A. Snapshot immutability

| Item | Detail |
|---|---|
| Task | Verify and tighten execution snapshot immutability |
| Files | snapshot resolver, snapshot tests |
| Output | replay-safe snapshots |
| Validation | hash and compare tests |
| Recommended owner | Claude |

Acceptance:

1. original snapshot remains stable after recipe updates
2. snapshot hash changes only when effective config changes

### P2-3B. Reprocess-from-step contract

| Item | Detail |
|---|---|
| Task | Define exactly what is skipped, reused, and rerun when `start_from_step` is set |
| Files | orchestrator, execution model, docs, E2E tests |
| Output | explicit replay semantics |
| Validation | failing-stage and replay-stage contract tests |
| Recommended owner | Claude |

Acceptance:

1. earlier succeeded steps are not silently rerun unless requested
2. replay execution history is auditable
3. `use_latest_recipe` vs original recipe behavior is explicit

### P2-3C. Bulk replay auditability

| Item | Detail |
|---|---|
| Task | Ensure bulk replay keeps request metadata and outcome visibility |
| Files | work item APIs, DB models, tests |
| Output | auditable replay queue |
| Validation | E2E/service tests |
| Recommended owner | Codex |

Acceptance:

1. each replay request preserves operator, reason, and strategy
2. bulk operations remain inspectable per work item

---

## P2-4. Failure Classification Framework

### P2-4A. Error taxonomy

| Item | Detail |
|---|---|
| Task | Standardize `transient / permanent / throttled / unknown` classification |
| Files | engine error handling layer, docs |
| Output | common connector failure language |
| Validation | table-driven tests |
| Recommended owner | Claude |

Acceptance:

1. connector failures map to one of the standard classes
2. retry policy depends on class, not ad hoc exception text

### P2-4B. Retry contract

| Item | Detail |
|---|---|
| Task | Make retry/backoff/jitter/max-attempt behavior explicit by connector class |
| Files | engine retry policies, docs, tests |
| Output | predictable retry behavior |
| Validation | deterministic retry tests |
| Recommended owner | Claude |

Acceptance:

1. transient failures retry deterministically
2. permanent failures fail fast
3. retries emit metrics and logs

### P2-4C. DLQ contract

| Item | Detail |
|---|---|
| Task | Define DLQ payload shape and replay metadata |
| Files | execution models, DLQ repository/model, docs, tests |
| Output | replayable failed item records |
| Validation | failure-path tests |
| Recommended owner | Claude |

Acceptance:

1. DLQ entries preserve source identity and failure reason
2. failed data is recoverable for manual replay

---

## P2-5. Integrity-Focused Test Harness

### P2-5A. E2E contract stabilization

| Item | Detail |
|---|---|
| Task | Turn contract tests in `backend/tests/e2e/` into trustworthy, runnable tests where possible |
| Files | `backend/tests/e2e/` |
| Output | stable operator-flow test suite |
| Validation | local pytest pass |
| Recommended owner | Codex |

Acceptance:

1. no hanging tests
2. each passing E2E test proves a meaningful operator contract
3. .NET-dependent scenarios remain clearly marked

### P2-5B. Real-service integration stack

| Item | Detail |
|---|---|
| Task | Make `deploy/docker-compose.e2e.yml` usable for FTP/SFTP/Kafka/PostgreSQL |
| Files | `deploy/docker-compose.e2e.yml`, integration tests |
| Output | real connector verification path |
| Validation | service bring-up + smoke tests |
| Recommended owner | Claude |

Acceptance:

1. FTP/SFTP and Kafka can be tested against real services
2. integration harness matches documented connector claims

---

## P2-6. UI/Runtime Trust Alignment

### P2-6A. Capability alignment audit

| Item | Detail |
|---|---|
| Task | Audit which UI options are implemented in runtime vs only documented |
| Files | webapp pages, runtime connectors, docs |
| Output | capability matrix |
| Validation | manual audit + doc update |
| Recommended owner | Codex |

Acceptance:

1. unsupported options are labeled, hidden, or deferred
2. UI does not imply runtime support that does not exist

### P2-6B. Support level surfacing

| Item | Detail |
|---|---|
| Task | Add Beta/Prototype/Production-ready support labels to docs first, UI second |
| Files | docs, optionally webapp |
| Output | honest operator expectations |
| Validation | review |
| Recommended owner | Codex |

Acceptance:

1. support level is obvious for each core connector
2. roadmap, docs, and UI use the same language

---

## Suggested Sequencing

### Week 1

1. P2-1A Stub mode visibility
2. P2-2A Dedup key contract
3. P2-5A E2E contract stabilization

### Week 2

1. P2-2B Persisted checkpoint storage
2. P2-3A Snapshot immutability verification
3. P2-4A Error taxonomy

### Week 3

1. P2-3B Reprocess-from-step contract
2. P2-4B Retry contract
3. P2-6A Capability alignment audit

### Week 4

1. P2-4C DLQ contract
2. P2-5B Real-service integration stack
3. P2-6B Support level surfacing

---

## Parallelization Guidance

### Claude

- engine runtime behavior
- checkpoint/dedup persistence
- retry/DLQ semantics
- real integration harness

### Codex

- contract tests
- docs and support-level alignment
- capability audit
- replay and operator-flow verification

### Shared files to coordinate carefully

- `backend/hermes/engine_client.py`
- execution and pipeline domain models
- orchestrator and snapshot resolver
- connector runtime classes

---

## Done Definition for Phase 2

Phase 2 is complete only when all of the following are true:

1. engine stub mode cannot masquerade as healthy production runtime
2. core collect sources have persisted checkpoint and dedup behavior
3. replay/reprocess behavior is explicit and tested
4. retry/DLQ behavior is standardized
5. operator-flow E2E tests are stable and meaningful
6. UI/docs no longer over-promise unsupported runtime capability
