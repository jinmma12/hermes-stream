using System.Text.Json;

namespace Hermes.Plugins.Sdk;

/// <summary>
/// Base class for Hermes plugins. Handles the JSON-line protocol automatically.
/// Plugin authors override <see cref="ExecuteAsync"/> to implement their logic.
/// </summary>
public abstract class PluginBase
{
    /// <summary>Run the plugin protocol loop: read CONFIGURE + EXECUTE, call ExecuteAsync, write responses.</summary>
    public async Task RunAsync()
    {
        var configMsg = await ReadMessageAsync();
        var config = configMsg?.GetProperty("data").GetProperty("config");

        var execMsg = await ReadMessageAsync();
        var input = execMsg?.TryGetProperty("data", out var d) == true &&
                    d.TryGetProperty("input", out var inp) ? inp : default;

        var configDict = config.HasValue
            ? JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(config.Value.GetRawText()) ?? new()
            : new Dictionary<string, JsonElement>();

        try
        {
            await ExecuteAsync(configDict, input, new PluginContext());
        }
        catch (Exception ex)
        {
            WriteError(ex.Message, "PLUGIN_EXCEPTION");
            WriteDone(new { error = ex.Message });
        }
    }

    /// <summary>Override this to implement plugin logic.</summary>
    protected abstract Task ExecuteAsync(
        Dictionary<string, JsonElement> config,
        JsonElement? input,
        PluginContext context);

    // ── Protocol helpers ──

    protected void WriteLog(string message, string level = "INFO")
        => WriteMessage("LOG", new { level, message });

    protected void WriteOutput(object data)
        => WriteMessage("OUTPUT", data);

    protected void WriteError(string message, string code = "PLUGIN_ERROR")
        => WriteMessage("ERROR", new { message, code });

    protected void WriteStatus(double progress)
        => WriteMessage("STATUS", new { progress });

    protected void WriteDone(object? summary = null)
        => WriteMessage("DONE", new { summary });

    private static void WriteMessage(string type, object data)
    {
        var json = JsonSerializer.Serialize(new { type, data });
        Console.WriteLine(json);
    }

    private static async Task<JsonElement?> ReadMessageAsync()
    {
        var line = await Console.In.ReadLineAsync();
        if (string.IsNullOrEmpty(line)) return null;
        return JsonDocument.Parse(line).RootElement;
    }
}

/// <summary>Execution context passed to plugins.</summary>
public class PluginContext
{
    public string JobId { get; set; } = "";
    public int ExecutionNo { get; set; }
    public string PipelineId { get; set; } = "";
    public string TriggerType { get; set; } = "INITIAL";
    public Dictionary<string, string> Metadata { get; set; } = new();
}
