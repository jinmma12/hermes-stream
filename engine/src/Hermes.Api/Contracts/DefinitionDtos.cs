namespace Hermes.Api.Contracts;

public sealed record DefinitionSummaryDto(
    Guid Id,
    string Code,
    string Name,
    string? Description,
    string? Category,
    string? IconUrl,
    string Status,
    string CreatedAt);

public sealed record DefinitionVersionDto(
    Guid Id,
    Guid DefinitionId,
    int VersionNo,
    Dictionary<string, object?> InputSchema,
    Dictionary<string, object?> UiSchema,
    Dictionary<string, object?> OutputSchema,
    Dictionary<string, object?> DefaultConfig,
    string ExecutionType,
    string? ExecutionRef,
    bool IsPublished,
    string CreatedAt);
