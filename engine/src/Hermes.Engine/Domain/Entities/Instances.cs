namespace Hermes.Engine.Domain.Entities;

// ── Collector Instance ──

public class CollectorInstance : AuditableEntity
{
    public Guid DefinitionId { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public InstanceStatus Status { get; set; } = InstanceStatus.Draft;
    public CollectorDefinition Definition { get; set; } = null!;
    public List<CollectorInstanceVersion> Versions { get; set; } = new();
}

public class CollectorInstanceVersion : BaseEntity
{
    public Guid InstanceId { get; set; }
    public Guid DefVersionId { get; set; }
    public int VersionNo { get; set; }
    public string ConfigJson { get; set; } = "{}";
    public string SecretBindingJson { get; set; } = "{}";
    public bool IsCurrent { get; set; }
    public string? CreatedBy { get; set; }
    public string? ChangeNote { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public CollectorInstance Instance { get; set; } = null!;
    public CollectorDefinitionVersion DefVersion { get; set; } = null!;
}

// ── Algorithm Instance ──

public class AlgorithmInstance : AuditableEntity
{
    public Guid DefinitionId { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public InstanceStatus Status { get; set; } = InstanceStatus.Draft;
    public AlgorithmDefinition Definition { get; set; } = null!;
    public List<AlgorithmInstanceVersion> Versions { get; set; } = new();
}

public class AlgorithmInstanceVersion : BaseEntity
{
    public Guid InstanceId { get; set; }
    public Guid DefVersionId { get; set; }
    public int VersionNo { get; set; }
    public string ConfigJson { get; set; } = "{}";
    public string SecretBindingJson { get; set; } = "{}";
    public bool IsCurrent { get; set; }
    public string? CreatedBy { get; set; }
    public string? ChangeNote { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public AlgorithmInstance Instance { get; set; } = null!;
    public AlgorithmDefinitionVersion DefVersion { get; set; } = null!;
}

// ── Transfer Instance ──

public class TransferInstance : AuditableEntity
{
    public Guid DefinitionId { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public InstanceStatus Status { get; set; } = InstanceStatus.Draft;
    public TransferDefinition Definition { get; set; } = null!;
    public List<TransferInstanceVersion> Versions { get; set; } = new();
}

public class TransferInstanceVersion : BaseEntity
{
    public Guid InstanceId { get; set; }
    public Guid DefVersionId { get; set; }
    public int VersionNo { get; set; }
    public string ConfigJson { get; set; } = "{}";
    public string SecretBindingJson { get; set; } = "{}";
    public bool IsCurrent { get; set; }
    public string? CreatedBy { get; set; }
    public string? ChangeNote { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public TransferInstance Instance { get; set; } = null!;
    public TransferDefinitionVersion DefVersion { get; set; } = null!;
}
