namespace Hermes.Api.Contracts;

public sealed record SchemaRevisionDto(
    Guid Id,
    string Provider,
    string SchemaName,
    string RevisionKey,
    string AppliedBy,
    string Notes,
    DateTimeOffset AppliedAt);
