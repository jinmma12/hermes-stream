using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Services;

namespace Hermes.Engine.Tests;

public class SnapshotResolverTests
{
    [Fact]
    public async Task Capture_CreatesSnapshotWithHash()
    {
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, _) = await TestDbHelper.SeedPipelineAsync(db);
        var resolver = new SnapshotResolver(db);

        var executionId = Guid.NewGuid();
        var steps = pipeline.Steps.OrderBy(s => s.StepOrder).ToList();

        var snapshot = await resolver.CaptureAsync(pipeline, steps, executionId);

        Assert.NotNull(snapshot);
        Assert.Equal(executionId, snapshot.ExecutionId);
        Assert.NotNull(snapshot.SnapshotHash);
        Assert.NotEmpty(snapshot.SnapshotHash);
        Assert.NotEqual("{}", snapshot.CollectorConfig);
        Assert.NotEqual("{}", snapshot.AlgorithmConfig);
        Assert.NotEqual("{}", snapshot.TransferConfig);
    }

    [Fact]
    public async Task Capture_ThenResolve_ReturnsStepConfigs()
    {
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, _) = await TestDbHelper.SeedPipelineAsync(db);
        var resolver = new SnapshotResolver(db);

        var executionId = Guid.NewGuid();
        var steps = pipeline.Steps.OrderBy(s => s.StepOrder).ToList();

        var snapshot = await resolver.CaptureAsync(pipeline, steps, executionId);
        var resolved = await resolver.ResolveAsync(snapshot.Id);

        Assert.NotNull(resolved);
        Assert.Equal(3, resolved.Steps.Count);
        Assert.Equal(StageType.Collect, resolved.Steps[0].StepType);
        Assert.Equal(StageType.Algorithm, resolved.Steps[1].StepType);
        Assert.Equal(StageType.Transfer, resolved.Steps[2].StepType);
    }

    [Fact]
    public async Task Capture_SameConfig_SameHash()
    {
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, _) = await TestDbHelper.SeedPipelineAsync(db);
        var resolver = new SnapshotResolver(db);

        var steps = pipeline.Steps.OrderBy(s => s.StepOrder).ToList();

        var snap1 = await resolver.CaptureAsync(pipeline, steps, Guid.NewGuid());
        var snap2 = await resolver.CaptureAsync(pipeline, steps, Guid.NewGuid());

        Assert.Equal(snap1.SnapshotHash, snap2.SnapshotHash);
    }

    [Fact]
    public async Task Resolve_GetConfigForStep_ReturnsCorrectConfig()
    {
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, _) = await TestDbHelper.SeedPipelineAsync(db);
        var resolver = new SnapshotResolver(db);

        var steps = pipeline.Steps.OrderBy(s => s.StepOrder).ToList();
        var snapshot = await resolver.CaptureAsync(pipeline, steps, Guid.NewGuid());
        var resolved = await resolver.ResolveAsync(snapshot.Id);

        var collectStep = steps.First(s => s.StepType == StageType.Collect);
        var config = resolved.GetConfigForStep(collectStep);

        Assert.NotNull(config);
        Assert.Equal(ExecutionType.Plugin, config.ExecutionType);
        Assert.Contains("url", config.ResolvedConfigJson);
    }
}
