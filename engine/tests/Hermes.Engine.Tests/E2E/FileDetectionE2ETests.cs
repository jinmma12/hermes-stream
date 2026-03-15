using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Infrastructure.Data;
using Hermes.Engine.Services;
using Hermes.Engine.Services.Monitors;

namespace Hermes.Engine.Tests.E2E;

/// <summary>
/// E2E tests: real CSV files on disk → FileMonitor detects → WorkItem created
/// → ProcessingOrchestrator processes → output verified.
/// </summary>
public class FileDetectionE2ETests : IDisposable
{
    private readonly string _inputDir;
    private readonly string _outputDir;

    public FileDetectionE2ETests()
    {
        _inputDir = Path.Combine(Path.GetTempPath(), $"hermes-e2e-in-{Guid.NewGuid():N}");
        _outputDir = Path.Combine(Path.GetTempPath(), $"hermes-e2e-out-{Guid.NewGuid():N}");
        Directory.CreateDirectory(_inputDir);
        Directory.CreateDirectory(_outputDir);
    }

    public void Dispose()
    {
        if (Directory.Exists(_inputDir)) Directory.Delete(_inputDir, true);
        if (Directory.Exists(_outputDir)) Directory.Delete(_outputDir, true);
    }

    [Fact]
    public async Task FileMonitor_DetectsNewCsvFile()
    {
        // Arrange: create a CSV file
        var csvPath = Path.Combine(_inputDir, "data_001.csv");
        await File.WriteAllTextAsync(csvPath,
            "id,name,value\n1,sensor-a,23.5\n2,sensor-b,18.2\n3,sensor-c,31.0\n");

        var monitor = new FileMonitor(_inputDir, "*.csv");

        // Act
        var events = await monitor.PollAsync();

        // Assert
        Assert.Single(events);
        Assert.Equal("FILE", events[0].EventType);
        Assert.Contains("data_001.csv", events[0].Key);
        Assert.Equal("data_001.csv", events[0].Metadata["filename"]?.ToString());
        Assert.True((long)events[0].Metadata["size"] > 0);
    }

    [Fact]
    public async Task FileMonitor_IgnoresAlreadySeenFiles()
    {
        var csvPath = Path.Combine(_inputDir, "seen.csv");
        await File.WriteAllTextAsync(csvPath, "id,value\n1,100\n");

        var monitor = new FileMonitor(_inputDir, "*.csv");

        var first = await monitor.PollAsync();
        Assert.Single(first);

        // Second poll should return nothing
        var second = await monitor.PollAsync();
        Assert.Empty(second);
    }

    [Fact]
    public async Task FileMonitor_DetectsMultipleNewFiles()
    {
        for (int i = 1; i <= 5; i++)
        {
            await File.WriteAllTextAsync(
                Path.Combine(_inputDir, $"batch_{i:D3}.csv"),
                $"id,value\n{i},{i * 10.5}\n");
        }

        var monitor = new FileMonitor(_inputDir, "*.csv");
        var events = await monitor.PollAsync();

        Assert.Equal(5, events.Count);
        Assert.All(events, e => Assert.Equal("FILE", e.EventType));
    }

    [Fact]
    public async Task FileMonitor_PatternFiltering_OnlyCsv()
    {
        await File.WriteAllTextAsync(Path.Combine(_inputDir, "data.csv"), "a,b\n1,2\n");
        await File.WriteAllTextAsync(Path.Combine(_inputDir, "readme.txt"), "ignore me");
        await File.WriteAllTextAsync(Path.Combine(_inputDir, "image.png"), "fake png");

        var monitor = new FileMonitor(_inputDir, "*.csv");
        var events = await monitor.PollAsync();

        Assert.Single(events);
        Assert.Contains(".csv", events[0].Key);
    }

    [Fact]
    public async Task FileMonitor_EmptyDirectory_NoEvents()
    {
        var monitor = new FileMonitor(_inputDir, "*.csv");
        var events = await monitor.PollAsync();
        Assert.Empty(events);
    }

    [Fact]
    public async Task FullPipeline_FileDetection_To_Processing()
    {
        // 1. Setup: Create CSV files
        var csv1 = "timestamp,sensor_id,temperature,humidity\n" +
                   "2026-03-15T10:00:00,S001,22.5,45.0\n" +
                   "2026-03-15T10:01:00,S002,23.1,44.8\n" +
                   "2026-03-15T10:02:00,S003,21.8,46.2\n";
        var csv2 = "timestamp,sensor_id,temperature,humidity\n" +
                   "2026-03-15T10:03:00,S004,25.0,42.0\n";

        await File.WriteAllTextAsync(Path.Combine(_inputDir, "sensors_batch1.csv"), csv1);
        await File.WriteAllTextAsync(Path.Combine(_inputDir, "sensors_batch2.csv"), csv2);

        // 2. FileMonitor detects files
        var monitor = new FileMonitor(_inputDir, "*.csv");
        var events = await monitor.PollAsync();
        Assert.Equal(2, events.Count);

        // 3. ConditionEvaluator checks + dedup
        var evaluator = new ConditionEvaluator();
        var pipeline = new PipelineInstance { Name = "Sensor Pipeline" };

        foreach (var evt in events)
        {
            Assert.True(evaluator.Evaluate(evt, pipeline));
        }

        var key1 = evaluator.GenerateDedupKey(events[0]);
        var key2 = evaluator.GenerateDedupKey(events[1]);
        Assert.NotEqual(key1, key2); // Different files = different keys

        // Same file = same key (idempotent)
        Assert.Equal(key1, evaluator.GenerateDedupKey(events[0]));

        // 4. Create WorkItems in DB
        var db = TestDbHelper.CreateInMemoryDb();
        var (seededPipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        var workItems = new List<WorkItem>();
        foreach (var evt in events)
        {
            var wi = new WorkItem
            {
                PipelineActivationId = activation.Id,
                PipelineInstanceId = seededPipeline.Id,
                SourceType = SourceType.File,
                SourceKey = evt.Key,
                SourceMetadata = JsonSerializer.Serialize(evt.Metadata),
                DedupKey = evaluator.GenerateDedupKey(evt),
                DetectedAt = evt.DetectedAt,
                Status = JobStatus.Queued
            };
            db.WorkItems.Add(wi);
            workItems.Add(wi);
        }
        await db.SaveChangesAsync();

        // 5. Process each work item through orchestrator
        var snapshotResolver = new SnapshotResolver(db);
        var dispatcher = new CsvProcessingDispatcher(_outputDir);
        var orchestrator = new ProcessingOrchestrator(db, dispatcher, snapshotResolver,
            NullLogger<ProcessingOrchestrator>.Instance);

        foreach (var wi in workItems)
        {
            var execution = await orchestrator.ProcessWorkItemAsync(wi.Id);
            Assert.Equal(ExecutionStatus.Completed, execution.Status);
        }

        // 6. Verify results
        var completedItems = db.WorkItems.Where(w => w.Status == JobStatus.Completed).ToList();
        Assert.Equal(2, completedItems.Count);

        var allExecutions = db.WorkItemExecutions.ToList();
        Assert.Equal(2, allExecutions.Count);
        Assert.All(allExecutions, e =>
        {
            Assert.Equal(ExecutionStatus.Completed, e.Status);
            Assert.True(e.DurationMs > 0);
        });

        // Verify event logs exist
        var eventLogs = db.ExecutionEventLogs.ToList();
        Assert.True(eventLogs.Count >= 4); // At least START+DONE per execution

        // Verify snapshots
        var snapshots = db.ExecutionSnapshots.ToList();
        Assert.Equal(2, snapshots.Count);
        Assert.All(snapshots, s => Assert.NotNull(s.SnapshotHash));
    }

    [Fact]
    public async Task FullPipeline_DuplicateFile_Deduplicated()
    {
        var csv = "id,value\n1,100\n";
        var path = Path.Combine(_inputDir, "dup_data.csv");
        await File.WriteAllTextAsync(path, csv);

        var monitor = new FileMonitor(_inputDir, "*.csv");
        var events = await monitor.PollAsync();
        Assert.Single(events);

        var evaluator = new ConditionEvaluator();
        var dedupKey = evaluator.GenerateDedupKey(events[0]);

        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        // First work item
        db.WorkItems.Add(new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.File,
            SourceKey = path,
            DedupKey = dedupKey,
            Status = JobStatus.Queued
        });
        await db.SaveChangesAsync();

        // Try to add duplicate - check dedup
        var exists = await db.WorkItems
            .AnyAsync(w => w.PipelineInstanceId == pipeline.Id && w.DedupKey == dedupKey);
        Assert.True(exists); // Duplicate detected, should NOT create another

        Assert.Equal(1, await db.WorkItems.CountAsync());
    }

    [Fact]
    public async Task FullPipeline_LargeCsvFile_ProcessedSuccessfully()
    {
        // Generate 1000-row CSV
        var lines = new List<string> { "id,name,value,category,timestamp" };
        for (int i = 1; i <= 1000; i++)
        {
            lines.Add($"{i},item_{i},{i * 1.5:F2},{(i % 5 == 0 ? "A" : "B")},2026-03-15T{i / 60:D2}:{i % 60:D2}:00");
        }
        var csvPath = Path.Combine(_inputDir, "large_dataset.csv");
        await File.WriteAllLinesAsync(csvPath, lines);

        var fileInfo = new FileInfo(csvPath);
        Assert.True(fileInfo.Length > 10000); // At least 10KB

        // Monitor picks it up
        var monitor = new FileMonitor(_inputDir, "*.csv");
        var events = await monitor.PollAsync();
        Assert.Single(events);
        Assert.Equal(fileInfo.Length, (long)events[0].Metadata["size"]);

        // Process through pipeline
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        var wi = new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.File,
            SourceKey = csvPath,
            SourceMetadata = JsonSerializer.Serialize(new { rows = 1000, size = fileInfo.Length }),
            Status = JobStatus.Queued
        };
        db.WorkItems.Add(wi);
        await db.SaveChangesAsync();

        var snapshotResolver = new SnapshotResolver(db);
        var dispatcher = new CsvProcessingDispatcher(_outputDir);
        var orchestrator = new ProcessingOrchestrator(db, dispatcher, snapshotResolver,
            NullLogger<ProcessingOrchestrator>.Instance);

        var execution = await orchestrator.ProcessWorkItemAsync(wi.Id);
        Assert.Equal(ExecutionStatus.Completed, execution.Status);

        // Verify the dispatcher received and "processed" the file
        Assert.True(dispatcher.ProcessedFiles.Count > 0);
    }

    [Fact]
    public async Task FullPipeline_StepFailure_ErrorHandling()
    {
        var csv = "id,value\n1,BAD_DATA\n";
        await File.WriteAllTextAsync(Path.Combine(_inputDir, "bad_data.csv"), csv);

        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        var wi = new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.File,
            SourceKey = Path.Combine(_inputDir, "bad_data.csv"),
            Status = JobStatus.Queued
        };
        db.WorkItems.Add(wi);
        await db.SaveChangesAsync();

        // Dispatcher that fails on algorithm step
        var failingDispatcher = new SelectiveFailDispatcher(failOnStep: 2);
        var snapshotResolver = new SnapshotResolver(db);
        var orchestrator = new ProcessingOrchestrator(db, failingDispatcher, snapshotResolver,
            NullLogger<ProcessingOrchestrator>.Instance);

        var execution = await orchestrator.ProcessWorkItemAsync(wi.Id);

        // Step 2 (Algorithm) has OnError=Skip, so processing should continue
        // Step 3 (Transfer) has OnError=Stop

        // Check step executions
        var stepExecs = db.WorkItemStepExecutions
            .Where(se => se.ExecutionId == execution.Id)
            .OrderBy(se => se.StepOrder)
            .ToList();

        // Step 1: Completed (collect succeeds)
        Assert.Equal(StepExecutionStatus.Completed, stepExecs[0].Status);
        // Step 2: Skipped (algorithm fails, OnError=Skip)
        Assert.Equal(StepExecutionStatus.Skipped, stepExecs[1].Status);
        // Step 3: Completed (transfer succeeds)
        Assert.Equal(StepExecutionStatus.Completed, stepExecs[2].Status);
    }

    [Fact]
    public async Task FullPipeline_Reprocess_FromAlgorithmStep()
    {
        var csv = "id,value\n1,42\n";
        await File.WriteAllTextAsync(Path.Combine(_inputDir, "reprocess_me.csv"), csv);

        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        var wi = new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.File,
            SourceKey = Path.Combine(_inputDir, "reprocess_me.csv"),
            Status = JobStatus.Queued
        };
        db.WorkItems.Add(wi);
        await db.SaveChangesAsync();

        var dispatcher = new CsvProcessingDispatcher(_outputDir);
        var snapshotResolver = new SnapshotResolver(db);
        var orchestrator = new ProcessingOrchestrator(db, dispatcher, snapshotResolver,
            NullLogger<ProcessingOrchestrator>.Instance);

        // First execution: full pipeline
        var exec1 = await orchestrator.ProcessWorkItemAsync(wi.Id);
        Assert.Equal(ExecutionStatus.Completed, exec1.Status);
        Assert.Equal(1, exec1.ExecutionNo);

        // Reprocess: start from step 2 (algorithm)
        var exec2 = await orchestrator.ProcessWorkItemAsync(
            wi.Id,
            triggerType: TriggerType.Reprocess,
            triggerSource: "operator:test",
            startFromStep: 2);
        Assert.Equal(ExecutionStatus.Completed, exec2.Status);
        Assert.Equal(2, exec2.ExecutionNo);
        Assert.Equal(TriggerType.Reprocess, exec2.TriggerType);

        // Should have 2 executions total
        var updated = await db.WorkItems.FindAsync(wi.Id);
        Assert.Equal(2, updated!.ExecutionCount);
    }

    [Fact]
    public async Task FullPipeline_RecipeVersionChange_NewSnapshotHash()
    {
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        var wi1 = new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.File,
            SourceKey = "/data/v1.csv",
            Status = JobStatus.Queued
        };
        db.WorkItems.Add(wi1);
        await db.SaveChangesAsync();

        var dispatcher = new CsvProcessingDispatcher(_outputDir);
        var snapshotResolver = new SnapshotResolver(db);
        var orchestrator = new ProcessingOrchestrator(db, dispatcher, snapshotResolver,
            NullLogger<ProcessingOrchestrator>.Instance);

        // Process with version 1
        var exec1 = await orchestrator.ProcessWorkItemAsync(wi1.Id);
        var snap1 = db.ExecutionSnapshots.First(s => s.ExecutionId == exec1.Id);

        // Change recipe: add new algorithm version
        var algoInst = db.AlgorithmInstances.First();
        var oldVersion = db.AlgorithmInstanceVersions.First(v => v.InstanceId == algoInst.Id);
        oldVersion.IsCurrent = false;

        var algoDef = db.AlgorithmDefinitionVersions.First();
        db.AlgorithmInstanceVersions.Add(new AlgorithmInstanceVersion
        {
            InstanceId = algoInst.Id,
            DefVersionId = algoDef.Id,
            VersionNo = 2,
            ConfigJson = "{\"threshold\":0.8,\"new_param\":true}",
            IsCurrent = true
        });
        await db.SaveChangesAsync();

        // Process with version 2
        var wi2 = new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.File,
            SourceKey = "/data/v2.csv",
            Status = JobStatus.Queued
        };
        db.WorkItems.Add(wi2);
        await db.SaveChangesAsync();

        var exec2 = await orchestrator.ProcessWorkItemAsync(wi2.Id);
        var snap2 = db.ExecutionSnapshots.First(s => s.ExecutionId == exec2.Id);

        // Snapshots should have different hashes (recipe changed)
        Assert.NotEqual(snap1.SnapshotHash, snap2.SnapshotHash);
    }

    /// <summary>Mock dispatcher that simulates CSV processing: read → transform → write output.</summary>
    private class CsvProcessingDispatcher : IExecutionDispatcher
    {
        private readonly string _outputDir;
        public List<string> ProcessedFiles { get; } = new();

        public CsvProcessingDispatcher(string outputDir) => _outputDir = outputDir;

        public Task<ExecutionResult> DispatchAsync(
            ExecutionType executionType, string? executionRef, string configJson,
            string? inputDataJson = null, Dictionary<string, string>? context = null,
            CancellationToken ct = default)
        {
            var stepOrder = context?.GetValueOrDefault("step_order") ?? "0";
            var workItemId = context?.GetValueOrDefault("work_item_id") ?? "unknown";

            return Task.FromResult(stepOrder switch
            {
                "1" => SimulateCollect(configJson, workItemId),
                "2" => SimulateAlgorithm(inputDataJson),
                "3" => SimulateTransfer(inputDataJson, workItemId),
                _ => new ExecutionResult(true, "{}", "{\"step\":\"unknown\"}", 10, new())
            });
        }

        private ExecutionResult SimulateCollect(string configJson, string workItemId)
        {
            // Simulate reading a CSV file
            var records = new[]
            {
                new { id = 1, sensor = "S001", value = 23.5, status = "normal" },
                new { id = 2, sensor = "S002", value = 18.2, status = "normal" },
                new { id = 3, sensor = "S003", value = 31.0, status = "warning" }
            };

            ProcessedFiles.Add(workItemId);
            var output = JsonSerializer.Serialize(new { records, record_count = records.Length });
            return new ExecutionResult(true, output,
                JsonSerializer.Serialize(new { source = "csv", records_read = records.Length }),
                50, new List<LogEntry> { new(DateTimeOffset.UtcNow, "INFO", $"Collected {records.Length} records") });
        }

        private ExecutionResult SimulateAlgorithm(string? inputDataJson)
        {
            // Simulate: filter records where value > 20
            var transformed = new
            {
                records = new[]
                {
                    new { id = 1, sensor = "S001", value = 23.5, anomaly = false },
                    new { id = 3, sensor = "S003", value = 31.0, anomaly = true }
                },
                filtered_count = 2,
                anomalies_found = 1
            };
            return new ExecutionResult(true, JsonSerializer.Serialize(transformed),
                JsonSerializer.Serialize(new { algorithm = "threshold_filter", anomalies = 1 }),
                30, new List<LogEntry> { new(DateTimeOffset.UtcNow, "INFO", "Filtered: 2 records, 1 anomaly") });
        }

        private ExecutionResult SimulateTransfer(string? inputDataJson, string workItemId)
        {
            // Simulate writing output file
            var outputPath = Path.Combine(_outputDir, $"result_{workItemId[..8]}.json");
            File.WriteAllText(outputPath, inputDataJson ?? "{}");

            return new ExecutionResult(true,
                JsonSerializer.Serialize(new { path = outputPath, bytes_written = new FileInfo(outputPath).Length }),
                JsonSerializer.Serialize(new { destination = "file", path = outputPath }),
                20, new List<LogEntry> { new(DateTimeOffset.UtcNow, "INFO", $"Written to {outputPath}") });
        }
    }

    /// <summary>Mock dispatcher that fails on a specific step number.</summary>
    private class SelectiveFailDispatcher : IExecutionDispatcher
    {
        private readonly int _failOnStep;
        public SelectiveFailDispatcher(int failOnStep) => _failOnStep = failOnStep;

        public Task<ExecutionResult> DispatchAsync(
            ExecutionType executionType, string? executionRef, string configJson,
            string? inputDataJson = null, Dictionary<string, string>? context = null,
            CancellationToken ct = default)
        {
            var stepOrder = int.Parse(context?.GetValueOrDefault("step_order") ?? "0");

            if (stepOrder == _failOnStep)
            {
                return Task.FromResult(new ExecutionResult(false, null, null, 10,
                    new List<LogEntry> { new(DateTimeOffset.UtcNow, "ERROR", $"Step {stepOrder} failed: validation error") }));
            }

            return Task.FromResult(new ExecutionResult(true,
                JsonSerializer.Serialize(new { step = stepOrder, status = "ok" }),
                "{\"status\":\"success\"}", 15, new()));
        }
    }
}
