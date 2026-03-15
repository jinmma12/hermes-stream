# Hermes Build And Test

## .NET Build Smoke

Build smoke is the shallowest safety check for the new .NET path.

It answers:

- does restore work?
- does the solution compile?
- do the minimum public API endpoints still respond?

It does not answer:

- does the full pipeline runtime work?
- is Python parity complete?
- does end-to-end data processing succeed?

## Local Commands

```bash
dotnet build engine/Hermes.sln
dotnet test engine/tests/Hermes.Api.Tests/Hermes.Api.Tests.csproj
```

## Current Contract Coverage

- `/`
- `/health/live`
- `/health/ready`
- `/api/v1/system/info`
- `/api/v1/definitions/{kind}`
- `/api/v1/pipelines`
- `/api/v1/pipelines/{id}`
- `/api/v1/jobs`

## Next Test Targets

1. `definitions/{kind}/{id}`
2. `pipelines/{id}/stages`
3. `jobs/{id}`
4. SignalR or WebSocket event streaming
5. Python-to-.NET parity scenarios for migrated routes
