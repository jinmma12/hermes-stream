using System.Text.Json;
using Microsoft.Extensions.Logging.Abstractions;
using Hermes.Engine.Services;

namespace Hermes.Engine.Tests.Phase3;

/// <summary>
/// Tests for Content-Based Router — conditional pipeline branching.
/// References: NiFi RouteOnAttribute, Apache Camel CBR, Spring Integration router.
/// </summary>
public class ContentRouterTests
{
    private readonly ContentRouter _router = new(NullLogger<ContentRouter>.Instance);

    // ── Condition Evaluation ──

    [Fact]
    public void EvaluateCondition_StringEquals()
    {
        var data = JsonSerializer.Serialize(new { severity = "HIGH", sensor = "S001" });
        Assert.True(_router.EvaluateCondition(data, "$.severity == 'HIGH'"));
        Assert.False(_router.EvaluateCondition(data, "$.severity == 'LOW'"));
    }

    [Fact]
    public void EvaluateCondition_NumericGreaterThan()
    {
        var data = JsonSerializer.Serialize(new { record_count = 1500, temperature = 35.2 });
        Assert.True(_router.EvaluateCondition(data, "$.record_count > 1000"));
        Assert.False(_router.EvaluateCondition(data, "$.record_count > 2000"));
    }

    [Fact]
    public void EvaluateCondition_NumericComparisons()
    {
        var data = JsonSerializer.Serialize(new { value = 50 });
        Assert.True(_router.EvaluateCondition(data, "$.value >= 50"));
        Assert.True(_router.EvaluateCondition(data, "$.value <= 50"));
        Assert.False(_router.EvaluateCondition(data, "$.value > 50"));
        Assert.False(_router.EvaluateCondition(data, "$.value < 50"));
        Assert.True(_router.EvaluateCondition(data, "$.value != 99"));
    }

    [Fact]
    public void EvaluateCondition_Contains()
    {
        var data = JsonSerializer.Serialize(new { message = "Temperature alert for sensor S001" });
        Assert.True(_router.EvaluateCondition(data, "$.message contains 'alert'"));
        Assert.False(_router.EvaluateCondition(data, "$.message contains 'critical'"));
    }

    [Fact]
    public void EvaluateCondition_StartsWith()
    {
        var data = JsonSerializer.Serialize(new { filename = "sensors_batch_001.csv" });
        Assert.True(_router.EvaluateCondition(data, "$.filename startswith 'sensors'"));
        Assert.False(_router.EvaluateCondition(data, "$.filename startswith 'logs'"));
    }

    [Fact]
    public void EvaluateCondition_NestedField()
    {
        var data = JsonSerializer.Serialize(new { result = new { status = "anomaly", score = 0.95 } });
        Assert.True(_router.EvaluateCondition(data, "$.result.status == 'anomaly'"));
        Assert.True(_router.EvaluateCondition(data, "$.result.score > 0.9"));
    }

    [Fact]
    public void EvaluateCondition_BooleanField()
    {
        var data = JsonSerializer.Serialize(new { is_anomaly = true, processed = false });
        Assert.True(_router.EvaluateCondition(data, "$.is_anomaly == 'true'"));
        Assert.True(_router.EvaluateCondition(data, "$.processed == 'false'"));
    }

    [Fact]
    public void EvaluateCondition_MissingField_ReturnsFalse()
    {
        var data = JsonSerializer.Serialize(new { name = "test" });
        Assert.False(_router.EvaluateCondition(data, "$.nonexistent == 'value'"));
    }

    [Fact]
    public void EvaluateCondition_NullData_ReturnsFalse()
    {
        Assert.False(_router.EvaluateCondition(null, "$.field == 'value'"));
        Assert.False(_router.EvaluateCondition("", "$.field == 'value'"));
    }

    // ── Route Evaluation ──

    [Fact]
    public void EvaluateRoutes_SingleMatch()
    {
        var data = JsonSerializer.Serialize(new { severity = "HIGH" });
        var config = JsonSerializer.Serialize(new
        {
            routes = new object[]
            {
                new { condition = "$.severity == 'HIGH'", target_step = 3 },
                new { condition = "$.severity == 'LOW'", target_step = 4 },
            }
        });

        var targets = _router.EvaluateRoutes(data, config);

        Assert.Single(targets);
        Assert.Equal(3, targets[0]);
    }

    [Fact]
    public void EvaluateRoutes_MultipleMatches()
    {
        var data = JsonSerializer.Serialize(new { severity = "HIGH", record_count = 1500 });
        var config = JsonSerializer.Serialize(new
        {
            routes = new object[]
            {
                new { condition = "$.severity == 'HIGH'", target_step = 3 },
                new { condition = "$.record_count > 1000", target_step = 4 },
            }
        });

        var targets = _router.EvaluateRoutes(data, config);

        Assert.Equal(2, targets.Count);
        Assert.Contains(3, targets);
        Assert.Contains(4, targets);
    }

    [Fact]
    public void EvaluateRoutes_DefaultFallback()
    {
        var data = JsonSerializer.Serialize(new { severity = "MEDIUM" });
        var config = JsonSerializer.Serialize(new
        {
            routes = new object[]
            {
                new { condition = "$.severity == 'HIGH'", target_step = 3 },
                new { condition = "$.severity == 'LOW'", target_step = 4 },
                new { @default = true, target_step = 5 }  // Default when no match
            }
        });

        var targets = _router.EvaluateRoutes(data, config);

        Assert.Single(targets);
        Assert.Equal(5, targets[0]); // Default route
    }

    [Fact]
    public void EvaluateRoutes_DefaultNotUsedWhenOtherMatches()
    {
        var data = JsonSerializer.Serialize(new { severity = "HIGH" });
        var config = JsonSerializer.Serialize(new
        {
            routes = new object[]
            {
                new { condition = "$.severity == 'HIGH'", target_step = 3 },
                new { @default = true, target_step = 99 }
            }
        });

        var targets = _router.EvaluateRoutes(data, config);

        Assert.Single(targets);
        Assert.Equal(3, targets[0]); // NOT default
    }

    [Fact]
    public void EvaluateRoutes_InvalidConfig_ReturnsEmpty()
    {
        var targets = _router.EvaluateRoutes("{}", "not json");
        Assert.Empty(targets);
    }

    [Fact]
    public void EvaluateRoutes_EmptyRoutes_ReturnsEmpty()
    {
        var config = JsonSerializer.Serialize(new { routes = Array.Empty<object>() });
        var targets = _router.EvaluateRoutes("{}", config);
        Assert.Empty(targets);
    }

    // ── Realistic Scenario ──

    [Fact]
    public void Scenario_SensorDataRouting()
    {
        // Sensor data arrives → route based on anomaly detection results
        var normalData = JsonSerializer.Serialize(new
        {
            sensor_id = "S001",
            temperature = 22.5,
            anomaly_score = 0.1,
            classification = "normal"
        });

        var alertData = JsonSerializer.Serialize(new
        {
            sensor_id = "S002",
            temperature = 85.0,
            anomaly_score = 0.95,
            classification = "critical"
        });

        var routingConfig = JsonSerializer.Serialize(new
        {
            routes = new object[]
            {
                new { condition = "$.classification == 'critical'", target_step = 10 },   // Alert system
                new { condition = "$.anomaly_score > 0.7", target_step = 11 },            // Investigation queue
                new { condition = "$.classification == 'normal'", target_step = 12 },     // Standard storage
                new { @default = true, target_step = 13 }                                  // Catch-all
            }
        });

        // Normal data → standard storage (step 12)
        var normalTargets = _router.EvaluateRoutes(normalData, routingConfig);
        Assert.Single(normalTargets);
        Assert.Equal(12, normalTargets[0]);

        // Alert data → both alert system AND investigation queue (multi-match)
        var alertTargets = _router.EvaluateRoutes(alertData, routingConfig);
        Assert.Equal(2, alertTargets.Count);
        Assert.Contains(10, alertTargets); // Critical → alert
        Assert.Contains(11, alertTargets); // High score → investigation
    }
}
