using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;

namespace Hermes.Engine.Tests;

/// <summary>
/// Tests for work item lifecycle: creation → queued → processing → completed/failed.
/// Mirrors backend/tests/test_work_item_lifecycle.py scenarios.
/// </summary>
public class WorkItemLifecycleTests
{
    [Fact]
    public async Task WorkItem_DefaultStatus_IsDetected()
    {
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        var workItem = new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.File,
            SourceKey = "/data/test.csv",
            SourceMetadata = "{\"size\":1024}",
            DedupKey = "FILE:abc123"
        };
        db.WorkItems.Add(workItem);
        await db.SaveChangesAsync();

        Assert.Equal(JobStatus.Detected, workItem.Status);
        Assert.Equal(0, workItem.ExecutionCount);
        Assert.Null(workItem.CurrentExecutionId);
    }

    [Fact]
    public async Task WorkItem_TransitionToQueued()
    {
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        var workItem = new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.File,
            SourceKey = "/data/test.csv",
            Status = JobStatus.Queued
        };
        db.WorkItems.Add(workItem);
        await db.SaveChangesAsync();

        Assert.Equal(JobStatus.Queued, workItem.Status);
    }

    [Fact]
    public async Task WorkItem_Execution_CreatesRecord()
    {
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        var workItem = new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.File,
            SourceKey = "/data/test.csv",
            Status = JobStatus.Processing
        };
        db.WorkItems.Add(workItem);
        await db.SaveChangesAsync();

        var execution = new WorkItemExecution
        {
            WorkItemId = workItem.Id,
            ExecutionNo = 1,
            TriggerType = TriggerType.Initial,
            TriggerSource = "SYSTEM",
            Status = ExecutionStatus.Running
        };
        db.WorkItemExecutions.Add(execution);
        workItem.ExecutionCount = 1;
        workItem.CurrentExecutionId = execution.Id;
        await db.SaveChangesAsync();

        Assert.Equal(1, workItem.ExecutionCount);
        Assert.Equal(ExecutionStatus.Running, execution.Status);
    }

    [Fact]
    public async Task ReprocessRequest_DefaultStatus_IsPending()
    {
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        var workItem = new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.File,
            SourceKey = "/data/test.csv",
            Status = JobStatus.Failed
        };
        db.WorkItems.Add(workItem);
        await db.SaveChangesAsync();

        var request = new ReprocessRequest
        {
            WorkItemId = workItem.Id,
            RequestedBy = "operator:kim",
            Reason = "Config updated",
            UseLatestRecipe = true,
            StartFromStep = 2
        };
        db.ReprocessRequests.Add(request);
        await db.SaveChangesAsync();

        Assert.Equal(ReprocessStatus.Pending, request.Status);
        Assert.Equal(2, request.StartFromStep);
        Assert.True(request.UseLatestRecipe);
    }

    [Fact]
    public async Task EventLog_RecordsExecutionEvents()
    {
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        var workItem = new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.File,
            SourceKey = "/data/test.csv"
        };
        db.WorkItems.Add(workItem);

        var execution = new WorkItemExecution
        {
            WorkItemId = workItem.Id,
            ExecutionNo = 1,
            Status = ExecutionStatus.Running
        };
        db.WorkItemExecutions.Add(execution);
        await db.SaveChangesAsync();

        db.ExecutionEventLogs.Add(new ExecutionEventLog
        {
            ExecutionId = execution.Id,
            EventType = EventLevel.Info,
            EventCode = "EXECUTION_START",
            Message = "Starting execution #1"
        });
        db.ExecutionEventLogs.Add(new ExecutionEventLog
        {
            ExecutionId = execution.Id,
            EventType = EventLevel.Error,
            EventCode = "STEP_FAILED",
            Message = "Step 2 failed: timeout"
        });
        await db.SaveChangesAsync();

        var logs = db.ExecutionEventLogs.Where(e => e.ExecutionId == execution.Id).ToList();
        Assert.Equal(2, logs.Count);
        Assert.Contains(logs, l => l.EventCode == "EXECUTION_START");
        Assert.Contains(logs, l => l.EventType == EventLevel.Error);
    }
}
