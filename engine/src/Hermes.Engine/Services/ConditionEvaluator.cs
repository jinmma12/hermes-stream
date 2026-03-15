using System.Security.Cryptography;
using System.Text;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;

namespace Hermes.Engine.Services;

public class ConditionEvaluator : IConditionEvaluator
{
    public bool Evaluate(MonitorEvent monitorEvent, PipelineInstance pipeline)
    {
        // Accept all known event types
        return true;
    }

    public string GenerateDedupKey(MonitorEvent monitorEvent)
    {
        var basis = monitorEvent.EventType switch
        {
            "FILE" => monitorEvent.Metadata.GetValueOrDefault("path")?.ToString() ?? monitorEvent.Key,
            "API_RESPONSE" => monitorEvent.Metadata.GetValueOrDefault("content_hash")?.ToString() ?? monitorEvent.Key,
            "DB_CHANGE" => monitorEvent.Key,
            _ => monitorEvent.Key
        };

        var content = $"{monitorEvent.EventType}:{basis}";
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(content));
        var digest = Convert.ToHexString(hash)[..32].ToLowerInvariant();
        return $"{monitorEvent.EventType}:{digest}";
    }
}
