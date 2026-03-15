# Hermes Delivery Agents

This repository is moving toward a V2 architecture centered on:

- React web UI
- ASP.NET Core public API
- .NET engine and workers
- gRPC for internal plugins and cluster communication

Use the following workstreams to parallelize feature delivery against `ROADMAP.md`.

## Agent 1: API Migration Agent

Scope:

- migrate FastAPI endpoints to ASP.NET Core
- preserve frontend contracts where reasonable
- replace Python WebSocket forwarding with SignalR or ASP.NET WebSockets

Primary files:

- `engine/src/Hermes.Api/`
- `backend/vessel/api/`
- `backend/vessel/main.py`
- `docs/NET_API_MIGRATION.md`

Definition of done:

- route parity for a targeted vertical slice
- OpenAPI exposed from `.NET`
- Python route for that slice marked deprecated or removed

## Agent 2: Domain Porting Agent

Scope:

- port Python domain services into .NET application/domain layers
- preserve behavior covered by the Python pytest suite

Primary files:

- `backend/vessel/domain/`
- `backend/tests/`
- `engine/reference/`
- future `.NET` domain and application projects

Definition of done:

- behavior exists in .NET
- equivalent automated tests exist in .NET
- no new logic is added only to Python

## Agent 3: Pipeline Runtime Agent

Scope:

- monitoring engine
- processing orchestrator
- snapshot handling
- retry, skip, stop, and reprocess behavior

Primary roadmap areas:

- Phase 1 Core Pipeline
- Phase 1 Monitoring Engine
- Phase 1 Processing Engine
- Phase 2 resilience gaps

Definition of done:

- worker can execute a pipeline end to end
- failure handling semantics are covered by automated tests

## Agent 4: Plugin Protocol Agent

Scope:

- finalize protobuf contracts
- implement plugin host lifecycle
- support long-lived gRPC plugins and subprocess mode

Primary files:

- `protos/`
- `plugins/`
- `engine/reference/plugins/`

Definition of done:

- built-in plugins run through the agreed protocol
- health, startup, and teardown are testable

## Agent 5: Realtime UX Agent

Scope:

- adapt the React app to the .NET API
- add stable client abstractions for REST and event streaming
- keep the UX aligned with the n8n-style operator-first goal

Primary files:

- `webapp/src/`
- `webapp/src/api/`

Definition of done:

- webapp uses the `.NET` API endpoints for migrated surfaces
- live status updates work without the Python layer

## Agent 6: Ops and Observability Agent

Scope:

- logging
- health checks
- metrics
- docker compose and deployment shape

Primary roadmap areas:

- Phase 1 Infrastructure
- Phase 2 Observability
- Phase 3 Deployment

Definition of done:

- API and engine expose health endpoints
- metrics and logs are consistent across services

## Execution Order

1. API Migration Agent
2. Domain Porting Agent
3. Pipeline Runtime Agent
4. Plugin Protocol Agent
5. Realtime UX Agent
6. Ops and Observability Agent

## Rule of Thumb

When a feature can be implemented directly in the new .NET API path, do not
add more functionality to FastAPI unless it is required as a temporary bridge.
