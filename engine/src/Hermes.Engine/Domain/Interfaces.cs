using System.Text.Json;
using Hermes.Engine.Domain.Entities;

namespace Hermes.Engine.Domain;

// ── Repository & UoW ──

public interface IRepository<T> where T : BaseEntity
{
    Task<T?> GetByIdAsync(Guid id, CancellationToken ct = default);
    Task<IReadOnlyList<T>> ListAllAsync(CancellationToken ct = default);
    Task<T> AddAsync(T entity, CancellationToken ct = default);
    Task UpdateAsync(T entity, CancellationToken ct = default);
    Task DeleteAsync(T entity, CancellationToken ct = default);
}

public interface IUnitOfWork : IDisposable
{
    Task<int> SaveChangesAsync(CancellationToken ct = default);
}

// ── Monitoring ──

public interface IMonitoringEngine
{
    Task StartMonitoringAsync(PipelineActivation activation, CancellationToken ct = default);
    Task StopMonitoringAsync(Guid activationId, CancellationToken ct = default);
    bool IsMonitoring(Guid activationId);
}

public record MonitorEvent(
    string EventType,
    string Key,
    Dictionary<string, object> Metadata,
    DateTimeOffset DetectedAt);

public interface IConditionEvaluator
{
    bool Evaluate(MonitorEvent monitorEvent, PipelineInstance pipeline);
    string GenerateDedupKey(MonitorEvent monitorEvent);
}

// ── Processing ──

public interface IProcessingOrchestrator
{
    Task<WorkItemExecution> ProcessWorkItemAsync(
        Guid workItemId,
        TriggerType triggerType = TriggerType.Initial,
        string triggerSource = "SYSTEM",
        int startFromStep = 1,
        bool useLatestRecipe = true,
        Guid? reprocessRequestId = null,
        CancellationToken ct = default);

    Task<WorkItemExecution> ReprocessWorkItemAsync(Guid reprocessRequestId, CancellationToken ct = default);

    Task<List<ReprocessRequest>> BulkReprocessAsync(
        List<Guid> workItemIds, string reason, string requestedBy,
        int? startFromStep = null, bool useLatestRecipe = true,
        CancellationToken ct = default);
}

// ── Execution ──

public record ExecutionResult(
    bool Success,
    string? OutputJson,
    string? SummaryJson,
    long DurationMs,
    List<LogEntry> Logs);

public record LogEntry(DateTimeOffset Timestamp, string Level, string Message);

public interface IExecutionDispatcher
{
    Task<ExecutionResult> DispatchAsync(
        ExecutionType executionType,
        string? executionRef,
        string configJson,
        string? inputDataJson = null,
        Dictionary<string, string>? context = null,
        CancellationToken ct = default);
}

// ── Snapshot ──

public record StepConfig(
    Guid StepId,
    int StepOrder,
    StageType StepType,
    RefType RefType,
    Guid RefId,
    ExecutionType ExecutionType,
    string? ExecutionRef,
    string ResolvedConfigJson,
    int VersionNo);

public record ResolvedConfig(
    string PipelineConfigJson,
    List<StepConfig> Steps)
{
    public StepConfig? GetConfigForStep(PipelineStep step)
        => Steps.FirstOrDefault(s => s.StepId == step.Id);
}

public interface ISnapshotResolver
{
    Task<ExecutionSnapshot> CaptureAsync(
        PipelineInstance pipeline,
        IReadOnlyList<PipelineStep> steps,
        Guid executionId,
        bool useLatestRecipe = true,
        CancellationToken ct = default);

    Task<ResolvedConfig> ResolveAsync(Guid snapshotId, CancellationToken ct = default);
}

// ── Plugin System ──

public record PluginManifest(
    string Name,
    string Version,
    PluginType Type,
    string Description,
    string Author,
    string License,
    string Runtime,
    string Entrypoint,
    string InputSchema,
    string OutputSchema,
    string UiSchema,
    string PluginDir)
{
    public string EntrypointPath => Path.Combine(PluginDir, Entrypoint);
    public string Key => $"{Type}:{Name}";
}

public record PluginError(string Message, string Code);

public record PluginResult(
    bool Success,
    List<string> Outputs,
    List<PluginError> Errors,
    List<LogEntry> Logs,
    Dictionary<string, object>? Summary,
    int? ExitCode,
    double DurationSeconds,
    double LastProgress);

public interface IPluginRegistry
{
    List<PluginManifest> DiscoverPlugins(string pluginsDir);
    void RegisterPlugin(PluginManifest manifest);
    PluginManifest? GetPlugin(PluginType type, string name);
    List<PluginManifest> ListPlugins(PluginType? typeFilter = null);
    bool UnregisterPlugin(PluginType type, string name);
    int Count { get; }
}

public interface IPluginExecutor
{
    Task<PluginResult> ExecuteAsync(
        PluginManifest plugin,
        string configJson,
        string? inputDataJson = null,
        Dictionary<string, string>? context = null,
        CancellationToken ct = default);
}
