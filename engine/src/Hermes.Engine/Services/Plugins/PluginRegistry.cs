using System.Text.Json;
using Microsoft.Extensions.Logging;
using Hermes.Engine.Domain;

namespace Hermes.Engine.Services.Plugins;

public class PluginRegistry : IPluginRegistry
{
    private const string ManifestFilename = "hermes-plugin.json";
    private readonly Dictionary<string, PluginManifest> _plugins = new();
    private readonly ILogger<PluginRegistry> _logger;

    public PluginRegistry(ILogger<PluginRegistry> logger) => _logger = logger;

    public int Count => _plugins.Count;

    public List<PluginManifest> DiscoverPlugins(string pluginsDir)
    {
        var discovered = new List<PluginManifest>();
        if (!Directory.Exists(pluginsDir)) return discovered;

        foreach (var manifestPath in Directory.EnumerateFiles(pluginsDir, ManifestFilename, SearchOption.AllDirectories))
        {
            try
            {
                var manifest = LoadManifest(manifestPath);
                RegisterPlugin(manifest);
                discovered.Add(manifest);
                _logger.LogInformation("Discovered plugin: {Key}", manifest.Key);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to load plugin manifest: {Path}", manifestPath);
            }
        }
        return discovered;
    }

    public void RegisterPlugin(PluginManifest manifest)
    {
        _plugins[manifest.Key] = manifest;
    }

    public PluginManifest? GetPlugin(PluginType type, string name)
    {
        var key = $"{type}:{name}";
        return _plugins.GetValueOrDefault(key);
    }

    public List<PluginManifest> ListPlugins(PluginType? typeFilter = null)
    {
        var plugins = _plugins.Values.AsEnumerable();
        if (typeFilter.HasValue)
            plugins = plugins.Where(p => p.Type == typeFilter.Value);
        return plugins.ToList();
    }

    public bool UnregisterPlugin(PluginType type, string name)
    {
        return _plugins.Remove($"{type}:{name}");
    }

    private static PluginManifest LoadManifest(string manifestPath)
    {
        var json = File.ReadAllText(manifestPath);
        var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        var dir = Path.GetDirectoryName(manifestPath)!;

        return new PluginManifest(
            Name: root.GetProperty("name").GetString()!,
            Version: root.GetProperty("version").GetString()!,
            Type: Enum.Parse<PluginType>(root.GetProperty("type").GetString()!, ignoreCase: true),
            Description: root.TryGetProperty("description", out var d) ? d.GetString() ?? "" : "",
            Author: root.TryGetProperty("author", out var a) ? a.GetString() ?? "" : "",
            License: root.TryGetProperty("license", out var l) ? l.GetString() ?? "" : "",
            Runtime: root.GetProperty("runtime").GetString()!,
            Entrypoint: root.GetProperty("entrypoint").GetString()!,
            InputSchema: root.TryGetProperty("input_schema", out var isc) ? isc.GetRawText() : "{}",
            OutputSchema: root.TryGetProperty("output_schema", out var osc) ? osc.GetRawText() : "{}",
            UiSchema: root.TryGetProperty("ui_schema", out var usc) ? usc.GetRawText() : "{}",
            PluginDir: dir
        );
    }
}
