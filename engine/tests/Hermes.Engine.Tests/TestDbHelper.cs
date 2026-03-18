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
    /// Seeds a complete pipeline with collector → process → export steps.
    /// </summary>
    public static async Task<(PipelineInstance Pipeline, PipelineActivation Activation)> SeedPipelineAsync(
        HermesDbContext db)
    {
        // Definitions
        var collectorDef = new CollectorDefinition { Code = "test-collector", Name = "Test Collector", Status = DefinitionStatus.Active };
        var algorithmDef = new ProcessDefinition { Code = "test-algorithm", Name = "Test Algorithm", Status = DefinitionStatus.Active };
        var transferDef = new ExportDefinition { Code = "test-transfer", Name = "Test Transfer", Status = DefinitionStatus.Active };
        db.CollectorDefinitions.Add(collectorDef);
        db.ProcessDefinitions.Add(algorithmDef);
        db.ExportDefinitions.Add(transferDef);
        await db.SaveChangesAsync();

        // Definition versions
        var collectorDefVersion = new CollectorDefinitionVersion
        {
            DefinitionId = collectorDef.Id, VersionNo = 1,
            ExecutionType = ExecutionType.Plugin, ExecutionRef = "COLLECTOR:test-collector",
            IsPublished = true
        };
        var algorithmDefVersion = new ProcessDefinitionVersion
        {
            DefinitionId = algorithmDef.Id, VersionNo = 1,
            ExecutionType = ExecutionType.Plugin, ExecutionRef = "ALGORITHM:test-algorithm",
            IsPublished = true
        };
        var transferDefVersion = new ExportDefinitionVersion
        {
            DefinitionId = transferDef.Id, VersionNo = 1,
            ExecutionType = ExecutionType.Plugin, ExecutionRef = "TRANSFER:test-transfer",
            IsPublished = true
        };
        db.CollectorDefinitionVersions.Add(collectorDefVersion);
        db.ProcessDefinitionVersions.Add(algorithmDefVersion);
        db.ExportDefinitionVersions.Add(transferDefVersion);
        await db.SaveChangesAsync();

        // Instances
        var collectorInst = new CollectorInstance { DefinitionId = collectorDef.Id, Name = "Test Collector Instance", Status = InstanceStatus.Active };
        var algorithmInst = new ProcessInstance { DefinitionId = algorithmDef.Id, Name = "Test Algorithm Instance", Status = InstanceStatus.Active };
        var transferInst = new ExportInstance { DefinitionId = transferDef.Id, Name = "Test Transfer Instance", Status = InstanceStatus.Active };
        db.CollectorInstances.Add(collectorInst);
        db.ProcessInstances.Add(algorithmInst);
        db.ExportInstances.Add(transferInst);
        await db.SaveChangesAsync();

        // Instance versions (current recipe)
        db.CollectorInstanceVersions.Add(new CollectorInstanceVersion
        {
            InstanceId = collectorInst.Id, DefVersionId = collectorDefVersion.Id,
            VersionNo = 1, ConfigJson = "{\"url\":\"http://test\"}", IsCurrent = true
        });
        db.ProcessInstanceVersions.Add(new ProcessInstanceVersion
        {
            InstanceId = algorithmInst.Id, DefVersionId = algorithmDefVersion.Id,
            VersionNo = 1, ConfigJson = "{\"threshold\":0.5}", IsCurrent = true
        });
        db.ExportInstanceVersions.Add(new ExportInstanceVersion
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
                new() { StepOrder = 2, StepType = StageType.Process, RefType = RefType.Process, RefId = algorithmInst.Id, OnError = OnErrorAction.Skip },
                new() { StepOrder = 3, StepType = StageType.Export, RefType = RefType.Export, RefId = transferInst.Id, OnError = OnErrorAction.Stop },
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
