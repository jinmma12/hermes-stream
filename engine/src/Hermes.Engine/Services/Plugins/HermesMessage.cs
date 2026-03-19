using System.Text.Json;
using Hermes.Engine.Domain;

namespace Hermes.Engine.Services.Plugins;

public class HermesMessage
{
    public MessageType Type { get; set; }
    public Dictionary<string, object?> Data { get; set; } = new();

    public string ToJson()
    {
        return JsonSerializer.Serialize(new { type = Type.ToString().ToUpperInvariant(), data = Data });
    }

    public static HermesMessage FromJson(string line)
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
        return new HermesMessage { Type = type, Data = data };
    }

    public static HermesMessage Configure(string configJson, string? contextJson = null)
        => new() { Type = MessageType.Configure, Data = new() { ["config"] = configJson, ["context"] = contextJson } };

    public static HermesMessage Execute(string? inputDataJson)
        => new() { Type = MessageType.Execute, Data = new() { ["input"] = inputDataJson } };
}
