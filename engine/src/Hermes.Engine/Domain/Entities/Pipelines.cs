namespace Hermes.Engine.Domain.Entities;

public class PipelineInstance : AuditableEntity
{
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public MonitoringType? MonitoringType { get; set; }
    public string MonitoringConfig { get; set; } = "{}";
    public PipelineStatus Status { get; set; } = PipelineStatus.Draft;
    public List<PipelineStep> Steps { get; set; } = new();
    public List<PipelineActivation> Activations { get; set; } = new();
}

public class PipelineStep : BaseEntity
{
    public Guid PipelineInstanceId { get; set; }
    public int StepOrder { get; set; }
    public StageType StepType { get; set; }
    public RefType RefType { get; set; }
    public Guid RefId { get; set; }
    public bool IsEnabled { get; set; } = true;
    public OnErrorAction OnError { get; set; } = OnErrorAction.Stop;
    public int RetryCount { get; set; }
    public int RetryDelaySeconds { get; set; }
    public PipelineInstance PipelineInstance { get; set; } = null!;
}
