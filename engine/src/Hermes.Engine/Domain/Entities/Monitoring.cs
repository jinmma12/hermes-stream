namespace Hermes.Engine.Domain.Entities;

public class PipelineActivation : BaseEntity
{
    public Guid PipelineInstanceId { get; set; }
    public ActivationStatus Status { get; set; } = ActivationStatus.Starting;
    public DateTimeOffset StartedAt { get; set; } = DateTimeOffset.UtcNow;
    public DateTimeOffset? StoppedAt { get; set; }
    public DateTimeOffset? LastHeartbeatAt { get; set; }
    public DateTimeOffset? LastPolledAt { get; set; }
    public string? ErrorMessage { get; set; }
    public string? WorkerId { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public PipelineInstance PipelineInstance { get; set; } = null!;
    public List<WorkItem> WorkItems { get; set; } = new();
}
