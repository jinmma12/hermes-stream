using System.Diagnostics;
using System.Text.Json;
using Microsoft.Extensions.Logging;

namespace Hermes.Engine.Services.Connectors;

/// <summary>
/// Adapter that runs Singer Taps/Targets as Hermes plugins.
/// Singer protocol: stdin/stdout JSON lines with RECORD, SCHEMA, STATE messages.
///
/// This enables reuse of 300+ Singer community connectors (Meltano Hub).
///
/// Reference: https://hub.meltano.com/singer/spec/
///            https://github.com/singer-io/getting-started/blob/master/docs/SPEC.md
/// </summary>
public interface ISingerAdapter
{
    /// <summary>Run a Singer tap and return extracted records.</summary>
    Task<SingerResult> RunTapAsync(string tapExecutable, string configJson, string? stateJson = null, CancellationToken ct = default);

    /// <summary>Run a Singer target, piping records to it.</summary>
    Task<SingerResult> RunTargetAsync(string targetExecutable, string configJson, List<string> inputLines, CancellationToken ct = default);
}

public record SingerResult(
    List<SingerRecord> Records,
    List<SingerSchema> Schemas,
    string? FinalStateJson,
    int RecordCount,
    List<string> Logs);

public record SingerRecord(string Stream, string DataJson, string? TimeExtracted);
public record SingerSchema(string Stream, string SchemaJson, List<string> KeyProperties);

public class SingerAdapter : ISingerAdapter
{
    private readonly ILogger<SingerAdapter> _logger;
    private readonly int _timeoutSeconds;

    public SingerAdapter(ILogger<SingerAdapter> logger, int timeoutSeconds = 300)
    {
        _logger = logger;
        _timeoutSeconds = timeoutSeconds;
    }

    public async Task<SingerResult> RunTapAsync(
        string tapExecutable, string configJson, string? stateJson = null, CancellationToken ct = default)
    {
        var tmpDir = Path.Combine(Path.GetTempPath(), $"hermes-singer-{Guid.NewGuid():N}");
        Directory.CreateDirectory(tmpDir);

        try
        {
            var configPath = Path.Combine(tmpDir, "config.json");
            await File.WriteAllTextAsync(configPath, configJson, ct);

            var args = $"--config {configPath}";
            if (stateJson != null)
            {
                var statePath = Path.Combine(tmpDir, "state.json");
                await File.WriteAllTextAsync(statePath, stateJson, ct);
                args += $" --state {statePath}";
            }

            var lines = await RunProcessAsync(tapExecutable, args, ct: ct);
            return ParseSingerOutput(lines);
        }
        finally
        {
            try { Directory.Delete(tmpDir, true); } catch { }
        }
    }

    public async Task<SingerResult> RunTargetAsync(
        string targetExecutable, string configJson, List<string> inputLines, CancellationToken ct = default)
    {
        var tmpDir = Path.Combine(Path.GetTempPath(), $"hermes-singer-{Guid.NewGuid():N}");
        Directory.CreateDirectory(tmpDir);

        try
        {
            var configPath = Path.Combine(tmpDir, "config.json");
            await File.WriteAllTextAsync(configPath, configJson, ct);

            var psi = new ProcessStartInfo
            {
                FileName = targetExecutable,
                Arguments = $"--config {configPath}",
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            using var process = Process.Start(psi)!;
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(_timeoutSeconds));

            // Pipe records to target
            foreach (var line in inputLines)
                await process.StandardInput.WriteLineAsync(line.AsMemory(), cts.Token);
            process.StandardInput.Close();

            var output = new List<string>();
            while (!process.StandardOutput.EndOfStream)
            {
                var line = await process.StandardOutput.ReadLineAsync(cts.Token);
                if (line != null) output.Add(line);
            }

            await process.WaitForExitAsync(cts.Token);
            return ParseSingerOutput(output);
        }
        finally
        {
            try { Directory.Delete(tmpDir, true); } catch { }
        }
    }

    private SingerResult ParseSingerOutput(List<string> lines)
    {
        var records = new List<SingerRecord>();
        var schemas = new List<SingerSchema>();
        string? latestState = null;
        var logs = new List<string>();

        foreach (var line in lines)
        {
            try
            {
                var doc = JsonDocument.Parse(line);
                var type = doc.RootElement.GetProperty("type").GetString();

                switch (type)
                {
                    case "RECORD":
                        var stream = doc.RootElement.GetProperty("stream").GetString() ?? "";
                        var data = doc.RootElement.GetProperty("record").GetRawText();
                        var timeExtracted = doc.RootElement.TryGetProperty("time_extracted", out var te) ? te.GetString() : null;
                        records.Add(new SingerRecord(stream, data, timeExtracted));
                        break;

                    case "SCHEMA":
                        var schemaStream = doc.RootElement.GetProperty("stream").GetString() ?? "";
                        var schema = doc.RootElement.GetProperty("schema").GetRawText();
                        var keys = new List<string>();
                        if (doc.RootElement.TryGetProperty("key_properties", out var kp))
                            keys = kp.EnumerateArray().Select(k => k.GetString() ?? "").ToList();
                        schemas.Add(new SingerSchema(schemaStream, schema, keys));
                        break;

                    case "STATE":
                        latestState = doc.RootElement.GetProperty("value").GetRawText();
                        break;
                }
            }
            catch
            {
                logs.Add(line); // Non-JSON lines are treated as logs
            }
        }

        _logger.LogInformation("Singer output: {Records} records, {Schemas} schemas", records.Count, schemas.Count);
        return new SingerResult(records, schemas, latestState, records.Count, logs);
    }

    private async Task<List<string>> RunProcessAsync(
        string executable, string arguments, string? stdin = null, CancellationToken ct = default)
    {
        var psi = new ProcessStartInfo
        {
            FileName = executable,
            Arguments = arguments,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = stdin != null,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        using var process = Process.Start(psi)!;
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(_timeoutSeconds));

        if (stdin != null)
        {
            await process.StandardInput.WriteAsync(stdin);
            process.StandardInput.Close();
        }

        var lines = new List<string>();
        while (!process.StandardOutput.EndOfStream)
        {
            var line = await process.StandardOutput.ReadLineAsync(cts.Token);
            if (line != null) lines.Add(line);
        }

        await process.WaitForExitAsync(cts.Token);
        return lines;
    }
}
