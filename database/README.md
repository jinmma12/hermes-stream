# Hermes Database Assets

## Goal

Hermes V2 should support both:

- PostgreSQL
- Microsoft SQL Server

## Schema Namespace

Use a dedicated Hermes schema instead of polluting the default namespace.

- PostgreSQL: `hermes.<table>`
- SQL Server: `hermes.<table>`

Do not use `dbo` for Hermes-owned tables unless a user explicitly overrides it.

## Canonical Rule

Whenever table structure, indexes, constraints, or enum/value-domain behavior
changes, the following assets must be updated together:

1. application models
2. migrations
3. `database/postgresql/init_query.sql`
4. `database/sqlserver/init_query.sql`
5. relevant setup docs and tests

## Existing DB Users

Users who already run PostgreSQL or SQL Server should be able to:

- skip the Docker DB container entirely
- point Hermes at an existing database server
- run the init query manually
- follow incremental migration scripts later without losing track

## Assets

- `postgresql/init_query.sql`: canonical PostgreSQL bootstrap
- `sqlserver/init_query.sql`: SQL Server bootstrap and schema ownership setup
