using Hermes.Api.Contracts;

namespace Hermes.Api.Services;

public sealed class InMemoryHermesReadStore : IHermesReadStore
{
    private readonly Dictionary<string, List<DefinitionSummaryDto>> _definitions;
    private readonly Dictionary<string, List<DefinitionVersionDto>> _definitionVersions;
    private readonly List<PipelineSummaryDto> _pipelines;
    private readonly Dictionary<Guid, List<PipelineStageDto>> _pipelineStages;
    private readonly List<PipelineActivationDto> _activations;
    private readonly List<JobSummaryDto> _jobs;

    public InMemoryHermesReadStore()
    {
        var now = "2026-03-15T00:00:00Z";

        var collectorId = Guid.Parse("11111111-1111-1111-1111-111111111111");
        var algorithmId = Guid.Parse("22222222-2222-2222-2222-222222222222");
        var transferId = Guid.Parse("33333333-3333-3333-3333-333333333333");

        _definitions = new(StringComparer.OrdinalIgnoreCase)
        {
            ["collectors"] =
            [
                new(collectorId, "rest-api", "REST API Collector", "Collect from REST endpoints", "collection", null, "ACTIVE", now)
            ],
            ["algorithms"] =
            [
                new(algorithmId, "json-transform", "JSON Transform", "Transform JSON payloads", "algorithm", null, "ACTIVE", now)
            ],
            ["transfers"] =
            [
                new(transferId, "file-output", "File Output", "Write processed content to disk", "transfer", null, "ACTIVE", now)
            ]
        };

        _definitionVersions = new(StringComparer.OrdinalIgnoreCase)
        {
            ["collectors"] =
            [
                new(
                    Guid.Parse("aaaaaaaa-1111-1111-1111-111111111111"),
                    collectorId,
                    1,
                    new() { ["url"] = "string", ["method"] = "string" },
                    new() { ["url"] = "text", ["method"] = "select" },
                    new() { ["records"] = "array" },
                    new() { ["method"] = "GET" },
                    "PLUGIN",
                    "builtin.collectors.rest-api",
                    true,
                    now)
            ],
            ["algorithms"] =
            [
                new(
                    Guid.Parse("bbbbbbbb-2222-2222-2222-222222222222"),
                    algorithmId,
                    1,
                    new() { ["expression"] = "string" },
                    new() { ["expression"] = "text" },
                    new() { ["transformed"] = "object" },
                    new() { ["expression"] = "{ data }" },
                    "PLUGIN",
                    "builtin.algorithms.json-transform",
                    true,
                    now)
            ],
            ["transfers"] =
            [
                new(
                    Guid.Parse("cccccccc-3333-3333-3333-333333333333"),
                    transferId,
                    1,
                    new() { ["path"] = "string" },
                    new() { ["path"] = "text" },
                    new() { ["written"] = "boolean" },
                    new() { ["path"] = "/tmp/output" },
                    "PLUGIN",
                    "builtin.transfers.file-output",
                    true,
                    now)
            ]
        };

        var pipelineId = Guid.Parse("44444444-4444-4444-4444-444444444444");
        var activationId = Guid.Parse("55555555-5555-5555-5555-555555555555");

        var pipeline = new PipelineSummaryDto(
            pipelineId,
            "Order Monitoring",
            "Collect, transform, and transfer vendor order batches",
            "API_POLL",
            new() { ["interval_seconds"] = 60 },
            "ACTIVE",
            now,
            now);

        _pipelines =
        [
            pipeline
        ];

        _pipelineStages = new()
        {
            [pipelineId] =
            [
                new(Guid.Parse("66666666-0000-0000-0000-000000000001"), pipelineId, 1, "COLLECT", "COLLECTOR", collectorId, "REST API Collector", true, "STOP", 0, 0),
                new(Guid.Parse("66666666-0000-0000-0000-000000000002"), pipelineId, 2, "ALGORITHM", "ALGORITHM", algorithmId, "JSON Transform", true, "RETRY", 3, 5),
                new(Guid.Parse("66666666-0000-0000-0000-000000000003"), pipelineId, 3, "TRANSFER", "TRANSFER", transferId, "File Output", true, "STOP", 0, 0)
            ]
        };

        _activations =
        [
            new(
                activationId,
                pipelineId,
                pipeline,
                "RUNNING",
                now,
                null,
                "2026-03-15T00:10:00Z",
                "2026-03-15T00:09:50Z",
                null,
                "worker-1",
                2)
        ];

        _jobs =
        [
            new(
                Guid.Parse("77777777-0000-0000-0000-000000000001"),
                activationId,
                pipelineId,
                pipeline.Name,
                "API_RESPONSE",
                "order_batch_001.json",
                new() { ["source"] = "vendor-a" },
                "order_batch_001",
                "2026-03-15T00:05:00Z",
                "COMPLETED",
                Guid.Parse("88888888-0000-0000-0000-000000000001"),
                1,
                "2026-03-15T00:05:03Z"),
            new(
                Guid.Parse("77777777-0000-0000-0000-000000000002"),
                activationId,
                pipelineId,
                pipeline.Name,
                "API_RESPONSE",
                "order_batch_002.json",
                new() { ["source"] = "vendor-a" },
                "order_batch_002",
                "2026-03-15T00:06:00Z",
                "FAILED",
                Guid.Parse("88888888-0000-0000-0000-000000000002"),
                1,
                null)
        ];
    }

    public IReadOnlyList<DefinitionSummaryDto> ListDefinitions(string kind) =>
        _definitions.TryGetValue(kind, out var definitions) ? definitions : [];

    public DefinitionSummaryDto? GetDefinition(string kind, Guid definitionId) =>
        ListDefinitions(kind).FirstOrDefault(x => x.Id == definitionId);

    public IReadOnlyList<DefinitionVersionDto> ListDefinitionVersions(string kind, Guid definitionId) =>
        _definitionVersions.TryGetValue(kind, out var versions)
            ? versions.Where(x => x.DefinitionId == definitionId).OrderByDescending(x => x.VersionNo).ToArray()
            : [];

    public IReadOnlyList<PipelineSummaryDto> ListPipelines() => _pipelines;

    public PipelineSummaryDto? GetPipeline(Guid pipelineId) =>
        _pipelines.FirstOrDefault(x => x.Id == pipelineId);

    public IReadOnlyList<PipelineStageDto> ListPipelineStages(Guid pipelineId) =>
        _pipelineStages.TryGetValue(pipelineId, out var stages) ? stages : [];

    public PaginatedResponseDto<JobSummaryDto> ListJobs(int page, int pageSize)
    {
        var items = _jobs
            .OrderByDescending(x => x.DetectedAt)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .ToArray();

        return new PaginatedResponseDto<JobSummaryDto>(items, _jobs.Count, page, pageSize);
    }

    public JobSummaryDto? GetJob(Guid jobId) =>
        _jobs.FirstOrDefault(x => x.Id == jobId);

    public MonitorStatsDto GetMonitorStats()
    {
        var completed = _jobs.Count(x => x.Status == "COMPLETED");
        var failed = _jobs.Count(x => x.Status == "FAILED");
        var successRate = _jobs.Count == 0 ? 0.0 : Math.Round((double)completed / _jobs.Count * 100.0, 1);

        return new MonitorStatsDto(
            _jobs.Count,
            completed,
            failed,
            successRate,
            2500,
            _activations.Count(x => x.Status == "RUNNING"));
    }

    public IReadOnlyList<PipelineActivationDto> ListMonitorActivations() => _activations;

    public IReadOnlyList<JobSummaryDto> ListRecentJobs(int limit) =>
        _jobs.OrderByDescending(x => x.DetectedAt).Take(limit).ToArray();
}
