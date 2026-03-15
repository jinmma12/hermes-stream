namespace Hermes.Api.Contracts;

public sealed record PipelineSummaryDto(
    Guid Id,
    string Name,
    string? Description,
    string MonitoringType,
    Dictionary<string, object?> MonitoringConfig,
    string Status,
    string CreatedAt,
    string UpdatedAt);

public sealed record PipelineStageDto(
    Guid Id,
    Guid PipelineInstanceId,
    int StageOrder,
    string StageType,
    string RefType,
    Guid RefId,
    string? RefName,
    bool IsEnabled,
    string OnError,
    int RetryCount,
    int RetryDelaySeconds);

public sealed record PipelineActivationDto(
    Guid Id,
    Guid PipelineInstanceId,
    PipelineSummaryDto? Pipeline,
    string Status,
    string StartedAt,
    string? StoppedAt,
    string? LastHeartbeatAt,
    string? LastPolledAt,
    string? ErrorMessage,
    string? WorkerId,
    int JobCount);
