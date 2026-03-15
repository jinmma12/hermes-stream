namespace Hermes.Engine.Domain.Entities;

// ── Collector ──

public class CollectorDefinition : AuditableEntity
{
    public string Code { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public string? Category { get; set; }
    public string? IconUrl { get; set; }
    public DefinitionStatus Status { get; set; } = DefinitionStatus.Draft;
    public List<CollectorDefinitionVersion> Versions { get; set; } = new();
}

public class CollectorDefinitionVersion : BaseEntity
{
    public Guid DefinitionId { get; set; }
    public int VersionNo { get; set; }
    public string InputSchema { get; set; } = "{}";
    public string UiSchema { get; set; } = "{}";
    public string OutputSchema { get; set; } = "{}";
    public string DefaultConfig { get; set; } = "{}";
    public ExecutionType ExecutionType { get; set; } = ExecutionType.Plugin;
    public string? ExecutionRef { get; set; }
    public bool IsPublished { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public CollectorDefinition Definition { get; set; } = null!;
}

// ── Algorithm ──

public class AlgorithmDefinition : AuditableEntity
{
    public string Code { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public string? Category { get; set; }
    public string? IconUrl { get; set; }
    public DefinitionStatus Status { get; set; } = DefinitionStatus.Draft;
    public List<AlgorithmDefinitionVersion> Versions { get; set; } = new();
}

public class AlgorithmDefinitionVersion : BaseEntity
{
    public Guid DefinitionId { get; set; }
    public int VersionNo { get; set; }
    public string InputSchema { get; set; } = "{}";
    public string UiSchema { get; set; } = "{}";
    public string OutputSchema { get; set; } = "{}";
    public string DefaultConfig { get; set; } = "{}";
    public ExecutionType ExecutionType { get; set; } = ExecutionType.Plugin;
    public string? ExecutionRef { get; set; }
    public bool IsPublished { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public AlgorithmDefinition Definition { get; set; } = null!;
}

// ── Transfer ──

public class TransferDefinition : AuditableEntity
{
    public string Code { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public string? Category { get; set; }
    public string? IconUrl { get; set; }
    public DefinitionStatus Status { get; set; } = DefinitionStatus.Draft;
    public List<TransferDefinitionVersion> Versions { get; set; } = new();
}

public class TransferDefinitionVersion : BaseEntity
{
    public Guid DefinitionId { get; set; }
    public int VersionNo { get; set; }
    public string InputSchema { get; set; } = "{}";
    public string UiSchema { get; set; } = "{}";
    public string OutputSchema { get; set; } = "{}";
    public string DefaultConfig { get; set; } = "{}";
    public ExecutionType ExecutionType { get; set; } = ExecutionType.Plugin;
    public string? ExecutionRef { get; set; }
    public bool IsPublished { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public TransferDefinition Definition { get; set; } = null!;
}
