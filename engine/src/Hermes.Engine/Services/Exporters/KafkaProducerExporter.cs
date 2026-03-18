using System.Text.Json;
using Confluent.Kafka;
using Microsoft.Extensions.Logging;

namespace Hermes.Engine.Services.Exporters;

/// <summary>
/// Exports data to Apache Kafka topics.
/// Supports key-based partitioning, configurable acks, compression,
/// idempotent delivery, and batch publishing.
/// </summary>
public class KafkaProducerExporter : BaseExporter
{
    private readonly KafkaProducerConfig _config;
    private readonly ILogger? _logger;

    public KafkaProducerExporter(KafkaProducerConfig config, ILogger? logger = null)
    {
        _config = config;
        _logger = logger;
    }

    public override async Task<ExportResult> ExportAsync(ExportContext context, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(_config.Topic))
            return new ExportResult(false, 0, ErrorMessage: "Kafka topic not configured");
        if (string.IsNullOrEmpty(_config.BootstrapServers))
            return new ExportResult(false, 0, ErrorMessage: "Kafka bootstrap servers not configured");

        var sw = System.Diagnostics.Stopwatch.StartNew();
        var producerConfig = new ProducerConfig
        {
            BootstrapServers = _config.BootstrapServers,
            Acks = _config.Acks switch
            {
                "0" => Confluent.Kafka.Acks.None,
                "1" => Confluent.Kafka.Acks.Leader,
                _ => Confluent.Kafka.Acks.All,
            },
            EnableIdempotence = _config.EnableIdempotence,
            BatchSize = _config.BatchSize,
            LingerMs = _config.LingerMs,
            CompressionType = _config.Compression switch
            {
                "gzip" => CompressionType.Gzip,
                "snappy" => CompressionType.Snappy,
                "lz4" => CompressionType.Lz4,
                "zstd" => CompressionType.Zstd,
                _ => CompressionType.None,
            },
            SecurityProtocol = _config.SecurityProtocol switch
            {
                "SSL" => Confluent.Kafka.SecurityProtocol.Ssl,
                "SASL_PLAINTEXT" => Confluent.Kafka.SecurityProtocol.SaslPlaintext,
                "SASL_SSL" => Confluent.Kafka.SecurityProtocol.SaslSsl,
                _ => Confluent.Kafka.SecurityProtocol.Plaintext,
            },
        };

        int recordCount = 0;
        int failedCount = 0;

        try
        {
            using var producer = new ProducerBuilder<string?, string>(producerConfig).Build();

            var records = ParseRecords(context.DataJson);
            foreach (var record in records)
            {
                ct.ThrowIfCancellationRequested();

                string? key = null;
                if (!string.IsNullOrEmpty(_config.KeyField) && record.TryGetProperty(_config.KeyField, out var keyVal))
                    key = keyVal.ToString();

                var message = new Message<string?, string>
                {
                    Key = key,
                    Value = record.GetRawText(),
                };

                try
                {
                    await producer.ProduceAsync(_config.Topic, message, ct);
                    recordCount++;
                }
                catch (ProduceException<string?, string> ex)
                {
                    failedCount++;
                    _logger?.LogWarning("Kafka produce failed for key={Key}: {Error}", key, ex.Error.Reason);
                }
            }

            producer.Flush(TimeSpan.FromSeconds(10));
            sw.Stop();

            _logger?.LogInformation("Kafka: Published {Count} records to {Topic}", recordCount, _config.Topic);

            return new ExportResult(
                Success: failedCount == 0,
                RecordsExported: recordCount,
                DestinationInfo: $"kafka://{_config.BootstrapServers}/{_config.Topic}",
                ErrorMessage: failedCount > 0 ? $"{failedCount} records failed" : null,
                DurationMs: sw.ElapsedMilliseconds,
                Summary: new Dictionary<string, object>
                {
                    ["topic"] = _config.Topic,
                    ["records_published"] = recordCount,
                    ["records_failed"] = failedCount,
                    ["compression"] = _config.Compression,
                }
            );
        }
        catch (Exception ex)
        {
            sw.Stop();
            _logger?.LogError(ex, "Kafka export failed: {Topic}", _config.Topic);
            return new ExportResult(false, recordCount, ErrorMessage: ex.Message, DurationMs: sw.ElapsedMilliseconds);
        }
    }

    private static List<JsonElement> ParseRecords(string dataJson)
    {
        var doc = JsonDocument.Parse(dataJson);
        if (doc.RootElement.ValueKind == JsonValueKind.Array)
            return doc.RootElement.EnumerateArray().ToList();

        // If single object with "records" array
        if (doc.RootElement.TryGetProperty("records", out var records) && records.ValueKind == JsonValueKind.Array)
            return records.EnumerateArray().ToList();

        // Single record
        return new List<JsonElement> { doc.RootElement };
    }
}
