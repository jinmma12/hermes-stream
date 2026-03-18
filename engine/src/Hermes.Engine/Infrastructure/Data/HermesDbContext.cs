using Microsoft.EntityFrameworkCore;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;

namespace Hermes.Engine.Infrastructure.Data;

public class HermesDbContext : DbContext, IUnitOfWork
{
    public HermesDbContext(DbContextOptions<HermesDbContext> options) : base(options) { }

    // Definitions
    public DbSet<CollectorDefinition> CollectorDefinitions => Set<CollectorDefinition>();
    public DbSet<CollectorDefinitionVersion> CollectorDefinitionVersions => Set<CollectorDefinitionVersion>();
    public DbSet<ProcessDefinition> ProcessDefinitions => Set<ProcessDefinition>();
    public DbSet<ProcessDefinitionVersion> ProcessDefinitionVersions => Set<ProcessDefinitionVersion>();
    public DbSet<ExportDefinition> ExportDefinitions => Set<ExportDefinition>();
    public DbSet<ExportDefinitionVersion> ExportDefinitionVersions => Set<ExportDefinitionVersion>();

    // Instances
    public DbSet<CollectorInstance> CollectorInstances => Set<CollectorInstance>();
    public DbSet<CollectorInstanceVersion> CollectorInstanceVersions => Set<CollectorInstanceVersion>();
    public DbSet<ProcessInstance> ProcessInstances => Set<ProcessInstance>();
    public DbSet<ProcessInstanceVersion> ProcessInstanceVersions => Set<ProcessInstanceVersion>();
    public DbSet<ExportInstance> ExportInstances => Set<ExportInstance>();
    public DbSet<ExportInstanceVersion> ExportInstanceVersions => Set<ExportInstanceVersion>();

    // Pipelines
    public DbSet<PipelineInstance> PipelineInstances => Set<PipelineInstance>();
    public DbSet<PipelineStep> PipelineSteps => Set<PipelineStep>();

    // Monitoring
    public DbSet<PipelineActivation> PipelineActivations => Set<PipelineActivation>();

    // Execution
    public DbSet<WorkItem> WorkItems => Set<WorkItem>();
    public DbSet<WorkItemExecution> WorkItemExecutions => Set<WorkItemExecution>();
    public DbSet<WorkItemStepExecution> WorkItemStepExecutions => Set<WorkItemStepExecution>();
    public DbSet<ExecutionSnapshot> ExecutionSnapshots => Set<ExecutionSnapshot>();
    public DbSet<ExecutionEventLog> ExecutionEventLogs => Set<ExecutionEventLog>();
    public DbSet<ReprocessRequest> ReprocessRequests => Set<ReprocessRequest>();
    public DbSet<DeadLetterEntry> DeadLetterEntries => Set<DeadLetterEntry>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        var isPostgres = Database.IsNpgsql();
        var jsonColumnType = isPostgres ? "jsonb" : "nvarchar(max)";
        // ── Definitions ──
        modelBuilder.Entity<CollectorDefinition>(e =>
        {
            e.ToTable("collector_definitions");
            e.HasKey(x => x.Id);
            e.HasIndex(x => x.Code).IsUnique();
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            e.HasMany(x => x.Versions).WithOne(x => x.Definition).HasForeignKey(x => x.DefinitionId);
        });
        modelBuilder.Entity<CollectorDefinitionVersion>(e =>
        {
            e.ToTable("collector_definition_versions");
            e.HasKey(x => x.Id);
            e.Property(x => x.ExecutionType).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.InputSchema).HasColumnType(jsonColumnType);
            e.Property(x => x.UiSchema).HasColumnType(jsonColumnType);
            e.Property(x => x.OutputSchema).HasColumnType(jsonColumnType);
            e.Property(x => x.DefaultConfig).HasColumnType(jsonColumnType);
        });

        modelBuilder.Entity<ProcessDefinition>(e =>
        {
            e.ToTable("process_definitions");
            e.HasKey(x => x.Id);
            e.HasIndex(x => x.Code).IsUnique();
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            e.HasMany(x => x.Versions).WithOne(x => x.Definition).HasForeignKey(x => x.DefinitionId);
        });
        modelBuilder.Entity<ProcessDefinitionVersion>(e =>
        {
            e.ToTable("process_definition_versions");
            e.HasKey(x => x.Id);
            e.Property(x => x.ExecutionType).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.InputSchema).HasColumnType(jsonColumnType);
            e.Property(x => x.UiSchema).HasColumnType(jsonColumnType);
            e.Property(x => x.OutputSchema).HasColumnType(jsonColumnType);
            e.Property(x => x.DefaultConfig).HasColumnType(jsonColumnType);
        });

        modelBuilder.Entity<ExportDefinition>(e =>
        {
            e.ToTable("export_definitions");
            e.HasKey(x => x.Id);
            e.HasIndex(x => x.Code).IsUnique();
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            e.HasMany(x => x.Versions).WithOne(x => x.Definition).HasForeignKey(x => x.DefinitionId);
        });
        modelBuilder.Entity<ExportDefinitionVersion>(e =>
        {
            e.ToTable("export_definition_versions");
            e.HasKey(x => x.Id);
            e.Property(x => x.ExecutionType).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.InputSchema).HasColumnType(jsonColumnType);
            e.Property(x => x.UiSchema).HasColumnType(jsonColumnType);
            e.Property(x => x.OutputSchema).HasColumnType(jsonColumnType);
            e.Property(x => x.DefaultConfig).HasColumnType(jsonColumnType);
        });

        // ── Instances ──
        modelBuilder.Entity<CollectorInstance>(e =>
        {
            e.ToTable("collector_instances");
            e.HasKey(x => x.Id);
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            e.HasMany(x => x.Versions).WithOne(x => x.Instance).HasForeignKey(x => x.InstanceId);
        });
        modelBuilder.Entity<CollectorInstanceVersion>(e =>
        {
            e.ToTable("collector_instance_versions");
            e.HasKey(x => x.Id);
            e.Property(x => x.ConfigJson).HasColumnType(jsonColumnType);
            e.Property(x => x.SecretBindingJson).HasColumnType(jsonColumnType);
        });

        modelBuilder.Entity<ProcessInstance>(e =>
        {
            e.ToTable("process_instances");
            e.HasKey(x => x.Id);
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            e.HasMany(x => x.Versions).WithOne(x => x.Instance).HasForeignKey(x => x.InstanceId);
        });
        modelBuilder.Entity<ProcessInstanceVersion>(e =>
        {
            e.ToTable("process_instance_versions");
            e.HasKey(x => x.Id);
            e.Property(x => x.ConfigJson).HasColumnType(jsonColumnType);
            e.Property(x => x.SecretBindingJson).HasColumnType(jsonColumnType);
        });

        modelBuilder.Entity<ExportInstance>(e =>
        {
            e.ToTable("export_instances");
            e.HasKey(x => x.Id);
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            e.HasMany(x => x.Versions).WithOne(x => x.Instance).HasForeignKey(x => x.InstanceId);
        });
        modelBuilder.Entity<ExportInstanceVersion>(e =>
        {
            e.ToTable("export_instance_versions");
            e.HasKey(x => x.Id);
            e.Property(x => x.ConfigJson).HasColumnType(jsonColumnType);
            e.Property(x => x.SecretBindingJson).HasColumnType(jsonColumnType);
        });

        // ── Pipelines ──
        modelBuilder.Entity<PipelineInstance>(e =>
        {
            e.ToTable("pipeline_instances");
            e.HasKey(x => x.Id);
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.MonitoringType).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.MonitoringConfig).HasColumnType(jsonColumnType);
            e.HasMany(x => x.Steps).WithOne(x => x.PipelineInstance)
                .HasForeignKey(x => x.PipelineInstanceId).OnDelete(DeleteBehavior.Cascade);
            e.HasMany(x => x.Activations).WithOne(x => x.PipelineInstance)
                .HasForeignKey(x => x.PipelineInstanceId);
        });
        modelBuilder.Entity<PipelineStep>(e =>
        {
            e.ToTable("pipeline_steps");
            e.HasKey(x => x.Id);
            e.Property(x => x.StepType).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.RefType).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.OnError).HasConversion<string>().HasMaxLength(10);
        });

        // ── Monitoring ──
        modelBuilder.Entity<PipelineActivation>(e =>
        {
            e.ToTable("pipeline_activations");
            e.HasKey(x => x.Id);
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            e.HasMany(x => x.WorkItems).WithOne(x => x.PipelineActivation)
                .HasForeignKey(x => x.PipelineActivationId);
            e.HasIndex(x => x.PipelineInstanceId);
            e.HasIndex(x => x.Status);
            e.HasIndex(x => new { x.PipelineInstanceId, x.Status });
        });

        // ── Execution ──
        modelBuilder.Entity<WorkItem>(e =>
        {
            e.ToTable("work_items");
            e.HasKey(x => x.Id);
            e.Property(x => x.SourceType).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.SourceMetadata).HasColumnType(jsonColumnType);
            e.HasMany(x => x.Executions).WithOne(x => x.WorkItem).HasForeignKey(x => x.WorkItemId);
            e.HasMany(x => x.ReprocessRequests).WithOne(x => x.WorkItem).HasForeignKey(x => x.WorkItemId);
            // Performance indexes for work item queries
            e.HasIndex(x => x.PipelineInstanceId);
            e.HasIndex(x => x.PipelineActivationId);
            e.HasIndex(x => x.Status);
            e.HasIndex(x => x.DedupKey);
            e.HasIndex(x => x.DetectedAt);
            e.HasIndex(x => x.SourceKey);
            e.HasIndex(x => new { x.PipelineInstanceId, x.Status }); // Pipeline + status filter
            e.HasIndex(x => new { x.PipelineInstanceId, x.DedupKey }).IsUnique(false); // Dedup lookup
            e.HasIndex(x => new { x.PipelineInstanceId, x.DetectedAt }); // Time-range queries
        });
        modelBuilder.Entity<WorkItemExecution>(e =>
        {
            e.ToTable("work_item_executions");
            e.HasKey(x => x.Id);
            e.Property(x => x.TriggerType).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            e.HasMany(x => x.StepExecutions).WithOne(x => x.Execution).HasForeignKey(x => x.ExecutionId);
            e.HasOne(x => x.Snapshot).WithOne(x => x.Execution)
                .HasForeignKey<ExecutionSnapshot>(x => x.ExecutionId);
            e.HasMany(x => x.EventLogs).WithOne(x => x.Execution).HasForeignKey(x => x.ExecutionId);
            e.HasIndex(x => x.WorkItemId);
            e.HasIndex(x => x.Status);
        });
        modelBuilder.Entity<WorkItemStepExecution>(e =>
        {
            e.ToTable("work_item_step_executions");
            e.HasKey(x => x.Id);
            e.Property(x => x.StepType).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.InputSummary).HasColumnType(jsonColumnType);
            e.Property(x => x.OutputSummary).HasColumnType(jsonColumnType);
            e.HasMany(x => x.EventLogs).WithOne(x => x.StepExecution).HasForeignKey(x => x.StepExecutionId);
            e.HasIndex(x => x.ExecutionId);
            e.HasIndex(x => x.Status);
        });
        modelBuilder.Entity<ExecutionSnapshot>(e =>
        {
            e.ToTable("execution_snapshots");
            e.HasKey(x => x.Id);
            e.HasIndex(x => x.ExecutionId).IsUnique();
            e.Property(x => x.PipelineConfig).HasColumnType(jsonColumnType);
            e.Property(x => x.CollectorConfig).HasColumnType(jsonColumnType);
            e.Property(x => x.ProcessConfig).HasColumnType(jsonColumnType);
            e.Property(x => x.ExportConfig).HasColumnType(jsonColumnType);
        });
        modelBuilder.Entity<ExecutionEventLog>(e =>
        {
            e.ToTable("execution_event_logs");
            e.HasKey(x => x.Id);
            e.Property(x => x.EventType).HasConversion<string>().HasMaxLength(10);
            e.Property(x => x.DetailJson).HasColumnType(jsonColumnType);
            e.HasIndex(x => x.ExecutionId);
            e.HasIndex(x => x.EventCode);
            e.HasIndex(x => x.CreatedAt);
            e.HasIndex(x => new { x.ExecutionId, x.EventCode }); // Checkpoint lookups
        });
        modelBuilder.Entity<ReprocessRequest>(e =>
        {
            e.ToTable("reprocess_requests");
            e.HasKey(x => x.Id);
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
        });
        modelBuilder.Entity<DeadLetterEntry>(e =>
        {
            e.ToTable("dead_letter_entries");
            e.HasKey(x => x.Id);
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.InputDataJson).HasColumnType(jsonColumnType);
            e.HasOne(x => x.WorkItem).WithMany().HasForeignKey(x => x.WorkItemId);
        });
    }

    public override Task<int> SaveChangesAsync(CancellationToken ct = default)
    {
        foreach (var entry in ChangeTracker.Entries<AuditableEntity>())
        {
            if (entry.State == EntityState.Modified)
                entry.Entity.UpdatedAt = DateTimeOffset.UtcNow;
        }
        return base.SaveChangesAsync(ct);
    }
}
