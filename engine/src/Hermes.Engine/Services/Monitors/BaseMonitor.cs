using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Hermes.Engine.Domain;

namespace Hermes.Engine.Services.Monitors;

public abstract class BaseMonitor
{
    public abstract Task<List<MonitorEvent>> PollAsync(CancellationToken ct = default);
}

public class FileMonitor : BaseMonitor
{
    private readonly string _watchPath;
    private readonly string _filePattern;
    private readonly HashSet<string> _seenFiles = new();

    public FileMonitor(string watchPath, string filePattern = "*")
    {
        _watchPath = watchPath;
        _filePattern = filePattern;
    }

    public override Task<List<MonitorEvent>> PollAsync(CancellationToken ct = default)
    {
        var events = new List<MonitorEvent>();
        if (!Directory.Exists(_watchPath)) return Task.FromResult(events);

        foreach (var file in Directory.EnumerateFiles(_watchPath, _filePattern, SearchOption.TopDirectoryOnly))
        {
            if (_seenFiles.Contains(file)) continue;
            _seenFiles.Add(file);

            var info = new FileInfo(file);
            events.Add(new MonitorEvent(
                EventType: "FILE",
                Key: file,
                Metadata: new Dictionary<string, object>
                {
                    ["path"] = file,
                    ["filename"] = info.Name,
                    ["size"] = info.Length,
                    ["last_modified"] = info.LastWriteTimeUtc.ToString("O")
                },
                DetectedAt: DateTimeOffset.UtcNow
            ));
        }
        return Task.FromResult(events);
    }
}

public class ApiPollMonitor : BaseMonitor
{
    private readonly HttpClient _httpClient;
    private readonly string _url;
    private readonly Dictionary<string, string> _headers;
    private string? _lastContentHash;

    public ApiPollMonitor(HttpClient httpClient, string url, Dictionary<string, string>? headers = null)
    {
        _httpClient = httpClient;
        _url = url;
        _headers = headers ?? new();
    }

    public override async Task<List<MonitorEvent>> PollAsync(CancellationToken ct = default)
    {
        var events = new List<MonitorEvent>();
        var request = new HttpRequestMessage(HttpMethod.Get, _url);
        foreach (var (key, value) in _headers)
            request.Headers.TryAddWithoutValidation(key, value);

        var response = await _httpClient.SendAsync(request, ct);
        var content = await response.Content.ReadAsStringAsync(ct);
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(content))).ToLowerInvariant();

        if (hash != _lastContentHash)
        {
            _lastContentHash = hash;
            events.Add(new MonitorEvent(
                EventType: "API_RESPONSE",
                Key: _url,
                Metadata: new Dictionary<string, object>
                {
                    ["url"] = _url,
                    ["status_code"] = (int)response.StatusCode,
                    ["content_hash"] = hash,
                    ["content_length"] = content.Length
                },
                DetectedAt: DateTimeOffset.UtcNow
            ));
        }
        return events;
    }
}
