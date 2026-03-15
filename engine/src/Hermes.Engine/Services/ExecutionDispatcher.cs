using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using Hermes.Engine.Domain;

namespace Hermes.Engine.Services;

public class ExecutionDispatcher : IExecutionDispatcher
{
    private readonly IPluginExecutor _pluginExecutor;
    private readonly IPluginRegistry _pluginRegistry;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<ExecutionDispatcher> _logger;

    public ExecutionDispatcher(
        IPluginExecutor pluginExecutor,
        IPluginRegistry pluginRegistry,
        IHttpClientFactory httpClientFactory,
        ILogger<ExecutionDispatcher> logger)
    {
        _pluginExecutor = pluginExecutor;
        _pluginRegistry = pluginRegistry;
        _httpClientFactory = httpClientFactory;
        _logger = logger;
    }

    public async Task<ExecutionResult> DispatchAsync(
        ExecutionType executionType,
        string? executionRef,
        string configJson,
        string? inputDataJson = null,
        Dictionary<string, string>? context = null,
        CancellationToken ct = default)
    {
        var sw = Stopwatch.StartNew();
        try
        {
            var result = executionType switch
            {
                ExecutionType.Plugin => await ExecutePluginAsync(executionRef!, configJson, inputDataJson, context, ct),
                ExecutionType.Script => await ExecuteScriptAsync(executionRef!, configJson, inputDataJson, context, ct),
                ExecutionType.Http => await ExecuteHttpAsync(executionRef!, configJson, inputDataJson, context, ct),
                ExecutionType.NifiFlow => await ExecuteNifiFlowAsync(executionRef!, configJson, inputDataJson, context, ct),
                _ => new ExecutionResult(false, null, null, 0, new List<LogEntry> { new(DateTimeOffset.UtcNow, "ERROR", $"Unsupported execution type: {executionType}") })
            };
            sw.Stop();
            return result with { DurationMs = sw.ElapsedMilliseconds };
        }
        catch (Exception ex)
        {
            sw.Stop();
            _logger.LogError(ex, "Execution failed: {Type} {Ref}", executionType, executionRef);
            return new ExecutionResult(false, null, null, sw.ElapsedMilliseconds,
                new List<LogEntry> { new(DateTimeOffset.UtcNow, "ERROR", ex.Message) });
        }
    }

    private async Task<ExecutionResult> ExecutePluginAsync(string executionRef, string configJson, string? inputDataJson, Dictionary<string, string>? context, CancellationToken ct)
    {
        // executionRef format: "TYPE:name" e.g. "COLLECTOR:rest-api-collector"
        var parts = executionRef.Split(':', 2);
        if (parts.Length != 2)
            return new ExecutionResult(false, null, null, 0, new List<LogEntry> { new(DateTimeOffset.UtcNow, "ERROR", $"Invalid plugin ref: {executionRef}") });

        var pluginType = Enum.Parse<PluginType>(parts[0], ignoreCase: true);
        var plugin = _pluginRegistry.GetPlugin(pluginType, parts[1]);
        if (plugin == null)
            return new ExecutionResult(false, null, null, 0, new List<LogEntry> { new(DateTimeOffset.UtcNow, "ERROR", $"Plugin not found: {executionRef}") });

        var pluginResult = await _pluginExecutor.ExecuteAsync(plugin, configJson, inputDataJson, context, ct);

        var outputJson = pluginResult.Outputs.Count > 0 ? JsonSerializer.Serialize(pluginResult.Outputs) : null;
        var summaryJson = pluginResult.Summary != null ? JsonSerializer.Serialize(pluginResult.Summary) : null;

        return new ExecutionResult(pluginResult.Success, outputJson, summaryJson, (long)(pluginResult.DurationSeconds * 1000), pluginResult.Logs);
    }

    private async Task<ExecutionResult> ExecuteScriptAsync(string executionRef, string configJson, string? inputDataJson, Dictionary<string, string>? context, CancellationToken ct)
    {
        var psi = new ProcessStartInfo
        {
            FileName = "/bin/bash",
            Arguments = $"-c \"{executionRef}\"",
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        psi.Environment["HERMES_CONFIG"] = configJson;
        psi.Environment["HERMES_CONTEXT"] = context != null ? JsonSerializer.Serialize(context) : "{}";

        using var process = Process.Start(psi)!;
        if (inputDataJson != null)
        {
            await process.StandardInput.WriteAsync(inputDataJson);
            process.StandardInput.Close();
        }

        var stdout = await process.StandardOutput.ReadToEndAsync(ct);
        var stderr = await process.StandardError.ReadToEndAsync(ct);
        await process.WaitForExitAsync(ct);

        var logs = new List<LogEntry>();
        if (!string.IsNullOrEmpty(stderr))
            logs.Add(new LogEntry(DateTimeOffset.UtcNow, "STDERR", stderr));

        return new ExecutionResult(process.ExitCode == 0, stdout, null, 0, logs);
    }

    private async Task<ExecutionResult> ExecuteHttpAsync(string executionRef, string configJson, string? inputDataJson, Dictionary<string, string>? context, CancellationToken ct)
    {
        var config = JsonSerializer.Deserialize<JsonElement>(configJson);
        var method = config.TryGetProperty("method", out var m) ? m.GetString()?.ToUpperInvariant() ?? "GET" : "GET";
        var headers = config.TryGetProperty("headers", out var h) ? h : default;

        var client = _httpClientFactory.CreateClient();
        var request = new HttpRequestMessage(new HttpMethod(method), executionRef);

        if (headers.ValueKind == JsonValueKind.Object)
        {
            foreach (var header in headers.EnumerateObject())
                request.Headers.TryAddWithoutValidation(header.Name, header.Value.GetString());
        }

        if (inputDataJson != null && method is "POST" or "PUT" or "PATCH")
            request.Content = new StringContent(inputDataJson, Encoding.UTF8, "application/json");

        var response = await client.SendAsync(request, ct);
        var body = await response.Content.ReadAsStringAsync(ct);

        return new ExecutionResult(
            response.IsSuccessStatusCode,
            body,
            JsonSerializer.Serialize(new { StatusCode = (int)response.StatusCode, response.ReasonPhrase }),
            0,
            new List<LogEntry>());
    }

    private Task<ExecutionResult> ExecuteNifiFlowAsync(string executionRef, string configJson, string? inputDataJson, Dictionary<string, string>? context, CancellationToken ct)
    {
        // NiFi integration placeholder
        _logger.LogWarning("NiFi flow execution not yet implemented: {Ref}", executionRef);
        return Task.FromResult(new ExecutionResult(false, null, null, 0,
            new List<LogEntry> { new(DateTimeOffset.UtcNow, "WARN", "NiFi flow execution not yet implemented") }));
    }
}
