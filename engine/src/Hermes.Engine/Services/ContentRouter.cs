using System.Text.Json;
using Microsoft.Extensions.Logging;

namespace Hermes.Engine.Services;

/// <summary>
/// Content-Based Router for conditional pipeline branching.
/// Evaluates routing rules against step output to determine which downstream
/// steps should execute. Enables DAG-style pipeline topology beyond linear chains.
///
/// Inspired by: NiFi RouteOnAttribute, Apache Camel Content-Based Router,
/// MassTransit message routing.
///
/// Rule format (JSON in PipelineStep config):
/// {
///   "routes": [
///     { "condition": "$.severity == 'HIGH'", "target_step": 3 },
///     { "condition": "$.record_count > 1000", "target_step": 4 },
///     { "default": true, "target_step": 5 }
///   ]
/// }
/// </summary>
public interface IContentRouter
{
    /// <summary>Evaluate routing rules and return target step orders.</summary>
    List<int> EvaluateRoutes(string? dataJson, string routingConfigJson);

    /// <summary>Check if a simple condition matches the data.</summary>
    bool EvaluateCondition(string? dataJson, string condition);
}

public class ContentRouter : IContentRouter
{
    private readonly ILogger<ContentRouter> _logger;

    public ContentRouter(ILogger<ContentRouter> logger) => _logger = logger;

    public List<int> EvaluateRoutes(string? dataJson, string routingConfigJson)
    {
        var targets = new List<int>();

        try
        {
            var config = JsonDocument.Parse(routingConfigJson).RootElement;
            if (!config.TryGetProperty("routes", out var routes)) return targets;

            JsonElement? data = null;
            if (!string.IsNullOrEmpty(dataJson))
                data = JsonDocument.Parse(dataJson).RootElement;

            foreach (var route in routes.EnumerateArray())
            {
                // Default route (always matches if no other matched)
                if (route.TryGetProperty("default", out var isDefault) && isDefault.GetBoolean())
                {
                    if (targets.Count == 0) // Only if no other route matched
                    {
                        var defaultTarget = route.GetProperty("target_step").GetInt32();
                        targets.Add(defaultTarget);
                    }
                    continue;
                }

                // Conditional route
                if (route.TryGetProperty("condition", out var conditionEl))
                {
                    var condition = conditionEl.GetString() ?? "";
                    if (EvaluateCondition(dataJson, condition))
                    {
                        var target = route.GetProperty("target_step").GetInt32();
                        targets.Add(target);
                        _logger.LogDebug("Route matched: condition='{Condition}' → step {Target}", condition, target);
                    }
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to evaluate routing rules");
        }

        return targets;
    }

    public bool EvaluateCondition(string? dataJson, string condition)
    {
        if (string.IsNullOrEmpty(dataJson) || string.IsNullOrEmpty(condition))
            return false;

        try
        {
            var data = JsonDocument.Parse(dataJson).RootElement;

            // Parse simple conditions: "$.field == 'value'" or "$.field > number"
            var parts = ParseCondition(condition);
            if (parts == null) return false;

            var (path, op, expectedValue) = parts.Value;
            var actualValue = ResolvePath(data, path);
            if (actualValue == null) return false;

            return op switch
            {
                "==" => StringEquals(actualValue, expectedValue),
                "!=" => !StringEquals(actualValue, expectedValue),
                ">" => CompareNumeric(actualValue, expectedValue) > 0,
                ">=" => CompareNumeric(actualValue, expectedValue) >= 0,
                "<" => CompareNumeric(actualValue, expectedValue) < 0,
                "<=" => CompareNumeric(actualValue, expectedValue) <= 0,
                "contains" => actualValue.Contains(expectedValue, StringComparison.OrdinalIgnoreCase),
                "startswith" => actualValue.StartsWith(expectedValue, StringComparison.OrdinalIgnoreCase),
                _ => false
            };
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Condition evaluation failed: {Condition}", condition);
            return false;
        }
    }

    private static (string path, string op, string value)? ParseCondition(string condition)
    {
        // Supported formats:
        // "$.field == 'value'"
        // "$.field > 100"
        // "$.nested.field contains 'text'"
        var operators = new[] { ">=", "<=", "!=", "==", ">", "<", "contains", "startswith" };

        foreach (var op in operators)
        {
            var idx = condition.IndexOf($" {op} ", StringComparison.Ordinal);
            if (idx < 0) continue;

            var path = condition[..idx].Trim();
            var value = condition[(idx + op.Length + 2)..].Trim().Trim('\'', '"');
            return (path, op, value);
        }
        return null;
    }

    private static string? ResolvePath(JsonElement root, string path)
    {
        // Simple JSON path: $.field or $.nested.field
        var parts = path.TrimStart('$', '.').Split('.');
        var current = root;

        foreach (var part in parts)
        {
            if (current.ValueKind != JsonValueKind.Object) return null;
            if (!current.TryGetProperty(part, out var next)) return null;
            current = next;
        }

        return current.ValueKind switch
        {
            JsonValueKind.String => current.GetString(),
            JsonValueKind.Number => current.GetRawText(),
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            JsonValueKind.Null => null,
            _ => current.GetRawText()
        };
    }

    private static bool StringEquals(string actual, string expected)
        => actual.Equals(expected, StringComparison.OrdinalIgnoreCase);

    private static int CompareNumeric(string actual, string expected)
    {
        if (double.TryParse(actual, out var a) && double.TryParse(expected, out var b))
            return a.CompareTo(b);
        return string.Compare(actual, expected, StringComparison.Ordinal);
    }
}
