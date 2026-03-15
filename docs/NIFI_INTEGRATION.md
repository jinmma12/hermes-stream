# NiFi Integration Guide

> Vessel + NiFi = NiFi's data movement power + Vessel's per-item tracking and simple UI

---

## Why NiFi + Vessel?

Apache NiFi and Vessel serve complementary roles in a data processing architecture:

| Capability | NiFi | Vessel | Together |
|---|---|---|---|
| **Data routing & transformation** | 300+ built-in processors, clustering, back-pressure | Lightweight plugin system | NiFi handles heavy data movement |
| **Per-item tracking** | Provenance events (developer-oriented) | WorkItem Explorer with search, filter, reprocess | Vessel surfaces NiFi provenance in a user-friendly UI |
| **Configuration management** | XML/JSON config, Parameter Contexts | Recipe UI with versioning, JSON Schema forms | Non-developers manage NiFi through Vessel's Recipe Editor |
| **Reprocessing** | Manual replay from provenance viewer | First-class reprocessing from any step | One-click reprocess through Vessel UI |
| **Deployment** | JVM 2GB+, complex clustering | Lightweight Python + React | Vessel adds management layer without duplicating NiFi's engine |

### When to use NiFi + Vessel

- Your organization has **existing NiFi flows** that work well but need better management UI
- **Non-developers** need to change NiFi processor parameters safely
- You need **per-item tracking** across NiFi flows visible to operations teams
- You want to **mix** NiFi-powered steps with custom Python processors in a single pipeline

### When NOT to use NiFi integration

- Your data volumes are small enough for Vessel's native plugins
- You don't have an existing NiFi installation
- You want the lightest possible deployment (Mode 3 below)

---

## Integration Modes

### Mode 1: Vessel as NiFi Manager (Recommended for legacy migration)

```
┌──────────────────────────────────────────────┐
│                Vessel Web UI                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Pipeline  │ │ Recipe   │ │ WorkItem     │ │
│  │ Designer  │ │ Editor   │ │ Explorer     │ │
│  └─────┬────┘ └─────┬────┘ └──────┬───────┘ │
└────────┼────────────┼─────────────┼──────────┘
         │            │             │
    ┌────▼────────────▼─────────────▼──────────┐
    │           NiFiVesselBridge                 │
    │                                            │
    │  sync_process_groups  →  Pipeline view     │
    │  push_recipe_to_nifi  →  Parameter update  │
    │  sync_provenance      →  WorkItem tracking │
    └────────────────────┬─────────────────────┘
                         │ REST API
    ┌────────────────────▼─────────────────────┐
    │         Apache NiFi (existing)            │
    │  Process Groups run unchanged             │
    │  Provenance captured automatically        │
    │  Parameter Contexts receive Recipe values  │
    └──────────────────────────────────────────┘
```

**How it works:**
- Existing NiFi flows continue running without modification
- Vessel periodically syncs NiFi process groups as Vessel pipelines
- Vessel reads NiFi provenance events to create WorkItem tracking records
- Vessel's Recipe UI pushes configuration to NiFi Parameter Contexts
- Non-developers manage NiFi through Vessel's simpler, form-based UI

**Best for:** Organizations with mature NiFi deployments that need a management layer.

### Mode 2: Vessel with NiFi Steps (Hybrid)

```
┌──────────────────────────────────────────────────┐
│              Vessel Pipeline                      │
│                                                   │
│  Step 1 (PLUGIN)     Step 2 (NIFI_FLOW)          │
│  ┌────────────┐      ┌──────────────────┐        │
│  │ Python     │ ───► │ NiFi Process     │        │
│  │ Collector  │      │ Group            │        │
│  └────────────┘      │ (heavy ETL)      │        │
│                      └────────┬─────────┘        │
│                               │                   │
│  Step 3 (PLUGIN)              │                   │
│  ┌────────────┐◄──────────────┘                   │
│  │ Python     │                                   │
│  │ Transfer   │                                   │
│  └────────────┘                                   │
└──────────────────────────────────────────────────┘
```

**How it works:**
- Vessel orchestrates the overall pipeline
- Individual steps can use `NIFI_FLOW` execution type
- NiFi handles specific heavy-duty collection/transformation steps
- Other steps use native Vessel plugins (Python, scripts, HTTP)
- Vessel tracks WorkItems across both native and NiFi steps

**Best for:** New pipelines that need NiFi's power for specific steps.

### Mode 3: Full Vessel (NiFi-free)

```
┌──────────────────────────────────────────┐
│           Vessel Pipeline                 │
│                                           │
│  Step 1 (PLUGIN)  →  Step 2 (SCRIPT)     │
│  │ Python          │ Any language         │
│  │ Collector       │ Algorithm            │
│  └─────────────────┘                      │
│                       Step 3 (HTTP)       │
│                       │ REST API          │
│                       │ Transfer          │
│                       └──────────────     │
└──────────────────────────────────────────┘
```

**How it works:**
- Vessel handles everything with native plugins
- No NiFi dependency — lighter deployment
- Set `VESSEL_NIFI_ENABLED=false` (the default)

**Best for:** New deployments without existing NiFi infrastructure.

---

## Setup Guide

### 1. Prerequisites

- Apache NiFi 1.9.x or later running and accessible via HTTP/HTTPS
- NiFi user account with API access (if secured)
- Vessel backend running (Python 3.12+)

### 2. Configuration

Add NiFi connection settings to your Vessel `.env` file:

```bash
# Required
VESSEL_NIFI_ENABLED=true
VESSEL_NIFI_BASE_URL=https://your-nifi-host:8443/nifi-api

# Authentication (if NiFi is secured)
VESSEL_NIFI_USERNAME=vessel-service-account
VESSEL_NIFI_PASSWORD=your-secure-password

# Optional tuning
VESSEL_NIFI_SYNC_INTERVAL=60         # seconds between process group syncs
VESSEL_NIFI_REQUEST_TIMEOUT=30       # HTTP timeout per request
VESSEL_NIFI_PROVENANCE_MAX_WAIT=300  # max seconds to wait for flow completion
```

### 3. Connect to existing NiFi flows

```python
from vessel.infrastructure.nifi import NiFiClient, NiFiConfig

config = NiFiConfig()  # reads from environment variables
async with NiFiClient(config) as client:
    # List all process groups (appears as pipelines in Vessel)
    groups = await client.list_process_groups()
    for g in groups:
        print(f"  {g.name} ({g.id}) - {g.running_count} running")
```

### 4. Import NiFi flows into Vessel

```python
from vessel.infrastructure.nifi.bridge import NiFiVesselBridge

bridge = NiFiVesselBridge(client, config)

# Sync all top-level process groups as Vessel pipelines
pipelines = await bridge.sync_process_groups_as_pipelines()
for p in pipelines:
    print(f"Pipeline: {p.name}")
    for step in p.steps:
        print(f"  Step: {step.name} ({step.processor_type}) [{step.state}]")
```

### 5. Map Parameter Contexts to Recipes

```python
# List NiFi parameter contexts
contexts = await client.list_parameter_contexts()

# Push a Vessel Recipe update to NiFi
recipe_config = {
    "api_url": "https://vendor.example.com/api/v2",
    "poll_interval": "5 min",
    "batch_size": "1000",
}
await bridge.push_recipe_to_nifi(recipe_config, parameter_context_id="ctx-123")
```

### 6. View NiFi provenance in Vessel's WorkItem Explorer

```python
from datetime import datetime, timedelta, timezone

# Sync recent provenance events as Vessel WorkItems
since = datetime.now(timezone.utc) - timedelta(hours=1)
work_items = await bridge.sync_nifi_provenance_to_work_items(
    pipeline_id="process-group-id",
    since=since,
)
for wi in work_items:
    print(f"  FlowFile {wi.flowfile_uuid}: {wi.event_type} at {wi.component_name}")
```

### 7. Use NiFi as a pipeline step

```python
from vessel.infrastructure.nifi.executor import NiFiFlowExecutor

executor = NiFiFlowExecutor(client, config)
result = await executor.execute(
    config={
        "process_group_id": "heavy-etl-group-id",
        "timeout": 120,
        "start_group": True,   # auto-start before execution
        "stop_after": False,   # leave running for next invocation
    },
    input_data={"records": [{"id": 1, "value": "test"}]},
    context={"pipeline_id": "my-pipeline", "step_id": "etl-step"},
)

if result.success:
    print(f"Flow completed with {result.provenance_event_count} events")
else:
    for error in result.errors:
        print(f"Error: {error['message']}")
```

---

## API Mapping

How NiFi concepts map to Vessel concepts:

| NiFi Concept | Vessel Concept | Bridge Method |
|---|---|---|
| Process Group | PipelineInstance | `sync_process_groups_as_pipelines()` |
| Processor | Pipeline Step | (included in sync) |
| Processor Properties | Recipe `config_json` | `push_recipe_to_nifi()` |
| Parameter Context | Recipe version | `push_recipe_to_nifi()` |
| FlowFile | WorkItem | `sync_nifi_provenance_to_work_items()` |
| Provenance Event | ExecutionEventLog | `sync_nifi_provenance_to_work_items()` |
| Input Port | Pipeline step boundary (entry) | `trigger_nifi_flow()` |
| Output Port | Pipeline step boundary (exit) | `monitor_nifi_flow_completion()` |
| Connection Queue | WorkItem queue between steps | `client.list_connections()` |
| Template (1.x) | Pipeline template | `client.instantiate_template()` |
| Processor Type | CollectorDefinition | `map_nifi_processor_to_definition()` |

### NiFi Processor State -> Vessel Pipeline Status

| NiFi State | Vessel Status |
|---|---|
| RUNNING | ACTIVE |
| STOPPED | PAUSED |
| DISABLED | DISABLED |
| Invalid (validation errors) | ERROR |

### NiFi Provenance Event Type -> Vessel WorkItem Event

| NiFi Event | Vessel Event | Meaning |
|---|---|---|
| CREATE | ITEM_CREATED | New data entered the flow |
| RECEIVE | ITEM_RECEIVED | Data received from external source |
| CONTENT_MODIFIED | STEP_COMPLETED | Processor transformed the data |
| ROUTE | STEP_COMPLETED | Data routed to next processor |
| SEND | ITEM_TRANSFERRED | Data sent to external destination |
| DROP | ITEM_FAILED | Data intentionally dropped |
| EXPIRE | ITEM_EXPIRED | Data expired from queue |
| FORK | ITEM_SPLIT | One item split into multiple |
| JOIN | ITEMS_MERGED | Multiple items merged into one |

---

## Architecture Details

### Authentication

Vessel uses NiFi's token-based authentication (NiFi 1.9.x+):

1. `POST /access/token` with username/password -> bearer token
2. Token included as `Authorization: Bearer <token>` on all requests
3. Auto-refresh before expiry (configurable via `token_refresh_interval`)
4. Pre-existing tokens supported via `VESSEL_NIFI_TOKEN` env var

### Optimistic Locking (Revisions)

NiFi uses a revision system to prevent concurrent modification conflicts:

- Every mutable entity has a `revision.version` number
- Before updating, Vessel fetches the current revision
- The revision is included in PUT/DELETE requests
- If another client modified the entity, NiFi returns HTTP 409
- Vessel raises `NiFiConflictError` which callers can retry

### Error Handling

The NiFi client provides structured error types:

| Exception | HTTP Status | When |
|---|---|---|
| `NiFiConnectionError` | N/A | Cannot reach NiFi |
| `NiFiAuthError` | 401, 403 | Invalid credentials or permissions |
| `NiFiNotFoundError` | 404 | Resource doesn't exist |
| `NiFiConflictError` | 409 | Revision conflict |
| `NiFiApiError` | Other | General API error |

### Rate Limiting & Retries

- GET requests retry up to `max_retries` times on 502/503/504
- Exponential backoff between retries (2^attempt seconds, max 10s)
- `Retry-After` header respected for HTTP 429 responses
- Mutation requests (POST/PUT/DELETE) are NOT retried automatically

---

## Module Structure

```
vessel/backend/vessel/infrastructure/nifi/
├── __init__.py      # Public API exports
├── config.py        # NiFiConfig (pydantic-settings)
├── models.py        # Pydantic models for NiFi API responses
├── client.py        # NiFiClient - async REST API client
├── bridge.py        # NiFiVesselBridge - concept mapping layer
└── executor.py      # NiFiFlowExecutor - pipeline step executor
```

### Dependency Flow

```
config.py  ←──  models.py
    ↑              ↑
    │              │
client.py ─────────┘
    ↑
bridge.py
    ↑
executor.py
```

---

## Forward Compatibility Notes (NiFi 2.x)

NiFi 2.0 introduces several changes. This integration handles them as follows:

| Change in NiFi 2.x | Impact | Mitigation |
|---|---|---|
| Templates removed | `list_templates()`, `instantiate_template()`, `upload_template()` will fail | Use Parameter Contexts instead; template methods are NiFi 1.x only |
| Parameter Providers | New way to inject parameters | Future bridge method can map Vessel as a Parameter Provider |
| Python processors | NiFi 2.0 supports Python processors natively | Vessel plugins can potentially run as NiFi processors |
| REST API changes | Some endpoints may change paths | All paths are relative to `base_url`; update config if needed |

The integration is designed to work with NiFi 1.9.x as the baseline, with
models using `extra="allow"` to accept new fields from newer versions without
breaking.
