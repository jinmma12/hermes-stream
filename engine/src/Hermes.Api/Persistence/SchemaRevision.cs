namespace Hermes.Api.Persistence;

public sealed class SchemaRevision
{
    public Guid Id { get; set; }

    public string Provider { get; set; } = string.Empty;

    public string SchemaName { get; set; } = string.Empty;

    public string RevisionKey { get; set; } = string.Empty;

    public string AppliedBy { get; set; } = string.Empty;

    public string Notes { get; set; } = string.Empty;

    public DateTimeOffset AppliedAt { get; set; }
}
