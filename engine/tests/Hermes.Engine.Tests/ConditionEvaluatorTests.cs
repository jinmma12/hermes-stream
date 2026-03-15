using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Services;

namespace Hermes.Engine.Tests;

public class ConditionEvaluatorTests
{
    private readonly ConditionEvaluator _evaluator = new();

    [Theory]
    [InlineData("FILE")]
    [InlineData("API_RESPONSE")]
    [InlineData("DB_CHANGE")]
    [InlineData("UNKNOWN_TYPE")]
    public void Evaluate_AcceptsAllEventTypes(string eventType)
    {
        var evt = new MonitorEvent(eventType, "key1", new(), DateTimeOffset.UtcNow);
        var pipeline = new PipelineInstance { Name = "test" };

        Assert.True(_evaluator.Evaluate(evt, pipeline));
    }

    [Fact]
    public void GenerateDedupKey_FileEvent_UsesPath()
    {
        var evt = new MonitorEvent("FILE", "key1",
            new() { ["path"] = "/data/file1.csv" }, DateTimeOffset.UtcNow);

        var key = _evaluator.GenerateDedupKey(evt);

        Assert.StartsWith("FILE:", key);
        Assert.Equal(37, key.Length); // "FILE:" + 32 hex chars
    }

    [Fact]
    public void GenerateDedupKey_ApiEvent_UsesContentHash()
    {
        var evt = new MonitorEvent("API_RESPONSE", "http://api",
            new() { ["content_hash"] = "abc123" }, DateTimeOffset.UtcNow);

        var key = _evaluator.GenerateDedupKey(evt);

        Assert.StartsWith("API_RESPONSE:", key);
    }

    [Fact]
    public void GenerateDedupKey_SameInput_SameOutput()
    {
        var evt1 = new MonitorEvent("FILE", "key",
            new() { ["path"] = "/data/same.csv" }, DateTimeOffset.UtcNow);
        var evt2 = new MonitorEvent("FILE", "key",
            new() { ["path"] = "/data/same.csv" }, DateTimeOffset.UtcNow);

        Assert.Equal(_evaluator.GenerateDedupKey(evt1), _evaluator.GenerateDedupKey(evt2));
    }

    [Fact]
    public void GenerateDedupKey_DifferentInput_DifferentOutput()
    {
        var evt1 = new MonitorEvent("FILE", "key",
            new() { ["path"] = "/data/file1.csv" }, DateTimeOffset.UtcNow);
        var evt2 = new MonitorEvent("FILE", "key",
            new() { ["path"] = "/data/file2.csv" }, DateTimeOffset.UtcNow);

        Assert.NotEqual(_evaluator.GenerateDedupKey(evt1), _evaluator.GenerateDedupKey(evt2));
    }
}
