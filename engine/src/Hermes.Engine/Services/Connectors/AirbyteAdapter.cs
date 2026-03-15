using System.Diagnostics;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using Hermes.Engine.Domain;

namespace Hermes.Engine.Services.Connectors;

/// <summary>
/// Adapter that runs Airbyte Docker connectors as Hermes plugins.
/// Airbyte connectors use a standard Docker protocol:
///   - stdin: config.json, catalog.json
///   - stdout: AirbyteMessage JSON lines (RECORD, STATE, LOG, SPEC, etc.)
///   - Commands: spec, check, discover, read
///
/// This adapter translates between Hermes Plugin Protocol ↔ Airbyte Protocol,
/// enabling 600+ Airbyte connectors to run as Hermes pipeline steps.
///
/// Reference: https://docs.airbyte.com/platform/understanding-airbyte/airbyte-protocol-docker
/// </summary>
public interface IAirbyteAdapter
{
    /// <summary>Get connector spec (schema, documentation).</summary>
    Task<AirbyteSpec?> GetSpecAsync(string dockerImage, CancellationToken ct = default);

    /// <summary>Check if connector config is valid and can connect.</summary>
    Task<AirbyteCheckResult> CheckAsync(string dockerImage, string configJson, CancellationToken ct = default);

    /// <summary>Discover available streams/tables.</summary>
    Task<AirbyteCatalog> DiscoverAsync(string dockerImage, string configJson, CancellationToken ct = default);

    /// <summary>Read data from the connector (returns records as JSON lines).</summary>
    Task<AirbyteReadResult> ReadAsync(string dockerImage, string configJson, string catalogJson, string? stateJson = null, CancellationToken ct = default);
}

public record AirbyteSpec(string ConnectionSpecJson, string DocumentationUrl);
public record AirbyteCheckResult(bool Succeeded, string Message);
public record AirbyteCatalog(List<AirbyteStream> Streams);
public record AirbyteStream(string Name, string JsonSchemaJson, List<string> SupportedSyncModes);
public record AirbyteReadResult(List<AirbyteRecord> Records, string? StateJson, int RecordCount);
public record AirbyteRecord(string Stream, string DataJson, DateTimeOffset EmittedAt);

public class AirbyteAdapter : IAirbyteAdapter
{
    private readonly ILogger<AirbyteAdapter> _logger;
    private readonly int _timeoutSeconds;

    public AirbyteAdapter(ILogger<AirbyteAdapter> logger, int timeoutSeconds = 300)
    {
        _logger = logger;
        _timeoutSeconds = timeoutSeconds;
    }

    public async Task<AirbyteSpec?> GetSpecAsync(string dockerImage, CancellationToken ct = default)
    {
        var output = await RunDockerAsync(dockerImage, "spec", ct: ct);
        foreach (var line in output)
        {
            var msg = TryParseMessage(line);
            if (msg?.Type == "SPEC" && msg.HasSpec)
            {
                return new AirbyteSpec(
                    msg.Spec.GetProperty("connectionSpecification").GetRawText(),
                    msg.Spec.TryGetProperty("documentationUrl", out var doc) ? doc.GetString() ?? "" : "");
            }
        }
        return null;
    }

    public async Task<AirbyteCheckResult> CheckAsync(string dockerImage, string configJson, CancellationToken ct = default)
    {
        var output = await RunDockerAsync(dockerImage, "check", configJson, ct: ct);
        foreach (var line in output)
        {
            var msg = TryParseMessage(line);
            if (msg?.Type == "CONNECTION_STATUS")
            {
                var status = msg.ConnectionStatus;
                return new AirbyteCheckResult(
                    status.GetProperty("status").GetString() == "SUCCEEDED",
                    status.TryGetProperty("message", out var m) ? m.GetString() ?? "" : "");
            }
        }
        return new AirbyteCheckResult(false, "No CONNECTION_STATUS message received");
    }

    public async Task<AirbyteCatalog> DiscoverAsync(string dockerImage, string configJson, CancellationToken ct = default)
    {
        var output = await RunDockerAsync(dockerImage, "discover", configJson, ct: ct);
        var streams = new List<AirbyteStream>();

        foreach (var line in output)
        {
            var msg = TryParseMessage(line);
            if (msg?.Type == "CATALOG" && msg.HasCatalog)
            {
                if (msg.Catalog.TryGetProperty("streams", out var streamsEl))
                {
                    foreach (var s in streamsEl.EnumerateArray())
                    {
                        var name = s.GetProperty("name").GetString() ?? "";
                        var schema = s.TryGetProperty("json_schema", out var js) ? js.GetRawText() : "{}";
                        var modes = new List<string>();
                        if (s.TryGetProperty("supported_sync_modes", out var sm))
                            modes = sm.EnumerateArray().Select(m => m.GetString() ?? "").ToList();
                        streams.Add(new AirbyteStream(name, schema, modes));
                    }
                }
            }
        }
        return new AirbyteCatalog(streams);
    }

    public async Task<AirbyteReadResult> ReadAsync(
        string dockerImage, string configJson, string catalogJson, string? stateJson = null, CancellationToken ct = default)
    {
        var records = new List<AirbyteRecord>();
        string? latestState = stateJson;

        var output = await RunDockerAsync(dockerImage, "read", configJson, catalogJson, stateJson, ct);

        foreach (var line in output)
        {
            var msg = TryParseMessage(line);
            if (msg == null) continue;

            switch (msg.Type)
            {
                case "RECORD":
                    if (msg.HasRecord)
                    {
                        records.Add(new AirbyteRecord(
                            msg.Record.GetProperty("stream").GetString() ?? "",
                            msg.Record.GetProperty("data").GetRawText(),
                            msg.Record.TryGetProperty("emitted_at", out var ea)
                                ? DateTimeOffset.FromUnixTimeMilliseconds(ea.GetInt64())
                                : DateTimeOffset.UtcNow));
                    }
                    break;
                case "STATE":
                    if (msg.HasState)
                        latestState = msg.State.GetRawText();
                    break;
                case "LOG":
                    if (msg.HasLog)
                    {
                        var level = msg.Log.TryGetProperty("level", out var l) ? l.GetString() : "INFO";
                        var message = msg.Log.TryGetProperty("message", out var m) ? m.GetString() : "";
                        _logger.LogInformation("[Airbyte {Image}] [{Level}] {Message}", dockerImage, level, message);
                    }
                    break;
            }
        }

        return new AirbyteReadResult(records, latestState, records.Count);
    }

    // ── Docker execution ──

    private async Task<List<string>> RunDockerAsync(
        string dockerImage, string command,
        string? configJson = null, string? catalogJson = null, string? stateJson = null,
        CancellationToken ct = default)
    {
        // Write config/catalog/state to temp files
        var tmpDir = Path.Combine(Path.GetTempPath(), $"hermes-airbyte-{Guid.NewGuid():N}");
        Directory.CreateDirectory(tmpDir);

        try
        {
            var args = new List<string> { "run", "--rm", "-v", $"{tmpDir}:/airbyte" };

            if (configJson != null)
            {
                await File.WriteAllTextAsync(Path.Combine(tmpDir, "config.json"), configJson, ct);
                args.AddRange(new[] { "-v", $"{tmpDir}/config.json:/airbyte/config.json" });
            }
            if (catalogJson != null)
            {
                await File.WriteAllTextAsync(Path.Combine(tmpDir, "catalog.json"), catalogJson, ct);
                args.AddRange(new[] { "-v", $"{tmpDir}/catalog.json:/airbyte/catalog.json" });
            }
            if (stateJson != null)
            {
                await File.WriteAllTextAsync(Path.Combine(tmpDir, "state.json"), stateJson, ct);
                args.AddRange(new[] { "-v", $"{tmpDir}/state.json:/airbyte/state.json" });
            }

            args.Add(dockerImage);
            args.Add(command);

            if (configJson != null) args.AddRange(new[] { "--config", "/airbyte/config.json" });
            if (catalogJson != null) args.AddRange(new[] { "--catalog", "/airbyte/catalog.json" });
            if (stateJson != null) args.AddRange(new[] { "--state", "/airbyte/state.json" });

            _logger.LogInformation("Running Airbyte connector: docker {Args}", string.Join(" ", args));

            var psi = new ProcessStartInfo
            {
                FileName = "docker",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            foreach (var arg in args) psi.ArgumentList.Add(arg);

            using var process = Process.Start(psi)!;
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(_timeoutSeconds));

            var lines = new List<string>();
            while (!process.StandardOutput.EndOfStream)
            {
                var line = await process.StandardOutput.ReadLineAsync(cts.Token);
                if (line != null) lines.Add(line);
            }

            var stderr = await process.StandardError.ReadToEndAsync(cts.Token);
            if (!string.IsNullOrEmpty(stderr))
                _logger.LogWarning("[Airbyte {Image}] stderr: {Error}", dockerImage, stderr);

            await process.WaitForExitAsync(cts.Token);
            return lines;
        }
        finally
        {
            try { Directory.Delete(tmpDir, true); } catch { }
        }
    }

    // ── Airbyte message parsing ──

    private static AirbyteMessage? TryParseMessage(string line)
    {
        try
        {
            var doc = JsonDocument.Parse(line);
            var root = doc.RootElement;
            var type = root.GetProperty("type").GetString() ?? "";

            return new AirbyteMessage
            {
                Type = type,
                Record = root.TryGetProperty("record", out var r) ? r : default,
                State = root.TryGetProperty("state", out var s) ? s : default,
                Log = root.TryGetProperty("log", out var l) ? l : default,
                Spec = root.TryGetProperty("spec", out var sp) ? sp : default,
                Catalog = root.TryGetProperty("catalog", out var c) ? c : default,
                ConnectionStatus = root.TryGetProperty("connectionStatus", out var cs) ? cs : default,
            };
        }
        catch { return null; }
    }

    private class AirbyteMessage
    {
        public string Type { get; set; } = "";
        public JsonElement Record { get; set; }
        public JsonElement State { get; set; }
        public JsonElement Log { get; set; }
        public JsonElement Spec { get; set; }
        public JsonElement Catalog { get; set; }
        public JsonElement ConnectionStatus { get; set; }
        public bool HasRecord => Record.ValueKind != JsonValueKind.Undefined;
        public bool HasState => State.ValueKind != JsonValueKind.Undefined;
        public bool HasLog => Log.ValueKind != JsonValueKind.Undefined;
        public bool HasSpec => Spec.ValueKind != JsonValueKind.Undefined;
        public bool HasCatalog => Catalog.ValueKind != JsonValueKind.Undefined;
    }
}
