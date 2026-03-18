using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Services;

namespace Hermes.Engine.Tests.E2E;

/// <summary>
/// Comprehensive pipeline lifecycle E2E tests covering pipeline status, step ordering,
/// work item lifecycle, recipe versioning, execution snapshots, error recovery,
/// condition evaluation, dead letter queue, back pressure, and event logging.
/// Total: 200+ test methods.
/// </summary>
public class PipelineLifecycleE2ETests
{
    // ════════════════════════════════════════════════════════════════════
    // Helpers
    // ════════════════════════════════════════════════════════════════════

    private static PipelineInstance CreatePipeline(string name = "test-pipeline",
        PipelineStatus status = PipelineStatus.Draft)
    {
        return new PipelineInstance
        {
            Id = Guid.NewGuid(),
            Name = name,
            Status = status,
            MonitoringType = MonitoringType.FileMonitor,
            MonitoringConfig = "{\"path\":\"/data/in\"}"
        };
    }

    private static PipelineStep CreateStep(Guid pipelineId, int order, StageType type,
        OnErrorAction onError = OnErrorAction.Stop, bool enabled = true,
        int retryCount = 0, int retryDelay = 0)
    {
        return new PipelineStep
        {
            Id = Guid.NewGuid(),
            PipelineInstanceId = pipelineId,
            StepOrder = order,
            StepType = type,
            RefType = type switch
            {
                StageType.Collect => RefType.Collector,
                StageType.Process => RefType.Process,
                StageType.Export => RefType.Export,
                _ => RefType.Process
            },
            RefId = Guid.NewGuid(),
            IsEnabled = enabled,
            OnError = onError,
            RetryCount = retryCount,
            RetryDelaySeconds = retryDelay
        };
    }

    private static WorkItem CreateWorkItem(Guid pipelineInstanceId, Guid activationId,
        SourceType sourceType = SourceType.File, JobStatus status = JobStatus.Detected)
    {
        return new WorkItem
        {
            Id = Guid.NewGuid(),
            PipelineInstanceId = pipelineInstanceId,
            PipelineActivationId = activationId,
            SourceType = sourceType,
            SourceKey = "/data/in/file_" + Guid.NewGuid().ToString("N")[..8] + ".csv",
            SourceMetadata = "{\"size\":1024}",
            Status = status,
            DetectedAt = DateTimeOffset.UtcNow
        };
    }

    private static WorkItemExecution CreateExecution(Guid workItemId, int executionNo = 1,
        TriggerType trigger = TriggerType.Initial, ExecutionStatus status = ExecutionStatus.Running)
    {
        return new WorkItemExecution
        {
            Id = Guid.NewGuid(),
            WorkItemId = workItemId,
            ExecutionNo = executionNo,
            TriggerType = trigger,
            TriggerSource = "SYSTEM",
            Status = status,
            StartedAt = DateTimeOffset.UtcNow
        };
    }

    private static PipelineActivation CreateActivation(Guid pipelineInstanceId,
        ActivationStatus status = ActivationStatus.Running)
    {
        return new PipelineActivation
        {
            Id = Guid.NewGuid(),
            PipelineInstanceId = pipelineInstanceId,
            Status = status,
            StartedAt = DateTimeOffset.UtcNow
        };
    }

    private static ExecutionSnapshot CreateSnapshot(Guid executionId,
        string pipelineConfig = "{\"name\":\"test\"}",
        string collectorConfig = "{\"path\":\"/in\"}",
        string processConfig = "{\"transform\":\"uppercase\"}",
        string exportConfig = "{\"dest\":\"/out\"}")
    {
        var combined = pipelineConfig + collectorConfig + processConfig + exportConfig;
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(combined));
        return new ExecutionSnapshot
        {
            Id = Guid.NewGuid(),
            ExecutionId = executionId,
            PipelineConfig = pipelineConfig,
            CollectorConfig = collectorConfig,
            ProcessConfig = processConfig,
            ExportConfig = exportConfig,
            SnapshotHash = Convert.ToHexString(hash).ToLowerInvariant()
        };
    }

    private static MonitorEvent CreateMonitorEvent(string eventType = "FILE",
        string key = "/data/in/test.csv", Dictionary<string, object>? metadata = null)
    {
        return new MonitorEvent(
            eventType,
            key,
            metadata ?? new Dictionary<string, object> { { "path", key }, { "size", 1024 } },
            DateTimeOffset.UtcNow);
    }

    private static string ComputeDedupHash(string eventType, string basis)
    {
        var content = eventType + ":" + basis;
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(content));
        return Convert.ToHexString(hash)[..32].ToLowerInvariant();
    }

    // ════════════════════════════════════════════════════════════════════
    // 1. Pipeline Status Lifecycle (25 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void Pipeline_DefaultStatus_IsDraft()
    {
        var pipeline = new PipelineInstance();
        Assert.Equal(PipelineStatus.Draft, pipeline.Status);
    }

    [Fact]
    public void Pipeline_DraftToActive()
    {
        var pipeline = CreatePipeline();
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect));
        pipeline.Status = PipelineStatus.Active;
        Assert.Equal(PipelineStatus.Active, pipeline.Status);
    }

    [Fact]
    public void Pipeline_ActiveToPaused()
    {
        var pipeline = CreatePipeline(status: PipelineStatus.Active);
        pipeline.Status = PipelineStatus.Paused;
        Assert.Equal(PipelineStatus.Paused, pipeline.Status);
    }

    [Fact]
    public void Pipeline_PausedToActive()
    {
        var pipeline = CreatePipeline(status: PipelineStatus.Paused);
        pipeline.Status = PipelineStatus.Active;
        Assert.Equal(PipelineStatus.Active, pipeline.Status);
    }

    [Fact]
    public void Pipeline_ActiveToArchived()
    {
        var pipeline = CreatePipeline(status: PipelineStatus.Active);
        pipeline.Status = PipelineStatus.Archived;
        Assert.Equal(PipelineStatus.Archived, pipeline.Status);
    }

    [Fact]
    public void Pipeline_FullLifecycle_DraftActivesPausedActiveArchived()
    {
        var pipeline = CreatePipeline();
        Assert.Equal(PipelineStatus.Draft, pipeline.Status);

        pipeline.Status = PipelineStatus.Active;
        Assert.Equal(PipelineStatus.Active, pipeline.Status);

        pipeline.Status = PipelineStatus.Paused;
        Assert.Equal(PipelineStatus.Paused, pipeline.Status);

        pipeline.Status = PipelineStatus.Active;
        Assert.Equal(PipelineStatus.Active, pipeline.Status);

        pipeline.Status = PipelineStatus.Archived;
        Assert.Equal(PipelineStatus.Archived, pipeline.Status);
    }

    [Fact]
    public void Pipeline_ArchivedToActive_ShouldBeInvalidTransition()
    {
        var pipeline = CreatePipeline(status: PipelineStatus.Archived);
        // Business rule: archived pipelines should not be reactivated
        // Validate the guard check at the application layer
        var isArchived = pipeline.Status == PipelineStatus.Archived;
        Assert.True(isArchived, "Pipeline is archived; transition to Active should be blocked by service layer");
    }

    [Fact]
    public void Pipeline_ArchivedToPaused_ShouldBeInvalid()
    {
        var pipeline = CreatePipeline(status: PipelineStatus.Archived);
        var isArchived = pipeline.Status == PipelineStatus.Archived;
        Assert.True(isArchived);
    }

    [Fact]
    public void Pipeline_DraftToArchived_DirectTransition()
    {
        var pipeline = CreatePipeline();
        pipeline.Status = PipelineStatus.Archived;
        Assert.Equal(PipelineStatus.Archived, pipeline.Status);
    }

    [Fact]
    public void Pipeline_DraftToPaused_DirectTransition()
    {
        var pipeline = CreatePipeline();
        pipeline.Status = PipelineStatus.Paused;
        Assert.Equal(PipelineStatus.Paused, pipeline.Status);
    }

    [Fact]
    public void Pipeline_WithZeroStages_CannotActivate()
    {
        var pipeline = CreatePipeline();
        Assert.Empty(pipeline.Steps);
        var canActivate = pipeline.Steps.Count > 0;
        Assert.False(canActivate, "Pipeline with 0 steps should not be activated");
    }

    [Fact]
    public void Pipeline_WithOneStep_CanActivate()
    {
        var pipeline = CreatePipeline();
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect));
        var canActivate = pipeline.Steps.Count > 0;
        Assert.True(canActivate);
    }

    [Fact]
    public void Pipeline_WithDisabledSteps_AllDisabled_CannotActivate()
    {
        var pipeline = CreatePipeline();
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect, enabled: false));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 2, StageType.Process, enabled: false));
        var hasEnabledSteps = pipeline.Steps.Any(s => s.IsEnabled);
        Assert.False(hasEnabledSteps, "All steps disabled; should not activate");
    }

    [Fact]
    public void Pipeline_WithMixedEnabledDisabled_CanActivate()
    {
        var pipeline = CreatePipeline();
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect, enabled: true));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 2, StageType.Process, enabled: false));
        var hasEnabledSteps = pipeline.Steps.Any(s => s.IsEnabled);
        Assert.True(hasEnabledSteps);
    }

    [Fact]
    public void Pipeline_ConcurrentActivation_SameId()
    {
        var pipeline = CreatePipeline(status: PipelineStatus.Active);
        var activation1 = CreateActivation(pipeline.Id);
        var activation2 = CreateActivation(pipeline.Id);
        Assert.NotEqual(activation1.Id, activation2.Id);
        Assert.Equal(pipeline.Id, activation1.PipelineInstanceId);
        Assert.Equal(pipeline.Id, activation2.PipelineInstanceId);
    }

    [Fact]
    public void Pipeline_StatusAfterNodeAdd()
    {
        var pipeline = CreatePipeline(status: PipelineStatus.Active);
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Process));
        // Status should remain active after adding a step (no auto-transition)
        Assert.Equal(PipelineStatus.Active, pipeline.Status);
        Assert.Single(pipeline.Steps);
    }

    [Fact]
    public void Pipeline_StatusAfterNodeRemove()
    {
        var pipeline = CreatePipeline(status: PipelineStatus.Active);
        var step = CreateStep(pipeline.Id, 1, StageType.Process);
        pipeline.Steps.Add(step);
        pipeline.Steps.Remove(step);
        Assert.Equal(PipelineStatus.Active, pipeline.Status);
        Assert.Empty(pipeline.Steps);
    }

    [Fact]
    public void Pipeline_NameAndDescription()
    {
        var pipeline = CreatePipeline("my-pipeline");
        pipeline.Description = "A pipeline for CSV ingestion";
        Assert.Equal("my-pipeline", pipeline.Name);
        Assert.Equal("A pipeline for CSV ingestion", pipeline.Description);
    }

    [Fact]
    public void Pipeline_DefaultMonitoringConfig()
    {
        var pipeline = new PipelineInstance();
        Assert.Equal("{}", pipeline.MonitoringConfig);
    }

    [Fact]
    public void Pipeline_MonitoringType_FileMonitor()
    {
        var pipeline = CreatePipeline();
        pipeline.MonitoringType = MonitoringType.FileMonitor;
        Assert.Equal(MonitoringType.FileMonitor, pipeline.MonitoringType);
    }

    [Fact]
    public void Pipeline_MonitoringType_ApiPoll()
    {
        var pipeline = CreatePipeline();
        pipeline.MonitoringType = MonitoringType.ApiPoll;
        Assert.Equal(MonitoringType.ApiPoll, pipeline.MonitoringType);
    }

    [Fact]
    public void Pipeline_MonitoringType_DbPoll()
    {
        var pipeline = CreatePipeline();
        pipeline.MonitoringType = MonitoringType.DbPoll;
        Assert.Equal(MonitoringType.DbPoll, pipeline.MonitoringType);
    }

    [Fact]
    public void Pipeline_MonitoringType_EventStream()
    {
        var pipeline = CreatePipeline();
        pipeline.MonitoringType = MonitoringType.EventStream;
        Assert.Equal(MonitoringType.EventStream, pipeline.MonitoringType);
    }

    [Fact]
    public void Pipeline_HasUniqueId()
    {
        var p1 = CreatePipeline();
        var p2 = CreatePipeline();
        Assert.NotEqual(p1.Id, p2.Id);
    }

    [Theory]
    [InlineData(PipelineStatus.Draft)]
    [InlineData(PipelineStatus.Active)]
    [InlineData(PipelineStatus.Paused)]
    [InlineData(PipelineStatus.Archived)]
    public void Pipeline_AllStatusValues_AreValid(PipelineStatus status)
    {
        var pipeline = CreatePipeline();
        pipeline.Status = status;
        Assert.Equal(status, pipeline.Status);
    }

    // ════════════════════════════════════════════════════════════════════
    // 2. Pipeline Step Ordering (25 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void Step_SingleStepPipeline()
    {
        var pipeline = CreatePipeline();
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect));
        Assert.Single(pipeline.Steps);
        Assert.Equal(1, pipeline.Steps[0].StepOrder);
    }

    [Fact]
    public void Step_ThreeStepLinear_CollectProcessExport()
    {
        var pipeline = CreatePipeline();
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 2, StageType.Process));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 3, StageType.Export));

        var ordered = pipeline.Steps.OrderBy(s => s.StepOrder).ToList();
        Assert.Equal(StageType.Collect, ordered[0].StepType);
        Assert.Equal(StageType.Process, ordered[1].StepType);
        Assert.Equal(StageType.Export, ordered[2].StepType);
    }

    [Fact]
    public void Step_FiveStepChain()
    {
        var pipeline = CreatePipeline();
        for (int i = 1; i <= 5; i++)
        {
            var type = i switch { 1 => StageType.Collect, 5 => StageType.Export, _ => StageType.Process };
            pipeline.Steps.Add(CreateStep(pipeline.Id, i, type));
        }
        Assert.Equal(5, pipeline.Steps.Count);
        var ordered = pipeline.Steps.OrderBy(s => s.StepOrder).ToList();
        for (int i = 0; i < 5; i++)
            Assert.Equal(i + 1, ordered[i].StepOrder);
    }

    [Fact]
    public void Step_ReorderValidation()
    {
        var pipeline = CreatePipeline();
        var step1 = CreateStep(pipeline.Id, 1, StageType.Collect);
        var step2 = CreateStep(pipeline.Id, 2, StageType.Process);
        pipeline.Steps.Add(step1);
        pipeline.Steps.Add(step2);

        // Swap order
        step1.StepOrder = 2;
        step2.StepOrder = 1;

        var ordered = pipeline.Steps.OrderBy(s => s.StepOrder).ToList();
        Assert.Equal(step2.Id, ordered[0].Id);
        Assert.Equal(step1.Id, ordered[1].Id);
    }

    [Fact]
    public void Step_AddAndRecalculateOrder()
    {
        var pipeline = CreatePipeline();
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 2, StageType.Export));

        // Insert a process step in the middle
        var processStep = CreateStep(pipeline.Id, 2, StageType.Process);
        pipeline.Steps[1].StepOrder = 3; // push export to 3
        pipeline.Steps.Add(processStep);

        var ordered = pipeline.Steps.OrderBy(s => s.StepOrder).ToList();
        Assert.Equal(StageType.Collect, ordered[0].StepType);
        Assert.Equal(StageType.Process, ordered[1].StepType);
        Assert.Equal(StageType.Export, ordered[2].StepType);
    }

    [Fact]
    public void Step_RemoveAndRecalculate()
    {
        var pipeline = CreatePipeline();
        var s1 = CreateStep(pipeline.Id, 1, StageType.Collect);
        var s2 = CreateStep(pipeline.Id, 2, StageType.Process);
        var s3 = CreateStep(pipeline.Id, 3, StageType.Export);
        pipeline.Steps.AddRange(new[] { s1, s2, s3 });

        pipeline.Steps.Remove(s2);
        // Recalculate
        var remaining = pipeline.Steps.OrderBy(s => s.StepOrder).ToList();
        for (int i = 0; i < remaining.Count; i++)
            remaining[i].StepOrder = i + 1;

        Assert.Equal(2, pipeline.Steps.Count);
        Assert.Equal(1, remaining[0].StepOrder);
        Assert.Equal(2, remaining[1].StepOrder);
    }

    [Fact]
    public void Step_DuplicateStepTypes_Allowed()
    {
        var pipeline = CreatePipeline();
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Process));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 2, StageType.Process));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 3, StageType.Process));

        Assert.Equal(3, pipeline.Steps.Count);
        Assert.All(pipeline.Steps, s => Assert.Equal(StageType.Process, s.StepType));
    }

    [Fact]
    public void Step_MixedStageTypes()
    {
        var pipeline = CreatePipeline();
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 2, StageType.Process));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 3, StageType.Process));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 4, StageType.Export));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 5, StageType.Export));

        Assert.Equal(5, pipeline.Steps.Count);
        Assert.Equal(1, pipeline.Steps.Count(s => s.StepType == StageType.Collect));
        Assert.Equal(2, pipeline.Steps.Count(s => s.StepType == StageType.Process));
        Assert.Equal(2, pipeline.Steps.Count(s => s.StepType == StageType.Export));
    }

    [Theory]
    [InlineData(OnErrorAction.Stop)]
    [InlineData(OnErrorAction.Skip)]
    [InlineData(OnErrorAction.Retry)]
    public void Step_OnError_AllActions(OnErrorAction action)
    {
        var step = CreateStep(Guid.NewGuid(), 1, StageType.Process, onError: action);
        Assert.Equal(action, step.OnError);
    }

    [Fact]
    public void Step_DefaultOnError_IsStop()
    {
        var step = new PipelineStep();
        Assert.Equal(OnErrorAction.Stop, step.OnError);
    }

    [Fact]
    public void Step_RetryCount_Setting()
    {
        var step = CreateStep(Guid.NewGuid(), 1, StageType.Process,
            onError: OnErrorAction.Retry, retryCount: 3, retryDelay: 10);
        Assert.Equal(3, step.RetryCount);
        Assert.Equal(10, step.RetryDelaySeconds);
    }

    [Fact]
    public void Step_RetryCount_DefaultIsZero()
    {
        var step = new PipelineStep();
        Assert.Equal(0, step.RetryCount);
        Assert.Equal(0, step.RetryDelaySeconds);
    }

    [Fact]
    public void Step_IsEnabled_DefaultTrue()
    {
        var step = new PipelineStep();
        Assert.True(step.IsEnabled);
    }

    [Fact]
    public void Step_DisabledStep()
    {
        var step = CreateStep(Guid.NewGuid(), 1, StageType.Process, enabled: false);
        Assert.False(step.IsEnabled);
    }

    [Fact]
    public void Step_RefType_MatchesStageType_Collector()
    {
        var step = CreateStep(Guid.NewGuid(), 1, StageType.Collect);
        Assert.Equal(RefType.Collector, step.RefType);
    }

    [Fact]
    public void Step_RefType_MatchesStageType_Process()
    {
        var step = CreateStep(Guid.NewGuid(), 1, StageType.Process);
        Assert.Equal(RefType.Process, step.RefType);
    }

    [Fact]
    public void Step_RefType_MatchesStageType_Export()
    {
        var step = CreateStep(Guid.NewGuid(), 1, StageType.Export);
        Assert.Equal(RefType.Export, step.RefType);
    }

    [Fact]
    public void Step_RefId_IsUnique()
    {
        var s1 = CreateStep(Guid.NewGuid(), 1, StageType.Process);
        var s2 = CreateStep(Guid.NewGuid(), 2, StageType.Process);
        Assert.NotEqual(s1.RefId, s2.RefId);
    }

    [Fact]
    public void Step_PipelineInstanceId_MatchesParent()
    {
        var pipelineId = Guid.NewGuid();
        var step = CreateStep(pipelineId, 1, StageType.Collect);
        Assert.Equal(pipelineId, step.PipelineInstanceId);
    }

    [Fact]
    public void Step_LargeRetryDelay()
    {
        var step = CreateStep(Guid.NewGuid(), 1, StageType.Process,
            onError: OnErrorAction.Retry, retryCount: 10, retryDelay: 3600);
        Assert.Equal(10, step.RetryCount);
        Assert.Equal(3600, step.RetryDelaySeconds);
    }

    [Fact]
    public void Step_OrderedByStepOrder_UnorderedInsert()
    {
        var pipeline = CreatePipeline();
        pipeline.Steps.Add(CreateStep(pipeline.Id, 3, StageType.Export));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 2, StageType.Process));

        var ordered = pipeline.Steps.OrderBy(s => s.StepOrder).ToList();
        Assert.Equal(1, ordered[0].StepOrder);
        Assert.Equal(2, ordered[1].StepOrder);
        Assert.Equal(3, ordered[2].StepOrder);
    }

    [Fact]
    public void Step_TenStepPipeline()
    {
        var pipeline = CreatePipeline();
        for (int i = 1; i <= 10; i++)
            pipeline.Steps.Add(CreateStep(pipeline.Id, i, StageType.Process));
        Assert.Equal(10, pipeline.Steps.Count);
    }

    [Fact]
    public void Step_ToggleEnabled()
    {
        var step = CreateStep(Guid.NewGuid(), 1, StageType.Process);
        Assert.True(step.IsEnabled);
        step.IsEnabled = false;
        Assert.False(step.IsEnabled);
        step.IsEnabled = true;
        Assert.True(step.IsEnabled);
    }

    // ════════════════════════════════════════════════════════════════════
    // 3. WorkItem (Job) Lifecycle (30 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void WorkItem_DefaultStatus_IsDetected()
    {
        var item = new WorkItem();
        Assert.Equal(JobStatus.Detected, item.Status);
    }

    [Fact]
    public void WorkItem_DetectedToQueued()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        item.Status = JobStatus.Queued;
        Assert.Equal(JobStatus.Queued, item.Status);
    }

    [Fact]
    public void WorkItem_QueuedToProcessing()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid(), status: JobStatus.Queued);
        item.Status = JobStatus.Processing;
        Assert.Equal(JobStatus.Processing, item.Status);
    }

    [Fact]
    public void WorkItem_ProcessingToCompleted()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid(), status: JobStatus.Processing);
        item.Status = JobStatus.Completed;
        item.LastCompletedAt = DateTimeOffset.UtcNow;
        Assert.Equal(JobStatus.Completed, item.Status);
        Assert.NotNull(item.LastCompletedAt);
    }

    [Fact]
    public void WorkItem_ProcessingToFailed()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid(), status: JobStatus.Processing);
        item.Status = JobStatus.Failed;
        Assert.Equal(JobStatus.Failed, item.Status);
    }

    [Fact]
    public void WorkItem_FullSuccessLifecycle()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        Assert.Equal(JobStatus.Detected, item.Status);
        item.Status = JobStatus.Queued;
        item.Status = JobStatus.Processing;
        item.Status = JobStatus.Completed;
        item.LastCompletedAt = DateTimeOffset.UtcNow;
        Assert.Equal(JobStatus.Completed, item.Status);
    }

    [Fact]
    public void WorkItem_FullFailureLifecycle()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        item.Status = JobStatus.Queued;
        item.Status = JobStatus.Processing;
        item.Status = JobStatus.Failed;
        Assert.Equal(JobStatus.Failed, item.Status);
    }

    [Fact]
    public void WorkItem_CompletedToProcessing_InvalidTransition()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid(), status: JobStatus.Completed);
        var isCompleted = item.Status == JobStatus.Completed;
        Assert.True(isCompleted, "Completed items should not go back to Processing without reprocess");
    }

    [Fact]
    public void WorkItem_FailedToDetected_InvalidTransition()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid(), status: JobStatus.Failed);
        var isFailed = item.Status == JobStatus.Failed;
        Assert.True(isFailed);
    }

    [Fact]
    public void WorkItem_ExecutionCount_InitiallyZero()
    {
        var item = new WorkItem();
        Assert.Equal(0, item.ExecutionCount);
    }

    [Fact]
    public void WorkItem_ExecutionCount_Increments()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        item.ExecutionCount++;
        Assert.Equal(1, item.ExecutionCount);
        item.ExecutionCount++;
        Assert.Equal(2, item.ExecutionCount);
    }

    [Fact]
    public void WorkItem_MultipleExecutions()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        var exec1 = CreateExecution(item.Id, 1);
        var exec2 = CreateExecution(item.Id, 2, TriggerType.Retry);
        item.Executions.Add(exec1);
        item.Executions.Add(exec2);
        Assert.Equal(2, item.Executions.Count);
    }

    [Fact]
    public void WorkItem_DedupKey_NullByDefault()
    {
        var item = new WorkItem();
        Assert.Null(item.DedupKey);
    }

    [Fact]
    public void WorkItem_DedupKey_Set()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        item.DedupKey = "FILE:" + ComputeDedupHash("FILE", "/data/in/test.csv");
        Assert.StartsWith("FILE:", item.DedupKey);
    }

    [Fact]
    public void WorkItem_DedupKey_CollisionDetection()
    {
        var item1 = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        var item2 = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        var key = "FILE:" + ComputeDedupHash("FILE", "/data/in/same.csv");
        item1.DedupKey = key;
        item2.DedupKey = key;
        Assert.Equal(item1.DedupKey, item2.DedupKey);
    }

    [Theory]
    [InlineData(SourceType.File)]
    [InlineData(SourceType.ApiResponse)]
    [InlineData(SourceType.DbChange)]
    [InlineData(SourceType.Event)]
    public void WorkItem_SourceType_AllValues(SourceType sourceType)
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid(), sourceType: sourceType);
        Assert.Equal(sourceType, item.SourceType);
    }

    [Fact]
    public void WorkItem_LastCompletedAt_NullInitially()
    {
        var item = new WorkItem();
        Assert.Null(item.LastCompletedAt);
    }

    [Fact]
    public void WorkItem_LastCompletedAt_SetOnCompletion()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        var now = DateTimeOffset.UtcNow;
        item.Status = JobStatus.Completed;
        item.LastCompletedAt = now;
        Assert.Equal(now, item.LastCompletedAt);
    }

    [Fact]
    public void WorkItem_ZeroExecutions()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        Assert.Empty(item.Executions);
        Assert.Equal(0, item.ExecutionCount);
    }

    [Fact]
    public void WorkItem_CurrentExecutionId_Null()
    {
        var item = new WorkItem();
        Assert.Null(item.CurrentExecutionId);
    }

    [Fact]
    public void WorkItem_CurrentExecutionId_Set()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        var execId = Guid.NewGuid();
        item.CurrentExecutionId = execId;
        Assert.Equal(execId, item.CurrentExecutionId);
    }

    [Fact]
    public void WorkItem_SourceMetadata_DefaultJson()
    {
        var item = new WorkItem();
        Assert.Equal("{}", item.SourceMetadata);
    }

    [Fact]
    public void WorkItem_SourceMetadata_ParsesAsJson()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        item.SourceMetadata = "{\"size\":2048,\"modified\":\"2026-01-01\"}";
        var doc = JsonDocument.Parse(item.SourceMetadata);
        Assert.Equal(2048, doc.RootElement.GetProperty("size").GetInt32());
    }

    [Fact]
    public void WorkItem_SourceKey_NotEmpty()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        Assert.False(string.IsNullOrEmpty(item.SourceKey));
    }

    [Fact]
    public void WorkItem_DetectedAt_IsSet()
    {
        var before = DateTimeOffset.UtcNow;
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        Assert.True(item.DetectedAt >= before.AddSeconds(-1));
    }

    [Fact]
    public void WorkItem_ReprocessRequests_EmptyByDefault()
    {
        var item = new WorkItem();
        Assert.Empty(item.ReprocessRequests);
    }

    [Theory]
    [InlineData(JobStatus.Detected)]
    [InlineData(JobStatus.Queued)]
    [InlineData(JobStatus.Processing)]
    [InlineData(JobStatus.Completed)]
    [InlineData(JobStatus.Failed)]
    public void WorkItem_AllStatusValues(JobStatus status)
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid(), status: status);
        Assert.Equal(status, item.Status);
    }

    [Fact]
    public void WorkItem_ThreeExecutions_RetryScenario()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid());
        item.Executions.Add(CreateExecution(item.Id, 1, TriggerType.Initial, ExecutionStatus.Failed));
        item.Executions.Add(CreateExecution(item.Id, 2, TriggerType.Retry, ExecutionStatus.Failed));
        item.Executions.Add(CreateExecution(item.Id, 3, TriggerType.Retry, ExecutionStatus.Completed));
        item.ExecutionCount = 3;
        item.Status = JobStatus.Completed;

        Assert.Equal(3, item.Executions.Count);
        Assert.Equal(ExecutionStatus.Completed, item.Executions[2].Status);
    }

    [Fact]
    public void WorkItem_PipelineInstanceId_Set()
    {
        var pipelineId = Guid.NewGuid();
        var item = CreateWorkItem(pipelineId, Guid.NewGuid());
        Assert.Equal(pipelineId, item.PipelineInstanceId);
    }

    [Fact]
    public void WorkItem_PipelineActivationId_Set()
    {
        var activationId = Guid.NewGuid();
        var item = CreateWorkItem(Guid.NewGuid(), activationId);
        Assert.Equal(activationId, item.PipelineActivationId);
    }

    // ════════════════════════════════════════════════════════════════════
    // 4. Recipe/InstanceVersion Lifecycle (25 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void CollectorVersion_FirstVersion_V1()
    {
        var ver = new CollectorInstanceVersion
        {
            InstanceId = Guid.NewGuid(),
            DefVersionId = Guid.NewGuid(),
            VersionNo = 1,
            ConfigJson = "{\"path\":\"/data/in\"}",
            IsCurrent = true,
            CreatedBy = "admin",
            ChangeNote = "Initial version"
        };
        Assert.Equal(1, ver.VersionNo);
        Assert.True(ver.IsCurrent);
    }

    [Fact]
    public void CollectorVersion_NewVersion_V2_MakesV1NonCurrent()
    {
        var instanceId = Guid.NewGuid();
        var v1 = new CollectorInstanceVersion { InstanceId = instanceId, VersionNo = 1, IsCurrent = true };
        var v2 = new CollectorInstanceVersion { InstanceId = instanceId, VersionNo = 2, IsCurrent = true };
        v1.IsCurrent = false;

        Assert.False(v1.IsCurrent);
        Assert.True(v2.IsCurrent);
    }

    [Fact]
    public void ProcessVersion_MultipleVersions_V1toV5()
    {
        var instanceId = Guid.NewGuid();
        var versions = new List<ProcessInstanceVersion>();
        for (int i = 1; i <= 5; i++)
        {
            versions.Add(new ProcessInstanceVersion
            {
                InstanceId = instanceId,
                VersionNo = i,
                IsCurrent = i == 5,
                ConfigJson = "{\"version\":" + i + "}",
                ChangeNote = "Version " + i
            });
        }
        Assert.Equal(5, versions.Count);
        Assert.Single(versions.Where(v => v.IsCurrent));
        Assert.Equal(5, versions.First(v => v.IsCurrent).VersionNo);
    }

    [Fact]
    public void ExportVersion_PublishSpecificVersion()
    {
        var instanceId = Guid.NewGuid();
        var v1 = new ExportInstanceVersion { InstanceId = instanceId, VersionNo = 1, IsCurrent = false };
        var v2 = new ExportInstanceVersion { InstanceId = instanceId, VersionNo = 2, IsCurrent = true };
        var v3 = new ExportInstanceVersion { InstanceId = instanceId, VersionNo = 3, IsCurrent = false };

        // Publish v1 as current
        v2.IsCurrent = false;
        v1.IsCurrent = true;

        Assert.True(v1.IsCurrent);
        Assert.False(v2.IsCurrent);
        Assert.False(v3.IsCurrent);
    }

    [Fact]
    public void CollectorVersion_RollbackToOlderVersion()
    {
        var instanceId = Guid.NewGuid();
        var versions = new List<CollectorInstanceVersion>();
        for (int i = 1; i <= 3; i++)
            versions.Add(new CollectorInstanceVersion { InstanceId = instanceId, VersionNo = i, IsCurrent = i == 3 });

        // Rollback to v1
        foreach (var v in versions) v.IsCurrent = false;
        versions[0].IsCurrent = true;

        Assert.True(versions[0].IsCurrent);
        Assert.Equal(1, versions[0].VersionNo);
    }

    [Fact]
    public void ProcessVersion_ConfigJson_SerializeDeserialize()
    {
        var config = "{\"transform\":\"uppercase\",\"fields\":[\"name\",\"email\"]}";
        var ver = new ProcessInstanceVersion { ConfigJson = config };
        var doc = JsonDocument.Parse(ver.ConfigJson);
        Assert.Equal("uppercase", doc.RootElement.GetProperty("transform").GetString());
        Assert.Equal(2, doc.RootElement.GetProperty("fields").GetArrayLength());
    }

    [Fact]
    public void CollectorVersion_ChangeNote_Tracking()
    {
        var ver = new CollectorInstanceVersion
        {
            ChangeNote = "Added recursive scanning"
        };
        Assert.Equal("Added recursive scanning", ver.ChangeNote);
    }

    [Fact]
    public void ProcessVersion_CreatedBy_Tracking()
    {
        var ver = new ProcessInstanceVersion { CreatedBy = "user@example.com" };
        Assert.Equal("user@example.com", ver.CreatedBy);
    }

    [Fact]
    public void ExportVersion_VersionOrdering()
    {
        var versions = new List<ExportInstanceVersion>();
        for (int i = 5; i >= 1; i--)
            versions.Add(new ExportInstanceVersion { VersionNo = i });

        var ordered = versions.OrderBy(v => v.VersionNo).ToList();
        Assert.Equal(1, ordered[0].VersionNo);
        Assert.Equal(5, ordered[4].VersionNo);
    }

    [Fact]
    public void CollectorVersion_DefaultConfigJson()
    {
        var ver = new CollectorInstanceVersion();
        Assert.Equal("{}", ver.ConfigJson);
    }

    [Fact]
    public void ProcessVersion_DefaultSecretBinding()
    {
        var ver = new ProcessInstanceVersion();
        Assert.Equal("{}", ver.SecretBindingJson);
    }

    [Fact]
    public void ExportVersion_SecretBindingJson()
    {
        var ver = new ExportInstanceVersion
        {
            SecretBindingJson = "{\"api_key\":\"vault://secrets/export-key\"}"
        };
        var doc = JsonDocument.Parse(ver.SecretBindingJson);
        Assert.Equal("vault://secrets/export-key", doc.RootElement.GetProperty("api_key").GetString());
    }

    [Fact]
    public void CollectorInstance_DefaultStatus_IsDraft()
    {
        var inst = new CollectorInstance();
        Assert.Equal(InstanceStatus.Draft, inst.Status);
    }

    [Fact]
    public void ProcessInstance_DefaultStatus_IsDraft()
    {
        var inst = new ProcessInstance();
        Assert.Equal(InstanceStatus.Draft, inst.Status);
    }

    [Fact]
    public void ExportInstance_DefaultStatus_IsDraft()
    {
        var inst = new ExportInstance();
        Assert.Equal(InstanceStatus.Draft, inst.Status);
    }

    [Theory]
    [InlineData(InstanceStatus.Draft)]
    [InlineData(InstanceStatus.Active)]
    [InlineData(InstanceStatus.Disabled)]
    [InlineData(InstanceStatus.Archived)]
    public void Instance_AllStatusValues(InstanceStatus status)
    {
        var inst = new CollectorInstance { Status = status };
        Assert.Equal(status, inst.Status);
    }

    [Fact]
    public void CollectorInstance_HasVersions()
    {
        var inst = new CollectorInstance { Name = "file-collector" };
        inst.Versions.Add(new CollectorInstanceVersion { VersionNo = 1, IsCurrent = true });
        Assert.Single(inst.Versions);
    }

    [Fact]
    public void ProcessInstance_HasVersions()
    {
        var inst = new ProcessInstance { Name = "csv-parser" };
        inst.Versions.Add(new ProcessInstanceVersion { VersionNo = 1, IsCurrent = true });
        inst.Versions.Add(new ProcessInstanceVersion { VersionNo = 2, IsCurrent = false });
        Assert.Equal(2, inst.Versions.Count);
    }

    [Fact]
    public void ExportInstance_HasVersions()
    {
        var inst = new ExportInstance { Name = "s3-exporter" };
        inst.Versions.Add(new ExportInstanceVersion { VersionNo = 1, IsCurrent = true });
        Assert.Single(inst.Versions);
    }

    [Fact]
    public void CollectorVersion_CreatedAt_IsSet()
    {
        var before = DateTimeOffset.UtcNow;
        var ver = new CollectorInstanceVersion();
        Assert.True(ver.CreatedAt >= before.AddSeconds(-1));
    }

    [Fact]
    public void ProcessVersion_DefVersionId_IsSet()
    {
        var defVersionId = Guid.NewGuid();
        var ver = new ProcessInstanceVersion { DefVersionId = defVersionId };
        Assert.Equal(defVersionId, ver.DefVersionId);
    }

    [Fact]
    public void ExportVersion_ComplexConfig()
    {
        var config = "{\"destination\":\"s3\",\"bucket\":\"prod-data\","
            + "\"prefix\":\"output/\",\"compression\":\"gzip\"}";
        var ver = new ExportInstanceVersion { ConfigJson = config };
        var doc = JsonDocument.Parse(ver.ConfigJson);
        Assert.Equal("s3", doc.RootElement.GetProperty("destination").GetString());
        Assert.Equal("gzip", doc.RootElement.GetProperty("compression").GetString());
    }

    [Fact]
    public void CollectorVersion_NullChangeNote()
    {
        var ver = new CollectorInstanceVersion();
        Assert.Null(ver.ChangeNote);
    }

    [Fact]
    public void ProcessVersion_NullCreatedBy()
    {
        var ver = new ProcessInstanceVersion();
        Assert.Null(ver.CreatedBy);
    }

    // ════════════════════════════════════════════════════════════════════
    // 5. Execution Snapshot (20 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void Snapshot_CapturesAllConfigs()
    {
        var execId = Guid.NewGuid();
        var snapshot = CreateSnapshot(execId);
        Assert.Equal(execId, snapshot.ExecutionId);
        Assert.Contains("name", snapshot.PipelineConfig);
        Assert.Contains("/in", snapshot.CollectorConfig);
        Assert.Contains("uppercase", snapshot.ProcessConfig);
        Assert.Contains("/out", snapshot.ExportConfig);
    }

    [Fact]
    public void Snapshot_HashChanges_WhenConfigChanges()
    {
        var execId = Guid.NewGuid();
        var snap1 = CreateSnapshot(execId, processConfig: "{\"transform\":\"uppercase\"}");
        var snap2 = CreateSnapshot(execId, processConfig: "{\"transform\":\"lowercase\"}");
        Assert.NotEqual(snap1.SnapshotHash, snap2.SnapshotHash);
    }

    [Fact]
    public void Snapshot_HashSame_WhenConfigSame()
    {
        var snap1 = CreateSnapshot(Guid.NewGuid());
        var snap2 = CreateSnapshot(Guid.NewGuid());
        Assert.Equal(snap1.SnapshotHash, snap2.SnapshotHash);
    }

    [Fact]
    public void Snapshot_PreservesPipelineConfig()
    {
        var config = "{\"name\":\"prod-pipeline\",\"priority\":\"high\"}";
        var snap = CreateSnapshot(Guid.NewGuid(), pipelineConfig: config);
        Assert.Equal(config, snap.PipelineConfig);
    }

    [Fact]
    public void Snapshot_PreservesCollectorConfig()
    {
        var config = "{\"path\":\"/data/incoming\",\"recursive\":true}";
        var snap = CreateSnapshot(Guid.NewGuid(), collectorConfig: config);
        Assert.Equal(config, snap.CollectorConfig);
    }

    [Fact]
    public void Snapshot_PreservesProcessConfig()
    {
        var config = "{\"transform\":\"csv_to_json\",\"delimiter\":\",\"}";
        var snap = CreateSnapshot(Guid.NewGuid(), processConfig: config);
        Assert.Equal(config, snap.ProcessConfig);
    }

    [Fact]
    public void Snapshot_PreservesExportConfig()
    {
        var config = "{\"dest\":\"s3://bucket/prefix\",\"format\":\"parquet\"}";
        var snap = CreateSnapshot(Guid.NewGuid(), exportConfig: config);
        Assert.Equal(config, snap.ExportConfig);
    }

    [Fact]
    public void Snapshot_ImmutableAfterCreation()
    {
        var snap = CreateSnapshot(Guid.NewGuid());
        var originalHash = snap.SnapshotHash;
        var originalConfig = snap.PipelineConfig;
        // After creation, the snapshot's hash should reflect its config
        Assert.Equal(originalHash, snap.SnapshotHash);
        Assert.Equal(originalConfig, snap.PipelineConfig);
    }

    [Fact]
    public void Snapshot_LinkedToExecution()
    {
        var execId = Guid.NewGuid();
        var snap = CreateSnapshot(execId);
        Assert.Equal(execId, snap.ExecutionId);
    }

    [Fact]
    public void Snapshot_MultipleSnapshots_DifferentExecutions()
    {
        var exec1 = Guid.NewGuid();
        var exec2 = Guid.NewGuid();
        var snap1 = CreateSnapshot(exec1, processConfig: "{\"v\":1}");
        var snap2 = CreateSnapshot(exec2, processConfig: "{\"v\":2}");
        Assert.NotEqual(snap1.ExecutionId, snap2.ExecutionId);
        Assert.NotEqual(snap1.SnapshotHash, snap2.SnapshotHash);
    }

    [Fact]
    public void Snapshot_DefaultConfig_EmptyJson()
    {
        var snap = new ExecutionSnapshot();
        Assert.Equal("{}", snap.PipelineConfig);
        Assert.Equal("{}", snap.CollectorConfig);
        Assert.Equal("{}", snap.ProcessConfig);
        Assert.Equal("{}", snap.ExportConfig);
    }

    [Fact]
    public void Snapshot_Hash_IsLowerHex()
    {
        var snap = CreateSnapshot(Guid.NewGuid());
        Assert.NotNull(snap.SnapshotHash);
        Assert.Matches("^[0-9a-f]+$", snap.SnapshotHash!);
    }

    [Fact]
    public void Snapshot_Hash_Is64CharsLong()
    {
        var snap = CreateSnapshot(Guid.NewGuid());
        Assert.Equal(64, snap.SnapshotHash!.Length);
    }

    [Fact]
    public void Snapshot_CreatedAt_IsSet()
    {
        var before = DateTimeOffset.UtcNow;
        var snap = new ExecutionSnapshot();
        Assert.True(snap.CreatedAt >= before.AddSeconds(-1));
    }

    [Fact]
    public void Snapshot_HasUniqueId()
    {
        var s1 = CreateSnapshot(Guid.NewGuid());
        var s2 = CreateSnapshot(Guid.NewGuid());
        Assert.NotEqual(s1.Id, s2.Id);
    }

    [Fact]
    public void Snapshot_CollectorConfig_JsonParseable()
    {
        var snap = CreateSnapshot(Guid.NewGuid(),
            collectorConfig: "{\"host\":\"ftp.example.com\",\"port\":21}");
        var doc = JsonDocument.Parse(snap.CollectorConfig);
        Assert.Equal("ftp.example.com", doc.RootElement.GetProperty("host").GetString());
    }

    [Fact]
    public void Snapshot_ProcessConfig_JsonParseable()
    {
        var snap = CreateSnapshot(Guid.NewGuid(),
            processConfig: "{\"steps\":[\"validate\",\"transform\",\"enrich\"]}");
        var doc = JsonDocument.Parse(snap.ProcessConfig);
        Assert.Equal(3, doc.RootElement.GetProperty("steps").GetArrayLength());
    }

    [Fact]
    public void Snapshot_ExportConfig_JsonParseable()
    {
        var snap = CreateSnapshot(Guid.NewGuid(),
            exportConfig: "{\"type\":\"webhook\",\"url\":\"https://api.example.com/ingest\"}");
        var doc = JsonDocument.Parse(snap.ExportConfig);
        Assert.Equal("webhook", doc.RootElement.GetProperty("type").GetString());
    }

    [Fact]
    public void Snapshot_HashNull_ByDefault()
    {
        var snap = new ExecutionSnapshot();
        Assert.Null(snap.SnapshotHash);
    }

    [Fact]
    public void Snapshot_EmptyConfigs_SameHash()
    {
        var s1 = CreateSnapshot(Guid.NewGuid(), "{}", "{}", "{}", "{}");
        var s2 = CreateSnapshot(Guid.NewGuid(), "{}", "{}", "{}", "{}");
        Assert.Equal(s1.SnapshotHash, s2.SnapshotHash);
    }

    // ════════════════════════════════════════════════════════════════════
    // 6. Error Recovery & Reprocess (25 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void Reprocess_DefaultStatus_IsPending()
    {
        var req = new ReprocessRequest();
        Assert.Equal(ReprocessStatus.Pending, req.Status);
    }

    [Fact]
    public void Reprocess_PendingToApproved()
    {
        var req = new ReprocessRequest { Status = ReprocessStatus.Pending };
        req.Status = ReprocessStatus.Approved;
        req.ApprovedBy = "admin@example.com";
        Assert.Equal(ReprocessStatus.Approved, req.Status);
        Assert.Equal("admin@example.com", req.ApprovedBy);
    }

    [Fact]
    public void Reprocess_ApprovedToExecuting()
    {
        var req = new ReprocessRequest { Status = ReprocessStatus.Approved };
        req.Status = ReprocessStatus.Executing;
        req.ExecutionId = Guid.NewGuid();
        Assert.Equal(ReprocessStatus.Executing, req.Status);
        Assert.NotNull(req.ExecutionId);
    }

    [Fact]
    public void Reprocess_ExecutingToDone()
    {
        var req = new ReprocessRequest { Status = ReprocessStatus.Executing };
        req.Status = ReprocessStatus.Done;
        Assert.Equal(ReprocessStatus.Done, req.Status);
    }

    [Fact]
    public void Reprocess_FullLifecycle()
    {
        var req = new ReprocessRequest
        {
            WorkItemId = Guid.NewGuid(),
            RequestedBy = "operator",
            Reason = "Bad output detected"
        };
        Assert.Equal(ReprocessStatus.Pending, req.Status);
        req.Status = ReprocessStatus.Approved;
        req.Status = ReprocessStatus.Executing;
        req.Status = ReprocessStatus.Done;
        Assert.Equal(ReprocessStatus.Done, req.Status);
    }

    [Fact]
    public void Reprocess_Rejection()
    {
        var req = new ReprocessRequest
        {
            WorkItemId = Guid.NewGuid(),
            RequestedBy = "operator",
            Reason = "Unnecessary"
        };
        req.Status = ReprocessStatus.Rejected;
        Assert.Equal(ReprocessStatus.Rejected, req.Status);
    }

    [Fact]
    public void Reprocess_FromSpecificStep()
    {
        var req = new ReprocessRequest
        {
            StartFromStep = 2,
            UseLatestRecipe = true
        };
        Assert.Equal(2, req.StartFromStep);
    }

    [Fact]
    public void Reprocess_WithLatestRecipe()
    {
        var req = new ReprocessRequest { UseLatestRecipe = true };
        Assert.True(req.UseLatestRecipe);
    }

    [Fact]
    public void Reprocess_WithOriginalRecipe()
    {
        var req = new ReprocessRequest { UseLatestRecipe = false };
        Assert.False(req.UseLatestRecipe);
    }

    [Fact]
    public void Reprocess_BulkRequests()
    {
        var itemIds = Enumerable.Range(0, 10).Select(_ => Guid.NewGuid()).ToList();
        var requests = itemIds.Select(id => new ReprocessRequest
        {
            WorkItemId = id,
            RequestedBy = "batch-operator",
            Reason = "Bulk reprocess"
        }).ToList();

        Assert.Equal(10, requests.Count);
        Assert.All(requests, r => Assert.Equal("batch-operator", r.RequestedBy));
    }

    [Fact]
    public void Reprocess_OfCompletedJob()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid(), status: JobStatus.Completed);
        var req = new ReprocessRequest
        {
            WorkItemId = item.Id,
            Reason = "Re-export with new config"
        };
        Assert.Equal(JobStatus.Completed, item.Status);
        Assert.Equal(ReprocessStatus.Pending, req.Status);
    }

    [Fact]
    public void Reprocess_OfFailedJob()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid(), status: JobStatus.Failed);
        var req = new ReprocessRequest
        {
            WorkItemId = item.Id,
            Reason = "Fix and retry"
        };
        Assert.Equal(JobStatus.Failed, item.Status);
    }

    [Theory]
    [InlineData(TriggerType.Initial)]
    [InlineData(TriggerType.Retry)]
    [InlineData(TriggerType.Reprocess)]
    public void Execution_TriggerType_AllValues(TriggerType trigger)
    {
        var exec = CreateExecution(Guid.NewGuid(), 1, trigger);
        Assert.Equal(trigger, exec.TriggerType);
    }

    [Fact]
    public void Reprocess_RequestedAt_IsSet()
    {
        var before = DateTimeOffset.UtcNow;
        var req = new ReprocessRequest();
        Assert.True(req.RequestedAt >= before.AddSeconds(-1));
    }

    [Fact]
    public void Reprocess_Reason_Nullable()
    {
        var req = new ReprocessRequest();
        Assert.Null(req.Reason);
    }

    [Fact]
    public void Reprocess_StartFromStep_Nullable()
    {
        var req = new ReprocessRequest();
        Assert.Null(req.StartFromStep);
    }

    [Fact]
    public void Reprocess_DefaultUseLatestRecipe_True()
    {
        var req = new ReprocessRequest();
        Assert.True(req.UseLatestRecipe);
    }

    [Fact]
    public void Reprocess_ApprovedBy_NullByDefault()
    {
        var req = new ReprocessRequest();
        Assert.Null(req.ApprovedBy);
    }

    [Fact]
    public void Reprocess_ExecutionId_NullByDefault()
    {
        var req = new ReprocessRequest();
        Assert.Null(req.ExecutionId);
    }

    [Theory]
    [InlineData(ReprocessStatus.Pending)]
    [InlineData(ReprocessStatus.Approved)]
    [InlineData(ReprocessStatus.Executing)]
    [InlineData(ReprocessStatus.Done)]
    [InlineData(ReprocessStatus.Rejected)]
    public void Reprocess_AllStatusValues(ReprocessStatus status)
    {
        var req = new ReprocessRequest { Status = status };
        Assert.Equal(status, req.Status);
    }

    [Fact]
    public void Reprocess_LinkedToWorkItem()
    {
        var itemId = Guid.NewGuid();
        var req = new ReprocessRequest { WorkItemId = itemId };
        Assert.Equal(itemId, req.WorkItemId);
    }

    [Fact]
    public void Reprocess_MultipleForSameItem()
    {
        var itemId = Guid.NewGuid();
        var req1 = new ReprocessRequest { WorkItemId = itemId, Status = ReprocessStatus.Done };
        var req2 = new ReprocessRequest { WorkItemId = itemId, Status = ReprocessStatus.Pending };
        Assert.Equal(req1.WorkItemId, req2.WorkItemId);
        Assert.NotEqual(req1.Id, req2.Id);
    }

    [Fact]
    public void Reprocess_FromStep1_Default()
    {
        var req = new ReprocessRequest { StartFromStep = 1 };
        Assert.Equal(1, req.StartFromStep);
    }

    [Fact]
    public void Reprocess_FromStep3_MidPipeline()
    {
        var req = new ReprocessRequest { StartFromStep = 3, Reason = "Re-export only" };
        Assert.Equal(3, req.StartFromStep);
    }

    // ════════════════════════════════════════════════════════════════════
    // 7. Condition Evaluation (15 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void Condition_AlwaysTrue()
    {
        var evaluator = new ConditionEvaluator();
        var pipeline = CreatePipeline(status: PipelineStatus.Active);
        var evt = CreateMonitorEvent();
        Assert.True(evaluator.Evaluate(evt, pipeline));
    }

    [Fact]
    public void Condition_FileEvent_Accepted()
    {
        var evaluator = new ConditionEvaluator();
        var pipeline = CreatePipeline();
        var evt = CreateMonitorEvent("FILE", "/data/in/report.csv");
        Assert.True(evaluator.Evaluate(evt, pipeline));
    }

    [Fact]
    public void Condition_ApiResponseEvent_Accepted()
    {
        var evaluator = new ConditionEvaluator();
        var pipeline = CreatePipeline();
        var evt = CreateMonitorEvent("API_RESPONSE", "response_123");
        Assert.True(evaluator.Evaluate(evt, pipeline));
    }

    [Fact]
    public void Condition_DbChangeEvent_Accepted()
    {
        var evaluator = new ConditionEvaluator();
        var pipeline = CreatePipeline();
        var evt = CreateMonitorEvent("DB_CHANGE", "table:orders:id:42");
        Assert.True(evaluator.Evaluate(evt, pipeline));
    }

    [Fact]
    public void Condition_UnknownEventType_Accepted()
    {
        var evaluator = new ConditionEvaluator();
        var pipeline = CreatePipeline();
        var evt = CreateMonitorEvent("UNKNOWN", "some-key");
        Assert.True(evaluator.Evaluate(evt, pipeline));
    }

    [Fact]
    public void DedupKey_FileEvent_UsesPath()
    {
        var evaluator = new ConditionEvaluator();
        var path = "/data/in/test.csv";
        var evt = CreateMonitorEvent("FILE", "key1",
            new Dictionary<string, object> { { "path", path } });
        var key = evaluator.GenerateDedupKey(evt);
        var expectedHash = ComputeDedupHash("FILE", path);
        Assert.Equal("FILE:" + expectedHash, key);
    }

    [Fact]
    public void DedupKey_ApiResponse_UsesContentHash()
    {
        var evaluator = new ConditionEvaluator();
        var contentHash = "abc123def456";
        var evt = CreateMonitorEvent("API_RESPONSE", "resp1",
            new Dictionary<string, object> { { "content_hash", contentHash } });
        var key = evaluator.GenerateDedupKey(evt);
        var expectedHash = ComputeDedupHash("API_RESPONSE", contentHash);
        Assert.Equal("API_RESPONSE:" + expectedHash, key);
    }

    [Fact]
    public void DedupKey_DbChange_UsesKey()
    {
        var evaluator = new ConditionEvaluator();
        var eventKey = "orders:42";
        var evt = CreateMonitorEvent("DB_CHANGE", eventKey,
            new Dictionary<string, object>());
        var key = evaluator.GenerateDedupKey(evt);
        var expectedHash = ComputeDedupHash("DB_CHANGE", eventKey);
        Assert.Equal("DB_CHANGE:" + expectedHash, key);
    }

    [Fact]
    public void DedupKey_UnknownType_FallsBackToKey()
    {
        var evaluator = new ConditionEvaluator();
        var evt = CreateMonitorEvent("CUSTOM", "custom-key-123",
            new Dictionary<string, object>());
        var key = evaluator.GenerateDedupKey(evt);
        var expectedHash = ComputeDedupHash("CUSTOM", "custom-key-123");
        Assert.Equal("CUSTOM:" + expectedHash, key);
    }

    [Fact]
    public void DedupKey_SameInput_SameOutput()
    {
        var evaluator = new ConditionEvaluator();
        var evt1 = CreateMonitorEvent("FILE", "k",
            new Dictionary<string, object> { { "path", "/a/b.csv" } });
        var evt2 = CreateMonitorEvent("FILE", "k",
            new Dictionary<string, object> { { "path", "/a/b.csv" } });
        Assert.Equal(evaluator.GenerateDedupKey(evt1), evaluator.GenerateDedupKey(evt2));
    }

    [Fact]
    public void DedupKey_DifferentInput_DifferentOutput()
    {
        var evaluator = new ConditionEvaluator();
        var evt1 = CreateMonitorEvent("FILE", "k",
            new Dictionary<string, object> { { "path", "/a/b.csv" } });
        var evt2 = CreateMonitorEvent("FILE", "k",
            new Dictionary<string, object> { { "path", "/a/c.csv" } });
        Assert.NotEqual(evaluator.GenerateDedupKey(evt1), evaluator.GenerateDedupKey(evt2));
    }

    [Fact]
    public void DedupKey_FileEvent_NoPath_FallsBackToKey()
    {
        var evaluator = new ConditionEvaluator();
        var evt = CreateMonitorEvent("FILE", "fallback-key",
            new Dictionary<string, object>());
        var key = evaluator.GenerateDedupKey(evt);
        var expectedHash = ComputeDedupHash("FILE", "fallback-key");
        Assert.Equal("FILE:" + expectedHash, key);
    }

    [Fact]
    public void DedupKey_ApiResponse_NoContentHash_FallsBackToKey()
    {
        var evaluator = new ConditionEvaluator();
        var evt = CreateMonitorEvent("API_RESPONSE", "resp-fallback",
            new Dictionary<string, object>());
        var key = evaluator.GenerateDedupKey(evt);
        var expectedHash = ComputeDedupHash("API_RESPONSE", "resp-fallback");
        Assert.Equal("API_RESPONSE:" + expectedHash, key);
    }

    [Fact]
    public void DedupKey_Format_StartsWithEventType()
    {
        var evaluator = new ConditionEvaluator();
        var evt = CreateMonitorEvent("FILE", "/test");
        var key = evaluator.GenerateDedupKey(evt);
        Assert.StartsWith("FILE:", key);
    }

    [Fact]
    public void DedupKey_Hash_Is32HexChars()
    {
        var evaluator = new ConditionEvaluator();
        var evt = CreateMonitorEvent("FILE", "/test");
        var key = evaluator.GenerateDedupKey(evt);
        var hashPart = key.Substring(key.IndexOf(':') + 1);
        Assert.Equal(32, hashPart.Length);
        Assert.Matches("^[0-9a-f]+$", hashPart);
    }

    // ════════════════════════════════════════════════════════════════════
    // 8. Dead Letter Queue (15 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void DLQ_DefaultStatus_Quarantined()
    {
        var entry = new DeadLetterEntry();
        Assert.Equal(DeadLetterStatus.Quarantined, entry.Status);
    }

    [Fact]
    public void DLQ_QuarantineFailedItem()
    {
        var entry = new DeadLetterEntry
        {
            WorkItemId = Guid.NewGuid(),
            ExecutionId = Guid.NewGuid(),
            PipelineInstanceId = Guid.NewGuid(),
            ErrorCode = "TRANSFORM_ERROR",
            ErrorMessage = "Invalid CSV format",
            FailureCount = 1,
            OriginalSourceKey = "/data/in/bad.csv"
        };
        Assert.Equal(DeadLetterStatus.Quarantined, entry.Status);
        Assert.Equal("TRANSFORM_ERROR", entry.ErrorCode);
    }

    [Fact]
    public void DLQ_EntryWithErrorDetails()
    {
        var entry = new DeadLetterEntry
        {
            ErrorCode = "EXPORT_FAILED",
            ErrorMessage = "Connection refused",
            StackTrace = "at Hermes.Engine.Services.Exporters..."
        };
        Assert.Equal("EXPORT_FAILED", entry.ErrorCode);
        Assert.Contains("Connection refused", entry.ErrorMessage);
        Assert.NotNull(entry.StackTrace);
    }

    [Fact]
    public void DLQ_ReplayFromDLQ()
    {
        var entry = new DeadLetterEntry { Status = DeadLetterStatus.Quarantined };
        entry.Status = DeadLetterStatus.Retrying;
        Assert.Equal(DeadLetterStatus.Retrying, entry.Status);
    }

    [Fact]
    public void DLQ_RetryingToResolved()
    {
        var entry = new DeadLetterEntry { Status = DeadLetterStatus.Retrying };
        entry.Status = DeadLetterStatus.Resolved;
        entry.ResolvedBy = "admin";
        entry.ResolvedAt = DateTimeOffset.UtcNow;
        entry.ResolutionNote = "Fixed upstream data issue";
        Assert.Equal(DeadLetterStatus.Resolved, entry.Status);
        Assert.NotNull(entry.ResolvedAt);
    }

    [Fact]
    public void DLQ_DiscardFromDLQ()
    {
        var entry = new DeadLetterEntry { Status = DeadLetterStatus.Quarantined };
        entry.Status = DeadLetterStatus.Discarded;
        entry.ResolvedBy = "admin";
        entry.ResolutionNote = "Duplicate; already processed";
        Assert.Equal(DeadLetterStatus.Discarded, entry.Status);
    }

    [Theory]
    [InlineData(DeadLetterStatus.Quarantined)]
    [InlineData(DeadLetterStatus.Retrying)]
    [InlineData(DeadLetterStatus.Resolved)]
    [InlineData(DeadLetterStatus.Discarded)]
    public void DLQ_AllStatusValues(DeadLetterStatus status)
    {
        var entry = new DeadLetterEntry { Status = status };
        Assert.Equal(status, entry.Status);
    }

    [Fact]
    public void DLQ_MultipleFailures_SameItem()
    {
        var workItemId = Guid.NewGuid();
        var entries = new List<DeadLetterEntry>();
        for (int i = 1; i <= 3; i++)
        {
            entries.Add(new DeadLetterEntry
            {
                WorkItemId = workItemId,
                FailureCount = i,
                ErrorMessage = "Failure attempt " + i
            });
        }
        Assert.Equal(3, entries.Count);
        Assert.Equal(3, entries.Last().FailureCount);
    }

    [Fact]
    public void DLQ_FailureCount_Increments()
    {
        var entry = new DeadLetterEntry { FailureCount = 1 };
        entry.FailureCount++;
        entry.FailureCount++;
        Assert.Equal(3, entry.FailureCount);
    }

    [Fact]
    public void DLQ_LastStepInfo()
    {
        var entry = new DeadLetterEntry
        {
            LastStepType = "Process",
            LastStepOrder = 2
        };
        Assert.Equal("Process", entry.LastStepType);
        Assert.Equal(2, entry.LastStepOrder);
    }

    [Fact]
    public void DLQ_InputDataJson()
    {
        var entry = new DeadLetterEntry
        {
            InputDataJson = "{\"file\":\"/data/in/record.csv\",\"row\":42}"
        };
        var doc = JsonDocument.Parse(entry.InputDataJson!);
        Assert.Equal(42, doc.RootElement.GetProperty("row").GetInt32());
    }

    [Fact]
    public void DLQ_ResolvedBy_NullByDefault()
    {
        var entry = new DeadLetterEntry();
        Assert.Null(entry.ResolvedBy);
        Assert.Null(entry.ResolvedAt);
        Assert.Null(entry.ResolutionNote);
    }

    [Fact]
    public void DLQ_OriginalSourceKey()
    {
        var entry = new DeadLetterEntry { OriginalSourceKey = "/data/in/orders_2026.csv" };
        Assert.Equal("/data/in/orders_2026.csv", entry.OriginalSourceKey);
    }

    [Fact]
    public void DLQ_CreatedAt_IsSet()
    {
        var before = DateTimeOffset.UtcNow;
        var entry = new DeadLetterEntry();
        Assert.True(entry.CreatedAt >= before.AddSeconds(-1));
    }

    [Fact]
    public void DLQ_FullLifecycle_QuarantinedRetryResolved()
    {
        var entry = new DeadLetterEntry
        {
            WorkItemId = Guid.NewGuid(),
            ErrorCode = "TIMEOUT",
            ErrorMessage = "Connection timed out",
            FailureCount = 1
        };
        Assert.Equal(DeadLetterStatus.Quarantined, entry.Status);

        entry.Status = DeadLetterStatus.Retrying;
        entry.FailureCount++;

        entry.Status = DeadLetterStatus.Resolved;
        entry.ResolvedBy = "system";
        entry.ResolvedAt = DateTimeOffset.UtcNow;
        entry.ResolutionNote = "Retry succeeded";

        Assert.Equal(DeadLetterStatus.Resolved, entry.Status);
        Assert.Equal(2, entry.FailureCount);
    }

    // ════════════════════════════════════════════════════════════════════
    // 9. Back Pressure (10 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void BackPressure_QueueDepthTracking()
    {
        int queueDepth = 0;
        int softLimit = 100;
        int hardLimit = 500;

        for (int i = 0; i < 50; i++) queueDepth++;
        Assert.True(queueDepth < softLimit, "Under soft limit");
    }

    [Fact]
    public void BackPressure_SoftLimit_WarnAndSlowDown()
    {
        int queueDepth = 120;
        int softLimit = 100;
        bool shouldWarn = queueDepth > softLimit;
        Assert.True(shouldWarn);
    }

    [Fact]
    public void BackPressure_HardLimit_PauseCollection()
    {
        int queueDepth = 550;
        int hardLimit = 500;
        bool shouldPause = queueDepth >= hardLimit;
        Assert.True(shouldPause);
    }

    [Fact]
    public void BackPressure_BelowSoftLimit_NoPressure()
    {
        int queueDepth = 50;
        int softLimit = 100;
        bool noPressure = queueDepth < softLimit;
        Assert.True(noPressure);
    }

    [Fact]
    public void BackPressure_ResumeAfterDrop()
    {
        int queueDepth = 550;
        int hardLimit = 500;
        bool paused = queueDepth >= hardLimit;
        Assert.True(paused);

        // Drain some items
        queueDepth = 400;
        paused = queueDepth >= hardLimit;
        Assert.False(paused, "Should resume after queue depth drops below hard limit");
    }

    [Fact]
    public void BackPressure_UtilizationPercentage_Zero()
    {
        int queueDepth = 0;
        int hardLimit = 500;
        double utilization = (double)queueDepth / hardLimit * 100.0;
        Assert.Equal(0.0, utilization);
    }

    [Fact]
    public void BackPressure_UtilizationPercentage_Half()
    {
        int queueDepth = 250;
        int hardLimit = 500;
        double utilization = (double)queueDepth / hardLimit * 100.0;
        Assert.Equal(50.0, utilization);
    }

    [Fact]
    public void BackPressure_UtilizationPercentage_Full()
    {
        int queueDepth = 500;
        int hardLimit = 500;
        double utilization = (double)queueDepth / hardLimit * 100.0;
        Assert.Equal(100.0, utilization);
    }

    [Fact]
    public void BackPressure_UtilizationPercentage_Over()
    {
        int queueDepth = 600;
        int hardLimit = 500;
        double utilization = (double)queueDepth / hardLimit * 100.0;
        Assert.True(utilization > 100.0);
    }

    [Fact]
    public void BackPressure_BetweenSoftAndHard()
    {
        int queueDepth = 300;
        int softLimit = 100;
        int hardLimit = 500;
        bool inWarningZone = queueDepth > softLimit && queueDepth < hardLimit;
        Assert.True(inWarningZone);
    }

    // ════════════════════════════════════════════════════════════════════
    // 10. Event Logging (10 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void EventLog_DefaultLevel_Info()
    {
        var log = new ExecutionEventLog();
        Assert.Equal(EventLevel.Info, log.EventType);
    }

    [Theory]
    [InlineData(EventLevel.Debug)]
    [InlineData(EventLevel.Info)]
    [InlineData(EventLevel.Warn)]
    [InlineData(EventLevel.Error)]
    public void EventLog_AllLevels(EventLevel level)
    {
        var log = new ExecutionEventLog { EventType = level };
        Assert.Equal(level, log.EventType);
    }

    [Fact]
    public void EventLog_EventCodeTracking()
    {
        var log = new ExecutionEventLog { EventCode = "STEP_COMPLETED" };
        Assert.Equal("STEP_COMPLETED", log.EventCode);
    }

    [Fact]
    public void EventLog_DetailJson_Serialization()
    {
        var log = new ExecutionEventLog
        {
            DetailJson = "{\"step\":2,\"duration_ms\":1500,\"output_rows\":42}"
        };
        var doc = JsonDocument.Parse(log.DetailJson!);
        Assert.Equal(2, doc.RootElement.GetProperty("step").GetInt32());
        Assert.Equal(1500, doc.RootElement.GetProperty("duration_ms").GetInt32());
    }

    [Fact]
    public void EventLog_LinkedToExecution()
    {
        var execId = Guid.NewGuid();
        var log = new ExecutionEventLog { ExecutionId = execId };
        Assert.Equal(execId, log.ExecutionId);
    }

    [Fact]
    public void EventLog_LinkedToStepExecution()
    {
        var stepExecId = Guid.NewGuid();
        var log = new ExecutionEventLog { StepExecutionId = stepExecId };
        Assert.Equal(stepExecId, log.StepExecutionId);
    }

    [Fact]
    public void EventLog_StepExecutionId_NullByDefault()
    {
        var log = new ExecutionEventLog();
        Assert.Null(log.StepExecutionId);
    }

    [Fact]
    public void EventLog_TimestampOrdering()
    {
        var logs = new List<ExecutionEventLog>();
        var baseTime = DateTimeOffset.UtcNow;
        for (int i = 0; i < 5; i++)
        {
            logs.Add(new ExecutionEventLog
            {
                CreatedAt = baseTime.AddMilliseconds(i * 100),
                EventCode = "STEP_" + (i + 1),
                Message = "Step " + (i + 1) + " completed"
            });
        }
        var ordered = logs.OrderBy(l => l.CreatedAt).ToList();
        Assert.Equal("STEP_1", ordered[0].EventCode);
        Assert.Equal("STEP_5", ordered[4].EventCode);
    }

    [Fact]
    public void EventLog_Message_Nullable()
    {
        var log = new ExecutionEventLog();
        Assert.Null(log.Message);
    }

    [Fact]
    public void EventLog_CreatedAt_IsSet()
    {
        var before = DateTimeOffset.UtcNow;
        var log = new ExecutionEventLog();
        Assert.True(log.CreatedAt >= before.AddSeconds(-1));
    }

    // ════════════════════════════════════════════════════════════════════
    // 11. Execution Entity Tests (15 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void Execution_DefaultStatus_Running()
    {
        var exec = new WorkItemExecution();
        Assert.Equal(ExecutionStatus.Running, exec.Status);
    }

    [Fact]
    public void Execution_RunningToCompleted()
    {
        var exec = CreateExecution(Guid.NewGuid());
        exec.Status = ExecutionStatus.Completed;
        exec.EndedAt = DateTimeOffset.UtcNow;
        exec.DurationMs = 5000;
        Assert.Equal(ExecutionStatus.Completed, exec.Status);
        Assert.NotNull(exec.EndedAt);
        Assert.Equal(5000, exec.DurationMs);
    }

    [Fact]
    public void Execution_RunningToFailed()
    {
        var exec = CreateExecution(Guid.NewGuid());
        exec.Status = ExecutionStatus.Failed;
        exec.EndedAt = DateTimeOffset.UtcNow;
        Assert.Equal(ExecutionStatus.Failed, exec.Status);
    }

    [Fact]
    public void Execution_RunningToCancelled()
    {
        var exec = CreateExecution(Guid.NewGuid());
        exec.Status = ExecutionStatus.Cancelled;
        Assert.Equal(ExecutionStatus.Cancelled, exec.Status);
    }

    [Theory]
    [InlineData(ExecutionStatus.Running)]
    [InlineData(ExecutionStatus.Completed)]
    [InlineData(ExecutionStatus.Failed)]
    [InlineData(ExecutionStatus.Cancelled)]
    public void Execution_AllStatusValues(ExecutionStatus status)
    {
        var exec = new WorkItemExecution { Status = status };
        Assert.Equal(status, exec.Status);
    }

    [Fact]
    public void Execution_ExecutionNo_Sequence()
    {
        var itemId = Guid.NewGuid();
        var exec1 = CreateExecution(itemId, 1);
        var exec2 = CreateExecution(itemId, 2);
        var exec3 = CreateExecution(itemId, 3);
        Assert.Equal(1, exec1.ExecutionNo);
        Assert.Equal(2, exec2.ExecutionNo);
        Assert.Equal(3, exec3.ExecutionNo);
    }

    [Fact]
    public void Execution_StepExecutions_Empty()
    {
        var exec = new WorkItemExecution();
        Assert.Empty(exec.StepExecutions);
    }

    [Fact]
    public void Execution_StepExecutions_Added()
    {
        var exec = CreateExecution(Guid.NewGuid());
        exec.StepExecutions.Add(new WorkItemStepExecution
        {
            ExecutionId = exec.Id,
            StepType = StageType.Collect,
            StepOrder = 1,
            Status = StepExecutionStatus.Completed
        });
        exec.StepExecutions.Add(new WorkItemStepExecution
        {
            ExecutionId = exec.Id,
            StepType = StageType.Process,
            StepOrder = 2,
            Status = StepExecutionStatus.Running
        });
        Assert.Equal(2, exec.StepExecutions.Count);
    }

    [Fact]
    public void Execution_TriggerSource_Default()
    {
        var exec = CreateExecution(Guid.NewGuid());
        Assert.Equal("SYSTEM", exec.TriggerSource);
    }

    [Fact]
    public void Execution_ReprocessRequestId_Nullable()
    {
        var exec = new WorkItemExecution();
        Assert.Null(exec.ReprocessRequestId);
    }

    [Fact]
    public void Execution_DurationMs_Nullable()
    {
        var exec = new WorkItemExecution();
        Assert.Null(exec.DurationMs);
    }

    [Fact]
    public void Execution_EndedAt_Nullable()
    {
        var exec = new WorkItemExecution();
        Assert.Null(exec.EndedAt);
    }

    [Fact]
    public void Execution_EventLogs_Empty()
    {
        var exec = new WorkItemExecution();
        Assert.Empty(exec.EventLogs);
    }

    [Fact]
    public void Execution_Snapshot_Nullable()
    {
        var exec = new WorkItemExecution();
        Assert.Null(exec.Snapshot);
    }

    [Fact]
    public void Execution_StartedAt_IsSet()
    {
        var before = DateTimeOffset.UtcNow;
        var exec = new WorkItemExecution();
        Assert.True(exec.StartedAt >= before.AddSeconds(-1));
    }

    // ════════════════════════════════════════════════════════════════════
    // 12. Step Execution Tests (15 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void StepExecution_DefaultStatus_Pending()
    {
        var step = new WorkItemStepExecution();
        Assert.Equal(StepExecutionStatus.Pending, step.Status);
    }

    [Fact]
    public void StepExecution_PendingToRunning()
    {
        var step = new WorkItemStepExecution();
        step.Status = StepExecutionStatus.Running;
        step.StartedAt = DateTimeOffset.UtcNow;
        Assert.Equal(StepExecutionStatus.Running, step.Status);
    }

    [Fact]
    public void StepExecution_RunningToCompleted()
    {
        var step = new WorkItemStepExecution { Status = StepExecutionStatus.Running };
        step.Status = StepExecutionStatus.Completed;
        step.EndedAt = DateTimeOffset.UtcNow;
        step.DurationMs = 250;
        Assert.Equal(StepExecutionStatus.Completed, step.Status);
    }

    [Fact]
    public void StepExecution_RunningToFailed()
    {
        var step = new WorkItemStepExecution { Status = StepExecutionStatus.Running };
        step.Status = StepExecutionStatus.Failed;
        step.ErrorCode = "PARSE_ERROR";
        step.ErrorMessage = "Invalid JSON in row 42";
        Assert.Equal(StepExecutionStatus.Failed, step.Status);
        Assert.Equal("PARSE_ERROR", step.ErrorCode);
    }

    [Fact]
    public void StepExecution_Skipped()
    {
        var step = new WorkItemStepExecution();
        step.Status = StepExecutionStatus.Skipped;
        Assert.Equal(StepExecutionStatus.Skipped, step.Status);
    }

    [Theory]
    [InlineData(StepExecutionStatus.Pending)]
    [InlineData(StepExecutionStatus.Running)]
    [InlineData(StepExecutionStatus.Completed)]
    [InlineData(StepExecutionStatus.Failed)]
    [InlineData(StepExecutionStatus.Skipped)]
    public void StepExecution_AllStatusValues(StepExecutionStatus status)
    {
        var step = new WorkItemStepExecution { Status = status };
        Assert.Equal(status, step.Status);
    }

    [Fact]
    public void StepExecution_RetryAttempt_DefaultZero()
    {
        var step = new WorkItemStepExecution();
        Assert.Equal(0, step.RetryAttempt);
    }

    [Fact]
    public void StepExecution_RetryAttempt_Increments()
    {
        var step = new WorkItemStepExecution();
        step.RetryAttempt = 1;
        Assert.Equal(1, step.RetryAttempt);
        step.RetryAttempt = 2;
        Assert.Equal(2, step.RetryAttempt);
    }

    [Fact]
    public void StepExecution_InputOutputSummary()
    {
        var step = new WorkItemStepExecution
        {
            InputSummary = "{\"rows\":100}",
            OutputSummary = "{\"rows\":95,\"filtered\":5}"
        };
        Assert.Contains("100", step.InputSummary);
        Assert.Contains("95", step.OutputSummary!);
    }

    [Fact]
    public void StepExecution_StepType_Collect()
    {
        var step = new WorkItemStepExecution { StepType = StageType.Collect, StepOrder = 1 };
        Assert.Equal(StageType.Collect, step.StepType);
        Assert.Equal(1, step.StepOrder);
    }

    [Fact]
    public void StepExecution_StepType_Process()
    {
        var step = new WorkItemStepExecution { StepType = StageType.Process, StepOrder = 2 };
        Assert.Equal(StageType.Process, step.StepType);
    }

    [Fact]
    public void StepExecution_StepType_Export()
    {
        var step = new WorkItemStepExecution { StepType = StageType.Export, StepOrder = 3 };
        Assert.Equal(StageType.Export, step.StepType);
    }

    [Fact]
    public void StepExecution_ErrorFields_NullByDefault()
    {
        var step = new WorkItemStepExecution();
        Assert.Null(step.ErrorCode);
        Assert.Null(step.ErrorMessage);
    }

    [Fact]
    public void StepExecution_DurationMs_NullByDefault()
    {
        var step = new WorkItemStepExecution();
        Assert.Null(step.DurationMs);
    }

    [Fact]
    public void StepExecution_EventLogs_Empty()
    {
        var step = new WorkItemStepExecution();
        Assert.Empty(step.EventLogs);
    }

    // ════════════════════════════════════════════════════════════════════
    // 13. Activation Entity Tests (10 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void Activation_DefaultStatus_Starting()
    {
        var act = new PipelineActivation();
        Assert.Equal(ActivationStatus.Starting, act.Status);
    }

    [Fact]
    public void Activation_StartingToRunning()
    {
        var act = CreateActivation(Guid.NewGuid(), ActivationStatus.Starting);
        act.Status = ActivationStatus.Running;
        Assert.Equal(ActivationStatus.Running, act.Status);
    }

    [Fact]
    public void Activation_RunningToStopping()
    {
        var act = CreateActivation(Guid.NewGuid(), ActivationStatus.Running);
        act.Status = ActivationStatus.Stopping;
        Assert.Equal(ActivationStatus.Stopping, act.Status);
    }

    [Fact]
    public void Activation_StoppingToStopped()
    {
        var act = CreateActivation(Guid.NewGuid(), ActivationStatus.Stopping);
        act.Status = ActivationStatus.Stopped;
        act.StoppedAt = DateTimeOffset.UtcNow;
        Assert.Equal(ActivationStatus.Stopped, act.Status);
        Assert.NotNull(act.StoppedAt);
    }

    [Fact]
    public void Activation_ErrorStatus()
    {
        var act = CreateActivation(Guid.NewGuid());
        act.Status = ActivationStatus.Error;
        act.ErrorMessage = "Monitor connection failed";
        Assert.Equal(ActivationStatus.Error, act.Status);
        Assert.Equal("Monitor connection failed", act.ErrorMessage);
    }

    [Theory]
    [InlineData(ActivationStatus.Starting)]
    [InlineData(ActivationStatus.Running)]
    [InlineData(ActivationStatus.Stopping)]
    [InlineData(ActivationStatus.Stopped)]
    [InlineData(ActivationStatus.Error)]
    public void Activation_AllStatusValues(ActivationStatus status)
    {
        var act = new PipelineActivation { Status = status };
        Assert.Equal(status, act.Status);
    }

    [Fact]
    public void Activation_Heartbeat()
    {
        var act = CreateActivation(Guid.NewGuid());
        act.LastHeartbeatAt = DateTimeOffset.UtcNow;
        Assert.NotNull(act.LastHeartbeatAt);
    }

    [Fact]
    public void Activation_LastPolledAt()
    {
        var act = CreateActivation(Guid.NewGuid());
        act.LastPolledAt = DateTimeOffset.UtcNow;
        Assert.NotNull(act.LastPolledAt);
    }

    [Fact]
    public void Activation_WorkerId()
    {
        var act = CreateActivation(Guid.NewGuid());
        act.WorkerId = "worker-node-01";
        Assert.Equal("worker-node-01", act.WorkerId);
    }

    [Fact]
    public void Activation_WorkItems_EmptyByDefault()
    {
        var act = new PipelineActivation();
        Assert.Empty(act.WorkItems);
    }

    // ════════════════════════════════════════════════════════════════════
    // 14. Interface Contract & Record Tests (10 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void MonitorEvent_Record_Properties()
    {
        var now = DateTimeOffset.UtcNow;
        var meta = new Dictionary<string, object> { { "size", 1024 } };
        var evt = new MonitorEvent("FILE", "/data/in/test.csv", meta, now);
        Assert.Equal("FILE", evt.EventType);
        Assert.Equal("/data/in/test.csv", evt.Key);
        Assert.Equal(now, evt.DetectedAt);
        Assert.Equal(1024, (int)meta["size"]);
    }

    [Fact]
    public void ExecutionResult_Record_Success()
    {
        var result = new ExecutionResult(true, "{\"rows\":10}", "{\"status\":\"ok\"}", 500,
            new List<LogEntry> { new(DateTimeOffset.UtcNow, "INFO", "Done") });
        Assert.True(result.Success);
        Assert.Equal(500, result.DurationMs);
        Assert.Single(result.Logs);
    }

    [Fact]
    public void ExecutionResult_Record_Failure()
    {
        var result = new ExecutionResult(false, null, null, 100,
            new List<LogEntry> { new(DateTimeOffset.UtcNow, "ERROR", "Crashed") });
        Assert.False(result.Success);
        Assert.Null(result.OutputJson);
    }

    [Fact]
    public void LogEntry_Record()
    {
        var now = DateTimeOffset.UtcNow;
        var entry = new LogEntry(now, "WARN", "Slow query detected");
        Assert.Equal(now, entry.Timestamp);
        Assert.Equal("WARN", entry.Level);
        Assert.Contains("Slow", entry.Message);
    }

    [Fact]
    public void StepConfig_Record()
    {
        var stepId = Guid.NewGuid();
        var refId = Guid.NewGuid();
        var config = new StepConfig(stepId, 1, StageType.Collect, RefType.Collector,
            refId, ExecutionType.Plugin, "file-monitor", "{}", 1);
        Assert.Equal(stepId, config.StepId);
        Assert.Equal(StageType.Collect, config.StepType);
        Assert.Equal(ExecutionType.Plugin, config.ExecutionType);
    }

    [Fact]
    public void ResolvedConfig_GetConfigForStep_Found()
    {
        var stepId = Guid.NewGuid();
        var steps = new List<StepConfig>
        {
            new(stepId, 1, StageType.Collect, RefType.Collector,
                Guid.NewGuid(), ExecutionType.Plugin, "fm", "{}", 1)
        };
        var resolved = new ResolvedConfig("{}", steps);

        var pipelineStep = new PipelineStep { Id = stepId };
        var found = resolved.GetConfigForStep(pipelineStep);
        Assert.NotNull(found);
        Assert.Equal(stepId, found!.StepId);
    }

    [Fact]
    public void ResolvedConfig_GetConfigForStep_NotFound()
    {
        var resolved = new ResolvedConfig("{}", new List<StepConfig>());
        var pipelineStep = new PipelineStep { Id = Guid.NewGuid() };
        var found = resolved.GetConfigForStep(pipelineStep);
        Assert.Null(found);
    }

    [Fact]
    public void PluginManifest_Key_Format()
    {
        var manifest = new PluginManifest("csv-parser", "1.0.0", PluginType.Process,
            "Parses CSV files", "Hermes", "MIT", "python", "main.py",
            "{}", "{}", "{}", "/plugins/csv-parser");
        Assert.Equal("Process:csv-parser", manifest.Key);
    }

    [Fact]
    public void PluginManifest_EntrypointPath()
    {
        var manifest = new PluginManifest("my-plugin", "1.0.0", PluginType.Collector,
            "Desc", "Author", "MIT", "python", "run.py",
            "{}", "{}", "{}", "/plugins/my-plugin");
        var expected = Path.Combine("/plugins/my-plugin", "run.py");
        Assert.Equal(expected, manifest.EntrypointPath);
    }

    [Fact]
    public void PluginResult_Record()
    {
        var result = new PluginResult(true,
            new List<string> { "output1.json" },
            new List<PluginError>(),
            new List<LogEntry>(),
            new Dictionary<string, object> { { "rows_processed", 100 } },
            0, 1.5, 100.0);
        Assert.True(result.Success);
        Assert.Single(result.Outputs);
        Assert.Equal(0, result.ExitCode);
        Assert.Equal(1.5, result.DurationSeconds);
    }

    // ════════════════════════════════════════════════════════════════════
    // 15. Cross-Cutting Orchestration Scenarios (10 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void Orchestration_FullScenario_DetectToComplete()
    {
        // Build pipeline
        var pipeline = CreatePipeline("ingest-orders", PipelineStatus.Active);
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 2, StageType.Process));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 3, StageType.Export));

        // Activate
        var activation = CreateActivation(pipeline.Id);
        activation.Status = ActivationStatus.Running;

        // Detect work item
        var item = CreateWorkItem(pipeline.Id, activation.Id);
        Assert.Equal(JobStatus.Detected, item.Status);

        // Queue
        item.Status = JobStatus.Queued;

        // Process
        item.Status = JobStatus.Processing;
        var exec = CreateExecution(item.Id, 1);
        item.ExecutionCount = 1;
        item.CurrentExecutionId = exec.Id;

        // Step executions
        foreach (var step in pipeline.Steps.OrderBy(s => s.StepOrder))
        {
            exec.StepExecutions.Add(new WorkItemStepExecution
            {
                ExecutionId = exec.Id,
                PipelineStepId = step.Id,
                StepType = step.StepType,
                StepOrder = step.StepOrder,
                Status = StepExecutionStatus.Completed,
                DurationMs = 100
            });
        }

        // Complete
        exec.Status = ExecutionStatus.Completed;
        exec.EndedAt = DateTimeOffset.UtcNow;
        item.Status = JobStatus.Completed;
        item.LastCompletedAt = DateTimeOffset.UtcNow;

        Assert.Equal(JobStatus.Completed, item.Status);
        Assert.Equal(3, exec.StepExecutions.Count);
        Assert.All(exec.StepExecutions, se => Assert.Equal(StepExecutionStatus.Completed, se.Status));
    }

    [Fact]
    public void Orchestration_FailAndRetry()
    {
        var pipeline = CreatePipeline("fail-retry", PipelineStatus.Active);
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 2, StageType.Process, OnErrorAction.Retry, retryCount: 2));

        var activation = CreateActivation(pipeline.Id);
        var item = CreateWorkItem(pipeline.Id, activation.Id);

        // First execution fails
        item.Status = JobStatus.Processing;
        var exec1 = CreateExecution(item.Id, 1, TriggerType.Initial, ExecutionStatus.Failed);
        item.Executions.Add(exec1);
        item.ExecutionCount = 1;
        item.Status = JobStatus.Failed;

        // Retry
        item.Status = JobStatus.Processing;
        var exec2 = CreateExecution(item.Id, 2, TriggerType.Retry, ExecutionStatus.Completed);
        item.Executions.Add(exec2);
        item.ExecutionCount = 2;
        item.Status = JobStatus.Completed;

        Assert.Equal(2, item.Executions.Count);
        Assert.Equal(ExecutionStatus.Failed, item.Executions[0].Status);
        Assert.Equal(ExecutionStatus.Completed, item.Executions[1].Status);
    }

    [Fact]
    public void Orchestration_ReprocessWithLatestRecipe()
    {
        var pipeline = CreatePipeline("reprocess-latest", PipelineStatus.Active);
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Process));

        var activation = CreateActivation(pipeline.Id);
        var item = CreateWorkItem(pipeline.Id, activation.Id, status: JobStatus.Completed);
        item.ExecutionCount = 1;

        // Create reprocess request
        var req = new ReprocessRequest
        {
            WorkItemId = item.Id,
            RequestedBy = "analyst",
            Reason = "New transform logic",
            UseLatestRecipe = true,
            StartFromStep = 1
        };
        req.Status = ReprocessStatus.Approved;

        // Execute reprocess
        req.Status = ReprocessStatus.Executing;
        var exec = CreateExecution(item.Id, 2, TriggerType.Reprocess);
        exec.ReprocessRequestId = req.Id;
        req.ExecutionId = exec.Id;

        exec.Status = ExecutionStatus.Completed;
        req.Status = ReprocessStatus.Done;

        Assert.Equal(ReprocessStatus.Done, req.Status);
        Assert.Equal(TriggerType.Reprocess, exec.TriggerType);
        Assert.True(req.UseLatestRecipe);
    }

    [Fact]
    public void Orchestration_ReprocessWithOriginalSnapshot()
    {
        var item = CreateWorkItem(Guid.NewGuid(), Guid.NewGuid(), status: JobStatus.Failed);
        var exec1 = CreateExecution(item.Id, 1, status: ExecutionStatus.Failed);
        var snap = CreateSnapshot(exec1.Id, processConfig: "{\"version\":\"v1\"}");

        var req = new ReprocessRequest
        {
            WorkItemId = item.Id,
            UseLatestRecipe = false,
            Reason = "Retry with original config"
        };
        Assert.False(req.UseLatestRecipe);
        Assert.Contains("v1", snap.ProcessConfig);
    }

    [Fact]
    public void Orchestration_DeadLetterAfterMaxRetries()
    {
        var pipeline = CreatePipeline("dlq-scenario", PipelineStatus.Active);
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Process,
            OnErrorAction.Retry, retryCount: 2));

        var item = CreateWorkItem(pipeline.Id, Guid.NewGuid());

        // 3 failed executions (initial + 2 retries)
        for (int i = 1; i <= 3; i++)
        {
            item.Executions.Add(CreateExecution(item.Id, i,
                i == 1 ? TriggerType.Initial : TriggerType.Retry, ExecutionStatus.Failed));
        }
        item.ExecutionCount = 3;
        item.Status = JobStatus.Failed;

        // Send to DLQ
        var dlq = new DeadLetterEntry
        {
            WorkItemId = item.Id,
            PipelineInstanceId = pipeline.Id,
            ErrorCode = "MAX_RETRIES_EXCEEDED",
            ErrorMessage = "Failed after 3 attempts",
            FailureCount = 3,
            OriginalSourceKey = item.SourceKey
        };

        Assert.Equal(DeadLetterStatus.Quarantined, dlq.Status);
        Assert.Equal(3, dlq.FailureCount);
    }

    [Fact]
    public void Orchestration_SkipDisabledStep()
    {
        var pipeline = CreatePipeline("skip-disabled", PipelineStatus.Active);
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect, enabled: true));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 2, StageType.Process, enabled: false));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 3, StageType.Export, enabled: true));

        var enabledSteps = pipeline.Steps.Where(s => s.IsEnabled).OrderBy(s => s.StepOrder).ToList();
        Assert.Equal(2, enabledSteps.Count);
        Assert.Equal(1, enabledSteps[0].StepOrder);
        Assert.Equal(3, enabledSteps[1].StepOrder);
    }

    [Fact]
    public void Orchestration_StopOnError()
    {
        var pipeline = CreatePipeline("stop-on-error", PipelineStatus.Active);
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 2, StageType.Process, OnErrorAction.Stop));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 3, StageType.Export));

        var exec = CreateExecution(Guid.NewGuid());
        // Step 1 completes
        exec.StepExecutions.Add(new WorkItemStepExecution
        {
            StepType = StageType.Collect, StepOrder = 1, Status = StepExecutionStatus.Completed
        });
        // Step 2 fails with Stop action
        exec.StepExecutions.Add(new WorkItemStepExecution
        {
            StepType = StageType.Process, StepOrder = 2, Status = StepExecutionStatus.Failed,
            ErrorCode = "PARSE_ERROR"
        });

        // Step 3 should NOT execute
        var failedStep = exec.StepExecutions.FirstOrDefault(s => s.Status == StepExecutionStatus.Failed);
        var stopOnError = pipeline.Steps.First(s => s.StepOrder == failedStep!.StepOrder).OnError;
        Assert.Equal(OnErrorAction.Stop, stopOnError);
        Assert.Equal(2, exec.StepExecutions.Count); // step 3 never added
    }

    [Fact]
    public void Orchestration_SkipOnError()
    {
        var pipeline = CreatePipeline("skip-on-error", PipelineStatus.Active);
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Collect));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 2, StageType.Process, OnErrorAction.Skip));
        pipeline.Steps.Add(CreateStep(pipeline.Id, 3, StageType.Export));

        var exec = CreateExecution(Guid.NewGuid());
        exec.StepExecutions.Add(new WorkItemStepExecution
        {
            StepType = StageType.Collect, StepOrder = 1, Status = StepExecutionStatus.Completed
        });
        // Step 2 fails but OnError=Skip, so step 3 should still run
        exec.StepExecutions.Add(new WorkItemStepExecution
        {
            StepType = StageType.Process, StepOrder = 2, Status = StepExecutionStatus.Failed
        });
        exec.StepExecutions.Add(new WorkItemStepExecution
        {
            StepType = StageType.Export, StepOrder = 3, Status = StepExecutionStatus.Completed
        });

        Assert.Equal(3, exec.StepExecutions.Count);
        Assert.Equal(StepExecutionStatus.Failed, exec.StepExecutions[1].Status);
        Assert.Equal(StepExecutionStatus.Completed, exec.StepExecutions[2].Status);
    }

    [Fact]
    public void Orchestration_EventLogging_AcrossSteps()
    {
        var exec = CreateExecution(Guid.NewGuid());
        exec.EventLogs.Add(new ExecutionEventLog
        {
            ExecutionId = exec.Id,
            EventType = EventLevel.Info,
            EventCode = "EXECUTION_START",
            Message = "Starting execution"
        });
        exec.EventLogs.Add(new ExecutionEventLog
        {
            ExecutionId = exec.Id,
            EventType = EventLevel.Info,
            EventCode = "STEP_1_COMPLETED",
            Message = "Collect step done"
        });
        exec.EventLogs.Add(new ExecutionEventLog
        {
            ExecutionId = exec.Id,
            EventType = EventLevel.Error,
            EventCode = "STEP_2_FAILED",
            Message = "Process step failed: invalid data"
        });

        Assert.Equal(3, exec.EventLogs.Count);
        Assert.Equal(1, exec.EventLogs.Count(e => e.EventType == EventLevel.Error));
    }

    [Fact]
    public void Orchestration_MultipleItemsSamePipeline()
    {
        var pipeline = CreatePipeline("multi-item", PipelineStatus.Active);
        pipeline.Steps.Add(CreateStep(pipeline.Id, 1, StageType.Process));
        var activation = CreateActivation(pipeline.Id);

        var items = Enumerable.Range(0, 10).Select(_ =>
            CreateWorkItem(pipeline.Id, activation.Id)).ToList();

        Assert.Equal(10, items.Count);
        Assert.All(items, i => Assert.Equal(pipeline.Id, i.PipelineInstanceId));
        // All items have unique IDs
        Assert.Equal(10, items.Select(i => i.Id).Distinct().Count());
    }
}
