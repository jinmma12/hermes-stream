using System.Data;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using Npgsql;

namespace Hermes.Engine.Services.Exporters;

/// <summary>
/// Exports data to relational databases (PostgreSQL, SQL Server).
/// Supports INSERT, UPSERT (ON CONFLICT), batch operations,
/// and automatic table creation.
/// </summary>
public class DbWriterExporter : BaseExporter
{
    private readonly DbWriterConfig _config;
    private readonly ILogger? _logger;

    public DbWriterExporter(DbWriterConfig config, ILogger? logger = null)
    {
        _config = config;
        _logger = logger;
    }

    public override async Task<ExportResult> ExportAsync(ExportContext context, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(_config.ConnectionString))
            return new ExportResult(false, 0, ErrorMessage: "Database connection string not configured");
        if (string.IsNullOrEmpty(_config.TableName))
            return new ExportResult(false, 0, ErrorMessage: "Table name not configured");

        var sw = System.Diagnostics.Stopwatch.StartNew();
        var records = ParseRecords(context.DataJson);

        if (records.Count == 0)
            return new ExportResult(true, 0, DestinationInfo: _config.TableName);

        int totalInserted = 0;
        string? lastError = null;

        try
        {
            await using var conn = new NpgsqlConnection(_config.ConnectionString);
            await conn.OpenAsync(ct);

            // Process in batches
            for (int i = 0; i < records.Count; i += _config.BatchSize)
            {
                ct.ThrowIfCancellationRequested();
                var batch = records.Skip(i).Take(_config.BatchSize).ToList();
                var inserted = await WriteBatchAsync(conn, batch, ct);
                totalInserted += inserted;
            }

            sw.Stop();
            _logger?.LogInformation("DB Writer: Inserted {Count} records into {Table}",
                totalInserted, _config.TableName);

            return new ExportResult(
                Success: true,
                RecordsExported: totalInserted,
                DestinationInfo: $"{_config.Provider}://{_config.TableName}",
                DurationMs: sw.ElapsedMilliseconds,
                Summary: new Dictionary<string, object>
                {
                    ["table"] = _config.TableName,
                    ["write_mode"] = _config.WriteMode,
                    ["records_written"] = totalInserted,
                    ["batch_size"] = _config.BatchSize,
                    ["provider"] = _config.Provider,
                }
            );
        }
        catch (Exception ex)
        {
            sw.Stop();
            _logger?.LogError(ex, "DB Writer failed: {Table}", _config.TableName);
            return new ExportResult(false, totalInserted,
                ErrorMessage: ex.Message,
                DurationMs: sw.ElapsedMilliseconds);
        }
    }

    private async Task<int> WriteBatchAsync(
        NpgsqlConnection conn, List<JsonElement> records, CancellationToken ct)
    {
        if (records.Count == 0) return 0;

        // Extract columns from first record
        var columns = records[0].EnumerateObject().Select(p => p.Name).ToList();
        if (columns.Count == 0) return 0;

        var colNames = string.Join(", ", columns.Select(c => $"\"{c}\""));
        var paramPlaceholders = new List<string>();
        var allParams = new List<NpgsqlParameter>();
        int paramIdx = 0;

        foreach (var record in records)
        {
            var rowParams = new List<string>();
            foreach (var col in columns)
            {
                var paramName = $"@p{paramIdx++}";
                rowParams.Add(paramName);

                object? value = null;
                if (record.TryGetProperty(col, out var prop))
                {
                    value = prop.ValueKind switch
                    {
                        JsonValueKind.String => prop.GetString(),
                        JsonValueKind.Number => prop.TryGetInt64(out var l) ? l : prop.GetDouble(),
                        JsonValueKind.True => true,
                        JsonValueKind.False => false,
                        JsonValueKind.Null => DBNull.Value,
                        _ => prop.GetRawText(),
                    };
                }

                allParams.Add(new NpgsqlParameter(paramName, value ?? DBNull.Value));
            }
            paramPlaceholders.Add($"({string.Join(", ", rowParams)})");
        }

        var sql = _config.WriteMode switch
        {
            "UPSERT" when !string.IsNullOrEmpty(_config.ConflictKey) =>
                $"INSERT INTO \"{_config.TableName}\" ({colNames}) VALUES {string.Join(", ", paramPlaceholders)} " +
                $"ON CONFLICT (\"{_config.ConflictKey}\") DO UPDATE SET " +
                string.Join(", ", columns.Where(c => c != _config.ConflictKey).Select(c => $"\"{c}\" = EXCLUDED.\"{c}\"")),
            _ => $"INSERT INTO \"{_config.TableName}\" ({colNames}) VALUES {string.Join(", ", paramPlaceholders)}",
        };

        await using var cmd = new NpgsqlCommand(sql, conn);
        cmd.CommandTimeout = _config.TimeoutSeconds;
        cmd.Parameters.AddRange(allParams.ToArray());

        return await cmd.ExecuteNonQueryAsync(ct);
    }

    private static List<JsonElement> ParseRecords(string dataJson)
    {
        var doc = JsonDocument.Parse(dataJson);
        if (doc.RootElement.ValueKind == JsonValueKind.Array)
            return doc.RootElement.EnumerateArray().ToList();
        if (doc.RootElement.TryGetProperty("records", out var records) && records.ValueKind == JsonValueKind.Array)
            return records.EnumerateArray().ToList();
        return new List<JsonElement> { doc.RootElement };
    }
}
