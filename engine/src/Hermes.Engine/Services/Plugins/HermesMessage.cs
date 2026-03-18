using System.Text.Json;
using Hermes.Engine.Domain;

namespace Hermes.Engine.Services.Plugins;

public class VesselMessage
{
    public MessageType Type { get; set; }
    public Dictionary<string, object?> Data { get; set; } = new();

    public string ToJson()
    {
        return JsonSerializer.Serialize(new { type = Type.ToString().ToUpperInvariant(), data = Data });
    }

    public static VesselMessage FromJson(string line)
    {
        var doc = JsonDocument.Parse(line);
        var root = doc.RootElement;
        var type = Enum.Parse<MessageType>(root.GetProperty("type").GetString()!, ignoreCase: true);
        var data = new Dictionary<string, object?>();
        if (root.TryGetProperty("data", out var dataEl) && dataEl.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in dataEl.EnumerateObject())
                data[prop.Name] = prop.Value.Clone();
        }
        return new VesselMessage { Type = type, Data = data };
    }

    public static VesselMessage Configure(string configJson, string? contextJson = null)
        => new() { Type = MessageType.Configure, Data = new() { ["config"] = configJson, ["context"] = contextJson } };

    public static VesselMessage Execute(string? inputDataJson)
        => new() { Type = MessageType.Execute, Data = new() { ["input"] = inputDataJson } };
}
