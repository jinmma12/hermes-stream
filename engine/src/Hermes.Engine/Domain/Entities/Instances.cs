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

// ── Process Instance ──

public class ProcessInstance : AuditableEntity
{
    public Guid DefinitionId { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public InstanceStatus Status { get; set; } = InstanceStatus.Draft;
    public ProcessDefinition Definition { get; set; } = null!;
    public List<ProcessInstanceVersion> Versions { get; set; } = new();
}

public class ProcessInstanceVersion : BaseEntity
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
    public ProcessInstance Instance { get; set; } = null!;
    public ProcessDefinitionVersion DefVersion { get; set; } = null!;
}

// ── Export Instance ──

public class ExportInstance : AuditableEntity
{
    public Guid DefinitionId { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public InstanceStatus Status { get; set; } = InstanceStatus.Draft;
    public ExportDefinition Definition { get; set; } = null!;
    public List<ExportInstanceVersion> Versions { get; set; } = new();
}

public class ExportInstanceVersion : BaseEntity
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
    public ExportInstance Instance { get; set; } = null!;
    public ExportDefinitionVersion DefVersion { get; set; } = null!;
}
