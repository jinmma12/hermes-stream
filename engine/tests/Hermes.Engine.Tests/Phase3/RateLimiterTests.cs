using Microsoft.Extensions.Logging.Abstractions;
using Hermes.Engine.Services;

namespace Hermes.Engine.Tests.Phase3;

public class RateLimiterTests
{
    private readonly TokenBucketRateLimiter _limiter = new(NullLogger<TokenBucketRateLimiter>.Instance);

    [Fact]
    public void TryAcquire_WithinLimit_Succeeds()
    {
        _limiter.Configure("api-calls", 10);
        for (int i = 0; i < 10; i++)
            Assert.True(_limiter.TryAcquire("api-calls"));
    }

    [Fact]
    public void TryAcquire_ExceedsLimit_Rejected()
    {
        _limiter.Configure("strict-resource", 5);
        for (int i = 0; i < 5; i++)
            Assert.True(_limiter.TryAcquire("strict-resource"));

        Assert.False(_limiter.TryAcquire("strict-resource"));
    }

    [Fact]
    public void TryAcquire_DefaultLimit_Works()
    {
        // Default is 100/sec
        for (int i = 0; i < 100; i++)
            Assert.True(_limiter.TryAcquire("default-resource"));
    }

    [Fact]
    public void GetInfo_TracksStats()
    {
        _limiter.Configure("tracked", 10);
        _limiter.TryAcquire("tracked");
        _limiter.TryAcquire("tracked");

        var info = _limiter.GetInfo("tracked");
        Assert.Equal("tracked", info.ResourceKey);
        Assert.Equal(10, info.MaxPerSecond);
        Assert.Equal(2, info.TotalAcquired);
    }

    [Fact]
    public void MultipleResources_Independent()
    {
        _limiter.Configure("fast", 1000);
        _limiter.Configure("slow", 2);

        Assert.True(_limiter.TryAcquire("fast"));
        Assert.True(_limiter.TryAcquire("fast"));
        Assert.True(_limiter.TryAcquire("slow"));
        Assert.True(_limiter.TryAcquire("slow"));
        Assert.False(_limiter.TryAcquire("slow")); // Exhausted
        Assert.True(_limiter.TryAcquire("fast"));   // Still available
    }

    [Fact]
    public async Task TokenRefill_AfterWait()
    {
        _limiter.Configure("refill-test", 10);
        for (int i = 0; i < 10; i++)
            _limiter.TryAcquire("refill-test");

        Assert.False(_limiter.TryAcquire("refill-test")); // Exhausted

        await Task.Delay(200); // Wait for partial refill

        Assert.True(_limiter.TryAcquire("refill-test")); // Tokens refilled
    }
}
