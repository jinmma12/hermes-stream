namespace Hermes.Api.Contracts;

public sealed record JobSummaryDto(
    Guid Id,
    Guid PipelineActivationId,
    Guid PipelineInstanceId,
    string? PipelineName,
    string SourceType,
    string SourceKey,
    Dictionary<string, object?> SourceMetadata,
    string DedupKey,
    string DetectedAt,
    string Status,
    Guid? CurrentExecutionId,
    int ExecutionCount,
    string? LastCompletedAt);

public sealed record PaginatedResponseDto<T>(
    IReadOnlyList<T> Items,
    int Total,
    int Page,
    int PageSize);

public sealed record MonitorStatsDto(
    int TotalItems,
    int CompletedItems,
    int FailedItems,
    double SuccessRate,
    int AvgDurationMs,
    int ActivePipelines);
