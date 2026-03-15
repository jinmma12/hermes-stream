using System.Text.Json;
using Microsoft.Extensions.Logging.Abstractions;
using Hermes.Engine.Services;

namespace Hermes.Engine.Tests.Phase2;

/// <summary>
/// Tests for Schema Registry — schema versioning, drift detection, compatibility.
/// References: Confluent Schema Registry, Apache Avro schema evolution,
/// dbt schema tests, Great Expectations.
///
/// Key behaviors:
/// - Schema registration with automatic versioning
/// - Drift detection: added/removed/changed fields
/// - Breaking change detection (type narrowing, field removal)
/// - Compatibility modes: forward, backward, full
/// - Schema inference from sample data
/// </summary>
public class SchemaRegistryTests
{
    private readonly SchemaRegistry _registry = new(NullLogger<SchemaRegistry>.Instance);

    // ── Registration ──

    [Fact]
    public async Task Register_FirstVersion_ReturnsV1()
    {
        var schema = MakeSchema(("id", "integer"), ("name", "string"));
        var version = await _registry.RegisterAsync("sensor-data", schema);

        Assert.Equal("sensor-data", version.SchemaName);
        Assert.Equal(1, version.Version);
        Assert.NotEmpty(version.SchemaHash);
    }

    [Fact]
    public async Task Register_SameSchema_NoNewVersion()
    {
        var schema = MakeSchema(("id", "integer"), ("value", "number"));

        var v1 = await _registry.RegisterAsync("metrics", schema);
        var v2 = await _registry.RegisterAsync("metrics", schema); // Same content

        Assert.Equal(1, v1.Version);
        Assert.Equal(1, v2.Version); // No new version created
        Assert.Equal(v1.SchemaHash, v2.SchemaHash);
    }

    [Fact]
    public async Task Register_ChangedSchema_IncrementsVersion()
    {
        var v1Schema = MakeSchema(("id", "integer"), ("name", "string"));
        var v2Schema = MakeSchema(("id", "integer"), ("name", "string"), ("email", "string"));

        var v1 = await _registry.RegisterAsync("users", v1Schema);
        var v2 = await _registry.RegisterAsync("users", v2Schema);

        Assert.Equal(1, v1.Version);
        Assert.Equal(2, v2.Version);
        Assert.NotEqual(v1.SchemaHash, v2.SchemaHash);
    }

    [Fact]
    public async Task GetLatest_ReturnsNewestVersion()
    {
        await _registry.RegisterAsync("evolving", MakeSchema(("a", "string")));
        await _registry.RegisterAsync("evolving", MakeSchema(("a", "string"), ("b", "integer")));
        await _registry.RegisterAsync("evolving", MakeSchema(("a", "string"), ("b", "integer"), ("c", "boolean")));

        var latest = await _registry.GetLatestAsync("evolving");
        Assert.Equal(3, latest!.Version);
    }

    [Fact]
    public async Task GetVersion_ReturnsSpecificVersion()
    {
        await _registry.RegisterAsync("versioned", MakeSchema(("x", "string")));
        await _registry.RegisterAsync("versioned", MakeSchema(("x", "string"), ("y", "number")));

        var v1 = await _registry.GetVersionAsync("versioned", 1);
        var v2 = await _registry.GetVersionAsync("versioned", 2);

        Assert.NotNull(v1);
        Assert.NotNull(v2);
        Assert.NotEqual(v1!.SchemaJson, v2!.SchemaJson);
    }

    [Fact]
    public async Task GetLatest_NonExistent_ReturnsNull()
    {
        var result = await _registry.GetLatestAsync("does-not-exist");
        Assert.Null(result);
    }

    [Fact]
    public async Task ListSchemas_ReturnsRegisteredNames()
    {
        await _registry.RegisterAsync("schema-a", MakeSchema(("a", "string")));
        await _registry.RegisterAsync("schema-b", MakeSchema(("b", "integer")));

        var names = _registry.ListSchemas();
        Assert.Contains("schema-a", names);
        Assert.Contains("schema-b", names);
    }

    // ── Drift Detection ──

    [Fact]
    public void DetectDrift_AddedFields()
    {
        var old = MakeSchema(("id", "integer"), ("name", "string"));
        var updated = MakeSchema(("id", "integer"), ("name", "string"), ("email", "string"));

        var drift = _registry.DetectDrift(old, updated);

        Assert.Single(drift.AddedFields);
        Assert.Contains("email", drift.AddedFields);
        Assert.Empty(drift.RemovedFields);
        Assert.False(drift.HasBreakingChanges);
    }

    [Fact]
    public void DetectDrift_RemovedFields_IsBreaking()
    {
        var old = MakeSchema(("id", "integer"), ("name", "string"), ("age", "integer"));
        var updated = MakeSchema(("id", "integer"), ("name", "string"));

        var drift = _registry.DetectDrift(old, updated);

        Assert.Single(drift.RemovedFields);
        Assert.Contains("age", drift.RemovedFields);
        Assert.True(drift.HasBreakingChanges);
    }

    [Fact]
    public void DetectDrift_TypeChanged_Breaking()
    {
        var old = MakeSchema(("value", "number"), ("name", "string"));
        var updated = MakeSchema(("value", "string"), ("name", "string")); // number→string: narrowing

        var drift = _registry.DetectDrift(old, updated);

        Assert.Single(drift.ChangedFields);
        Assert.Equal("value", drift.ChangedFields[0].FieldPath);
        Assert.Equal("number", drift.ChangedFields[0].OldType);
        Assert.Equal("string", drift.ChangedFields[0].NewType);
    }

    [Fact]
    public void DetectDrift_TypeWidening_NotBreaking()
    {
        var old = MakeSchema(("count", "integer"));
        var updated = MakeSchema(("count", "number")); // integer→number is widening (safe)

        var drift = _registry.DetectDrift(old, updated);

        Assert.Single(drift.ChangedFields);
        Assert.False(drift.ChangedFields[0].IsBreaking);
        Assert.False(drift.HasBreakingChanges);
    }

    [Fact]
    public void DetectDrift_NoChanges()
    {
        var schema = MakeSchema(("id", "integer"), ("name", "string"));

        var drift = _registry.DetectDrift(schema, schema);

        Assert.Empty(drift.AddedFields);
        Assert.Empty(drift.RemovedFields);
        Assert.Empty(drift.ChangedFields);
        Assert.False(drift.HasBreakingChanges);
    }

    // ── Compatibility ──

    [Fact]
    public void Compatibility_Backward_FieldRemovalBreaks()
    {
        var existing = MakeSchema(("id", "integer"), ("name", "string"), ("value", "number"));
        var newSchema = MakeSchema(("id", "integer"), ("name", "string")); // Removed "value"

        var result = _registry.CheckCompatibility(existing, newSchema, CompatibilityMode.Backward);

        Assert.False(result.IsCompatible);
        Assert.Contains(result.Issues, i => i.Contains("value") && i.Contains("removed"));
    }

    [Fact]
    public void Compatibility_Backward_FieldAddition_OK()
    {
        var existing = MakeSchema(("id", "integer"));
        var newSchema = MakeSchema(("id", "integer"), ("extra", "string"));

        var result = _registry.CheckCompatibility(existing, newSchema, CompatibilityMode.Backward);

        Assert.True(result.IsCompatible);
    }

    [Fact]
    public void Compatibility_Forward_FieldAddition_HasIssue()
    {
        var existing = MakeSchema(("id", "integer"));
        var newSchema = MakeSchema(("id", "integer"), ("extra", "string"));

        var result = _registry.CheckCompatibility(existing, newSchema, CompatibilityMode.Forward);

        Assert.False(result.IsCompatible);
        Assert.Contains(result.Issues, i => i.Contains("extra"));
    }

    [Fact]
    public void Compatibility_None_AlwaysCompatible()
    {
        var existing = MakeSchema(("a", "string"));
        var newSchema = MakeSchema(("completely", "integer"), ("different", "boolean"));

        var result = _registry.CheckCompatibility(existing, newSchema, CompatibilityMode.None);

        Assert.True(result.IsCompatible);
    }

    // ── Schema Inference ──

    [Fact]
    public void InferSchema_FromObject()
    {
        var data = JsonSerializer.Serialize(new { id = 1, name = "sensor-a", value = 23.5, active = true });

        var schema = _registry.InferSchema(data);

        Assert.Contains("\"id\"", schema);
        Assert.Contains("\"name\"", schema);
        Assert.Contains("\"value\"", schema);
        Assert.Contains("\"active\"", schema);
        Assert.Contains("\"integer\"", schema); // id is integer
        Assert.Contains("\"string\"", schema);  // name is string
    }

    [Fact]
    public void InferSchema_FromArray()
    {
        var data = JsonSerializer.Serialize(new[]
        {
            new { timestamp = "2026-03-15", sensor_id = "S001", temperature = 22.5 },
            new { timestamp = "2026-03-15", sensor_id = "S002", temperature = 23.1 },
        });

        var schema = _registry.InferSchema(data);

        Assert.Contains("\"timestamp\"", schema);
        Assert.Contains("\"sensor_id\"", schema);
        Assert.Contains("\"temperature\"", schema);
    }

    [Fact]
    public void InferSchema_EmptyOrInvalid_ReturnsEmptySchema()
    {
        Assert.Equal("{}", _registry.InferSchema("not json"));
        Assert.Equal("{}", _registry.InferSchema(""));
    }

    // ── Realistic Scenario ──

    [Fact]
    public async Task Scenario_SensorDataEvolution()
    {
        // V1: Initial sensor schema
        var v1 = MakeSchema(("sensor_id", "string"), ("temperature", "number"), ("timestamp", "string"));
        await _registry.RegisterAsync("sensor-readings", v1);

        // V2: Added humidity field (non-breaking)
        var v2 = MakeSchema(("sensor_id", "string"), ("temperature", "number"), ("timestamp", "string"), ("humidity", "number"));
        var ver2 = await _registry.RegisterAsync("sensor-readings", v2);
        Assert.Equal(2, ver2.Version);

        // V3: Changed temperature from number to boolean (BREAKING — type narrowing)
        var v3 = MakeSchema(("sensor_id", "string"), ("temperature", "boolean"), ("timestamp", "string"), ("humidity", "number"));
        var ver3 = await _registry.RegisterAsync("sensor-readings", v3);
        Assert.Equal(3, ver3.Version);

        // Verify drift v2→v3 is breaking (number→boolean is narrowing)
        var drift = _registry.DetectDrift(v2, v3);
        Assert.True(drift.HasBreakingChanges);
        Assert.Single(drift.ChangedFields);
        Assert.Equal("temperature", drift.ChangedFields[0].FieldPath);

        // Backward compat check: v3 breaks readers of v2
        var compat = _registry.CheckCompatibility(v2, v3, CompatibilityMode.Backward);
        Assert.False(compat.IsCompatible);
    }

    // ── Helper ──

    private static string MakeSchema(params (string name, string type)[] fields)
    {
        var props = new Dictionary<string, object>();
        foreach (var (name, type) in fields)
            props[name] = new { type };

        return JsonSerializer.Serialize(new
        {
            type = "object",
            properties = props,
            required = fields.Select(f => f.name).ToArray()
        });
    }
}
