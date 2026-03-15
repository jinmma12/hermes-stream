using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Infrastructure.Data;

namespace Hermes.Engine.Workers;

public class ProcessingWorker : BackgroundService
{
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ILogger<ProcessingWorker> _logger;
    private readonly SemaphoreSlim _semaphore;
    private const int PollIntervalSeconds = 5;
    private const int MaxConcurrent = 5;

    public ProcessingWorker(
        IServiceScopeFactory scopeFactory,
        ILogger<ProcessingWorker> logger)
    {
        _scopeFactory = scopeFactory;
        _logger = logger;
        _semaphore = new SemaphoreSlim(MaxConcurrent, MaxConcurrent);
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("ProcessingWorker starting...");

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await ProcessQueuedItemsAsync(stoppingToken);
                await ProcessReprocessRequestsAsync(stoppingToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error in processing worker loop");
            }

            await Task.Delay(TimeSpan.FromSeconds(PollIntervalSeconds), stoppingToken);
        }
    }

    private async Task ProcessQueuedItemsAsync(CancellationToken ct)
    {
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();

        var queuedItems = await db.WorkItems
            .Where(w => w.Status == JobStatus.Queued)
            .OrderBy(w => w.DetectedAt)
            .Take(MaxConcurrent)
            .Select(w => w.Id)
            .ToListAsync(ct);

        var tasks = new List<Task>();
        foreach (var itemId in queuedItems)
        {
            await _semaphore.WaitAsync(ct);
            tasks.Add(Task.Run(async () =>
            {
                try
                {
                    await ProcessItemAsync(itemId, ct);
                }
                finally
                {
                    _semaphore.Release();
                }
            }, ct));
        }

        await Task.WhenAll(tasks);
    }

    private async Task ProcessItemAsync(Guid workItemId, CancellationToken ct)
    {
        using var scope = _scopeFactory.CreateScope();
        var orchestrator = scope.ServiceProvider.GetRequiredService<IProcessingOrchestrator>();

        try
        {
            _logger.LogInformation("Processing work item {Id}", workItemId);
            await orchestrator.ProcessWorkItemAsync(workItemId, ct: ct);
            _logger.LogInformation("Completed work item {Id}", workItemId);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to process work item {Id}", workItemId);

            // Mark as failed
            try
            {
                var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();
                var workItem = await db.WorkItems.FindAsync(new object[] { workItemId }, ct);
                if (workItem != null)
                {
                    workItem.Status = JobStatus.Failed;
                    await db.SaveChangesAsync(ct);
                }
            }
            catch { }
        }
    }

    private async Task ProcessReprocessRequestsAsync(CancellationToken ct)
    {
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();

        var pendingRequests = await db.ReprocessRequests
            .Where(r => r.Status == ReprocessStatus.Approved)
            .OrderBy(r => r.RequestedAt)
            .Take(MaxConcurrent)
            .ToListAsync(ct);

        foreach (var request in pendingRequests)
        {
            await _semaphore.WaitAsync(ct);
            _ = Task.Run(async () =>
            {
                try
                {
                    var orchestrator = scope.ServiceProvider.GetRequiredService<IProcessingOrchestrator>();
                    await orchestrator.ReprocessWorkItemAsync(request.Id, ct);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Failed to reprocess request {Id}", request.Id);
                }
                finally
                {
                    _semaphore.Release();
                }
            }, ct);
        }
    }
}
