using System.Diagnostics;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Infrastructure.Data;

namespace Hermes.Engine.Services;

public class ProcessingOrchestrator : IProcessingOrchestrator
{
    private readonly HermesDbContext _db;
    private readonly IExecutionDispatcher _dispatcher;
    private readonly ISnapshotResolver _snapshotResolver;
    private readonly ILogger<ProcessingOrchestrator> _logger;

    public ProcessingOrchestrator(
        HermesDbContext db,
        IExecutionDispatcher dispatcher,
        ISnapshotResolver snapshotResolver,
        ILogger<ProcessingOrchestrator> logger)
    {
        _db = db;
        _dispatcher = dispatcher;
        _snapshotResolver = snapshotResolver;
        _logger = logger;
    }

    public async Task<WorkItemExecution> ProcessWorkItemAsync(
        Guid workItemId,
        TriggerType triggerType = TriggerType.Initial,
        string triggerSource = "SYSTEM",
        int startFromStep = 1,
        bool useLatestRecipe = true,
        Guid? reprocessRequestId = null,
        CancellationToken ct = default)
    {
        // Load work item with pipeline
        var workItem = await _db.WorkItems
            .Include(w => w.PipelineInstance)
                .ThenInclude(p => p.Steps)
            .FirstOrDefaultAsync(w => w.Id == workItemId, ct)
            ?? throw new InvalidOperationException($"WorkItem {workItemId} not found");

        var pipeline = workItem.PipelineInstance;
        var steps = pipeline.Steps.OrderBy(s => s.StepOrder).ToList();

        // 1. Create execution record
        var execution = new WorkItemExecution
        {
            WorkItemId = workItemId,
            ExecutionNo = workItem.ExecutionCount + 1,
            TriggerType = triggerType,
            TriggerSource = triggerSource,
            Status = ExecutionStatus.Running,
            StartedAt = DateTimeOffset.UtcNow,
            ReprocessRequestId = reprocessRequestId,
            CreatedAt = DateTimeOffset.UtcNow
        };
        _db.WorkItemExecutions.Add(execution);

        workItem.Status = JobStatus.Processing;
        workItem.ExecutionCount++;
        workItem.CurrentExecutionId = execution.Id;
        await _db.SaveChangesAsync(ct);

        await LogEventAsync(execution.Id, null, EventLevel.Info, "EXECUTION_START",
            $"Starting execution #{execution.ExecutionNo} ({triggerType})", ct);

        // 2. Capture snapshot
        var snapshot = await _snapshotResolver.CaptureAsync(pipeline, steps, execution.Id, useLatestRecipe, ct);
        var resolved = await _snapshotResolver.ResolveAsync(snapshot.Id, ct);

        // 3. Execute steps
        var sw = Stopwatch.StartNew();
        string? previousOutput = null;
        var failed = false;

        foreach (var step in steps)
        {
            if (step.StepOrder < startFromStep) continue;
            if (!step.IsEnabled) continue;

            var stepConfig = resolved.GetConfigForStep(step);
            if (stepConfig == null)
            {
                _logger.LogWarning("No config for step {StepId}, skipping", step.Id);
                continue;
            }

            // Create step execution
            var stepExec = new WorkItemStepExecution
            {
                ExecutionId = execution.Id,
                PipelineStepId = step.Id,
                StepType = step.StepType,
                StepOrder = step.StepOrder,
                Status = StepExecutionStatus.Running,
                StartedAt = DateTimeOffset.UtcNow,
                CreatedAt = DateTimeOffset.UtcNow
            };
            _db.WorkItemStepExecutions.Add(stepExec);
            await _db.SaveChangesAsync(ct);

            await LogEventAsync(execution.Id, stepExec.Id, EventLevel.Info, "STEP_START",
                $"Starting step {step.StepOrder} ({step.StepType})", ct);

            try
            {
                var contextDict = new Dictionary<string, string>
                {
                    ["work_item_id"] = workItemId.ToString(),
                    ["execution_id"] = execution.Id.ToString(),
                    ["execution_no"] = execution.ExecutionNo.ToString(),
                    ["pipeline_id"] = pipeline.Id.ToString(),
                    ["step_order"] = step.StepOrder.ToString()
                };

                var result = await _dispatcher.DispatchAsync(
                    stepConfig.ExecutionType,
                    stepConfig.ExecutionRef,
                    stepConfig.ResolvedConfigJson,
                    previousOutput,
                    contextDict,
                    ct);

                if (result.Success)
                {
                    stepExec.Status = StepExecutionStatus.Completed;
                    stepExec.OutputSummary = result.SummaryJson;
                    previousOutput = result.OutputJson;

                    await LogEventAsync(execution.Id, stepExec.Id, EventLevel.Info, "STEP_DONE",
                        $"Step {step.StepOrder} completed in {result.DurationMs}ms", ct);
                }
                else
                {
                    var errorMsg = result.Logs.LastOrDefault()?.Message ?? "Unknown error";
                    throw new InvalidOperationException(errorMsg);
                }
            }
            catch (Exception ex)
            {
                stepExec.Status = StepExecutionStatus.Failed;
                stepExec.ErrorMessage = ex.Message;
                stepExec.ErrorCode = "STEP_FAILED";

                await LogEventAsync(execution.Id, stepExec.Id, EventLevel.Error, "STEP_FAILED",
                    $"Step {step.StepOrder} failed: {ex.Message}", ct);

                if (step.OnError == OnErrorAction.Stop)
                {
                    failed = true;
                    break;
                }
                else if (step.OnError == OnErrorAction.Skip)
                {
                    stepExec.Status = StepExecutionStatus.Skipped;
                    _logger.LogWarning("Step {Order} failed, skipping: {Error}", step.StepOrder, ex.Message);
                    continue;
                }
                else if (step.OnError == OnErrorAction.Retry)
                {
                    var retrySuccess = await RetryStepAsync(step, stepExec, stepConfig, previousOutput, execution, ct);
                    if (!retrySuccess)
                    {
                        failed = true;
                        break;
                    }
                    previousOutput = stepExec.OutputSummary; // Use retry output
                }
            }
            finally
            {
                stepExec.EndedAt = DateTimeOffset.UtcNow;
                stepExec.DurationMs = (long)(stepExec.EndedAt.Value - stepExec.StartedAt!.Value).TotalMilliseconds;
                await _db.SaveChangesAsync(ct);
            }
        }

        // 4. Finalize
        sw.Stop();
        execution.Status = failed ? ExecutionStatus.Failed : ExecutionStatus.Completed;
        execution.EndedAt = DateTimeOffset.UtcNow;
        execution.DurationMs = sw.ElapsedMilliseconds;

        workItem.Status = failed ? JobStatus.Failed : JobStatus.Completed;
        if (!failed) workItem.LastCompletedAt = DateTimeOffset.UtcNow;

        await _db.SaveChangesAsync(ct);

        await LogEventAsync(execution.Id, null, EventLevel.Info, "EXECUTION_DONE",
            $"Execution #{execution.ExecutionNo} {execution.Status} in {execution.DurationMs}ms", ct);

        return execution;
    }

    public async Task<WorkItemExecution> ReprocessWorkItemAsync(Guid reprocessRequestId, CancellationToken ct = default)
    {
        var request = await _db.ReprocessRequests.FindAsync(new object[] { reprocessRequestId }, ct)
            ?? throw new InvalidOperationException($"ReprocessRequest {reprocessRequestId} not found");

        request.Status = ReprocessStatus.Executing;
        await _db.SaveChangesAsync(ct);

        var execution = await ProcessWorkItemAsync(
            request.WorkItemId,
            TriggerType.Reprocess,
            request.RequestedBy,
            request.StartFromStep ?? 1,
            request.UseLatestRecipe,
            reprocessRequestId,
            ct);

        request.Status = ReprocessStatus.Done;
        request.ExecutionId = execution.Id;
        await _db.SaveChangesAsync(ct);

        return execution;
    }

    public async Task<List<ReprocessRequest>> BulkReprocessAsync(
        List<Guid> workItemIds, string reason, string requestedBy,
        int? startFromStep = null, bool useLatestRecipe = true,
        CancellationToken ct = default)
    {
        var requests = workItemIds.Select(id => new ReprocessRequest
        {
            WorkItemId = id,
            RequestedBy = requestedBy,
            RequestedAt = DateTimeOffset.UtcNow,
            Reason = reason,
            StartFromStep = startFromStep,
            UseLatestRecipe = useLatestRecipe,
            Status = ReprocessStatus.Pending
        }).ToList();

        _db.ReprocessRequests.AddRange(requests);
        await _db.SaveChangesAsync(ct);
        return requests;
    }

    private async Task<bool> RetryStepAsync(
        PipelineStep step,
        WorkItemStepExecution stepExec,
        StepConfig stepConfig,
        string? previousOutput,
        WorkItemExecution execution,
        CancellationToken ct)
    {
        for (var attempt = 1; attempt <= step.RetryCount; attempt++)
        {
            stepExec.RetryAttempt = attempt;
            var delay = step.RetryDelaySeconds * (int)Math.Pow(2, attempt - 1); // exponential backoff

            _logger.LogInformation("Retrying step {Order}, attempt {Attempt}/{Max}, delay {Delay}s",
                step.StepOrder, attempt, step.RetryCount, delay);

            await Task.Delay(TimeSpan.FromSeconds(delay), ct);

            try
            {
                var contextDict = new Dictionary<string, string>
                {
                    ["work_item_id"] = stepExec.ExecutionId.ToString(),
                    ["retry_attempt"] = attempt.ToString()
                };

                var result = await _dispatcher.DispatchAsync(
                    stepConfig.ExecutionType, stepConfig.ExecutionRef,
                    stepConfig.ResolvedConfigJson, previousOutput, contextDict, ct);

                if (result.Success)
                {
                    stepExec.Status = StepExecutionStatus.Completed;
                    stepExec.OutputSummary = result.SummaryJson;
                    stepExec.ErrorMessage = null;

                    await LogEventAsync(execution.Id, stepExec.Id, EventLevel.Info, "STEP_RETRY_SUCCESS",
                        $"Step {step.StepOrder} succeeded on retry {attempt}", ct);
                    return true;
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Retry {Attempt} failed for step {Order}", attempt, step.StepOrder);
            }
        }

        await LogEventAsync(execution.Id, stepExec.Id, EventLevel.Error, "STEP_RETRY_EXHAUSTED",
            $"Step {step.StepOrder} failed after {step.RetryCount} retries", ct);
        return false;
    }

    private async Task LogEventAsync(
        Guid executionId, Guid? stepExecutionId, EventLevel level,
        string code, string message, CancellationToken ct)
    {
        _db.ExecutionEventLogs.Add(new ExecutionEventLog
        {
            ExecutionId = executionId,
            StepExecutionId = stepExecutionId,
            EventType = level,
            EventCode = code,
            Message = message,
            CreatedAt = DateTimeOffset.UtcNow
        });
        await _db.SaveChangesAsync(ct);
    }
}
