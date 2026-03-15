using System.Text.Json;
using Microsoft.Extensions.Logging.Abstractions;
using Hermes.Engine.Domain;
using Hermes.Engine.Domain.Entities;
using Hermes.Engine.Services;
using Hermes.Engine.Services.Monitors;

namespace Hermes.Engine.Tests.E2E;

/// <summary>
/// E2E tests simulating FTP-style collection: remote directory listing → download → process.
/// FTP is mocked via a local temp directory representing the FTP server's file system.
/// </summary>
public class FtpCollectionE2ETests : IDisposable
{
    private readonly string _ftpRoot;
    private readonly string _localStaging;
    private readonly string _outputDir;

    public FtpCollectionE2ETests()
    {
        _ftpRoot = Path.Combine(Path.GetTempPath(), $"hermes-ftp-{Guid.NewGuid():N}");
        _localStaging = Path.Combine(Path.GetTempPath(), $"hermes-staging-{Guid.NewGuid():N}");
        _outputDir = Path.Combine(Path.GetTempPath(), $"hermes-out-{Guid.NewGuid():N}");
        Directory.CreateDirectory(_ftpRoot);
        Directory.CreateDirectory(_localStaging);
        Directory.CreateDirectory(_outputDir);
    }

    public void Dispose()
    {
        if (Directory.Exists(_ftpRoot)) Directory.Delete(_ftpRoot, true);
        if (Directory.Exists(_localStaging)) Directory.Delete(_localStaging, true);
        if (Directory.Exists(_outputDir)) Directory.Delete(_outputDir, true);
    }

    [Fact]
    public async Task FtpCollection_DetectRemoteFiles_DownloadAndProcess()
    {
        // 1. Simulate FTP server with CSV files uploaded by external system
        await SimulateFtpUpload("equipment_log_20260315_001.csv", new[]
        {
            "timestamp,equipment_id,metric,value,unit",
            "2026-03-15T08:00:00,EQ-001,temperature,72.3,F",
            "2026-03-15T08:00:00,EQ-001,pressure,14.7,psi",
            "2026-03-15T08:00:00,EQ-001,vibration,0.02,mm/s",
        });
        await SimulateFtpUpload("equipment_log_20260315_002.csv", new[]
        {
            "timestamp,equipment_id,metric,value,unit",
            "2026-03-15T09:00:00,EQ-002,temperature,185.0,F",
            "2026-03-15T09:00:00,EQ-002,pressure,15.1,psi",
            "2026-03-15T09:00:00,EQ-002,vibration,0.85,mm/s",
        });

        // 2. FTP monitor scans remote directory (simulated as local dir)
        var ftpMonitor = new FileMonitor(_ftpRoot, "*.csv");
        var remoteFiles = await ftpMonitor.PollAsync();
        Assert.Equal(2, remoteFiles.Count);

        // 3. Simulate "download" to local staging
        foreach (var evt in remoteFiles)
        {
            var remotePath = evt.Metadata["path"]!.ToString()!;
            var localPath = Path.Combine(_localStaging, Path.GetFileName(remotePath));
            File.Copy(remotePath, localPath);
            Assert.True(File.Exists(localPath));
        }

        // 4. Verify downloaded files content
        var stagedFiles = Directory.GetFiles(_localStaging, "*.csv");
        Assert.Equal(2, stagedFiles.Length);

        foreach (var file in stagedFiles)
        {
            var lines = await File.ReadAllLinesAsync(file);
            Assert.True(lines.Length > 1); // Header + data
            Assert.Contains("equipment_id", lines[0]); // Has expected columns
        }

        // 5. Process through pipeline
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);
        var evaluator = new ConditionEvaluator();

        // Create work items for downloaded files
        var stagingMonitor = new FileMonitor(_localStaging, "*.csv");
        var localEvents = await stagingMonitor.PollAsync();

        foreach (var evt in localEvents)
        {
            var wi = new WorkItem
            {
                PipelineActivationId = activation.Id,
                PipelineInstanceId = pipeline.Id,
                SourceType = SourceType.File,
                SourceKey = evt.Key,
                SourceMetadata = JsonSerializer.Serialize(new
                {
                    ftp_source = "ftp://data-server/incoming/",
                    original_filename = evt.Metadata["filename"],
                    file_size = evt.Metadata["size"],
                    download_timestamp = DateTimeOffset.UtcNow
                }),
                DedupKey = evaluator.GenerateDedupKey(evt),
                Status = JobStatus.Queued
            };
            db.WorkItems.Add(wi);
        }
        await db.SaveChangesAsync();

        var snapshotResolver = new SnapshotResolver(db);
        var dispatcher = new EquipmentDataDispatcher(_outputDir);
        var orchestrator = new ProcessingOrchestrator(db, dispatcher, snapshotResolver,
            NullLogger<ProcessingOrchestrator>.Instance);

        var workItems = db.WorkItems.ToList();
        foreach (var wi in workItems)
        {
            var execution = await orchestrator.ProcessWorkItemAsync(wi.Id);
            Assert.Equal(ExecutionStatus.Completed, execution.Status);
        }

        // 6. Verify all items completed
        Assert.Equal(2, db.WorkItems.Count(w => w.Status == JobStatus.Completed));
        Assert.Equal(2, db.WorkItemExecutions.Count(e => e.Status == ExecutionStatus.Completed));
    }

    [Fact]
    public async Task FtpCollection_IncrementalSync_OnlyNewFiles()
    {
        // Day 1: 2 files
        await SimulateFtpUpload("day1_file1.csv", new[] { "a,b", "1,2" });
        await SimulateFtpUpload("day1_file2.csv", new[] { "a,b", "3,4" });

        var monitor = new FileMonitor(_ftpRoot, "*.csv");
        var day1Events = await monitor.PollAsync();
        Assert.Equal(2, day1Events.Count);

        // Day 2: 1 new file added (monitor remembers seen files)
        await SimulateFtpUpload("day2_file1.csv", new[] { "a,b", "5,6" });

        var day2Events = await monitor.PollAsync();
        Assert.Single(day2Events);
        Assert.Contains("day2_file1.csv", day2Events[0].Metadata["filename"]?.ToString());
    }

    [Fact]
    public async Task FtpCollection_CorruptedFile_GracefulHandling()
    {
        // Simulate a truncated/corrupted CSV file
        var corruptPath = Path.Combine(_ftpRoot, "corrupt.csv");
        await File.WriteAllTextAsync(corruptPath, "id,name,value\n1,sensor-a,");  // Incomplete row

        var monitor = new FileMonitor(_ftpRoot, "*.csv");
        var events = await monitor.PollAsync();
        Assert.Single(events);

        // File is still detected, pipeline should handle the bad data
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        var wi = new WorkItem
        {
            PipelineActivationId = activation.Id,
            PipelineInstanceId = pipeline.Id,
            SourceType = SourceType.File,
            SourceKey = corruptPath,
            SourceMetadata = JsonSerializer.Serialize(new { corrupted = true }),
            Status = JobStatus.Queued
        };
        db.WorkItems.Add(wi);
        await db.SaveChangesAsync();

        // Dispatcher simulates algorithm detecting corrupt data but continuing
        var dispatcher = new EquipmentDataDispatcher(_outputDir);
        var snapshotResolver = new SnapshotResolver(db);
        var orchestrator = new ProcessingOrchestrator(db, dispatcher, snapshotResolver,
            NullLogger<ProcessingOrchestrator>.Instance);

        var execution = await orchestrator.ProcessWorkItemAsync(wi.Id);
        Assert.Equal(ExecutionStatus.Completed, execution.Status);
    }

    [Fact]
    public async Task FtpCollection_BulkReprocess_AllFailedItems()
    {
        var db = TestDbHelper.CreateInMemoryDb();
        var (pipeline, activation) = await TestDbHelper.SeedPipelineAsync(db);

        // Create 5 failed work items
        for (int i = 0; i < 5; i++)
        {
            await SimulateFtpUpload($"failed_{i}.csv", new[] { "id,val", $"{i},{i * 10}" });
            db.WorkItems.Add(new WorkItem
            {
                PipelineActivationId = activation.Id,
                PipelineInstanceId = pipeline.Id,
                SourceType = SourceType.File,
                SourceKey = Path.Combine(_ftpRoot, $"failed_{i}.csv"),
                Status = JobStatus.Failed,
                ExecutionCount = 1
            });
        }
        await db.SaveChangesAsync();

        var failedIds = db.WorkItems.Where(w => w.Status == JobStatus.Failed).Select(w => w.Id).ToList();
        Assert.Equal(5, failedIds.Count);

        var snapshotResolver = new SnapshotResolver(db);
        var dispatcher = new EquipmentDataDispatcher(_outputDir);
        var orchestrator = new ProcessingOrchestrator(db, dispatcher, snapshotResolver,
            NullLogger<ProcessingOrchestrator>.Instance);

        // Bulk create reprocess requests
        var requests = await orchestrator.BulkReprocessAsync(
            failedIds, "Recipe v2 deployed", "operator:admin");
        Assert.Equal(5, requests.Count);
        Assert.All(requests, r => Assert.Equal(ReprocessStatus.Pending, r.Status));

        // Approve and reprocess each
        foreach (var req in requests)
        {
            req.Status = ReprocessStatus.Approved;
        }
        await db.SaveChangesAsync();

        foreach (var req in requests)
        {
            var execution = await orchestrator.ReprocessWorkItemAsync(req.Id);
            Assert.Equal(ExecutionStatus.Completed, execution.Status);
            Assert.Equal(TriggerType.Reprocess, execution.TriggerType);
        }

        // All items should now be completed
        var reprocessedItems = db.WorkItems.Where(w => w.Status == JobStatus.Completed).ToList();
        Assert.Equal(5, reprocessedItems.Count);
        Assert.All(reprocessedItems, wi => Assert.Equal(2, wi.ExecutionCount));
    }

    private async Task SimulateFtpUpload(string filename, string[] lines)
    {
        var path = Path.Combine(_ftpRoot, filename);
        await File.WriteAllLinesAsync(path, lines);
    }

    /// <summary>Dispatcher simulating equipment data processing pipeline.</summary>
    private class EquipmentDataDispatcher : IExecutionDispatcher
    {
        private readonly string _outputDir;
        public EquipmentDataDispatcher(string outputDir) => _outputDir = outputDir;

        public Task<ExecutionResult> DispatchAsync(
            ExecutionType executionType, string? executionRef, string configJson,
            string? inputDataJson = null, Dictionary<string, string>? context = null,
            CancellationToken ct = default)
        {
            var step = int.Parse(context?.GetValueOrDefault("step_order") ?? "0");

            var output = step switch
            {
                1 => JsonSerializer.Serialize(new
                {
                    records = new[]
                    {
                        new { equipment_id = "EQ-001", metric = "temperature", value = 72.3, alert = false },
                        new { equipment_id = "EQ-001", metric = "vibration", value = 0.02, alert = false }
                    },
                    record_count = 2
                }),
                2 => JsonSerializer.Serialize(new
                {
                    processed_records = 2,
                    alerts = Array.Empty<object>(),
                    quality_score = 0.98
                }),
                3 => JsonSerializer.Serialize(new
                {
                    destination = "equipment-db",
                    records_written = 2,
                    output_path = Path.Combine(_outputDir, $"eq_{Guid.NewGuid():N}.json")
                }),
                _ => "{}"
            };

            return Task.FromResult(new ExecutionResult(true, output,
                JsonSerializer.Serialize(new { step, ok = true }), 20, new()));
        }
    }
}
