using Microsoft.EntityFrameworkCore;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Infrastructure.Data;

namespace Hermes.Engine.Tests;

/// <summary>
/// Helper to create in-memory DbContext for testing.
/// </summary>
public static class TestDbHelper
{
    public static HermesDbContext CreateInMemoryDb(string? dbName = null)
    {
        var options = new DbContextOptionsBuilder<HermesDbContext>()
            .UseInMemoryDatabase(dbName ?? Guid.NewGuid().ToString())
            .Options;
        var db = new HermesDbContext(options);
        db.Database.EnsureCreated();
        return db;
    }

    /// <summary>
    /// Seeds a complete pipeline with collector → algorithm → transfer steps.
    /// </summary>
    public static async Task<(PipelineInstance Pipeline, PipelineActivation Activation)> SeedPipelineAsync(
        HermesDbContext db)
    {
        // Definitions
        var collectorDef = new CollectorDefinition { Code = "test-collector", Name = "Test Collector", Status = DefinitionStatus.Active };
        var algorithmDef = new AlgorithmDefinition { Code = "test-algorithm", Name = "Test Algorithm", Status = DefinitionStatus.Active };
        var transferDef = new TransferDefinition { Code = "test-transfer", Name = "Test Transfer", Status = DefinitionStatus.Active };
        db.CollectorDefinitions.Add(collectorDef);
        db.AlgorithmDefinitions.Add(algorithmDef);
        db.TransferDefinitions.Add(transferDef);
        await db.SaveChangesAsync();

        // Definition versions
        var collectorDefVersion = new CollectorDefinitionVersion
        {
            DefinitionId = collectorDef.Id, VersionNo = 1,
            ExecutionType = ExecutionType.Plugin, ExecutionRef = "COLLECTOR:test-collector",
            IsPublished = true
        };
        var algorithmDefVersion = new AlgorithmDefinitionVersion
        {
            DefinitionId = algorithmDef.Id, VersionNo = 1,
            ExecutionType = ExecutionType.Plugin, ExecutionRef = "ALGORITHM:test-algorithm",
            IsPublished = true
        };
        var transferDefVersion = new TransferDefinitionVersion
        {
            DefinitionId = transferDef.Id, VersionNo = 1,
            ExecutionType = ExecutionType.Plugin, ExecutionRef = "TRANSFER:test-transfer",
            IsPublished = true
        };
        db.CollectorDefinitionVersions.Add(collectorDefVersion);
        db.AlgorithmDefinitionVersions.Add(algorithmDefVersion);
        db.TransferDefinitionVersions.Add(transferDefVersion);
        await db.SaveChangesAsync();

        // Instances
        var collectorInst = new CollectorInstance { DefinitionId = collectorDef.Id, Name = "Test Collector Instance", Status = InstanceStatus.Active };
        var algorithmInst = new AlgorithmInstance { DefinitionId = algorithmDef.Id, Name = "Test Algorithm Instance", Status = InstanceStatus.Active };
        var transferInst = new TransferInstance { DefinitionId = transferDef.Id, Name = "Test Transfer Instance", Status = InstanceStatus.Active };
        db.CollectorInstances.Add(collectorInst);
        db.AlgorithmInstances.Add(algorithmInst);
        db.TransferInstances.Add(transferInst);
        await db.SaveChangesAsync();

        // Instance versions (current recipe)
        db.CollectorInstanceVersions.Add(new CollectorInstanceVersion
        {
            InstanceId = collectorInst.Id, DefVersionId = collectorDefVersion.Id,
            VersionNo = 1, ConfigJson = "{\"url\":\"http://test\"}", IsCurrent = true
        });
        db.AlgorithmInstanceVersions.Add(new AlgorithmInstanceVersion
        {
            InstanceId = algorithmInst.Id, DefVersionId = algorithmDefVersion.Id,
            VersionNo = 1, ConfigJson = "{\"threshold\":0.5}", IsCurrent = true
        });
        db.TransferInstanceVersions.Add(new TransferInstanceVersion
        {
            InstanceId = transferInst.Id, DefVersionId = transferDefVersion.Id,
            VersionNo = 1, ConfigJson = "{\"path\":\"/output\"}", IsCurrent = true
        });
        await db.SaveChangesAsync();

        // Pipeline
        var pipeline = new PipelineInstance
        {
            Name = "Test Pipeline",
            MonitoringType = MonitoringType.FileMonitor,
            MonitoringConfig = "{\"watch_path\":\"/data/input\",\"interval\":\"5s\"}",
            Status = PipelineStatus.Active,
            Steps = new List<PipelineStep>
            {
                new() { StepOrder = 1, StepType = StageType.Collect, RefType = RefType.Collector, RefId = collectorInst.Id, OnError = OnErrorAction.Stop },
                new() { StepOrder = 2, StepType = StageType.Algorithm, RefType = RefType.Algorithm, RefId = algorithmInst.Id, OnError = OnErrorAction.Skip },
                new() { StepOrder = 3, StepType = StageType.Transfer, RefType = RefType.Transfer, RefId = transferInst.Id, OnError = OnErrorAction.Stop },
            }
        };
        db.PipelineInstances.Add(pipeline);
        await db.SaveChangesAsync();

        // Activation
        var activation = new PipelineActivation
        {
            PipelineInstanceId = pipeline.Id,
            Status = ActivationStatus.Running,
            WorkerId = "test-worker"
        };
        db.PipelineActivations.Add(activation);
        await db.SaveChangesAsync();

        return (pipeline, activation);
    }
}
