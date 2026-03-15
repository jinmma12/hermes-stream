using System.Text.Json;
using Hermes.Engine.Domain;
using Hermes.Engine.Services.Plugins;
using Microsoft.Extensions.Logging.Abstractions;

namespace Hermes.Engine.Tests;

public class PluginRegistryTests
{
    private readonly PluginRegistry _registry = new(NullLogger<PluginRegistry>.Instance);

    [Fact]
    public void RegisterPlugin_IncreasesCount()
    {
        Assert.Equal(0, _registry.Count);

        _registry.RegisterPlugin(MakeManifest("test-plugin", PluginType.Collector));

        Assert.Equal(1, _registry.Count);
    }

    [Fact]
    public void GetPlugin_ReturnsRegisteredPlugin()
    {
        _registry.RegisterPlugin(MakeManifest("my-collector", PluginType.Collector));

        var result = _registry.GetPlugin(PluginType.Collector, "my-collector");

        Assert.NotNull(result);
        Assert.Equal("my-collector", result.Name);
        Assert.Equal(PluginType.Collector, result.Type);
    }

    [Fact]
    public void GetPlugin_WrongType_ReturnsNull()
    {
        _registry.RegisterPlugin(MakeManifest("my-collector", PluginType.Collector));

        var result = _registry.GetPlugin(PluginType.Algorithm, "my-collector");

        Assert.Null(result);
    }

    [Fact]
    public void ListPlugins_NoFilter_ReturnsAll()
    {
        _registry.RegisterPlugin(MakeManifest("c1", PluginType.Collector));
        _registry.RegisterPlugin(MakeManifest("a1", PluginType.Algorithm));
        _registry.RegisterPlugin(MakeManifest("t1", PluginType.Transfer));

        Assert.Equal(3, _registry.ListPlugins().Count);
    }

    [Fact]
    public void ListPlugins_WithFilter_ReturnsFiltered()
    {
        _registry.RegisterPlugin(MakeManifest("c1", PluginType.Collector));
        _registry.RegisterPlugin(MakeManifest("c2", PluginType.Collector));
        _registry.RegisterPlugin(MakeManifest("a1", PluginType.Algorithm));

        Assert.Equal(2, _registry.ListPlugins(PluginType.Collector).Count);
        Assert.Single(_registry.ListPlugins(PluginType.Algorithm));
    }

    [Fact]
    public void UnregisterPlugin_RemovesAndReturnsTrue()
    {
        _registry.RegisterPlugin(MakeManifest("doomed", PluginType.Transfer));
        Assert.Equal(1, _registry.Count);

        var removed = _registry.UnregisterPlugin(PluginType.Transfer, "doomed");

        Assert.True(removed);
        Assert.Equal(0, _registry.Count);
    }

    [Fact]
    public void UnregisterPlugin_NotFound_ReturnsFalse()
    {
        Assert.False(_registry.UnregisterPlugin(PluginType.Collector, "nonexistent"));
    }

    [Fact]
    public void DiscoverPlugins_EmptyDir_ReturnsEmpty()
    {
        var tempDir = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        Directory.CreateDirectory(tempDir);
        try
        {
            var result = _registry.DiscoverPlugins(tempDir);
            Assert.Empty(result);
        }
        finally
        {
            Directory.Delete(tempDir, true);
        }
    }

    [Fact]
    public void DiscoverPlugins_WithManifest_Discovers()
    {
        var tempDir = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        var pluginDir = Path.Combine(tempDir, "my-plugin");
        Directory.CreateDirectory(pluginDir);

        var manifest = new
        {
            name = "discovered-plugin",
            version = "1.0.0",
            type = "collector",
            runtime = "python",
            entrypoint = "main.py",
            input_schema = new { type = "object" }
        };
        File.WriteAllText(
            Path.Combine(pluginDir, "hermes-plugin.json"),
            JsonSerializer.Serialize(manifest));

        try
        {
            var result = _registry.DiscoverPlugins(tempDir);
            Assert.Single(result);
            Assert.Equal("discovered-plugin", result[0].Name);
            Assert.Equal(1, _registry.Count);
        }
        finally
        {
            Directory.Delete(tempDir, true);
        }
    }

    private static PluginManifest MakeManifest(string name, PluginType type) =>
        new(name, "1.0.0", type, "desc", "author", "MIT", "python", "main.py",
            "{}", "{}", "{}", "/tmp");
}
