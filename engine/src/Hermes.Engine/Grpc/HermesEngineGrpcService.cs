using Grpc.Core;
using Microsoft.EntityFrameworkCore;
using Hermes.Bridge.V1;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Infrastructure.Data;

namespace Hermes.Engine.Grpc;

/// <summary>
/// gRPC service implementation for the Python Web API ↔ .NET Engine bridge.
/// </summary>
public class HermesEngineGrpcService : HermesEngineService.HermesEngineServiceBase
{
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly IMonitoringEngine _monitoringEngine;
    private readonly ILogger<HermesEngineGrpcService> _logger;
    private readonly DateTimeOffset _startedAt = DateTimeOffset.UtcNow;

    public HermesEngineGrpcService(
        IServiceScopeFactory scopeFactory,
        IMonitoringEngine monitoringEngine,
        ILogger<HermesEngineGrpcService> logger)
    {
        _scopeFactory = scopeFactory;
        _monitoringEngine = monitoringEngine;
        _logger = logger;
    }

    // ── Pipeline Lifecycle ──

    public override async Task<ActivateResponse> ActivatePipeline(
        ActivateRequest request, ServerCallContext context)
    {
        _logger.LogInformation("gRPC ActivatePipeline: {PipelineId}", request.PipelineId);

        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();

        var pipelineId = Guid.Parse(request.PipelineId);
        var pipeline = await db.PipelineInstances
            .Include(p => p.Steps)
            .FirstOrDefaultAsync(p => p.Id == pipelineId, context.CancellationToken);

        if (pipeline == null)
            return new ActivateResponse { Success = false, ErrorMessage = "Pipeline not found" };

        // Create activation record
        var activation = new PipelineActivation
        {
            PipelineInstanceId = pipelineId,
            Status = ActivationStatus.Starting,
            StartedAt = DateTimeOffset.UtcNow,
            WorkerId = Environment.MachineName
        };
        db.PipelineActivations.Add(activation);

        pipeline.Status = PipelineStatus.Active;
        await db.SaveChangesAsync(context.CancellationToken);

        // Reload with navigation for monitoring engine
        activation.PipelineInstance = pipeline;

        try
        {
            await _monitoringEngine.StartMonitoringAsync(activation, context.CancellationToken);
            activation.Status = ActivationStatus.Running;
            await db.SaveChangesAsync(context.CancellationToken);

            return new ActivateResponse
            {
                Success = true,
                ActivationId = activation.Id.ToString(),
                Status = PipelineRuntimeStatus.Active
            };
        }
        catch (Exception ex)
        {
            activation.Status = ActivationStatus.Error;
            activation.ErrorMessage = ex.Message;
            await db.SaveChangesAsync(context.CancellationToken);

            return new ActivateResponse
            {
                Success = false,
                ErrorMessage = ex.Message,
                Status = PipelineRuntimeStatus.Error
            };
        }
    }

    public override async Task<DeactivateResponse> DeactivatePipeline(
        DeactivateRequest request, ServerCallContext context)
    {
        _logger.LogInformation("gRPC DeactivatePipeline: {PipelineId}", request.PipelineId);

        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();

        var pipelineId = Guid.Parse(request.PipelineId);

        // Find active activation
        var activation = await db.PipelineActivations
            .Where(a => a.PipelineInstanceId == pipelineId &&
                       (a.Status == ActivationStatus.Running || a.Status == ActivationStatus.Starting))
            .FirstOrDefaultAsync(context.CancellationToken);

        if (activation == null)
            return new DeactivateResponse { Success = true, Status = PipelineRuntimeStatus.Inactive };

        await _monitoringEngine.StopMonitoringAsync(activation.Id, context.CancellationToken);

        activation.Status = ActivationStatus.Stopped;
        activation.StoppedAt = DateTimeOffset.UtcNow;

        var pipeline = await db.PipelineInstances.FindAsync(
            new object[] { pipelineId }, context.CancellationToken);
        if (pipeline != null)
            pipeline.Status = PipelineStatus.Paused;

        // Count in-flight jobs
        var inFlightJobs = await db.WorkItems
            .CountAsync(w => w.PipelineActivationId == activation.Id &&
                            (w.Status == JobStatus.Queued || w.Status == JobStatus.Processing),
                       context.CancellationToken);

        await db.SaveChangesAsync(context.CancellationToken);

        return new DeactivateResponse
        {
            Success = true,
            InFlightJobs = inFlightJobs,
            Status = PipelineRuntimeStatus.Inactive
        };
    }

    public override async Task<PipelineStatusResponse> GetPipelineStatus(
        StatusRequest request, ServerCallContext context)
    {
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();

        var pipelineId = Guid.Parse(request.PipelineId);
        var activation = await db.PipelineActivations
            .Where(a => a.PipelineInstanceId == pipelineId &&
                       (a.Status == ActivationStatus.Running || a.Status == ActivationStatus.Starting))
            .FirstOrDefaultAsync(context.CancellationToken);

        var response = new PipelineStatusResponse
        {
            PipelineId = request.PipelineId,
            Status = activation == null ? PipelineRuntimeStatus.Inactive :
                     activation.Status == ActivationStatus.Running ? PipelineRuntimeStatus.Active :
                     activation.Status == ActivationStatus.Error ? PipelineRuntimeStatus.Error :
                     PipelineRuntimeStatus.Starting,
        };

        if (activation != null)
        {
            response.ActivationId = activation.Id.ToString();
            response.ActivatedAt = Google.Protobuf.WellKnownTypes.Timestamp.FromDateTimeOffset(activation.StartedAt);
            response.WorkerId = activation.WorkerId ?? "";
            response.LastError = activation.ErrorMessage ?? "";

            response.ActiveJobs = await db.WorkItems
                .CountAsync(w => w.PipelineActivationId == activation.Id && w.Status == JobStatus.Processing,
                           context.CancellationToken);
            response.QueuedJobs = await db.WorkItems
                .CountAsync(w => w.PipelineActivationId == activation.Id && w.Status == JobStatus.Queued,
                           context.CancellationToken);
            response.TotalJobsProcessed = await db.WorkItems
                .CountAsync(w => w.PipelineActivationId == activation.Id && w.Status == JobStatus.Completed,
                           context.CancellationToken);
            response.TotalJobsFailed = await db.WorkItems
                .CountAsync(w => w.PipelineActivationId == activation.Id && w.Status == JobStatus.Failed,
                           context.CancellationToken);
        }

        return response;
    }

    // ── Job Management ──

    public override async Task<Hermes.Bridge.V1.ReprocessResponse> ReprocessJob(
        Hermes.Bridge.V1.ReprocessRequest request, ServerCallContext context)
    {
        _logger.LogInformation("gRPC ReprocessJob: {JobId}", request.JobId);

        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();
        var orchestrator = scope.ServiceProvider.GetRequiredService<IProcessingOrchestrator>();

        var jobId = Guid.Parse(request.JobId);

        // Create reprocess request
        var reprocessReq = new Domain.Entities.ReprocessRequest
        {
            WorkItemId = jobId,
            RequestedBy = request.RequestedBy,
            Reason = request.Reason,
            StartFromStep = request.StartFromStep > 0 ? request.StartFromStep : null,
            UseLatestRecipe = request.UseLatestRecipe,
            Status = ReprocessStatus.Approved // Auto-approve via gRPC
        };
        db.ReprocessRequests.Add(reprocessReq);
        await db.SaveChangesAsync(context.CancellationToken);

        try
        {
            var execution = await orchestrator.ReprocessWorkItemAsync(
                reprocessReq.Id, context.CancellationToken);

            return new Hermes.Bridge.V1.ReprocessResponse
            {
                Success = true,
                ExecutionId = execution.Id.ToString()
            };
        }
        catch (Exception ex)
        {
            return new Hermes.Bridge.V1.ReprocessResponse
            {
                Success = false,
                ErrorMessage = ex.Message
            };
        }
    }

    public override async Task<BulkReprocessResponse> BulkReprocessJobs(
        BulkReprocessRequest request, ServerCallContext context)
    {
        _logger.LogInformation("gRPC BulkReprocessJobs: {Count} jobs", request.JobIds.Count);

        using var scope = _scopeFactory.CreateScope();
        var orchestrator = scope.ServiceProvider.GetRequiredService<IProcessingOrchestrator>();

        var jobIds = request.JobIds.Select(Guid.Parse).ToList();

        var requests = await orchestrator.BulkReprocessAsync(
            jobIds, request.Reason, request.RequestedBy,
            useLatestRecipe: request.UseLatestRecipe,
            ct: context.CancellationToken);

        return new BulkReprocessResponse
        {
            AcceptedCount = requests.Count,
            RejectedCount = 0
        };
    }

    public override async Task<CancelResponse> CancelJob(
        CancelRequest request, ServerCallContext context)
    {
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();

        var jobId = Guid.Parse(request.JobId);
        var workItem = await db.WorkItems.FindAsync(
            new object[] { jobId }, context.CancellationToken);

        if (workItem == null)
            return new CancelResponse { Success = false, ErrorMessage = "Job not found" };

        var previousStatus = workItem.Status.ToString();
        workItem.Status = JobStatus.Failed;
        await db.SaveChangesAsync(context.CancellationToken);

        return new CancelResponse
        {
            Success = true,
            StatusAtCancel = previousStatus
        };
    }

    // ── Health & Monitoring ──

    public override async Task<EngineHealthResponse> GetEngineHealth(
        HealthRequest request, ServerCallContext context)
    {
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();

        var activePipelines = await db.PipelineActivations
            .CountAsync(a => a.Status == ActivationStatus.Running, context.CancellationToken);
        var jobsProcessing = await db.WorkItems
            .CountAsync(w => w.Status == JobStatus.Processing, context.CancellationToken);
        var jobsQueued = await db.WorkItems
            .CountAsync(w => w.Status == JobStatus.Queued, context.CancellationToken);

        var uptime = (long)(DateTimeOffset.UtcNow - _startedAt).TotalSeconds;
        var memory = GC.GetTotalMemory(false) / (1024 * 1024);

        return new EngineHealthResponse
        {
            Status = EngineHealthStatus.Healthy,
            UptimeSeconds = uptime,
            ActivePipelines = activePipelines,
            JobsProcessing = jobsProcessing,
            JobsQueued = jobsQueued,
            MemoryUsedMb = memory,
            ThreadCount = ThreadPool.ThreadCount,
            EngineVersion = "0.1.0",
            Timestamp = Google.Protobuf.WellKnownTypes.Timestamp.FromDateTimeOffset(DateTimeOffset.UtcNow)
        };
    }

    public override Task<MetricsResponse> GetMetrics(
        MetricsRequest request, ServerCallContext context)
    {
        // Placeholder - integrate with prometheus-net later
        return Task.FromResult(new MetricsResponse
        {
            MetricsPayload = "# Hermes Engine Metrics\n",
            ContentType = "text/plain"
        });
    }

    public override Task<TestConnectionResponse> TestConnection(
        TestConnectionRequest request, ServerCallContext context)
    {
        // Placeholder
        return Task.FromResult(new TestConnectionResponse
        {
            Success = true,
            Message = "Connection test not yet implemented",
            ResponseTimeMs = 0
        });
    }

    public override Task<PreviewResponse> PreviewData(
        PreviewRequest request, ServerCallContext context)
    {
        // Placeholder
        return Task.FromResult(new PreviewResponse
        {
            Success = false,
            ErrorMessage = "Preview not yet implemented"
        });
    }

    // ── Event Streaming ──

    public override async Task StreamEvents(
        EventStreamRequest request,
        IServerStreamWriter<EngineEvent> responseStream,
        ServerCallContext context)
    {
        _logger.LogInformation("gRPC StreamEvents started for pipeline: {PipelineId}",
            string.IsNullOrEmpty(request.PipelineId) ? "ALL" : request.PipelineId);

        // Simple polling implementation - watches for new event logs
        var lastEventTime = DateTimeOffset.UtcNow;
        Guid? pipelineFilter = string.IsNullOrEmpty(request.PipelineId)
            ? null : Guid.Parse(request.PipelineId);

        while (!context.CancellationToken.IsCancellationRequested)
        {
            try
            {
                using var scope = _scopeFactory.CreateScope();
                var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();

                var query = db.ExecutionEventLogs
                    .Where(e => e.CreatedAt > lastEventTime);

                if (pipelineFilter.HasValue)
                {
                    query = query.Where(e =>
                        db.WorkItemExecutions
                            .Where(we => we.Id == e.ExecutionId)
                            .Any(we => db.WorkItems
                                .Where(w => w.Id == we.WorkItemId && w.PipelineInstanceId == pipelineFilter.Value)
                                .Any()));
                }

                var events = await query
                    .OrderBy(e => e.CreatedAt)
                    .Take(100)
                    .ToListAsync(context.CancellationToken);

                foreach (var evt in events)
                {
                    var engineEvent = new EngineEvent
                    {
                        EventId = evt.Id.ToString(),
                        EventType = MapEventType(evt.EventCode),
                        ExecutionId = evt.ExecutionId.ToString(),
                        Timestamp = Google.Protobuf.WellKnownTypes.Timestamp.FromDateTimeOffset(evt.CreatedAt),
                        Message = evt.Message ?? "",
                        DetailJson = evt.DetailJson ?? "{}",
                        Severity = evt.EventType.ToString()
                    };
                    await responseStream.WriteAsync(engineEvent, context.CancellationToken);
                    lastEventTime = evt.CreatedAt;
                }

                await Task.Delay(1000, context.CancellationToken);
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error streaming events");
                await Task.Delay(5000, context.CancellationToken);
            }
        }
    }

    private static EngineEventType MapEventType(string eventCode)
    {
        return eventCode switch
        {
            "EXECUTION_START" => EngineEventType.JobStarted,
            "EXECUTION_DONE" => EngineEventType.JobCompleted,
            "STEP_START" => EngineEventType.StepStarted,
            "STEP_DONE" => EngineEventType.StepCompleted,
            "STEP_FAILED" => EngineEventType.StepFailed,
            _ when eventCode.Contains("FAIL") => EngineEventType.JobFailed,
            _ => EngineEventType.Unspecified
        };
    }
}
