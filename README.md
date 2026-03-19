<p align="center">
  <img src="docs/assets/hermes-logo.png" alt="Hermes" width="200" />
</p>

<h1 align="center">Hermes</h1>

<p align="center">
  <strong>The Messenger of Data.</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#key-features">Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="docs/ARCHITECTURE.md">Full Docs</a> •
  <a href="ROADMAP.md">Roadmap</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/.NET-8.0-purple.svg" alt=".NET" />
  <img src="https://img.shields.io/badge/status-Integrity%20Track-orange.svg" alt="Status" />
</p>

---

## What is Hermes?

Hermes is an **operator-first orchestration and control plane for existing data platforms**.

It sits on top of tools you already run, such as:

- Kafka
- databases
- NiFi
- FTP/SFTP
- REST APIs

and gives you one place to manage:

- source configuration
- recipe and parameter versioning
- pipeline assembly
- per-item provenance
- replay and reprocessing

Think of it as **Apache NiFi's per-item tracking** + **n8n's operator UX** + **recipe/replay control** for a mixed data stack.

### The Problem

| Tool | What's Missing |
|---|---|
| **Kafka / DB / FTP / NiFi** | Powerful individually, but fragmented to operate together |
| **Apache NiFi** | Strong flow tooling, but heavy to run and hard to adapt for operator-friendly recipe/version workflows |
| **Airbyte** | Great for EL, weak for custom process/replay control |
| **n8n** | Good UX, weak for high-volume item-level provenance |
| **Airflow/Dagster** | Developer-centric orchestration, not operator-first runtime control |

### Hermes Fills the Gap

```
Existing Data Platforms

 Kafka     DB      NiFi     FTP/SFTP     REST APIs
   │        │        │          │             │
   └────────┴────────┴──────────┴─────────────┘
                         │
                    ★ Hermes
      (recipe/versioning, pipeline assembly, provenance,
             operator UI, replay, runtime coordination)
```

---

## Key Features

### 🔍 Job-Level Tracking
Every data item (Job) is individually tracked through the entire pipeline. Know exactly what happened to each file, API response, or database record — when it was collected, how it was processed, and where it was delivered.

### 🎛️ Recipe Management for Non-Developers
Operators configure collection settings, process parameters, and export options through a **visual web UI**. Recipes are version-controlled with full diff/compare history.

### ♻️ First-Class Reprocessing
Failed items can be reprocessed from any stage, with the original or updated recipe. Bulk reprocess hundreds of items with one click. No other platform does this well.

### 🔗 Existing Platform Connectors
Hermes is designed to orchestrate existing Kafka, DB, NiFi, FTP/SFTP, file, and API systems rather than replace them. Connectors normalize operational concerns such as preview, recipe binding, provenance, replay, and failure visibility.

### 🔌 Language-Agnostic Processing
Process steps can call containers or plugins over **gRPC** — Python, C#, R, Java, or any other language — while Hermes keeps execution history and recipe snapshots consistent.

### 🔗 NiFi-Friendly
Existing NiFi flows can continue running. Hermes adds orchestration, recipe/version control, job tracking, and reprocessing around them.

### 📊 Visual Pipeline Designer
Drag-and-drop pipeline assembly inspired by n8n. Click any stage to configure its Recipe with auto-generated forms (sliders, dropdowns, toggles).

### 🛡️ Integrity-Oriented Runtime
Hermes is being hardened around checkpointing, deduplication, retry/DLQ behavior, snapshot correctness, and replay semantics so operators can trust what ran and what should run again.

### 🌐 Distributed Clustering
The long-term direction includes multi-worker coordination, failover, and centralized logs, but single-node runtime integrity comes first.

---

## Quick Start

```bash
# Clone
git clone https://github.com/jinmma12/hermes-stream.git
cd hermes-stream

# Copy environment config
cp .env.example .env

# Run with Docker Compose
docker compose up -d

# Open Web UI
open http://localhost:3000

# API docs
open http://localhost:8000/docs
```

## Current Direction

- `.NET` is the runtime source of truth for collect/process/export execution
- Python is the management/query API layer and migration/reference layer
- React is the operator console for recipes, pipelines, monitoring, and replay
- Hermes is positioned as an orchestrator over existing data platforms, not a replacement for Kafka, NiFi, or your databases

## Database

Hermes should support:

- PostgreSQL
- Microsoft SQL Server

Recommended schema ownership:

- PostgreSQL: `hermes.<table>`
- SQL Server: `hermes.<table>`

The Docker database is optional. Users who already run PostgreSQL or SQL Server
should be able to connect Hermes directly to an existing instance by
configuration.

Bootstrap assets:

- `database/postgresql/init_query.sql`
- `database/sqlserver/init_query.sql`

Prototype operator flow for existing SQL Server installs:

1. Set `Database__Provider=sqlserver`
2. Set `Database__Schema=hermes` or your preferred schema name
3. Set `Database__ConnectionStrings__SqlServer` to the existing database
4. Fetch bootstrap SQL from `GET /api/v1/system/database/bootstrap-script?provider=sqlserver&schema=<schema>`
5. Apply the script before Hermes-owned tables and runtime state are enabled

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     HERMES WEB UI (React)                     │
│  Pipeline Designer │ Recipe Editor │ Monitor │ Job Explorer   │
└────────────────────────────┬─────────────────────────────────┘
                             │ REST API + WebSocket
┌────────────────────────────▼─────────────────────────────────┐
│            HERMES CONTROL PLANE (Python API)                 │
│  CRUD │ Recipe History │ Query APIs │ Health │ WebSocket     │
└────────────────────────────┬─────────────────────────────────┘
                             │ gRPC / commands / status
┌────────────────────────────▼─────────────────────────────────┐
│                 HERMES RUNTIME (.NET Engine)                 │
│                                                               │
│  Monitoring ──→ Orchestration ──→ Process / Export Runtime   │
│  Checkpoints │ Dedup │ Snapshot │ Provenance │ Replay        │
└────────────────────────────┬─────────────────────────────────┘
                             │
         ┌───────────────────┼──────────────────────────────┐
         ▼                   ▼                              ▼
   Kafka / MQ         DB / File / Object Store        NiFi / APIs / FTP
```

Hermes is not trying to replace Kafka, NiFi, or your databases.
It is the orchestration layer that makes those systems easier to connect,
configure, track, and replay as one operator-facing runtime.

---

## Core Concepts

```
Job          "What to collect" — a tracking unit with its own Recipe
               e.g., Order Sync, Log Aggregation, Report Generation

Target       "Where to collect from" — sources within a Job
               e.g., Server A, Region US-East, Source DB-2

Recipe       Processing configuration — versioned, diffable
               e.g., { threshold: 3.5, method: "z-score" }

Pipeline     Processing flow — ordered Stages
               COLLECT → PROCESS → EXPORT

Stage        Individual processing step within a Pipeline

Message      Data unit flowing between Stages
               content (on disk) + metadata (key-value)

TraceEvent   Processing history — provenance for every Message
               CREATED → COLLECTED → ANALYZED → SENT
```

---

## How It Works

```
1. Operator creates a Job via Web UI
   → Selects source type (File/FTP/API/DB/Kafka)
   → Configures Target paths and patterns
   → Sets Recipe parameters (threshold, algorithm, etc.)

2. Pipeline activates and starts monitoring
   → File appears / API changes / Kafka message arrives
   → Hermes creates a Job entry and begins processing

3. Data flows through Stages
   COLLECT  → gather data from Kafka/DB/NiFi/FTP/API/file sources
   PROCESS  → transform/analyze/enrich via plugin or runtime step
   EXPORT   → deliver to destinations such as DB/Kafka/file/S3/webhook

4. Everything is tracked
   → Every Stage records a TraceEvent
   → Recipe snapshot preserved at execution time
   → Full history available in Job Explorer

5. Failures? Just reprocess.
   → Click "Reprocess" on any failed Job
   → Choose: same Recipe or updated Recipe
   → Start from any Stage (skip already-succeeded Stages)
```

---

## Documentation

| Document | Description |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full architecture specification |
| [FTP_SFTP_COLLECTOR_CONFIG_SPEC.md](docs/FTP_SFTP_COLLECTOR_CONFIG_SPEC.md) | FTP/SFTP settings vs recipe vs runtime policy contract |
| [V2_ARCHITECTURE.md](docs/V2_ARCHITECTURE.md) | Distributed system, resilience patterns |
| [DOTNET_SOLUTION_DESIGN.md](docs/DOTNET_SOLUTION_DESIGN.md) | C# project structure (Clean Architecture) |
| [DOMAIN_INTERFACES.md](docs/DOMAIN_INTERFACES.md) | Service interfaces and domain model |
| [DATA_COLLECTION_DESIGN.md](docs/DATA_COLLECTION_DESIGN.md) | Collection strategies and data formats |
| [MESSAGE_AND_TRACE.md](docs/MESSAGE_AND_TRACE.md) | Message flow and provenance design |
| [NIFI_INTEGRATION.md](docs/NIFI_INTEGRATION.md) | NiFi integration modes |
| [CLUSTER_DESIGN.md](docs/CLUSTER_DESIGN.md) | Distributed cluster and log viewer |
| [TEST_STRATEGY.md](docs/TEST_STRATEGY.md) | Testing approach (550+ scenarios) |
| [DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md) | TDD, CI/CD, PR process |
| [ROADMAP.md](ROADMAP.md) | Phase 0-4 roadmap |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Core** | .NET 8 / ASP.NET Core |
| **Database** | PostgreSQL 15 (JSONB) |
| **ORM** | Entity Framework Core 8 |
| **Messaging** | Kafka (Confluent.Kafka) |
| **Plugin Protocol** | gRPC (protobuf) |
| **Resilience** | Polly (.NET resilience library) |
| **Web UI** | React 18 + TypeScript + Vite |
| **Visual Editor** | React Flow (@xyflow/react) |
| **Forms** | react-jsonschema-form (@rjsf) |
| **Styling** | Tailwind CSS |
| **Metrics** | Prometheus (prometheus-net) |
| **Logging** | Serilog |
| **Deployment** | Docker Compose / Kubernetes |

---

## Project Status

**Phase 0: Design** — Complete ✅

All architecture, design documents, gRPC protocols, domain interfaces, and test strategies are finalized. Python prototype with 550+ test scenarios validates the core concepts.

**Phase 1: MVP** — Starting

.NET implementation beginning. See [ROADMAP.md](ROADMAP.md) for full timeline.

---

## Contributing

We welcome contributions! See [DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md) for:
- Test-driven development process
- PR checklist
- Code standards
- CI/CD pipeline

---

## License

[Apache License 2.0](LICENSE)

---

<p align="center">
  <sub>Built with ❤️ for data engineers who deserve better tools.</sub>
</p>
