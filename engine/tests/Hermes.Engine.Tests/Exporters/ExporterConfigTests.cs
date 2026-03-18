using Hermes.Engine.Services.Exporters;

namespace Hermes.Engine.Tests.Exporters;

/// <summary>
/// Tests for Export connector configuration parsing and validation.
/// </summary>
public class ExporterConfigTests
{
    // ================================================================
    // KafkaProducerConfig
    // ================================================================

    [Fact]
    public void KafkaConfig_ParsesAllFields()
    {
        var json = System.Text.Json.JsonDocument.Parse("""
        {
            "bootstrap_servers": "broker1:9092,broker2:9092",
            "topic": "equipment-events",
            "key_field": "device_id",
            "acks": "all",
            "security_protocol": "SASL_SSL",
            "enable_idempotence": true,
            "batch_size": 32768,
            "linger_ms": 10,
            "compression": "snappy"
        }
        """).RootElement;

        var config = KafkaProducerConfig.FromJson(json);

        Assert.Equal("broker1:9092,broker2:9092", config.BootstrapServers);
        Assert.Equal("equipment-events", config.Topic);
        Assert.Equal("device_id", config.KeyField);
        Assert.Equal("all", config.Acks);
        Assert.Equal("SASL_SSL", config.SecurityProtocol);
        Assert.True(config.EnableIdempotence);
        Assert.Equal(32768, config.BatchSize);
        Assert.Equal(10, config.LingerMs);
        Assert.Equal("snappy", config.Compression);
    }

    [Fact]
    public void KafkaConfig_Defaults()
    {
        var json = System.Text.Json.JsonDocument.Parse("{}").RootElement;
        var config = KafkaProducerConfig.FromJson(json);

        Assert.Equal("localhost:9092", config.BootstrapServers);
        Assert.Equal("", config.Topic);
        Assert.Null(config.KeyField);
        Assert.Equal("all", config.Acks);
        Assert.Equal("PLAINTEXT", config.SecurityProtocol);
        Assert.True(config.EnableIdempotence);
        Assert.Equal("none", config.Compression);
    }

    [Theory]
    [InlineData("0")]
    [InlineData("1")]
    [InlineData("all")]
    public void KafkaConfig_AckModes(string acks)
    {
        var json = System.Text.Json.JsonDocument.Parse(
            "{\"acks\": \"" + acks + "\"}"
        ).RootElement;
        var config = KafkaProducerConfig.FromJson(json);
        Assert.Equal(acks, config.Acks);
    }

    [Theory]
    [InlineData("none")]
    [InlineData("gzip")]
    [InlineData("snappy")]
    [InlineData("lz4")]
    [InlineData("zstd")]
    public void KafkaConfig_CompressionTypes(string compression)
    {
        var json = System.Text.Json.JsonDocument.Parse(
            "{\"compression\": \"" + compression + "\"}"
        ).RootElement;
        var config = KafkaProducerConfig.FromJson(json);
        Assert.Equal(compression, config.Compression);
    }

    // ================================================================
    // DbWriterConfig
    // ================================================================

    [Fact]
    public void DbWriterConfig_ParsesAllFields()
    {
        var json = System.Text.Json.JsonDocument.Parse("""
        {
            "connection_string": "Host=db.local;Database=hermes;Username=writer;Password=pass",
            "provider": "PostgreSQL",
            "table_name": "sensor_readings",
            "write_mode": "UPSERT",
            "conflict_key": "id",
            "batch_size": 500,
            "create_table": true,
            "timeout_seconds": 60
        }
        """).RootElement;

        var config = DbWriterConfig.FromJson(json);

        Assert.Contains("db.local", config.ConnectionString);
        Assert.Equal("PostgreSQL", config.Provider);
        Assert.Equal("sensor_readings", config.TableName);
        Assert.Equal("UPSERT", config.WriteMode);
        Assert.Equal("id", config.ConflictKey);
        Assert.Equal(500, config.BatchSize);
        Assert.True(config.CreateTableIfNotExists);
        Assert.Equal(60, config.TimeoutSeconds);
    }

    [Fact]
    public void DbWriterConfig_Defaults()
    {
        var json = System.Text.Json.JsonDocument.Parse("{}").RootElement;
        var config = DbWriterConfig.FromJson(json);

        Assert.Equal("", config.ConnectionString);
        Assert.Equal("PostgreSQL", config.Provider);
        Assert.Equal("INSERT", config.WriteMode);
        Assert.Equal(1000, config.BatchSize);
        Assert.False(config.CreateTableIfNotExists);
        Assert.Equal(30, config.TimeoutSeconds);
    }

    [Theory]
    [InlineData("INSERT")]
    [InlineData("UPSERT")]
    [InlineData("MERGE")]
    public void DbWriterConfig_WriteModes(string mode)
    {
        var json = System.Text.Json.JsonDocument.Parse(
            "{\"write_mode\": \"" + mode + "\"}"
        ).RootElement;
        var config = DbWriterConfig.FromJson(json);
        Assert.Equal(mode, config.WriteMode);
    }

    // ================================================================
    // WebhookSenderConfig
    // ================================================================

    [Fact]
    public void WebhookConfig_ParsesAllFields()
    {
        var json = System.Text.Json.JsonDocument.Parse("""
        {
            "url": "https://api.partner.com/webhook/data",
            "method": "POST",
            "auth_type": "bearer",
            "auth_token": "eyJhbGciOi...",
            "timeout_seconds": 15,
            "max_retries": 5,
            "batch_mode": true,
            "content_type": "application/json",
            "headers": {
                "X-Source": "hermes",
                "X-Pipeline": "vendor-a"
            }
        }
        """).RootElement;

        var config = WebhookSenderConfig.FromJson(json);

        Assert.Equal("https://api.partner.com/webhook/data", config.Url);
        Assert.Equal("POST", config.Method);
        Assert.Equal("bearer", config.AuthType);
        Assert.Equal("eyJhbGciOi...", config.AuthToken);
        Assert.Equal(15, config.TimeoutSeconds);
        Assert.Equal(5, config.MaxRetries);
        Assert.True(config.BatchMode);
        Assert.Equal(2, config.Headers.Count);
        Assert.Equal("hermes", config.Headers["X-Source"]);
    }

    [Fact]
    public void WebhookConfig_Defaults()
    {
        var json = System.Text.Json.JsonDocument.Parse("{}").RootElement;
        var config = WebhookSenderConfig.FromJson(json);

        Assert.Equal("", config.Url);
        Assert.Equal("POST", config.Method);
        Assert.Equal("none", config.AuthType);
        Assert.Equal(30, config.TimeoutSeconds);
        Assert.Equal(3, config.MaxRetries);
        Assert.False(config.BatchMode);
        Assert.Equal("application/json", config.ContentType);
    }

    [Theory]
    [InlineData("none")]
    [InlineData("bearer")]
    [InlineData("basic")]
    [InlineData("api_key")]
    public void WebhookConfig_AuthTypes(string authType)
    {
        var json = System.Text.Json.JsonDocument.Parse(
            "{\"auth_type\": \"" + authType + "\"}"
        ).RootElement;
        var config = WebhookSenderConfig.FromJson(json);
        Assert.Equal(authType, config.AuthType);
    }

    // ================================================================
    // S3UploadConfig
    // ================================================================

    [Fact]
    public void S3Config_ParsesAllFields()
    {
        var json = System.Text.Json.JsonDocument.Parse("""
        {
            "region": "ap-northeast-2",
            "bucket_name": "hermes-data-lake",
            "key_prefix": "pipeline-output/vendor-a",
            "access_key_id": "AKIAIOSFODNN7EXAMPLE",
            "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "output_format": "csv",
            "compression": "gzip",
            "partition_by_date": true,
            "date_partition_format": "yyyy/MM/dd",
            "include_metadata": true,
            "multipart_threshold_mb": 50
        }
        """).RootElement;

        var config = S3UploadConfig.FromJson(json);

        Assert.Equal("ap-northeast-2", config.Region);
        Assert.Equal("hermes-data-lake", config.BucketName);
        Assert.Equal("pipeline-output/vendor-a", config.KeyPrefix);
        Assert.Equal("AKIAIOSFODNN7EXAMPLE", config.AccessKeyId);
        Assert.Equal("csv", config.OutputFormat);
        Assert.Equal("gzip", config.Compression);
        Assert.True(config.PartitionByDate);
        Assert.Equal("yyyy/MM/dd", config.DatePartitionFormat);
        Assert.True(config.IncludeMetadata);
        Assert.Equal(50, config.MultipartThresholdMb);
    }

    [Fact]
    public void S3Config_Defaults()
    {
        var json = System.Text.Json.JsonDocument.Parse("{}").RootElement;
        var config = S3UploadConfig.FromJson(json);

        Assert.Equal("us-east-1", config.Region);
        Assert.Equal("", config.BucketName);
        Assert.Equal("json", config.OutputFormat);
        Assert.Equal("none", config.Compression);
        Assert.True(config.PartitionByDate);
        Assert.True(config.IncludeMetadata);
        Assert.Equal(100, config.MultipartThresholdMb);
    }

    [Fact]
    public void S3Config_ContentType_Json()
    {
        var config = new S3UploadConfig { OutputFormat = "json", Compression = "none" };
        Assert.Equal("application/json", config.ContentType());
    }

    [Fact]
    public void S3Config_ContentType_CsvGzipped()
    {
        var config = new S3UploadConfig { OutputFormat = "csv", Compression = "gzip" };
        Assert.Equal("application/gzip", config.ContentType());
    }

    // ================================================================
    // E2E Config Scenarios
    // ================================================================

    [Fact]
    public void E2E_Scenario_EquipmentKafkaExport()
    {
        var config = new KafkaProducerConfig
        {
            BootstrapServers = "kafka1:9092,kafka2:9092,kafka3:9092",
            Topic = "equipment-anomalies",
            KeyField = "equipment_id",
            Acks = "all",
            EnableIdempotence = true,
            Compression = "lz4",
            BatchSize = 65536,
            LingerMs = 50,
        };

        Assert.Equal("all", config.Acks);
        Assert.True(config.EnableIdempotence);
        Assert.Equal("lz4", config.Compression);
    }

    [Fact]
    public void E2E_Scenario_DataWarehouseLoad()
    {
        var config = new DbWriterConfig
        {
            Provider = "PostgreSQL",
            TableName = "fact_sensor_readings",
            WriteMode = "UPSERT",
            ConflictKey = "reading_id",
            BatchSize = 5000,
            TimeoutSeconds = 120,
        };

        Assert.Equal("UPSERT", config.WriteMode);
        Assert.Equal(5000, config.BatchSize);
    }

    [Fact]
    public void E2E_Scenario_PartnerWebhookNotification()
    {
        var config = new WebhookSenderConfig
        {
            Url = "https://partner-api.com/v2/ingest",
            Method = "POST",
            AuthType = "bearer",
            AuthToken = "prod-token-xxx",
            TimeoutSeconds = 10,
            MaxRetries = 5,
            BatchMode = true,
            Headers = { ["X-Hermes-Pipeline"] = "vendor-a-orders" },
        };

        Assert.True(config.BatchMode);
        Assert.Equal(5, config.MaxRetries);
    }

    [Fact]
    public void E2E_Scenario_S3DataLakeArchive()
    {
        var config = new S3UploadConfig
        {
            Region = "ap-northeast-2",
            BucketName = "hermes-data-lake",
            KeyPrefix = "raw/equipment",
            OutputFormat = "json",
            Compression = "gzip",
            PartitionByDate = true,
            DatePartitionFormat = "yyyy/MM/dd",
            IncludeMetadata = true,
        };

        Assert.Equal("gzip", config.Compression);
        Assert.True(config.PartitionByDate);
    }
}
