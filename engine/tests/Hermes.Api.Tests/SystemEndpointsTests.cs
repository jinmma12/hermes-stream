using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using Xunit;

namespace Hermes.Api.Tests;

public sealed class SystemEndpointsTests : IClassFixture<ApiApplicationFactory>
{
    private readonly HttpClient _client;

    public SystemEndpointsTests(ApiApplicationFactory factory)
    {
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task Root_Returns_Service_Metadata()
    {
        var response = await _client.GetAsync("/");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        var payload = await response.Content.ReadFromJsonAsync<Dictionary<string, string>>();

        Assert.NotNull(payload);
        Assert.Equal("Hermes API", payload["name"]);
        Assert.Equal(".NET 8", payload["runtime"]);
    }

    [Fact]
    public async Task Live_Health_Returns_Ok_Status()
    {
        var payload = await _client.GetFromJsonAsync<Dictionary<string, string>>("/health/live");

        Assert.NotNull(payload);
        Assert.Equal("ok", payload["status"]);
        Assert.Equal("hermes-api", payload["service"]);
    }

    [Fact]
    public async Task Ready_Health_Returns_Ready_Status()
    {
        var payload = await _client.GetFromJsonAsync<ReadyPayload>("/health/ready");

        Assert.NotNull(payload);
        Assert.Equal("ready", payload.Status);
        Assert.Equal("hermes-api", payload.Service);
        Assert.Contains("http", payload.Checks);
    }

    [Fact]
    public async Task System_Info_Exposes_Migration_Status()
    {
        var payload = await _client.GetFromJsonAsync<SystemInfoPayload>("/api/v1/system/info");

        Assert.NotNull(payload);
        Assert.Equal("Hermes.Api", payload.Api);
        Assert.Equal("Hermes.Engine", payload.Engine);
        Assert.Contains(".NET", payload.Migration);
    }

    [Theory]
    [InlineData("/api/v1/definitions/collectors")]
    [InlineData("/api/v1/definitions/algorithms")]
    [InlineData("/api/v1/definitions/transfers")]
    [InlineData("/api/v1/pipelines")]
    public async Task Read_List_Endpoints_Return_Success(string path)
    {
        var response = await _client.GetAsync(path);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task Unknown_Definition_Kind_Returns_NotFound()
    {
        var response = await _client.GetAsync("/api/v1/definitions/unknown");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task Definition_Detail_Returns_Requested_Id()
    {
        var definitionId = Guid.Parse("11111111-1111-1111-1111-111111111111");

        var payload = await _client.GetFromJsonAsync<DefinitionPayload>($"/api/v1/definitions/collectors/{definitionId}");

        Assert.NotNull(payload);
        Assert.Equal(definitionId, payload.Id);
        Assert.Equal("ACTIVE", payload.Status);
        Assert.Equal("rest-api", payload.Code);
    }

    [Fact]
    public async Task Definition_Versions_Returns_Success()
    {
        var definitionId = Guid.Parse("22222222-2222-2222-2222-222222222222");

        var payload = await _client.GetFromJsonAsync<DefinitionVersionPayload[]>($"/api/v1/definitions/algorithms/{definitionId}/versions");

        Assert.NotNull(payload);
        Assert.Single(payload);
        Assert.Equal(1, payload[0].VersionNo);
    }

    [Fact]
    public async Task Jobs_List_Returns_Paginated_Shape()
    {
        var payload = await _client.GetFromJsonAsync<JobListPayload>("/api/v1/jobs?page=2&page_size=25");

        Assert.NotNull(payload);
        Assert.Equal(2, payload.Total);
        Assert.Equal(2, payload.Page);
        Assert.Equal(25, payload.PageSize);
        Assert.Empty(payload.Items);
    }

    [Fact]
    public async Task Pipeline_Detail_Returns_Requested_Id()
    {
        var pipelineId = Guid.Parse("44444444-4444-4444-4444-444444444444");

        var payload = await _client.GetFromJsonAsync<PipelinePayload>($"/api/v1/pipelines/{pipelineId}");

        Assert.NotNull(payload);
        Assert.Equal(pipelineId, payload.Id);
        Assert.Equal("ACTIVE", payload.Status);
        Assert.Equal("Order Monitoring", payload.Name);
    }

    [Fact]
    public async Task Job_Detail_Returns_Requested_Id()
    {
        var jobId = Guid.Parse("77777777-0000-0000-0000-000000000001");

        var payload = await _client.GetFromJsonAsync<JobPayload>($"/api/v1/jobs/{jobId}");

        Assert.NotNull(payload);
        Assert.Equal(jobId, payload.Id);
        Assert.Equal("COMPLETED", payload.Status);
        Assert.Equal("order_batch_001.json", payload.SourceKey);
    }

    [Fact]
    public async Task Monitor_Stats_Returns_Dashboard_Shape()
    {
        var payload = await _client.GetFromJsonAsync<MonitorStatsPayload>("/api/v1/monitor/stats");

        Assert.NotNull(payload);
        Assert.Equal(2, payload.TotalItems);
        Assert.Equal(1, payload.ActivePipelines);
        Assert.Equal(50.0, payload.SuccessRate);
    }

    [Theory]
    [InlineData("/api/v1/monitor/activations", 1)]
    [InlineData("/api/v1/monitor/recent-jobs?limit=10", 2)]
    public async Task Monitor_List_Endpoints_Return_Data(string path, int expectedCount)
    {
        var payload = await _client.GetFromJsonAsync<object[]>(path);

        Assert.NotNull(payload);
        Assert.Equal(expectedCount, payload.Length);
    }

    public sealed record ReadyPayload(string Status, string Service, string[] Checks);

    public sealed record SystemInfoPayload(string Api, string Engine, string Migration);

    public sealed record JobListPayload(
        object[] Items,
        int Total,
        int Page,
        [property: JsonPropertyName("page_size")] int PageSize);

    public sealed record PipelinePayload(Guid Id, string Name, string Status);

    public sealed record DefinitionPayload(Guid Id, string Code, string Name, string Status);

    public sealed record DefinitionVersionPayload(
        Guid Id,
        [property: JsonPropertyName("definition_id")] Guid DefinitionId,
        [property: JsonPropertyName("version_no")] int VersionNo);

    public sealed record JobPayload(
        Guid Id,
        string Status,
        [property: JsonPropertyName("source_key")] string SourceKey);

    public sealed record MonitorStatsPayload(
        [property: JsonPropertyName("total_items")] int TotalItems,
        [property: JsonPropertyName("completed_items")] int CompletedItems,
        [property: JsonPropertyName("failed_items")] int FailedItems,
        [property: JsonPropertyName("success_rate")] double SuccessRate,
        [property: JsonPropertyName("avg_duration_ms")] int AvgDurationMs,
        [property: JsonPropertyName("active_pipelines")] int ActivePipelines);
}
