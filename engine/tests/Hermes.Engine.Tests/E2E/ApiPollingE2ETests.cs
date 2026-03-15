using System.Net;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging.Abstractions;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Services;
using Hermes.Engine.Services.Monitors;

namespace Hermes.Engine.Tests.E2E;

/// <summary>
/// E2E tests: Mock HTTP server → ApiPollMonitor detects → WorkItem created → processed.
/// Uses a custom HttpMessageHandler to simulate API responses without a real HTTP server.
/// </summary>
public class ApiPollingE2ETests
{
    [Fact]
    public async Task ApiPollMonitor_DetectsNewResponse()
    {
        var handler = new MockHttpHandler("""{"items":[{"id":1,"name":"alpha"}]}""");
        var client = new HttpClient(handler);

        var monitor = new ApiPollMonitor(client, "http://mock-api/data");

        var events = await monitor.PollAsync();

        Assert.Single(events);
        Assert.Equal("API_RESPONSE", events[0].EventType);
        Assert.Equal("http://mock-api/data", events[0].Key);
        Assert.Equal(200, (int)events[0].Metadata["status_code"]);
        Assert.NotNull(events[0].Metadata["content_hash"]);
    }

    [Fact]
    public async Task ApiPollMonitor_NoChangeOnSecondPoll()
    {
        var handler = new MockHttpHandler("""{"items":[{"id":1}]}""");
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "http://mock-api/data");

        var first = await monitor.PollAsync();
        Assert.Single(first);

        // Same content = no new event
        var second = await monitor.PollAsync();
        Assert.Empty(second);
    }

    [Fact]
    public async Task ApiPollMonitor_DetectsContentChange()
    {
        var handler = new MockHttpHandler("""{"items":[{"id":1}]}""");
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "http://mock-api/data");

        var first = await monitor.PollAsync();
        Assert.Single(first);

        // Change content
        handler.ResponseBody = """{"items":[{"id":1},{"id":2}]}""";
        var second = await monitor.PollAsync();
        Assert.Single(second); // New data detected

        var hash1 = first[0].Metadata["content_hash"]?.ToString();
        var hash2 = second[0].Metadata["content_hash"]?.ToString();
        Assert.NotEqual(hash1, hash2);
    }

    [Fact]
    public async Task FullPipeline_ApiPoll_To_Processing()
    {
        // 1. Simulate API returning sensor data
        var apiResponse = JsonSerializer.Serialize(new
        {
            timestamp = "2026-03-15T12:00:00Z",
            sensors = new[]
            {
                new { id = "S001", temperature = 22.5, humidity = 45.0, status = "normal" },
                new { id = "S002", temperature = 35.1, humidity = 30.0, status = "alert" },
                new { id = "S003", temperature = 21.0, humidity = 50.0, status = "normal" },
            }
        });

        var handler = new MockHttpHandler(apiResponse);
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "http://sensor-api/v1/readings",
            headers: new() { ["X-Api-Key"] = "test-key-123" });

        // 2. Poll detects data
        var events = await monitor.PollAsync();
        Assert.Single(events);

        // 3. Create work item & process
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        var evaluator = new ConditionEvaluator();
        var evt = events[0];

        var wi = new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.ApiResponse,
            SourceKey = evt.Key,
            SourceMetadata = JsonSerializer.Serialize(evt.Metadata),
            DedupKey = evaluator.GenerateDedupKey(evt),
            DetectedAt = evt.DetectedAt,
            Status = JobStatus.Queued
        };
        db.WorkItems.Add(wi);
        await db.SaveChangesAsync();

        var snapshotResolver = new SnapshotResolver(db);
        var dispatcher = new ApiDataDispatcher();
        var orchestrator = new ProcessingOrchestrator(db, dispatcher, snapshotResolver,
            NullLogger<ProcessingOrchestrator>.Instance);

        var execution = await orchestrator.ProcessWorkItemAsync(wi.Id);

        Assert.Equal(ExecutionStatus.Completed, execution.Status);
        Assert.Equal(1, execution.ExecutionNo);

        // Verify output contains processed sensor data
        var stepExecs = db.WorkItemStepExecutions
            .Where(se => se.ExecutionId == execution.Id)
            .OrderBy(se => se.StepOrder).ToList();
        Assert.Equal(3, stepExecs.Count);
        Assert.All(stepExecs, se => Assert.Equal(StepExecutionStatus.Completed, se.Status));
    }

    [Fact]
    public async Task ApiPollMonitor_PaginatedResponse_MultiplePages()
    {
        // Simulate paginated API: page 1 returns data + next_page, page 2 returns data + no next
        var page1 = JsonSerializer.Serialize(new
        {
            data = new[] { new { id = 1, value = "a" }, new { id = 2, value = "b" } },
            next_page = "http://mock-api/data?page=2",
            total = 4
        });

        var handler = new MockHttpHandler(page1);
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "http://mock-api/data?page=1");

        var events = await monitor.PollAsync();
        Assert.Single(events);
        Assert.NotNull(events[0].Metadata["content_hash"]);

        // Simulate page 2 with different content
        var page2 = JsonSerializer.Serialize(new
        {
            data = new[] { new { id = 3, value = "c" }, new { id = 4, value = "d" } },
            total = 4
        });
        handler.ResponseBody = page2;
        var monitor2 = new ApiPollMonitor(client, "http://mock-api/data?page=2");
        var events2 = await monitor2.PollAsync();
        Assert.Single(events2);
    }

    [Fact]
    public async Task DeduplicationAcross_FileAndApiSources()
    {
        var evaluator = new ConditionEvaluator();

        // File event
        var fileEvt = new MonitorEvent("FILE", "/data/report.csv",
            new() { ["path"] = "/data/report.csv", ["size"] = 1024L },
            DateTimeOffset.UtcNow);

        // API event with same logical data
        var apiEvt = new MonitorEvent("API_RESPONSE", "http://api/report",
            new() { ["url"] = "http://api/report", ["content_hash"] = "abc123" },
            DateTimeOffset.UtcNow);

        var fileKey = evaluator.GenerateDedupKey(fileEvt);
        var apiKey = evaluator.GenerateDedupKey(apiEvt);

        // Different source types should produce different dedup keys
        Assert.NotEqual(fileKey, apiKey);
        Assert.StartsWith("FILE:", fileKey);
        Assert.StartsWith("API_RESPONSE:", apiKey);
    }

    /// <summary>Mock HTTP handler for testing without real network calls.</summary>
    private class MockHttpHandler : HttpMessageHandler
    {
        public string ResponseBody { get; set; }
        public HttpStatusCode StatusCode { get; set; } = HttpStatusCode.OK;
        public Dictionary<string, string> ResponseHeaders { get; } = new();

        public MockHttpHandler(string responseBody) => ResponseBody = responseBody;

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken ct)
        {
            var response = new HttpResponseMessage(StatusCode)
            {
                Content = new StringContent(ResponseBody, Encoding.UTF8, "application/json")
            };
            foreach (var (key, value) in ResponseHeaders)
                response.Headers.TryAddWithoutValidation(key, value);
            return Task.FromResult(response);
        }
    }

    /// <summary>Dispatcher that simulates API data processing (collect → transform → transfer).</summary>
    private class ApiDataDispatcher : IExecutionDispatcher
    {
        public Task<ExecutionResult> DispatchAsync(
            ExecutionType executionType, string? executionRef, string configJson,
            string? inputDataJson = null, Dictionary<string, string>? context = null,
            CancellationToken ct = default)
        {
            var step = context?.GetValueOrDefault("step_order") ?? "0";
            var output = step switch
            {
                "1" => JsonSerializer.Serialize(new
                {
                    records = new[]
                    {
                        new { id = "S001", temperature = 22.5, alert = false },
                        new { id = "S002", temperature = 35.1, alert = true },
                        new { id = "S003", temperature = 21.0, alert = false },
                    }
                }),
                "2" => JsonSerializer.Serialize(new
                {
                    alerts = new[] { new { id = "S002", temperature = 35.1, severity = "HIGH" } },
                    normal_count = 2,
                    alert_count = 1
                }),
                "3" => JsonSerializer.Serialize(new
                {
                    destination = "alert-system",
                    alerts_sent = 1,
                    timestamp = DateTimeOffset.UtcNow
                }),
                _ => "{}"
            };

            return Task.FromResult(new ExecutionResult(true, output,
                JsonSerializer.Serialize(new { step, status = "ok" }), 25, new()));
        }
    }
}
