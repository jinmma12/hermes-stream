using System.Collections.Concurrent;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Infrastructure.Data;

namespace Hermes.Engine.Services;

/// <summary>
/// Manages incremental sync state per pipeline + source.
/// Persists cursor positions so monitors can resume from where they left off.
/// Inspired by: Airbyte state management, Kafka consumer offsets, Flink savepoints.
/// </summary>
public interface IIncrementalSyncManager
{
    Task<string?> GetCursorAsync(Guid pipelineId, string sourceKey, CancellationToken ct = default);
    Task SaveCursorAsync(Guid pipelineId, string sourceKey, string cursorValue, CancellationToken ct = default);
    Task<Dictionary<string, string>> GetAllCursorsAsync(Guid pipelineId, CancellationToken ct = default);
    Task ResetCursorAsync(Guid pipelineId, string sourceKey, CancellationToken ct = default);
}

public class IncrementalSyncManager : IIncrementalSyncManager
{
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ConcurrentDictionary<string, string> _cache = new();
    private readonly ILogger<IncrementalSyncManager> _logger;

    public IncrementalSyncManager(IServiceScopeFactory scopeFactory, ILogger<IncrementalSyncManager> logger)
    {
        _scopeFactory = scopeFactory;
        _logger = logger;
    }

    public async Task<string?> GetCursorAsync(Guid pipelineId, string sourceKey, CancellationToken ct = default)
    {
        var cacheKey = $"{pipelineId}:{sourceKey}";
        if (_cache.TryGetValue(cacheKey, out var cached))
            return cached;

        // Load from DB (stored as ExecutionEventLog with code SYNC_CURSOR)
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();
        var log = await db.ExecutionEventLogs
            .Where(e => e.EventCode == "SYNC_CURSOR" && e.Message == cacheKey)
            .OrderByDescending(e => e.CreatedAt)
            .FirstOrDefaultAsync(ct);

        if (log?.DetailJson != null)
        {
            var doc = JsonDocument.Parse(log.DetailJson);
            if (doc.RootElement.TryGetProperty("cursor", out var cursor))
            {
                var val = cursor.GetString();
                if (val != null) _cache[cacheKey] = val;
                return val;
            }
        }
        return null;
    }

    public async Task SaveCursorAsync(Guid pipelineId, string sourceKey, string cursorValue, CancellationToken ct = default)
    {
        var cacheKey = $"{pipelineId}:{sourceKey}";
        _cache[cacheKey] = cursorValue;

        // Persist to DB
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();

        // Find any existing execution to attach to (use pipeline's latest)
        var latestExec = await db.WorkItemExecutions
            .Where(e => db.WorkItems.Any(w => w.Id == e.WorkItemId && w.PipelineInstanceId == pipelineId))
            .OrderByDescending(e => e.CreatedAt)
            .FirstOrDefaultAsync(ct);

        if (latestExec != null)
        {
            db.ExecutionEventLogs.Add(new ExecutionEventLog
            {
                ExecutionId = latestExec.Id,
                EventType = EventLevel.Info,
                EventCode = "SYNC_CURSOR",
                Message = cacheKey,
                DetailJson = JsonSerializer.Serialize(new { cursor = cursorValue, saved_at = DateTimeOffset.UtcNow })
            });
            await db.SaveChangesAsync(ct);
        }

        _logger.LogDebug("Sync cursor saved: {Pipeline}:{Source} = {Cursor}", pipelineId, sourceKey, cursorValue);
    }

    public async Task<Dictionary<string, string>> GetAllCursorsAsync(Guid pipelineId, CancellationToken ct = default)
    {
        var prefix = $"{pipelineId}:";
        var result = new Dictionary<string, string>();

        foreach (var kvp in _cache.Where(k => k.Key.StartsWith(prefix)))
        {
            var sourceKey = kvp.Key[prefix.Length..];
            result[sourceKey] = kvp.Value;
        }

        return await Task.FromResult(result);
    }

    public Task ResetCursorAsync(Guid pipelineId, string sourceKey, CancellationToken ct = default)
    {
        var cacheKey = $"{pipelineId}:{sourceKey}";
        _cache.TryRemove(cacheKey, out _);
        _logger.LogInformation("Sync cursor reset: {Pipeline}:{Source}", pipelineId, sourceKey);
        return Task.CompletedTask;
    }
}
