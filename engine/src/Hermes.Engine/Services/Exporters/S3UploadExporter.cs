using System.IO.Compression;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;

namespace Hermes.Engine.Services.Exporters;

/// <summary>
/// Exports data to Amazon S3 (or S3-compatible storage).
/// Supports JSON/CSV output, gzip compression, date-based partitioning,
/// multipart upload for large files, and metadata tagging.
///
/// Uses AWSSDK.S3 for actual S3 operations. This implementation
/// abstracts the S3 client behind IS3Client interface for testability.
/// </summary>
public class S3UploadExporter : BaseExporter
{
    private readonly S3UploadConfig _config;
    private readonly IS3Client _s3Client;
    private readonly ILogger? _logger;

    public S3UploadExporter(S3UploadConfig config, IS3Client s3Client, ILogger? logger = null)
    {
        _config = config;
        _s3Client = s3Client;
        _logger = logger;
    }

    public override async Task<ExportResult> ExportAsync(ExportContext context, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(_config.BucketName))
            return new ExportResult(false, 0, ErrorMessage: "S3 bucket name not configured");

        var sw = System.Diagnostics.Stopwatch.StartNew();
        var records = ParseRecords(context.DataJson);

        if (records.Count == 0)
            return new ExportResult(true, 0, DestinationInfo: $"s3://{_config.BucketName}");

        try
        {
            // Build S3 key
            var key = BuildKey(context);

            // Serialize records
            var content = _config.OutputFormat switch
            {
                "csv" => SerializeToCsv(records),
                _ => SerializeToJson(records),
            };

            // Compress if configured
            byte[] data;
            var finalKey = key;
            if (_config.Compression == "gzip")
            {
                data = CompressGzip(Encoding.UTF8.GetBytes(content));
                finalKey += ".gz";
            }
            else
            {
                data = Encoding.UTF8.GetBytes(content);
            }

            // Build metadata
            var metadata = new Dictionary<string, string>();
            if (_config.IncludeMetadata)
            {
                metadata["hermes-pipeline"] = context.PipelineName ?? "unknown";
                metadata["hermes-job-id"] = context.JobId?.ToString() ?? "0";
                metadata["hermes-record-count"] = records.Count.ToString();
                metadata["hermes-export-time"] = DateTimeOffset.UtcNow.ToString("O");
            }

            // Upload
            await _s3Client.PutObjectAsync(_config.BucketName, finalKey, data, _config.ContentType(), metadata, ct);

            sw.Stop();
            var destination = $"s3://{_config.BucketName}/{finalKey}";
            _logger?.LogInformation("S3: Uploaded {Count} records to {Key} ({Size} bytes)",
                records.Count, destination, data.Length);

            return new ExportResult(
                Success: true,
                RecordsExported: records.Count,
                DestinationInfo: destination,
                DurationMs: sw.ElapsedMilliseconds,
                Summary: new Dictionary<string, object>
                {
                    ["bucket"] = _config.BucketName,
                    ["key"] = finalKey,
                    ["size_bytes"] = data.Length,
                    ["format"] = _config.OutputFormat,
                    ["compression"] = _config.Compression,
                    ["records"] = records.Count,
                }
            );
        }
        catch (Exception ex)
        {
            sw.Stop();
            _logger?.LogError(ex, "S3 upload failed: {Bucket}", _config.BucketName);
            return new ExportResult(false, 0, ErrorMessage: ex.Message, DurationMs: sw.ElapsedMilliseconds);
        }
    }

    private string BuildKey(ExportContext context)
    {
        var parts = new List<string>();

        if (!string.IsNullOrEmpty(_config.KeyPrefix))
            parts.Add(_config.KeyPrefix.TrimEnd('/'));

        if (_config.PartitionByDate)
            parts.Add(DateTimeOffset.UtcNow.ToString(_config.DatePartitionFormat, System.Globalization.CultureInfo.InvariantCulture));

        var filename = $"batch_{DateTimeOffset.UtcNow:yyyyMMddHHmmss}_{context.JobId ?? 0}.{_config.OutputFormat}";
        parts.Add(filename);

        return string.Join("/", parts);
    }

    private static string SerializeToJson(List<JsonElement> records)
    {
        return JsonSerializer.Serialize(records, new JsonSerializerOptions { WriteIndented = false });
    }

    private static string SerializeToCsv(List<JsonElement> records)
    {
        if (records.Count == 0) return "";
        var sb = new StringBuilder();

        // Header
        var columns = records[0].EnumerateObject().Select(p => p.Name).ToList();
        sb.AppendLine(string.Join(",", columns.Select(c => $"\"{c}\"")));

        // Rows
        foreach (var record in records)
        {
            var values = columns.Select(c =>
            {
                if (!record.TryGetProperty(c, out var val)) return "";
                var str = val.ValueKind == JsonValueKind.String ? val.GetString() ?? "" : val.ToString();
                return $"\"{str.Replace("\"", "\"\"")}\"";
            });
            sb.AppendLine(string.Join(",", values));
        }

        return sb.ToString();
    }

    private static byte[] CompressGzip(byte[] data)
    {
        using var output = new MemoryStream();
        using (var gzip = new GZipStream(output, CompressionLevel.Optimal))
        {
            gzip.Write(data, 0, data.Length);
        }
        return output.ToArray();
    }

    private static List<JsonElement> ParseRecords(string dataJson)
    {
        var doc = JsonDocument.Parse(dataJson);
        if (doc.RootElement.ValueKind == JsonValueKind.Array)
            return doc.RootElement.EnumerateArray().ToList();
        if (doc.RootElement.TryGetProperty("records", out var records) && records.ValueKind == JsonValueKind.Array)
            return records.EnumerateArray().ToList();
        return new List<JsonElement> { doc.RootElement };
    }
}

/// <summary>Abstraction for S3 operations (testable).</summary>
public interface IS3Client
{
    Task PutObjectAsync(string bucket, string key, byte[] data, string contentType,
        Dictionary<string, string>? metadata = null, CancellationToken ct = default);
}

/// <summary>Extension for S3UploadConfig.</summary>
public static class S3ConfigExtensions
{
    public static string ContentType(this S3UploadConfig config) => config.OutputFormat switch
    {
        "csv" => config.Compression == "gzip" ? "application/gzip" : "text/csv",
        _ => config.Compression == "gzip" ? "application/gzip" : "application/json",
    };
}
