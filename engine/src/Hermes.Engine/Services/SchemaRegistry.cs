using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;

namespace Hermes.Engine.Services;

/// <summary>
/// Schema Registry for tracking, versioning, and drift detection.
/// Inspired by Confluent Schema Registry and NiFi's Record-based schema management.
///
/// Key capabilities:
/// - Register schemas (JSON Schema format) with versioning
/// - Detect schema drift (field additions, removals, type changes)
/// - Compatibility checking (forward, backward, full)
/// </summary>
public interface ISchemaRegistry
{
    /// <summary>Register or update a schema. Returns version number.</summary>
    Task<SchemaVersion> RegisterAsync(string schemaName, string schemaJson, CancellationToken ct = default);

    /// <summary>Get the latest version of a schema.</summary>
    Task<SchemaVersion?> GetLatestAsync(string schemaName, CancellationToken ct = default);

    /// <summary>Get a specific version of a schema.</summary>
    Task<SchemaVersion?> GetVersionAsync(string schemaName, int version, CancellationToken ct = default);

    /// <summary>List all registered schema names.</summary>
    List<string> ListSchemas();

    /// <summary>Detect drift between two schema versions.</summary>
    SchemaDrift DetectDrift(string oldSchemaJson, string newSchemaJson);

    /// <summary>Check compatibility between schemas.</summary>
    CompatibilityResult CheckCompatibility(string existingSchema, string newSchema, CompatibilityMode mode);

    /// <summary>Infer a JSON schema from sample data.</summary>
    string InferSchema(string sampleDataJson);
}

public record SchemaVersion(
    string SchemaName,
    int Version,
    string SchemaJson,
    string SchemaHash,
    DateTimeOffset RegisteredAt);

public record SchemaDrift(
    List<string> AddedFields,
    List<string> RemovedFields,
    List<SchemaFieldChange> ChangedFields,
    bool HasBreakingChanges);

public record SchemaFieldChange(
    string FieldPath,
    string OldType,
    string NewType,
    bool IsBreaking);

public enum CompatibilityMode { Forward, Backward, Full, None }

public record CompatibilityResult(bool IsCompatible, List<string> Issues);

public class SchemaRegistry : ISchemaRegistry
{
    private readonly Dictionary<string, List<SchemaVersion>> _schemas = new();
    private readonly ILogger<SchemaRegistry> _logger;

    public SchemaRegistry(ILogger<SchemaRegistry> logger) => _logger = logger;

    public Task<SchemaVersion> RegisterAsync(string schemaName, string schemaJson, CancellationToken ct = default)
    {
        var hash = ComputeHash(schemaJson);

        if (!_schemas.TryGetValue(schemaName, out var versions))
        {
            versions = new List<SchemaVersion>();
            _schemas[schemaName] = versions;
        }

        // Check if schema is unchanged
        var latest = versions.LastOrDefault();
        if (latest != null && latest.SchemaHash == hash)
        {
            _logger.LogDebug("Schema {Name} unchanged (v{Version})", schemaName, latest.Version);
            return Task.FromResult(latest);
        }

        // Detect drift if there's a previous version
        if (latest != null)
        {
            var drift = DetectDrift(latest.SchemaJson, schemaJson);
            if (drift.HasBreakingChanges)
            {
                _logger.LogWarning("BREAKING schema change detected for {Name}: removed={Removed}, changed={Changed}",
                    schemaName, string.Join(", ", drift.RemovedFields),
                    string.Join(", ", drift.ChangedFields.Where(c => c.IsBreaking).Select(c => c.FieldPath)));
            }
            else if (drift.AddedFields.Count > 0 || drift.RemovedFields.Count > 0)
            {
                _logger.LogInformation("Schema drift detected for {Name}: +{Added} -{Removed} fields",
                    schemaName, drift.AddedFields.Count, drift.RemovedFields.Count);
            }
        }

        var version = new SchemaVersion(
            schemaName,
            (latest?.Version ?? 0) + 1,
            schemaJson,
            hash,
            DateTimeOffset.UtcNow);

        versions.Add(version);
        _logger.LogInformation("Schema {Name} registered v{Version}", schemaName, version.Version);
        return Task.FromResult(version);
    }

    public Task<SchemaVersion?> GetLatestAsync(string schemaName, CancellationToken ct = default)
    {
        if (!_schemas.TryGetValue(schemaName, out var versions) || versions.Count == 0)
            return Task.FromResult<SchemaVersion?>(null);
        return Task.FromResult<SchemaVersion?>(versions.Last());
    }

    public Task<SchemaVersion?> GetVersionAsync(string schemaName, int version, CancellationToken ct = default)
    {
        if (!_schemas.TryGetValue(schemaName, out var versions))
            return Task.FromResult<SchemaVersion?>(null);
        return Task.FromResult(versions.FirstOrDefault(v => v.Version == version));
    }

    public List<string> ListSchemas() => _schemas.Keys.ToList();

    public SchemaDrift DetectDrift(string oldSchemaJson, string newSchemaJson)
    {
        var oldFields = ExtractFields(oldSchemaJson);
        var newFields = ExtractFields(newSchemaJson);

        var added = newFields.Keys.Except(oldFields.Keys).ToList();
        var removed = oldFields.Keys.Except(newFields.Keys).ToList();
        var changed = new List<SchemaFieldChange>();

        foreach (var field in oldFields.Keys.Intersect(newFields.Keys))
        {
            if (oldFields[field] != newFields[field])
            {
                var isBreaking = IsBreakingChange(oldFields[field], newFields[field]);
                changed.Add(new SchemaFieldChange(field, oldFields[field], newFields[field], isBreaking));
            }
        }

        var hasBreaking = removed.Count > 0 || changed.Any(c => c.IsBreaking);

        return new SchemaDrift(added, removed, changed, hasBreaking);
    }

    public CompatibilityResult CheckCompatibility(string existingSchema, string newSchema, CompatibilityMode mode)
    {
        var drift = DetectDrift(existingSchema, newSchema);
        var issues = new List<string>();

        switch (mode)
        {
            case CompatibilityMode.Backward:
                // New schema can read data written by old schema
                // Breaking if: fields removed from new, type narrowing
                foreach (var removed in drift.RemovedFields)
                    issues.Add($"Field '{removed}' removed — readers expecting it will break");
                foreach (var change in drift.ChangedFields.Where(c => c.IsBreaking))
                    issues.Add($"Field '{change.FieldPath}' type changed: {change.OldType} → {change.NewType}");
                break;

            case CompatibilityMode.Forward:
                // Old schema can read data written by new schema
                // Breaking if: required fields added in new
                foreach (var added in drift.AddedFields)
                    issues.Add($"New field '{added}' — old readers won't understand it");
                break;

            case CompatibilityMode.Full:
                // Both directions
                var backward = CheckCompatibility(existingSchema, newSchema, CompatibilityMode.Backward);
                var forward = CheckCompatibility(existingSchema, newSchema, CompatibilityMode.Forward);
                issues.AddRange(backward.Issues);
                issues.AddRange(forward.Issues);
                break;

            case CompatibilityMode.None:
                break;
        }

        return new CompatibilityResult(issues.Count == 0, issues);
    }

    public string InferSchema(string sampleDataJson)
    {
        try
        {
            var doc = JsonDocument.Parse(sampleDataJson);
            var root = doc.RootElement;

            if (root.ValueKind == JsonValueKind.Array && root.GetArrayLength() > 0)
            {
                // Infer from first element of array
                return InferObjectSchema(root[0]);
            }
            if (root.ValueKind == JsonValueKind.Object)
            {
                return InferObjectSchema(root);
            }
        }
        catch { }

        return "{}";
    }

    // ── Private helpers ──

    private static Dictionary<string, string> ExtractFields(string schemaJson)
    {
        var fields = new Dictionary<string, string>();
        try
        {
            var doc = JsonDocument.Parse(schemaJson);
            if (doc.RootElement.TryGetProperty("properties", out var props))
            {
                foreach (var prop in props.EnumerateObject())
                {
                    var type = prop.Value.TryGetProperty("type", out var t) ? t.GetString() ?? "unknown" : "unknown";
                    fields[prop.Name] = type;
                }
            }
        }
        catch { }
        return fields;
    }

    private static bool IsBreakingChange(string oldType, string newType)
    {
        // Widening is safe (int→number, string→any), narrowing is breaking
        var wideningSafe = new HashSet<(string from, string to)>
        {
            ("integer", "number"),
            ("integer", "string"),
            ("number", "string"),
        };
        return !wideningSafe.Contains((oldType, newType));
    }

    private static string InferObjectSchema(JsonElement element)
    {
        var properties = new Dictionary<string, object>();
        var required = new List<string>();

        foreach (var prop in element.EnumerateObject())
        {
            var type = prop.Value.ValueKind switch
            {
                JsonValueKind.String => "string",
                JsonValueKind.Number => prop.Value.TryGetInt64(out _) ? "integer" : "number",
                JsonValueKind.True or JsonValueKind.False => "boolean",
                JsonValueKind.Array => "array",
                JsonValueKind.Object => "object",
                JsonValueKind.Null => "null",
                _ => "string"
            };
            properties[prop.Name] = new { type };
            if (prop.Value.ValueKind != JsonValueKind.Null)
                required.Add(prop.Name);
        }

        return JsonSerializer.Serialize(new
        {
            type = "object",
            properties,
            required
        }, new JsonSerializerOptions { WriteIndented = false });
    }

    private static string ComputeHash(string content)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(content));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}
