using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Infrastructure.Data;

namespace Hermes.Engine.Workers;

public class MonitoringWorker : BackgroundService
{
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly IMonitoringEngine _monitoringEngine;
    private readonly ILogger<MonitoringWorker> _logger;
    private const int NewActivationPollIntervalSeconds = 10;

    public MonitoringWorker(
        IServiceScopeFactory scopeFactory,
        IMonitoringEngine monitoringEngine,
        ILogger<MonitoringWorker> logger)
    {
        _scopeFactory = scopeFactory;
        _monitoringEngine = monitoringEngine;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("MonitoringWorker starting...");

        // Load existing active activations
        await LoadActiveActivationsAsync(stoppingToken);

        // Poll for new activations
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await PollNewActivationsAsync(stoppingToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error polling for new activations");
            }

            await Task.Delay(TimeSpan.FromSeconds(NewActivationPollIntervalSeconds), stoppingToken);
        }
    }

    private async Task LoadActiveActivationsAsync(CancellationToken ct)
    {
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();

        var activeActivations = await db.PipelineActivations
            .Include(a => a.PipelineInstance)
                .ThenInclude(p => p.Steps)
            .Where(a => a.Status == ActivationStatus.Starting || a.Status == ActivationStatus.Running)
            .ToListAsync(ct);

        foreach (var activation in activeActivations)
        {
            try
            {
                await _monitoringEngine.StartMonitoringAsync(activation, ct);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to start monitoring for activation {Id}", activation.Id);
            }
        }

        _logger.LogInformation("Loaded {Count} active activations", activeActivations.Count);
    }

    private async Task PollNewActivationsAsync(CancellationToken ct)
    {
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<HermesDbContext>();

        var newActivations = await db.PipelineActivations
            .Include(a => a.PipelineInstance)
                .ThenInclude(p => p.Steps)
            .Where(a => a.Status == ActivationStatus.Starting && !_monitoringEngine.IsMonitoring(a.Id))
            .ToListAsync(ct);

        foreach (var activation in newActivations)
        {
            try
            {
                await _monitoringEngine.StartMonitoringAsync(activation, ct);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to start monitoring for new activation {Id}", activation.Id);
            }
        }

        // Clean up stopped activations
        var stoppedActivations = await db.PipelineActivations
            .Where(a => (a.Status == ActivationStatus.Stopping || a.Status == ActivationStatus.Stopped || a.Status == ActivationStatus.Error))
            .Select(a => a.Id)
            .ToListAsync(ct);

        foreach (var activationId in stoppedActivations)
        {
            if (_monitoringEngine.IsMonitoring(activationId))
                await _monitoringEngine.StopMonitoringAsync(activationId, ct);
        }
    }
}
