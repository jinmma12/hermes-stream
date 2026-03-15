# Vessel

> **Carry your data. Track every item.**

Vessel is a lightweight, user-friendly data processing platform with per-item tracking, visual recipe management, and first-class reprocessing.

## What is Vessel?

Vessel sits between heavyweight platforms like Apache NiFi and lightweight tools like Singer/Benthos. It provides:

- **Visual Pipeline Designer** — n8n-style drag-and-drop pipeline configuration
- **Recipe Management** — Non-developers can configure collection settings, algorithm parameters, and transfer options through a web UI
- **WorkItem Tracking** — Every data item is tracked through collect → algorithm → transfer with full execution history
- **First-Class Reprocessing** — Failed items can be reprocessed from any step, with original or updated recipes
- **Plugin Architecture** — Language-agnostic plugins via stdin/stdout JSON protocol
- **NiFi-Friendly** — Optional NiFi integration as execution backend, but fully independent

## Quick Start

```bash
# Clone
git clone https://github.com/your-org/vessel.git
cd vessel

# Run with Docker Compose
docker compose up -d

# Open Web UI
open http://localhost:3000

# API
curl http://localhost:8000/api/v1/health
```

## Architecture

```
Web UI (React) → API Server (FastAPI) → PostgreSQL
                      │
                      ├── Monitoring Engine (file/API/DB watching)
                      ├── Processing Orchestrator (step execution)
                      ├── Recipe Engine (versioned configuration)
                      └── Execution Dispatcher
                           ├── PLUGIN (stdin/stdout protocol)
                           ├── SCRIPT (subprocess)
                           ├── HTTP (REST call)
                           ├── DOCKER (container)
                           └── NIFI_FLOW (NiFi REST API)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full specification.

## Key Concepts

| Concept | Description |
|---|---|
| **Definition** | Plugin type catalog (e.g., "REST API Collector") |
| **Instance** | Configured plugin with Recipe (e.g., "Vendor A Order API") |
| **Recipe** | Versioned configuration values for an instance |
| **Pipeline** | Ordered steps: COLLECT → ALGORITHM → TRANSFER |
| **WorkItem** | Single data item detected by monitoring |
| **Execution** | Processing run of a WorkItem through pipeline steps |
| **Reprocess** | Re-execute a WorkItem with same or updated recipe |

## For Non-Developers

Vessel is designed so that **operators (non-SW engineers) can**:
1. Configure data collection settings through web forms
2. Adjust algorithm parameters (recipes) with sliders, dropdowns, and input fields
3. Monitor pipeline status in real-time
4. View processing history for any data item
5. Reprocess failed items with one click

**Developers** create plugin Definitions with JSON Schema; **operators** fill in the values.

## License

Apache License 2.0
