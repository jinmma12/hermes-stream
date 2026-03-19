# Hermes Stream

Lightweight data processing platform with per-job tracking, visual recipe management, and first-class reprocessing.

"The Messenger of Data."

## Tech Stack

- **Web API (Python)**: Python 3.12, FastAPI, SQLAlchemy (async), PostgreSQL 15
- **Core Engine (.NET)**: .NET 8 Worker Service, gRPC, EF Core, Polly, Serilog
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, React Flow (@xyflow/react)
- **Forms**: react-jsonschema-form (@rjsf) for dynamic processor config
- **Infrastructure**: Docker Compose

## CRITICAL RULES

### Core Engine = C# Only
**All core connectors, monitors, and processors MUST be written in C# (.NET 8).**
- Core connectors: FTP/SFTP, Kafka, REST API, File Watcher, Database CDC, DB Writer, S3, Webhook
- Location: `engine/src/Hermes.Engine/Services/Monitors/` and `engine/src/Hermes.Engine/Services/`
- NuGet packages: FluentFTP, SSH.NET, Confluent.Kafka, Polly, etc.
- Tests: xUnit in `engine/tests/`

**Python plugin protocol is ONLY for external/community plugins** (marketplace, user-defined).
- `plugins/` directory = community/user extensions executed as separate processes
- NOT for core functionality — never write core connectors in Python

### Pipeline Categories
| Stage | C# Enum | Frontend Enum | Purpose | Color |
|---|---|---|---|---|
| **Collect** | `StageType.Collect` | `COLLECT` | 데이터 수집 (Source) | Blue |
| **Process** | `StageType.Process` | `PROCESS` | 변환/분석/필터링 | Purple |
| **Export** | `StageType.Export` | `EXPORT` | 목적지 전달 (Sink) | Emerald |

**NEVER use old names**: ~~Algorithm~~→Process, ~~Transfer~~→Export

### Demo Data Consistency
All demo/mock data across pages MUST use the same pipeline names, IDs, and connector codes.
Standard pipeline IDs: see `webapp/src/pages/PipelineListPage.tsx`.

## Architecture Split

| Layer | Language | Responsibility |
|---|---|---|
| **Web API** (`backend/`) | Python/FastAPI | REST API, WebSocket, CRUD, DB access |
| **Core Engine** (`engine/`) | .NET 8 | Monitoring, processing, connectors, NiFi |
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
    hermes/             # Python package
      main.py           # App entrypoint
      engine_client.py  # gRPC client to .NET Engine
      api/              # REST route handlers
      api/schemas/      # Pydantic DTOs
      api/websocket.py  # WebSocket forwarding
      domain/models/    # SQLAlchemy models
      domain/services/  # Web API services + engine stubs
      infrastructure/   # Database session, repositories
    tests/              # pytest tests (API + behavioral specs)
  engine/               # .NET Core Engine (ALL core logic here)
    Hermes.sln          # Solution file
    Dockerfile          # Multi-stage .NET build
    src/Hermes.Engine/  # Worker service project
      Domain/           # Enums, interfaces, entities
      Services/
        Monitors/       # FTP/SFTP, File, API, Kafka, CDC monitors (C#)
        Connectors/     # Airbyte/Singer adapters (external protocol)
        Plugins/        # Plugin registry + executor (for community plugins)
        Nifi/           # Optional NiFi bridge
      Infrastructure/   # EF Core, DB context
      Workers/          # Background hosted services
    tests/              # xUnit tests (core engine tests)
    reference/          # Python reference implementations (read-only spec)
  webapp/               # React frontend (Vite)
  plugins/              # Community/user-defined plugins (Python/Go/etc.)
  protos/               # gRPC proto definitions
  docs/                 # Architecture and design docs
```

## Key Commands

```bash
# Start all services
docker compose up -d

# Backend only (local dev)
cd backend && pip install -e ".[dev]" && uvicorn hermes.main:app --reload

# Engine only (local dev, requires .NET 8 SDK)
cd engine && dotnet run --project src/Hermes.Engine

# Run engine tests
cd engine && dotnet test

# Frontend only (local dev)
cd webapp && npm install && npm run dev

# Build frontend for production
cd webapp && npm run build

# Run backend tests
cd backend && pytest
```

## Requirements

- **Database**: Must support both PostgreSQL and Microsoft SQL Server simultaneously.
  - EF Core provider is selected via `Database:Provider` in appsettings.json (`PostgreSQL` or `SqlServer`)
  - JSONB columns use `jsonb` on PostgreSQL and `nvarchar(max)` on SQL Server
  - All enums are stored as strings (not integers) for both providers
  - Schema creation via `EnsureCreated` must produce identical table structures on both providers

## Core Connectors (C# — engine built-in)

| Type | Connector | NuGet | C# File |
|---|---|---|---|
| Collect | FTP/SFTP | FluentFTP, SSH.NET | `Services/Monitors/FtpSftpMonitor.cs` |
| Collect | File Watcher | System.IO | `Services/Monitors/BaseMonitor.cs` |
| Collect | REST API | HttpClient | `Services/Monitors/BaseMonitor.cs` |
| Collect | Kafka Consumer | Confluent.Kafka | `Services/Monitors/KafkaMonitor.cs` |
| Collect | Database CDC | Npgsql | `Services/Monitors/CdcMonitor.cs` |
| Export | Kafka Producer | Confluent.Kafka | `Services/Exporters/KafkaProducerExporter.cs` |
| Export | DB Writer | EF Core | `Services/Exporters/DbWriterExporter.cs` |
| Export | S3 Upload | AWSSDK.S3 | `Services/Exporters/S3UploadExporter.cs` |
| Export | Webhook | HttpClient | `Services/Exporters/WebhookSenderExporter.cs` |

## Development Operations

### CI Must Stay Green
**GitHub Actions CI가 깨지면 즉시 수정해야 한다. CI가 깨진 상태로 방치하지 않는다.**
- 코드 변경 후 커밋 전에 반드시 빌드 가능 여부를 확인한다
  - Engine: `dotnet build` 성공 확인
  - Frontend: `npx tsc --noEmit` 또는 `npm run build` 성공 확인
  - Backend: `pip install ".[dev]"` + `ruff check .` 성공 확인
- 새 파일을 만들었으면 반드시 `git add`에 포함시킨다 (untracked 파일 누락 = CI 실패의 주범)
- CI가 깨진 것을 발견하면 다른 기능 개발보다 CI 수정을 우선한다
- 커밋 메시지에 "195 E2E tests" 같은 내용이 있으면서 실제로는 테스트가 CI에서 실패하면 안 된다

### Pre-commit Checklist
새로운 커밋을 만들기 전에 반드시 확인:
1. `git status`로 untracked 파일 중 커밋해야 할 것이 있는지 확인
2. 참조하는 타입/클래스가 모두 해당 커밋에 포함되는지 확인
3. 구 명칭(Algorithm, Transfer) 잔존 여부 확인
4. TypeScript strict mode 에러 확인 (`npx tsc --noEmit`)

## Engine Reference Files

The `engine/reference/` directory contains the original Python implementations
of engine-layer services. These serve as the **read-only specification** for the .NET
implementation. The Python test suite in `backend/tests/` acts as a behavioral
specification — .NET xUnit tests should replicate the same scenarios.
