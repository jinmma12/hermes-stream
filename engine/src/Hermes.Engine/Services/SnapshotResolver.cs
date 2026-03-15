using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Infrastructure.Data;

namespace Hermes.Engine.Services;

public class SnapshotResolver : ISnapshotResolver
{
    private readonly HermesDbContext _db;

    public SnapshotResolver(HermesDbContext db) => _db = db;

    public async Task<ExecutionSnapshot> CaptureAsync(
        PipelineInstance pipeline,
        IReadOnlyList<PipelineStep> steps,
        Guid executionId,
        bool useLatestRecipe = true,
        CancellationToken ct = default)
    {
        var pipelineConfig = JsonSerializer.Serialize(new {
            pipeline.Name,
            MonitoringType = pipeline.MonitoringType?.ToString(),
            pipeline.MonitoringConfig,
            Status = pipeline.Status.ToString()
        });

        var collectorConfigs = new Dictionary<string, object>();
        var algorithmConfigs = new Dictionary<string, object>();
        var transferConfigs = new Dictionary<string, object>();

        foreach (var step in steps.OrderBy(s => s.StepOrder))
        {
            var (configJson, executionType, executionRef, versionNo) = step.RefType switch
            {
                RefType.Collector => await ResolveCollectorAsync(step.RefId, useLatestRecipe, ct),
                RefType.Algorithm => await ResolveAlgorithmAsync(step.RefId, useLatestRecipe, ct),
                RefType.Transfer => await ResolveTransferAsync(step.RefId, useLatestRecipe, ct),
                _ => ("{}",  ExecutionType.Internal, (string?)null, 0)
            };

            var stepData = new {
                StepId = step.Id,
                step.StepOrder,
                StepType = step.StepType.ToString(),
                RefType = step.RefType.ToString(),
                step.RefId,
                ExecutionType = executionType.ToString(),
                ExecutionRef = executionRef,
                Config = configJson,
                VersionNo = versionNo
            };

            var bucket = step.RefType switch
            {
                RefType.Collector => collectorConfigs,
                RefType.Algorithm => algorithmConfigs,
                RefType.Transfer => transferConfigs,
                _ => collectorConfigs
            };
            bucket[step.Id.ToString()] = stepData;
        }

        var allConfigText = pipelineConfig +
            JsonSerializer.Serialize(collectorConfigs) +
            JsonSerializer.Serialize(algorithmConfigs) +
            JsonSerializer.Serialize(transferConfigs);
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(allConfigText))).ToLowerInvariant();

        var snapshot = new ExecutionSnapshot
        {
            ExecutionId = executionId,
            PipelineConfig = pipelineConfig,
            CollectorConfig = JsonSerializer.Serialize(collectorConfigs),
            AlgorithmConfig = JsonSerializer.Serialize(algorithmConfigs),
            TransferConfig = JsonSerializer.Serialize(transferConfigs),
            SnapshotHash = hash,
            CreatedAt = DateTimeOffset.UtcNow
        };

        _db.ExecutionSnapshots.Add(snapshot);
        await _db.SaveChangesAsync(ct);
        return snapshot;
    }

    public async Task<ResolvedConfig> ResolveAsync(Guid snapshotId, CancellationToken ct = default)
    {
        var snapshot = await _db.ExecutionSnapshots.FindAsync(new object[] { snapshotId }, ct)
            ?? throw new InvalidOperationException($"Snapshot {snapshotId} not found");

        var steps = new List<StepConfig>();

        // Parse all config buckets and rebuild StepConfigs
        foreach (var bucket in new[] { snapshot.CollectorConfig, snapshot.AlgorithmConfig, snapshot.TransferConfig })
        {
            if (string.IsNullOrEmpty(bucket) || bucket == "{}") continue;
            var dict = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(bucket);
            if (dict == null) continue;

            foreach (var (_, value) in dict)
            {
                steps.Add(new StepConfig(
                    StepId: value.GetProperty("StepId").GetGuid(),
                    StepOrder: value.GetProperty("StepOrder").GetInt32(),
                    StepType: Enum.Parse<StageType>(value.GetProperty("StepType").GetString()!),
                    RefType: Enum.Parse<RefType>(value.GetProperty("RefType").GetString()!),
                    RefId: value.GetProperty("RefId").GetGuid(),
                    ExecutionType: Enum.Parse<ExecutionType>(value.GetProperty("ExecutionType").GetString()!),
                    ExecutionRef: value.GetProperty("ExecutionRef").GetString(),
                    ResolvedConfigJson: value.GetProperty("Config").GetString() ?? "{}",
                    VersionNo: value.GetProperty("VersionNo").GetInt32()
                ));
            }
        }

        return new ResolvedConfig(snapshot.PipelineConfig, steps.OrderBy(s => s.StepOrder).ToList());
    }

    private async Task<(string configJson, ExecutionType execType, string? execRef, int versionNo)> ResolveCollectorAsync(Guid refId, bool useLatest, CancellationToken ct)
    {
        var version = useLatest
            ? await _db.CollectorInstanceVersions.Where(v => v.InstanceId == refId && v.IsCurrent).FirstOrDefaultAsync(ct)
              ?? await _db.CollectorInstanceVersions.Where(v => v.InstanceId == refId).OrderByDescending(v => v.VersionNo).FirstOrDefaultAsync(ct)
            : await _db.CollectorInstanceVersions.Where(v => v.InstanceId == refId).OrderByDescending(v => v.VersionNo).FirstOrDefaultAsync(ct);

        if (version == null) return ("{}", ExecutionType.Plugin, null, 0);

        var defVersion = await _db.CollectorDefinitionVersions.FindAsync(new object[] { version.DefVersionId }, ct);
        return (version.ConfigJson, defVersion?.ExecutionType ?? ExecutionType.Plugin, defVersion?.ExecutionRef, version.VersionNo);
    }

    private async Task<(string configJson, ExecutionType execType, string? execRef, int versionNo)> ResolveAlgorithmAsync(Guid refId, bool useLatest, CancellationToken ct)
    {
        var version = useLatest
            ? await _db.AlgorithmInstanceVersions.Where(v => v.InstanceId == refId && v.IsCurrent).FirstOrDefaultAsync(ct)
              ?? await _db.AlgorithmInstanceVersions.Where(v => v.InstanceId == refId).OrderByDescending(v => v.VersionNo).FirstOrDefaultAsync(ct)
            : await _db.AlgorithmInstanceVersions.Where(v => v.InstanceId == refId).OrderByDescending(v => v.VersionNo).FirstOrDefaultAsync(ct);

        if (version == null) return ("{}", ExecutionType.Plugin, null, 0);

        var defVersion = await _db.AlgorithmDefinitionVersions.FindAsync(new object[] { version.DefVersionId }, ct);
        return (version.ConfigJson, defVersion?.ExecutionType ?? ExecutionType.Plugin, defVersion?.ExecutionRef, version.VersionNo);
    }

    private async Task<(string configJson, ExecutionType execType, string? execRef, int versionNo)> ResolveTransferAsync(Guid refId, bool useLatest, CancellationToken ct)
    {
        var version = useLatest
            ? await _db.TransferInstanceVersions.Where(v => v.InstanceId == refId && v.IsCurrent).FirstOrDefaultAsync(ct)
              ?? await _db.TransferInstanceVersions.Where(v => v.InstanceId == refId).OrderByDescending(v => v.VersionNo).FirstOrDefaultAsync(ct)
            : await _db.TransferInstanceVersions.Where(v => v.InstanceId == refId).OrderByDescending(v => v.VersionNo).FirstOrDefaultAsync(ct);

        if (version == null) return ("{}", ExecutionType.Plugin, null, 0);

        var defVersion = await _db.TransferDefinitionVersions.FindAsync(new object[] { version.DefVersionId }, ct);
        return (version.ConfigJson, defVersion?.ExecutionType ?? ExecutionType.Plugin, defVersion?.ExecutionRef, version.VersionNo);
    }
}
