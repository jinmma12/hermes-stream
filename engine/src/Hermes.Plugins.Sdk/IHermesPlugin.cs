using System.Text.Json;

namespace Hermes.Plugins.Sdk;

/// <summary>
/// Interface for Hermes plugins. Implement this for DI-based plugin registration.
/// For simple plugins, extend <see cref="PluginBase"/> instead.
/// </summary>
public interface IHermesPlugin
{
    /// <summary>Plugin metadata.</summary>
    PluginSpec Spec { get; }

    /// <summary>Validate configuration and connectivity.</summary>
    Task<CheckResult> CheckAsync(Dictionary<string, JsonElement> config, CancellationToken ct = default);

    /// <summary>Execute the plugin with the given configuration and input.</summary>
    Task<PluginResult> ExecuteAsync(
        Dictionary<string, JsonElement> config,
        JsonElement? input,
        PluginContext context,
        CancellationToken ct = default);
}

/// <summary>Plugin self-description.</summary>
public record PluginSpec(
    string Name,
    string DisplayName,
    string Version,
    PluginKind Type,
    string Description,
    string Author = "",
    string License = "Apache-2.0",
    string InputSchemaJson = "{}",
    string OutputSchemaJson = "{}",
    string UiSchemaJson = "{}");

public enum PluginKind { Collector, Algorithm, Transfer }

/// <summary>Result of a Check call.</summary>
public record CheckResult(bool Success, string Message = "", Dictionary<string, string>? FieldErrors = null);

/// <summary>Result of an Execute call.</summary>
public record PluginResult(
    bool Success,
    string? OutputJson = null,
    string? SummaryJson = null,
    List<string>? Logs = null,
    List<PluginErrorInfo>? Errors = null);

public record PluginErrorInfo(string Message, string Code = "PLUGIN_ERROR", bool IsRetryable = false);
