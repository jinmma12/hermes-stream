using Microsoft.Extensions.Logging.Abstractions;
using Hermes.Engine.Services;

namespace Hermes.Engine.Tests.Phase2;

/// <summary>
/// Tests for Content Repository — disk-based content-addressed storage.
/// References: NiFi Content Repository, Git object store, IPFS CID.
///
/// Key behaviors:
/// - Content stored as immutable SHA-256 addressed blobs
/// - Automatic deduplication (same content → same hash → no duplicate storage)
/// - Temp file → atomic rename pattern for crash safety
/// - Directory sharding: claims/{aa}/{bb}/{hash}
/// </summary>
public class ContentRepositoryTests : IDisposable
{
    private readonly string _repoPath;
    private readonly ContentRepository _repo;

    public ContentRepositoryTests()
    {
        _repoPath = Path.Combine(Path.GetTempPath(), $"hermes-content-{Guid.NewGuid():N}");
        _repo = new ContentRepository(_repoPath, NullLogger<ContentRepository>.Instance);
    }

    public void Dispose()
    {
        if (Directory.Exists(_repoPath)) Directory.Delete(_repoPath, true);
    }

    [Fact]
    public async Task WriteString_ReturnsClaimWithHash()
    {
        var claim = await _repo.WriteStringAsync("{\"sensor\":\"S001\",\"value\":23.5}");

        Assert.NotNull(claim);
        Assert.Equal(64, claim.ClaimId.Length); // SHA-256 hex = 64 chars
        Assert.True(claim.SizeBytes > 0);
        Assert.Equal("application/json", claim.MimeType);
        Assert.False(claim.WasDeduped);
    }

    [Fact]
    public async Task WriteAndRead_Roundtrip()
    {
        var original = "{\"records\":[{\"id\":1,\"name\":\"test\"}]}";
        var claim = await _repo.WriteStringAsync(original);

        var read = await _repo.ReadStringAsync(claim.ClaimId);

        Assert.Equal(original, read);
    }

    [Fact]
    public async Task WriteSameContent_Deduplicates()
    {
        var content = "duplicate content for dedup test";

        var claim1 = await _repo.WriteStringAsync(content);
        var claim2 = await _repo.WriteStringAsync(content);

        Assert.Equal(claim1.ClaimId, claim2.ClaimId); // Same hash
        Assert.False(claim1.WasDeduped);
        Assert.True(claim2.WasDeduped); // Second write deduped
    }

    [Fact]
    public async Task WriteDifferentContent_DifferentClaims()
    {
        var claim1 = await _repo.WriteStringAsync("content A");
        var claim2 = await _repo.WriteStringAsync("content B");

        Assert.NotEqual(claim1.ClaimId, claim2.ClaimId);
    }

    [Fact]
    public async Task WriteBytes_Works()
    {
        var data = new byte[] { 0x48, 0x45, 0x52, 0x4D, 0x45, 0x53 }; // "HERMES"
        var claim = await _repo.WriteAsync(data, "application/octet-stream");

        Assert.Equal(6, claim.SizeBytes);
        Assert.Equal("application/octet-stream", claim.MimeType);

        var stream = await _repo.ReadAsync(claim.ClaimId);
        Assert.NotNull(stream);
        using (stream!)
        {
            var read = new byte[6];
            await stream.ReadAsync(read);
            Assert.Equal(data, read);
        }
    }

    [Fact]
    public async Task WriteStream_LargeContent()
    {
        // 1MB of random-ish data
        var data = new byte[1024 * 1024];
        new Random(42).NextBytes(data);

        using var stream = new MemoryStream(data);
        var claim = await _repo.WriteAsync(stream);

        Assert.Equal(1024 * 1024, claim.SizeBytes);
        Assert.True(_repo.Exists(claim.ClaimId));

        var readStream = await _repo.ReadAsync(claim.ClaimId);
        Assert.NotNull(readStream);
        using (readStream!)
        {
            using var ms = new MemoryStream();
            await readStream.CopyToAsync(ms);
            Assert.Equal(data.Length, ms.Length);
        }
    }

    [Fact]
    public async Task Exists_TrueForStored_FalseForMissing()
    {
        var claim = await _repo.WriteStringAsync("exists test");

        Assert.True(_repo.Exists(claim.ClaimId));
        Assert.False(_repo.Exists("0000000000000000000000000000000000000000000000000000000000000000"));
    }

    [Fact]
    public async Task Delete_RemovesContent()
    {
        var claim = await _repo.WriteStringAsync("delete me");
        Assert.True(_repo.Exists(claim.ClaimId));

        var deleted = await _repo.DeleteAsync(claim.ClaimId);
        Assert.True(deleted);
        Assert.False(_repo.Exists(claim.ClaimId));

        var read = await _repo.ReadStringAsync(claim.ClaimId);
        Assert.Null(read);
    }

    [Fact]
    public async Task Delete_NonExistent_ReturnsFalse()
    {
        var result = await _repo.DeleteAsync("nonexistent_hash_that_does_not_exist_at_all_64chars_padding_here");
        Assert.False(result);
    }

    [Fact]
    public async Task ReadNonExistent_ReturnsNull()
    {
        var result = await _repo.ReadStringAsync("0000000000000000000000000000000000000000000000000000000000000000");
        Assert.Null(result);
    }

    [Fact]
    public async Task Stats_TracksClaimsAndSize()
    {
        await _repo.WriteStringAsync("data 1");
        await _repo.WriteStringAsync("data 2");
        await _repo.WriteStringAsync("data 3");

        var stats = _repo.GetStats();

        Assert.Equal(3, stats.TotalClaims);
        Assert.True(stats.TotalSizeBytes > 0);
        Assert.Equal(_repoPath, stats.RepositoryPath);
    }

    [Fact]
    public async Task Stats_TracksDedupSavings()
    {
        var content = "dedup savings test content";
        await _repo.WriteStringAsync(content);
        await _repo.WriteStringAsync(content); // Deduped
        await _repo.WriteStringAsync(content); // Deduped

        var stats = _repo.GetStats();

        Assert.Equal(1, stats.TotalClaims); // Only 1 actual file
        Assert.True(stats.DedupSavedBytes > 0); // 2x saves tracked
    }

    [Fact]
    public async Task DirectorySharding_CreatesSubdirs()
    {
        var claim = await _repo.WriteStringAsync("sharding test");

        // Verify sharded path: claims/{aa}/{bb}/{hash}
        var claimsDir = Path.Combine(_repoPath, "claims");
        var subdirs = Directory.GetDirectories(claimsDir, "*", SearchOption.AllDirectories);
        Assert.True(subdirs.Length >= 2); // At least 2 levels of sharding
    }

    [Fact]
    public async Task ConcurrentWrites_NoCorruption()
    {
        // Simulate concurrent writes from multiple pipeline steps
        var tasks = Enumerable.Range(0, 20).Select(async i =>
        {
            var content = $"concurrent write #{i} with unique data {Guid.NewGuid()}";
            var claim = await _repo.WriteStringAsync(content);
            var read = await _repo.ReadStringAsync(claim.ClaimId);
            Assert.Equal(content, read);
            return claim;
        });

        var claims = await Task.WhenAll(tasks);
        Assert.Equal(20, claims.Length);
        Assert.Equal(20, claims.Select(c => c.ClaimId).Distinct().Count()); // All unique
    }

    [Fact]
    public async Task CsvFileStorage_RealisticScenario()
    {
        // Simulate storing CSV data through pipeline steps
        var csvData = "timestamp,sensor_id,temperature,humidity\n" +
                      "2026-03-15T10:00:00,S001,22.5,45.0\n" +
                      "2026-03-15T10:01:00,S002,23.1,44.8\n" +
                      "2026-03-15T10:02:00,S003,31.0,46.2\n";

        // Step 1: Collector stores raw CSV
        var rawClaim = await _repo.WriteStringAsync(csvData, "text/csv");

        // Step 2: Algorithm transforms and stores result
        var processedJson = "{\"records\":3,\"anomalies\":[{\"sensor\":\"S003\",\"value\":31.0}]}";
        var processedClaim = await _repo.WriteStringAsync(processedJson);

        // Step 3: Transfer reads processed data
        var transferInput = await _repo.ReadStringAsync(processedClaim.ClaimId);
        Assert.Contains("S003", transferInput!);

        // Original CSV is still accessible
        var originalCsv = await _repo.ReadStringAsync(rawClaim.ClaimId);
        Assert.Contains("sensor_id", originalCsv!);

        // Both claims exist independently
        Assert.True(_repo.Exists(rawClaim.ClaimId));
        Assert.True(_repo.Exists(processedClaim.ClaimId));
        Assert.NotEqual(rawClaim.ClaimId, processedClaim.ClaimId);
    }
}
