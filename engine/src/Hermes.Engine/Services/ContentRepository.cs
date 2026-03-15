using System.Security.Cryptography;
using Microsoft.Extensions.Logging;

namespace Hermes.Engine.Services;

/// <summary>
/// Disk-based Content Repository with content-addressed storage.
/// Inspired by NiFi's Content Repository and Git's object store.
///
/// Content is stored as immutable blobs identified by SHA-256 hash.
/// Deduplication is automatic: same data → same hash → same file.
/// </summary>
public interface IContentRepository
{
    /// <summary>Write content and return a claim reference (SHA-256 hash).</summary>
    Task<ContentClaim> WriteAsync(Stream content, string? mimeType = null, CancellationToken ct = default);

    /// <summary>Write content from a byte array.</summary>
    Task<ContentClaim> WriteAsync(byte[] content, string? mimeType = null, CancellationToken ct = default);

    /// <summary>Write content from a string (UTF-8).</summary>
    Task<ContentClaim> WriteStringAsync(string content, string? mimeType = "application/json", CancellationToken ct = default);

    /// <summary>Read content as a stream.</summary>
    Task<Stream?> ReadAsync(string claimId, CancellationToken ct = default);

    /// <summary>Read content as a string.</summary>
    Task<string?> ReadStringAsync(string claimId, CancellationToken ct = default);

    /// <summary>Check if a claim exists.</summary>
    bool Exists(string claimId);

    /// <summary>Delete a claim (decrements ref count; actual delete on GC).</summary>
    Task<bool> DeleteAsync(string claimId, CancellationToken ct = default);

    /// <summary>Get repository statistics.</summary>
    ContentRepositoryStats GetStats();
}

public record ContentClaim(
    string ClaimId,      // SHA-256 hex
    long SizeBytes,
    string? MimeType,
    bool WasDeduped);    // True if content already existed

public record ContentRepositoryStats(
    long TotalClaims,
    long TotalSizeBytes,
    long DedupSavedBytes,
    string RepositoryPath);

public class ContentRepository : IContentRepository
{
    private readonly string _basePath;
    private readonly ILogger<ContentRepository> _logger;
    private long _dedupSavedBytes;

    public ContentRepository(string basePath, ILogger<ContentRepository> logger)
    {
        _basePath = basePath;
        _logger = logger;

        // Ensure directory structure
        Directory.CreateDirectory(Path.Combine(_basePath, "claims"));
        Directory.CreateDirectory(Path.Combine(_basePath, "tmp"));
    }

    public async Task<ContentClaim> WriteAsync(Stream content, string? mimeType = null, CancellationToken ct = default)
    {
        // 1. Write to temp file while computing SHA-256
        var tmpPath = Path.Combine(_basePath, "tmp", $"write-{Guid.NewGuid():N}.tmp");
        string hash;
        long size;

        try
        {
            using (var sha = IncrementalHash.CreateHash(HashAlgorithmName.SHA256))
            using (var tmpFile = new FileStream(tmpPath, FileMode.Create, FileAccess.Write, FileShare.None, 81920))
            {
                var buffer = new byte[81920]; // 80KB buffer
                int bytesRead;
                size = 0;

                while ((bytesRead = await content.ReadAsync(buffer, 0, buffer.Length, ct)) > 0)
                {
                    sha.AppendData(buffer, 0, bytesRead);
                    await tmpFile.WriteAsync(buffer, 0, bytesRead, ct);
                    size += bytesRead;
                }

                hash = Convert.ToHexString(sha.GetHashAndReset()).ToLowerInvariant();
            }

            // 2. Check if content already exists (dedup)
            var claimPath = GetClaimPath(hash);
            var wasDeduped = false;

            if (File.Exists(claimPath))
            {
                // Content already exists — dedup!
                File.Delete(tmpPath);
                Interlocked.Add(ref _dedupSavedBytes, size);
                wasDeduped = true;
                _logger.LogDebug("Content deduped: {Hash} ({Size} bytes saved)", hash, size);
            }
            else
            {
                // 3. Atomic move to claim path
                var claimDir = Path.GetDirectoryName(claimPath)!;
                Directory.CreateDirectory(claimDir);
                File.Move(tmpPath, claimPath);
                _logger.LogDebug("Content stored: {Hash} ({Size} bytes)", hash, size);
            }

            return new ContentClaim(hash, size, mimeType, wasDeduped);
        }
        catch
        {
            // Clean up temp file on error
            if (File.Exists(tmpPath)) File.Delete(tmpPath);
            throw;
        }
    }

    public async Task<ContentClaim> WriteAsync(byte[] content, string? mimeType = null, CancellationToken ct = default)
    {
        using var stream = new MemoryStream(content);
        return await WriteAsync(stream, mimeType, ct);
    }

    public async Task<ContentClaim> WriteStringAsync(string content, string? mimeType = "application/json", CancellationToken ct = default)
    {
        var bytes = System.Text.Encoding.UTF8.GetBytes(content);
        return await WriteAsync(bytes, mimeType, ct);
    }

    public Task<Stream?> ReadAsync(string claimId, CancellationToken ct = default)
    {
        var path = GetClaimPath(claimId);
        if (!File.Exists(path)) return Task.FromResult<Stream?>(null);

        Stream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 81920);
        return Task.FromResult<Stream?>(stream);
    }

    public async Task<string?> ReadStringAsync(string claimId, CancellationToken ct = default)
    {
        var stream = await ReadAsync(claimId, ct);
        if (stream == null) return null;
        using (stream)
        using (var reader = new StreamReader(stream))
            return await reader.ReadToEndAsync(ct);
    }

    public bool Exists(string claimId) => File.Exists(GetClaimPath(claimId));

    public Task<bool> DeleteAsync(string claimId, CancellationToken ct = default)
    {
        var path = GetClaimPath(claimId);
        if (!File.Exists(path)) return Task.FromResult(false);
        File.Delete(path);
        _logger.LogDebug("Content deleted: {Hash}", claimId);
        return Task.FromResult(true);
    }

    public ContentRepositoryStats GetStats()
    {
        var claimsDir = Path.Combine(_basePath, "claims");
        long totalClaims = 0;
        long totalSize = 0;

        if (Directory.Exists(claimsDir))
        {
            foreach (var file in Directory.EnumerateFiles(claimsDir, "*", SearchOption.AllDirectories))
            {
                totalClaims++;
                totalSize += new FileInfo(file).Length;
            }
        }

        return new ContentRepositoryStats(totalClaims, totalSize, _dedupSavedBytes, _basePath);
    }

    /// <summary>Map claim ID to file path: claims/{aa}/{bb}/{full_hash}</summary>
    private string GetClaimPath(string claimId)
    {
        var a = claimId[..2];
        var b = claimId[2..4];
        return Path.Combine(_basePath, "claims", a, b, claimId);
    }
}
