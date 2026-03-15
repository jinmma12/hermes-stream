# Hermes Stream

Lightweight data processing platform with per-job tracking, visual recipe management, and first-class reprocessing.

"The Messenger of Data."

## Tech Stack

- **Web API (Python)**: Python 3.12, FastAPI, SQLAlchemy (async), PostgreSQL 15
- **Core Engine (.NET)**: .NET 8 Worker Service, gRPC, EF Core, Polly, Serilog
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, React Flow (@xyflow/react)
- **Forms**: react-jsonschema-form (@rjsf) for dynamic processor config
- **Infrastructure**: Docker Compose

## Architecture Split

| Layer | Language | Responsibility |
|---|---|---|
| **Web API** (`backend/`) | Python/FastAPI | REST API, WebSocket, CRUD, DB access |
| **Core Engine** (`engine/`) | .NET 8 | Monitoring, processing, plugins, NiFi |
| **Frontend** (`webapp/`) | React/TypeScript | Visual UI |

Communication: Web API <--gRPC--> Engine (port 50051)

## Quick Start

```bash
cp .env.example .env
docker compose up -d
```

- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Web UI: http://localhost:3000
- Engine gRPC: localhost:50051
- Engine metrics: http://localhost:9090

## Directory Structure

```
hermes/
  backend/              # Python Web API (FastAPI)
    vessel/             # Python package
      main.py           # App entrypoint
      engine_client.py  # gRPC client to .NET Engine
      api/              # REST route handlers
      api/schemas/      # Pydantic DTOs
      api/websocket.py  # WebSocket forwarding
      domain/models/    # SQLAlchemy models
      domain/services/  # Web API services + engine stubs (test compat)
      infrastructure/   # Database session, repositories
    tests/              # pytest tests (API + engine reference specs)
  engine/               # .NET Core Engine
    Hermes.sln          # Solution file
    Dockerfile          # Multi-stage .NET build
    src/Hermes.Engine/  # Worker service project
    reference/          # Python reference implementations (read-only)
      domain/services/  # monitoring, processing, execution, conditions
      workers/          # monitoring_worker, processing_worker
      plugins/          # protocol, registry, executor
      infrastructure/   # nifi client, bridge, executor
  webapp/               # React frontend (Vite)
  plugins/              # User-defined processors (YAML + optional Python)
  protos/               # gRPC proto definitions
  docs/                 # Architecture and design docs
```

## Key Commands

```bash
# Start all services
docker compose up -d

# Backend only (local dev)
cd backend && pip install -e ".[dev]" && uvicorn vessel.main:app --reload

# Engine only (local dev, requires .NET 8 SDK)
cd engine && dotnet run --project src/Hermes.Engine

# Frontend only (local dev)
cd webapp && npm install && npm run dev

# Run backend tests
cd backend && pytest

# Lint & type check
cd backend && ruff check . && mypy vessel/

# Build frontend for production
cd webapp && npm run build
```

## Architecture

See `docs/ARCHITECTURE.md` for full design specification including:

- Core concepts: Recipes, Processors, Items, Provenance
- Processing engine and execution model
- Plugin system (YAML + JSON Schema config)
- API design and WebSocket events
- Database schema (recipes, stages, runs, items, provenance)
- NiFi bridge integration (optional)

## Engine Reference Files

The `engine/reference/` directory contains the original Python implementations
of engine-layer services. These serve as the specification for the .NET
implementation. The Python test suite in `backend/tests/` acts as a behavioral
specification -- .NET xUnit tests should replicate the same scenarios.
