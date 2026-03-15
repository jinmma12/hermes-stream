using System.Text.Json;
using Microsoft.Extensions.Logging;

namespace Hermes.Engine.Services;

/// <summary>
/// Preview data from a source before activating a pipeline.
/// Shows operators sample rows, inferred schema, and estimated volume.
/// Inspired by: Airbyte connection test, NiFi provenance viewer, dbt preview.
/// </summary>
public interface IDataPreviewService
{
    Task<DataPreview> PreviewFileAsync(string filePath, int maxRows = 10, CancellationToken ct = default);
    Task<DataPreview> PreviewJsonAsync(string jsonData, int maxRows = 10);
}

public record DataPreview(
    bool Success,
    string? ErrorMessage,
    List<Dictionary<string, object?>> SampleRows,
    List<ColumnInfo> Columns,
    int TotalRowsEstimate,
    string? InferredSchemaJson);

public record ColumnInfo(string Name, string InferredType, int NonNullCount, int SampleSize);

public class DataPreviewService : IDataPreviewService
{
    private readonly ISchemaRegistry _schemaRegistry;
    private readonly ILogger<DataPreviewService> _logger;

    public DataPreviewService(ISchemaRegistry schemaRegistry, ILogger<DataPreviewService> logger)
    {
        _schemaRegistry = schemaRegistry;
        _logger = logger;
    }

    public async Task<DataPreview> PreviewFileAsync(string filePath, int maxRows = 10, CancellationToken ct = default)
    {
        try
        {
            if (!File.Exists(filePath))
                return new DataPreview(false, $"File not found: {filePath}", new(), new(), 0, null);

            var ext = Path.GetExtension(filePath).ToLowerInvariant();
            return ext switch
            {
                ".csv" => await PreviewCsvAsync(filePath, maxRows, ct),
                ".json" => PreviewJsonAsync(await File.ReadAllTextAsync(filePath, ct), maxRows).Result,
                _ => new DataPreview(false, $"Unsupported file type: {ext}", new(), new(), 0, null)
            };
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Preview failed for {Path}", filePath);
            return new DataPreview(false, ex.Message, new(), new(), 0, null);
        }
    }

    public Task<DataPreview> PreviewJsonAsync(string jsonData, int maxRows = 10)
    {
        try
        {
            var doc = JsonDocument.Parse(jsonData);
            var root = doc.RootElement;

            var rows = new List<Dictionary<string, object?>>();
            var elements = root.ValueKind == JsonValueKind.Array
                ? root.EnumerateArray().Take(maxRows)
                : new[] { root }.AsEnumerable();

            foreach (var el in elements)
            {
                if (el.ValueKind != JsonValueKind.Object) continue;
                var row = new Dictionary<string, object?>();
                foreach (var prop in el.EnumerateObject())
                    row[prop.Name] = GetJsonValue(prop.Value);
                rows.Add(row);
            }

            var totalEstimate = root.ValueKind == JsonValueKind.Array ? root.GetArrayLength() : 1;
            var columns = InferColumns(rows);
            var schema = _schemaRegistry.InferSchema(jsonData);

            return Task.FromResult(new DataPreview(true, null, rows, columns, totalEstimate, schema));
        }
        catch (Exception ex)
        {
            return Task.FromResult(new DataPreview(false, ex.Message, new(), new(), 0, null));
        }
    }

    private async Task<DataPreview> PreviewCsvAsync(string filePath, int maxRows, CancellationToken ct)
    {
        var lines = new List<string>();
        using (var reader = new StreamReader(filePath))
        {
            string? line;
            while ((line = await reader.ReadLineAsync(ct)) != null && lines.Count <= maxRows)
                lines.Add(line);
        }

        if (lines.Count < 2)
            return new DataPreview(true, null, new(), new(), 0, null);

        var headers = lines[0].Split(',').Select(h => h.Trim().Trim('"')).ToArray();
        var rows = new List<Dictionary<string, object?>>();

        for (int i = 1; i < lines.Count; i++)
        {
            var values = lines[i].Split(',');
            var row = new Dictionary<string, object?>();
            for (int j = 0; j < headers.Length && j < values.Length; j++)
            {
                var val = values[j].Trim().Trim('"');
                row[headers[j]] = ParseValue(val);
            }
            rows.Add(row);
        }

        // Estimate total rows (file size / avg line size)
        var fileSize = new FileInfo(filePath).Length;
        var avgLineSize = lines.Sum(l => l.Length + 1) / lines.Count;
        var totalEstimate = (int)(fileSize / Math.Max(1, avgLineSize));

        var columns = InferColumns(rows);
        var schemaJson = _schemaRegistry.InferSchema(JsonSerializer.Serialize(rows));

        return new DataPreview(true, null, rows, columns, totalEstimate, schemaJson);
    }

    private static List<ColumnInfo> InferColumns(List<Dictionary<string, object?>> rows)
    {
        if (rows.Count == 0) return new();

        var allKeys = rows.SelectMany(r => r.Keys).Distinct().ToList();
        return allKeys.Select(key =>
        {
            var values = rows.Select(r => r.GetValueOrDefault(key)).ToList();
            var nonNull = values.Count(v => v != null);
            var types = values.Where(v => v != null).Select(v => v switch
            {
                int or long => "integer",
                float or double or decimal => "number",
                bool => "boolean",
                _ => "string"
            }).Distinct().ToList();

            var inferredType = types.Count == 1 ? types[0] : types.Count == 0 ? "null" : "string";
            return new ColumnInfo(key, inferredType, nonNull, rows.Count);
        }).ToList();
    }

    private static object? ParseValue(string val)
    {
        if (string.IsNullOrEmpty(val) || val == "null") return null;
        if (int.TryParse(val, out var i)) return i;
        if (double.TryParse(val, out var d)) return d;
        if (bool.TryParse(val, out var b)) return b;
        return val;
    }

    private static object? GetJsonValue(JsonElement el) => el.ValueKind switch
    {
        JsonValueKind.String => el.GetString(),
        JsonValueKind.Number => el.TryGetInt64(out var l) ? l : el.GetDouble(),
        JsonValueKind.True => true,
        JsonValueKind.False => false,
        JsonValueKind.Null => null,
        _ => el.GetRawText()
    };
}
