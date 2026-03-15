/*
Hermes SQL Server bootstrap.

This file establishes the schema namespace and documents the expected ownership
model for a SQL Server deployment. Full SQL Server schema parity must evolve in
lockstep with the PostgreSQL init query and the application models.
*/

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'hermes')
BEGIN
    EXEC('CREATE SCHEMA hermes AUTHORIZATION dbo;');
END;
GO

/*
Future SQL Server parity work must add:
- tables under hermes.<table>
- indexes
- unique constraints
- foreign keys
- migration history table

Do not add Hermes tables under dbo by default.
*/
