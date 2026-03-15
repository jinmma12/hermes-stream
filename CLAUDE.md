# Vessel

Lightweight data processing platform with per-item tracking, visual recipe management, and first-class reprocessing.

"Carry your data. Track every item."

## Tech Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy (async), PostgreSQL 15
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, React Flow (@xyflow/react)
- **Forms**: react-jsonschema-form (@rjsf) for dynamic processor config
- **Infrastructure**: Docker Compose

## Quick Start

```bash
cp .env.example .env
docker compose up -d
```

- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Web UI: http://localhost:3000

## Directory Structure

```
vessel/
  backend/           # FastAPI application
    vessel/          # Python package
      main.py        # App entrypoint
      models/        # SQLAlchemy models
      api/           # Route handlers
      core/          # Engine, runtime, plugin loader
    tests/           # pytest tests
  webapp/            # React frontend (Vite)
    src/
      components/    # React components
      pages/         # Route pages
      hooks/         # Custom hooks
      api/           # API client
  plugins/           # User-defined processors (YAML + optional Python)
  docs/              # Architecture and design docs
```

## Key Commands

```bash
# Start all services
docker compose up -d

# Backend only (local dev)
cd backend && pip install -e ".[dev]" && uvicorn vessel.main:app --reload

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
- Database schema (recipes, steps, runs, items, provenance)
- NiFi bridge integration (optional)
