# Hermes .NET API Migration Plan

> Decision date: 2026-03-15
> Status: Approved direction for V2

## Decision

Hermes V2 should consolidate the public backend onto ASP.NET Core.

The current Python FastAPI layer was a reasonable prototype choice, but it now
creates avoidable duplication:

- HTTP models exist separately from the .NET engine domain
- state ownership is split across Python writes, Python reads, and future .NET writes
- authentication, validation, WebSocket forwarding, and operational concerns are duplicated
- the gRPC bridge becomes a permanent internal tax instead of a temporary migration tool

For V2, Hermes should use:

- React for the web UI
- ASP.NET Core for the public API
- .NET worker services for monitoring and execution
- gRPC for internal worker, plugin, and cluster communication
- Python only for plugins, algorithm containers, and optional SDK/runtime support

## Target Architecture

```text
React UI
  -> ASP.NET Core API
       -> Application services / EF Core / SignalR
       -> .NET workers and engine services
       -> gRPC plugin hosts / cluster nodes
```

## Public vs Internal Transport

- Public edge: HTTP/JSON + WebSocket or SignalR
- Internal control plane: gRPC
- Plugin protocol: gRPC or stdin/stdout
- Cluster communication: gRPC

This keeps browser and external client integration simple while preserving
high-performance binary protocols where they are actually useful.

## Migration Phases

### Phase 1: Bootstrap the .NET API

- create `Hermes.Api`
- expose root, health, and system endpoints
- establish the ASP.NET Core deployment path
- leave Python FastAPI in place for feature parity reference only

### Phase 2: Move read-only routes first

- migrate `system`, `definitions`, `pipelines`, and `work_items` GET routes
- move websocket/event streaming to SignalR or ASP.NET WebSockets
- align DTO names with the existing frontend contract where possible

### Phase 3: Move mutation routes

- move pipeline activation/deactivation, CRUD mutations, and reprocess flows
- stop Python from writing to the shared database
- move validation rules into shared .NET application services

### Phase 4: Remove the Python API layer

- freeze FastAPI routes
- keep Python only for plugin runtime support and test fixtures
- remove the Python gRPC bridge from production deployment

## Non-Goals

- rewriting the React UI in C#
- removing Python from plugin development
- forcing browsers to use gRPC directly

## Immediate Build Priorities

1. create the ASP.NET Core API host
2. add OpenAPI and Swagger once the route surface stabilizes
3. add matching route groups for the current frontend pages
4. introduce SignalR or WebSocket event streaming
5. port Python service logic into .NET application services
6. retire FastAPI once route coverage is sufficient
