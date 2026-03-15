using System.Diagnostics;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using Hermes.Engine.Domain;

namespace Hermes.Engine.Services.Plugins;

public class PluginExecutor : IPluginExecutor
{
    private static readonly Dictionary<string, string[]> RuntimeCommands = new()
    {
        ["python"] = new[] { "python3" },
        ["python3"] = new[] { "python3" },
        ["node"] = new[] { "node" },
        ["bash"] = new[] { "bash" },
        ["sh"] = new[] { "sh" }
    };

    private readonly int _timeoutSeconds;
    private readonly ILogger<PluginExecutor> _logger;

    public PluginExecutor(ILogger<PluginExecutor> logger, int timeoutSeconds = 300)
    {
        _logger = logger;
        _timeoutSeconds = timeoutSeconds;
    }

    public async Task<PluginResult> ExecuteAsync(
        PluginManifest plugin,
        string configJson,
        string? inputDataJson = null,
        Dictionary<string, string>? context = null,
        CancellationToken ct = default)
    {
        var sw = Stopwatch.StartNew();
        var logs = new List<LogEntry>();
        var outputs = new List<string>();
        var errors = new List<PluginError>();
        Dictionary<string, object>? summary = null;
        double lastProgress = 0;

        // Build command
        var (command, args) = BuildCommand(plugin);
        var psi = new ProcessStartInfo
        {
            FileName = command,
            Arguments = args,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = plugin.PluginDir
        };

        using var process = Process.Start(psi);
        if (process == null)
        {
            return new PluginResult(false, outputs, errors, logs, null, -1, 0, 0);
        }

        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(_timeoutSeconds));

        try
        {
            // Send CONFIGURE
            var configMsg = VesselMessage.Configure(configJson, context != null ? JsonSerializer.Serialize(context) : null);
            await process.StandardInput.WriteLineAsync(configMsg.ToJson());

            // Send EXECUTE
            var execMsg = VesselMessage.Execute(inputDataJson);
            await process.StandardInput.WriteLineAsync(execMsg.ToJson());
            process.StandardInput.Close();

            // Read output
            while (!process.StandardOutput.EndOfStream)
            {
                var line = await process.StandardOutput.ReadLineAsync(cts.Token);
                if (string.IsNullOrEmpty(line)) continue;

                try
                {
                    var msg = VesselMessage.FromJson(line);
                    switch (msg.Type)
                    {
                        case MessageType.Log:
                            var logLevel = msg.Data.GetValueOrDefault("level")?.ToString() ?? "INFO";
                            var logMessage = msg.Data.GetValueOrDefault("message")?.ToString() ?? "";
                            logs.Add(new LogEntry(DateTimeOffset.UtcNow, logLevel, logMessage));
                            break;
                        case MessageType.Output:
                            outputs.Add(line);
                            break;
                        case MessageType.Error:
                            var errMsg = msg.Data.GetValueOrDefault("message")?.ToString() ?? "Unknown error";
                            var errCode = msg.Data.GetValueOrDefault("code")?.ToString() ?? "PLUGIN_ERROR";
                            errors.Add(new PluginError(errMsg, errCode));
                            break;
                        case MessageType.Status:
                            if (msg.Data.TryGetValue("progress", out var p) && p is JsonElement je)
                                lastProgress = je.GetDouble();
                            break;
                        case MessageType.Done:
                            if (msg.Data.TryGetValue("summary", out var s) && s is JsonElement se)
                                summary = JsonSerializer.Deserialize<Dictionary<string, object>>(se.GetRawText());
                            break;
                    }
                }
                catch
                {
                    logs.Add(new LogEntry(DateTimeOffset.UtcNow, "STDERR", line));
                }
            }

            // Read stderr
            var stderr = await process.StandardError.ReadToEndAsync(cts.Token);
            if (!string.IsNullOrWhiteSpace(stderr))
                logs.Add(new LogEntry(DateTimeOffset.UtcNow, "STDERR", stderr));

            await process.WaitForExitAsync(cts.Token);
            sw.Stop();

            return new PluginResult(
                Success: process.ExitCode == 0 && errors.Count == 0,
                Outputs: outputs,
                Errors: errors,
                Logs: logs,
                Summary: summary,
                ExitCode: process.ExitCode,
                DurationSeconds: sw.Elapsed.TotalSeconds,
                LastProgress: lastProgress
            );
        }
        catch (OperationCanceledException)
        {
            try { process.Kill(entireProcessTree: true); } catch { }
            sw.Stop();
            errors.Add(new PluginError("Plugin execution timed out", "TIMEOUT"));
            return new PluginResult(false, outputs, errors, logs, null, -1, sw.Elapsed.TotalSeconds, lastProgress);
        }
    }

    private static (string command, string args) BuildCommand(PluginManifest plugin)
    {
        if (RuntimeCommands.TryGetValue(plugin.Runtime.ToLowerInvariant(), out var runtimeCmd))
            return (runtimeCmd[0], plugin.EntrypointPath);

        // Default: treat entrypoint as executable
        return (plugin.EntrypointPath, "");
    }
}
