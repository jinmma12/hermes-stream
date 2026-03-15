using System.Text.Json;
using Microsoft.Extensions.Logging;
using Hermes.Engine.Domain;

namespace Hermes.Engine.Services.Monitors;

/// <summary>
/// Change Data Capture monitor using polling pattern.
/// Tracks new/changed rows via a cursor column (timestamp or sequence).
/// Inspired by: Debezium polling mode, Airbyte incremental sync, NiFi QueryDatabaseTable.
/// </summary>
public class CdcMonitor : BaseMonitor
{
    private readonly string _connectionString;
    private readonly string _tableName;
    private readonly string _cursorColumn;
    private readonly string _query;
    private string? _lastCursorValue;
    private readonly ILogger? _logger;

    public CdcMonitor(string connectionString, string tableName, string cursorColumn, string? customQuery = null, ILogger? logger = null)
    {
        _connectionString = connectionString;
        _tableName = tableName;
        _cursorColumn = cursorColumn;
        _query = customQuery ?? $"SELECT * FROM {tableName} WHERE {cursorColumn} > @cursor ORDER BY {cursorColumn} LIMIT 100";
        _logger = logger;
    }

    public override async Task<List<MonitorEvent>> PollAsync(CancellationToken ct = default)
    {
        var events = new List<MonitorEvent>();

        try
        {
            // Use Npgsql directly for DB polling
            using var conn = new Npgsql.NpgsqlConnection(_connectionString);
            await conn.OpenAsync(ct);

            using var cmd = conn.CreateCommand();
            cmd.CommandText = _query;
            cmd.Parameters.AddWithValue("cursor", _lastCursorValue ?? "1970-01-01T00:00:00Z");

            using var reader = await cmd.ExecuteReaderAsync(ct);
            while (await reader.ReadAsync(ct))
            {
                var row = new Dictionary<string, object>();
                for (int i = 0; i < reader.FieldCount; i++)
                {
                    row[reader.GetName(i)] = reader.IsDBNull(i) ? "null" : reader.GetValue(i);
                }

                var cursorValue = reader[_cursorColumn]?.ToString() ?? "";
                _lastCursorValue = cursorValue;

                events.Add(new MonitorEvent(
                    EventType: "DB_CHANGE",
                    Key: $"{_tableName}:{cursorValue}",
                    Metadata: new Dictionary<string, object>
                    {
                        ["table"] = _tableName,
                        ["cursor_column"] = _cursorColumn,
                        ["cursor_value"] = cursorValue,
                        ["row_data"] = JsonSerializer.Serialize(row)
                    },
                    DetectedAt: DateTimeOffset.UtcNow
                ));
            }

            if (events.Count > 0)
                _logger?.LogInformation("CDC: {Count} changes detected in {Table} (cursor > {Cursor})",
                    events.Count, _tableName, _lastCursorValue);
        }
        catch (Exception ex)
        {
            _logger?.LogWarning(ex, "CDC poll failed for {Table}", _tableName);
        }

        return events;
    }

    /// <summary>Get/set the cursor for incremental sync state persistence.</summary>
    public string? Cursor
    {
        get => _lastCursorValue;
        set => _lastCursorValue = value;
    }
}
