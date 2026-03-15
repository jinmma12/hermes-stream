# Hermes Roadmap Execution Plan

> Based on the repository roadmap as of 2026-03-15 and the current code state.

## Current Reality

- Python still contains the richest reference implementation and test corpus.
- `.NET` now has the strategic center of gravity.
- React remains the correct UI direction.
- The highest-risk gap is not UI polish; it is backend duplication and missing `.NET` parity.

## Recommended Order Of Attack

### Track 1: V2 Backend Consolidation

Goal:

- replace FastAPI with ASP.NET Core as the public API
- keep gRPC for internal worker/plugin communication only

Immediate tasks:

1. port GET routes first
2. port mutation routes second
3. move live events to SignalR/WebSocket in `.NET`
4. retire FastAPI from production path

### Track 2: Read Parity Before Write Parity

Goal:

- make the frontend read from `.NET` before moving all writes

Immediate tasks:

1. definitions list/detail/versions
2. pipelines list/detail/stages
3. jobs list/detail
4. monitor dashboard feeds

Why first:

- lower blast radius
- easier frontend integration
- gives a visible migration milestone without database write risk

### Track 3: Roadmap Phase 1 MVP

The local roadmap puts the next implementation weight in these areas:

1. ASP.NET Core 8 Web API setup
2. definition CRUD and instance CRUD
3. pipeline CRUD and activation
4. monitoring engine
5. processing orchestrator
6. plugin protocol v2

Interpretation:

- the `.NET API` move is not optional side work; it is on the critical path
- engine write-path parity should follow immediately after read-path parity

### Track 4: Production Gaps From V2

After MVP parity:

1. back-pressure
2. DLQ
3. content repository
4. observability
5. graceful shutdown
6. exactly-once/checkpointing where justified

## What To Build Next

### Next 3 concrete milestones

1. Replace in-memory `.NET` read store with EF Core-backed query services
2. Port `definitions` and `pipelines` mutations from Python to `.NET`
3. Add SignalR endpoint and swap the monitor dashboard to `.NET` live updates

### What not to do yet

- do not rewrite the React UI
- do not add more FastAPI-only features
- do not start cluster features before single-node parity is solid
- do not delete Python reference logic until `.NET` tests cover the behavior

## Exit Criteria For FastAPI Removal

- React read traffic no longer depends on FastAPI
- pipeline activation and reprocess flows run through ASP.NET Core
- monitor live events come from `.NET`
- parity tests exist for the migrated surfaces
- FastAPI remains only as temporary reference code or is removed entirely
