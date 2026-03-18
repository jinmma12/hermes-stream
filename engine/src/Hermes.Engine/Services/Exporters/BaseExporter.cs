using System.Text.Json;
using Microsoft.Extensions.Logging;
using Hermes.Engine.Domain;

namespace Hermes.Engine.Services.Exporters;

/// <summary>
/// Base class for all Export connectors.
/// Exporters receive processed data and deliver it to a target destination.
/// </summary>
public abstract class BaseExporter
{
    public abstract Task<ExportResult> ExportAsync(
        ExportContext context,
        CancellationToken ct = default);
}

/// <summary>Input context for an export operation.</summary>
public record ExportContext(
    string DataJson,
    Dictionary<string, object> Metadata,
    string? PipelineName = null,
    int? JobId = null,
    int? StepOrder = null
);

/// <summary>Result of an export operation.</summary>
public record ExportResult(
    bool Success,
    int RecordsExported,
    string? DestinationInfo = null,
    string? ErrorMessage = null,
    long DurationMs = 0,
    Dictionary<string, object>? Summary = null
);

/// <summary>Config for Kafka Producer export.</summary>
public class KafkaProducerConfig
{
    public string BootstrapServers { get; set; } = "localhost:9092";
    public string Topic { get; set; } = "";
    public string? KeyField { get; set; }
    public string Acks { get; set; } = "all"; // "0", "1", "all"
    public string SecurityProtocol { get; set; } = "PLAINTEXT";
    public bool EnableIdempotence { get; set; } = true;
    public int BatchSize { get; set; } = 16384;
    public int LingerMs { get; set; } = 5;
    public string Compression { get; set; } = "none"; // none, gzip, snappy, lz4, zstd

    public static KafkaProducerConfig FromJson(JsonElement json)
    {
        return new KafkaProducerConfig
        {
            BootstrapServers = json.TryGetProperty("bootstrap_servers", out var bs) ? bs.GetString() ?? "localhost:9092" : "localhost:9092",
            Topic = json.TryGetProperty("topic", out var t) ? t.GetString() ?? "" : "",
            KeyField = json.TryGetProperty("key_field", out var kf) ? kf.GetString() : null,
            Acks = json.TryGetProperty("acks", out var a) ? a.GetString() ?? "all" : "all",
            SecurityProtocol = json.TryGetProperty("security_protocol", out var sp) ? sp.GetString() ?? "PLAINTEXT" : "PLAINTEXT",
            EnableIdempotence = !json.TryGetProperty("enable_idempotence", out var ei) || ei.GetBoolean(),
            BatchSize = json.TryGetProperty("batch_size", out var bsz) ? bsz.GetInt32() : 16384,
            LingerMs = json.TryGetProperty("linger_ms", out var lm) ? lm.GetInt32() : 5,
            Compression = json.TryGetProperty("compression", out var c) ? c.GetString() ?? "none" : "none",
        };
    }
}

/// <summary>Config for Database Writer export.</summary>
public class DbWriterConfig
{
    public string ConnectionString { get; set; } = "";
    public string Provider { get; set; } = "PostgreSQL"; // PostgreSQL, SqlServer
    public string TableName { get; set; } = "";
    public string WriteMode { get; set; } = "INSERT"; // INSERT, UPSERT, MERGE
    public string? ConflictKey { get; set; }
    public int BatchSize { get; set; } = 1000;
    public bool CreateTableIfNotExists { get; set; } = false;
    public int TimeoutSeconds { get; set; } = 30;

    public static DbWriterConfig FromJson(JsonElement json)
    {
        return new DbWriterConfig
        {
            ConnectionString = json.TryGetProperty("connection_string", out var cs) ? cs.GetString() ?? "" : "",
            Provider = json.TryGetProperty("provider", out var p) ? p.GetString() ?? "PostgreSQL" : "PostgreSQL",
            TableName = json.TryGetProperty("table_name", out var tn) ? tn.GetString() ?? "" : "",
            WriteMode = json.TryGetProperty("write_mode", out var wm) ? wm.GetString() ?? "INSERT" : "INSERT",
            ConflictKey = json.TryGetProperty("conflict_key", out var ck) ? ck.GetString() : null,
            BatchSize = json.TryGetProperty("batch_size", out var bs) ? bs.GetInt32() : 1000,
            CreateTableIfNotExists = json.TryGetProperty("create_table", out var ct) && ct.GetBoolean(),
            TimeoutSeconds = json.TryGetProperty("timeout_seconds", out var ts) ? ts.GetInt32() : 30,
        };
    }
}

/// <summary>Config for Webhook Sender export.</summary>
public class WebhookSenderConfig
{
    public string Url { get; set; } = "";
    public string Method { get; set; } = "POST"; // POST, PUT, PATCH
    public Dictionary<string, string> Headers { get; set; } = new();
    public string AuthType { get; set; } = "none"; // none, bearer, basic, api_key
    public string? AuthToken { get; set; }
    public string? ApiKeyHeader { get; set; } = "X-API-Key";
    public int TimeoutSeconds { get; set; } = 30;
    public int MaxRetries { get; set; } = 3;
    public bool BatchMode { get; set; } = false;
    public string ContentType { get; set; } = "application/json";

    public static WebhookSenderConfig FromJson(JsonElement json)
    {
        var config = new WebhookSenderConfig
        {
            Url = json.TryGetProperty("url", out var u) ? u.GetString() ?? "" : "",
            Method = json.TryGetProperty("method", out var m) ? m.GetString() ?? "POST" : "POST",
            AuthType = json.TryGetProperty("auth_type", out var at) ? at.GetString() ?? "none" : "none",
            AuthToken = json.TryGetProperty("auth_token", out var tok) ? tok.GetString() : null,
            ApiKeyHeader = json.TryGetProperty("api_key_header", out var akh) ? akh.GetString() : "X-API-Key",
            TimeoutSeconds = json.TryGetProperty("timeout_seconds", out var ts) ? ts.GetInt32() : 30,
            MaxRetries = json.TryGetProperty("max_retries", out var mr) ? mr.GetInt32() : 3,
            BatchMode = json.TryGetProperty("batch_mode", out var bm) && bm.GetBoolean(),
            ContentType = json.TryGetProperty("content_type", out var ct) ? ct.GetString() ?? "application/json" : "application/json",
        };

        if (json.TryGetProperty("headers", out var headers) && headers.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in headers.EnumerateObject())
                config.Headers[prop.Name] = prop.Value.GetString() ?? "";
        }

        return config;
    }
}

/// <summary>Config for S3 Upload export.</summary>
public class S3UploadConfig
{
    public string Region { get; set; } = "us-east-1";
    public string BucketName { get; set; } = "";
    public string KeyPrefix { get; set; } = "";
    public string AccessKeyId { get; set; } = "";
    public string SecretAccessKey { get; set; } = "";
    public string OutputFormat { get; set; } = "json"; // json, csv, parquet
    public string Compression { get; set; } = "none"; // none, gzip, snappy, zstd
    public bool PartitionByDate { get; set; } = true;
    public string DatePartitionFormat { get; set; } = "yyyy/MM/dd";
    public bool IncludeMetadata { get; set; } = true;
    public int MultipartThresholdMb { get; set; } = 100;

    public static S3UploadConfig FromJson(JsonElement json)
    {
        return new S3UploadConfig
        {
            Region = json.TryGetProperty("region", out var r) ? r.GetString() ?? "us-east-1" : "us-east-1",
            BucketName = json.TryGetProperty("bucket_name", out var bn) ? bn.GetString() ?? "" : "",
            KeyPrefix = json.TryGetProperty("key_prefix", out var kp) ? kp.GetString() ?? "" : "",
            AccessKeyId = json.TryGetProperty("access_key_id", out var ak) ? ak.GetString() ?? "" : "",
            SecretAccessKey = json.TryGetProperty("secret_access_key", out var sk) ? sk.GetString() ?? "" : "",
            OutputFormat = json.TryGetProperty("output_format", out var of) ? of.GetString() ?? "json" : "json",
            Compression = json.TryGetProperty("compression", out var c) ? c.GetString() ?? "none" : "none",
            PartitionByDate = !json.TryGetProperty("partition_by_date", out var pd) || pd.GetBoolean(),
            DatePartitionFormat = json.TryGetProperty("date_partition_format", out var dpf) ? dpf.GetString() ?? "yyyy/MM/dd" : "yyyy/MM/dd",
            IncludeMetadata = !json.TryGetProperty("include_metadata", out var im) || im.GetBoolean(),
            MultipartThresholdMb = json.TryGetProperty("multipart_threshold_mb", out var mt) ? mt.GetInt32() : 100,
        };
    }
}
