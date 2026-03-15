using System.Collections.Concurrent;
using Microsoft.Extensions.Logging;

namespace Hermes.Engine.Services;

/// <summary>
/// Token bucket rate limiter for controlling throughput per pipeline/resource.
/// Prevents overwhelming downstream systems.
///
/// Inspired by: Guava RateLimiter, Polly RateLimit, NiFi FlowFile priority.
/// </summary>
public interface IRateLimiter
{
    /// <summary>Try to acquire a permit. Returns true if allowed, false if rate limited.</summary>
    bool TryAcquire(string resourceKey, int permits = 1);

    /// <summary>Configure rate limit for a resource.</summary>
    void Configure(string resourceKey, int maxPermitsPerSecond);

    /// <summary>Get current rate info for a resource.</summary>
    RateLimitInfo GetInfo(string resourceKey);
}

public record RateLimitInfo(
    string ResourceKey,
    int MaxPerSecond,
    int AvailablePermits,
    long TotalAcquired,
    long TotalRejected);

public class TokenBucketRateLimiter : IRateLimiter
{
    private readonly ConcurrentDictionary<string, Bucket> _buckets = new();
    private readonly ILogger<TokenBucketRateLimiter> _logger;
    private const int DefaultMaxPerSecond = 100;

    public TokenBucketRateLimiter(ILogger<TokenBucketRateLimiter> logger) => _logger = logger;

    public bool TryAcquire(string resourceKey, int permits = 1)
    {
        var bucket = _buckets.GetOrAdd(resourceKey, _ => new Bucket(DefaultMaxPerSecond));
        bucket.Refill();

        if (bucket.Tokens >= permits)
        {
            bucket.Tokens -= permits;
            Interlocked.Add(ref bucket.TotalAcquired, permits);
            return true;
        }

        Interlocked.Add(ref bucket.TotalRejected, permits);
        return false;
    }

    public void Configure(string resourceKey, int maxPermitsPerSecond)
    {
        var bucket = _buckets.GetOrAdd(resourceKey, _ => new Bucket(maxPermitsPerSecond));
        bucket.MaxPerSecond = maxPermitsPerSecond;
        bucket.MaxTokens = maxPermitsPerSecond;
        _logger.LogInformation("Rate limit configured: {Resource} = {Max}/sec", resourceKey, maxPermitsPerSecond);
    }

    public RateLimitInfo GetInfo(string resourceKey)
    {
        if (!_buckets.TryGetValue(resourceKey, out var bucket))
            return new RateLimitInfo(resourceKey, DefaultMaxPerSecond, DefaultMaxPerSecond, 0, 0);

        bucket.Refill();
        return new RateLimitInfo(resourceKey, bucket.MaxPerSecond,
            (int)bucket.Tokens, bucket.TotalAcquired, bucket.TotalRejected);
    }

    private class Bucket
    {
        public int MaxPerSecond;
        public int MaxTokens;
        public double Tokens;
        public long LastRefillTicks;
        public long TotalAcquired;
        public long TotalRejected;

        public Bucket(int maxPerSecond)
        {
            MaxPerSecond = maxPerSecond;
            MaxTokens = maxPerSecond;
            Tokens = maxPerSecond;
            LastRefillTicks = Environment.TickCount64;
        }

        public void Refill()
        {
            var now = Environment.TickCount64;
            var elapsed = (now - LastRefillTicks) / 1000.0; // seconds
            LastRefillTicks = now;

            Tokens = Math.Min(MaxTokens, Tokens + elapsed * MaxPerSecond);
        }
    }
}
