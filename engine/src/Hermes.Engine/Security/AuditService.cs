using System.Collections.Concurrent;
using Microsoft.Extensions.Logging;

namespace Hermes.Engine.Security;

public interface IAuditService
{
    Task LogAsync(string userId, string userName, string action, string resource, string? detail = null, string? ipAddress = null);
    Task<List<AuditEntry>> GetRecentAsync(int limit = 100, string? userId = null, string? action = null);
}

public class AuditService : IAuditService
{
    private readonly ConcurrentQueue<AuditEntry> _entries = new();
    private readonly ILogger<AuditService> _logger;
    private const int MaxEntries = 10000;

    public AuditService(ILogger<AuditService> logger) => _logger = logger;

    public Task LogAsync(string userId, string userName, string action, string resource, string? detail = null, string? ipAddress = null)
    {
        var entry = new AuditEntry
        {
            UserId = userId,
            UserName = userName,
            Action = action,
            Resource = resource,
            Detail = detail,
            IpAddress = ipAddress
        };
        _entries.Enqueue(entry);

        // Trim if over limit
        while (_entries.Count > MaxEntries)
            _entries.TryDequeue(out _);

        _logger.LogInformation("AUDIT: {User} {Action} {Resource}", userName, action, resource);
        return Task.CompletedTask;
    }

    public Task<List<AuditEntry>> GetRecentAsync(int limit = 100, string? userId = null, string? action = null)
    {
        var query = _entries.AsEnumerable().Reverse();
        if (userId != null) query = query.Where(e => e.UserId == userId);
        if (action != null) query = query.Where(e => e.Action == action);
        return Task.FromResult(query.Take(limit).ToList());
    }
}
