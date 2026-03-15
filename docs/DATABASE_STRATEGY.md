# Hermes Database Strategy

## Supported Providers

Hermes V2 should support:

- PostgreSQL
- Microsoft SQL Server

The provider must be selectable by configuration, not by branch or fork.

## Schema Ownership

Hermes should own a dedicated schema:

- PostgreSQL: `hermes`
- SQL Server: `hermes`

This avoids collisions with user tables and makes it obvious what Hermes owns.

Recommended names:

- `hermes.collector_definitions`
- `hermes.pipeline_instances`
- `hermes.work_items`

Avoid `dbo.*` as the default Hermes namespace.

## Initialization Policy

Every schema change must update:

1. runtime models
2. migration assets
3. provider-specific init queries
4. tests and docs

Canonical init query locations:

- [database/postgresql/init_query.sql](/C:/Users/acood/hermes-stream/database/postgresql/init_query.sql)
- [database/sqlserver/init_query.sql](/C:/Users/acood/hermes-stream/database/sqlserver/init_query.sql)

## Existing Database Users

Hermes must support users who already have a database installed.

That means:

- Docker database service is optional
- connection strings can point to an existing PostgreSQL or SQL Server instance
- setup docs must work for both "start a container" and "connect to my existing DB"

## Configuration Shape

Suggested config:

```json
{
  "Database": {
    "Provider": "postgres",
    "Schema": "hermes",
    "UseDocker": false,
    "ConnectionStrings": {
      "Postgres": "Host=localhost;Database=hermes_db;Username=hermes;Password=hermes",
      "SqlServer": "Server=localhost,1433;Database=hermes_db;User Id=sa;Password=Your_password123;TrustServerCertificate=True"
    }
  }
}
```

## Test Matrix

At minimum, Hermes should eventually validate:

1. PostgreSQL in Docker
2. PostgreSQL existing instance
3. SQL Server existing instance
4. schema bootstrap scripts apply cleanly
5. migrations upgrade from previous schema versions

## Immediate Follow-Up

1. add provider-aware EF Core or query infrastructure
2. make schema name configurable in the data layer
3. port PostgreSQL schema into `.NET` migrations
4. add SQL Server migration parity
