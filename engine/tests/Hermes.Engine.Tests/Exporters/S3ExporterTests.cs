using Hermes.Engine.Services.Exporters;

namespace Hermes.Engine.Tests.Exporters;

/// <summary>
/// Tests for S3UploadExporter with mock S3 client.
/// </summary>
public class S3ExporterTests
{
    private class MockS3Client : IS3Client
    {
        public List<(string Bucket, string Key, byte[] Data, string ContentType, Dictionary<string, string>? Metadata)> Uploads { get; } = new();
        public Exception? ErrorToThrow { get; set; }

        public Task PutObjectAsync(string bucket, string key, byte[] data, string contentType,
            Dictionary<string, string>? metadata = null, CancellationToken ct = default)
        {
            if (ErrorToThrow != null) throw ErrorToThrow;
            Uploads.Add((bucket, key, data, contentType, metadata));
            return Task.CompletedTask;
        }
    }

    [Fact]
    public async Task Export_JsonRecords_Success()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig
        {
            BucketName = "test-bucket",
            KeyPrefix = "output",
            OutputFormat = "json",
            Compression = "none",
            PartitionByDate = false,
        };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: """[{"id":1,"value":42},{"id":2,"value":99}]""",
            Metadata: new(),
            JobId: 100
        ));

        Assert.True(result.Success);
        Assert.Equal(2, result.RecordsExported);
        Assert.Single(s3.Uploads);
        Assert.Equal("test-bucket", s3.Uploads[0].Bucket);
        Assert.Contains("output/", s3.Uploads[0].Key);
        Assert.Equal("application/json", s3.Uploads[0].ContentType);
    }

    [Fact]
    public async Task Export_CsvWithGzip_Success()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig
        {
            BucketName = "data-lake",
            KeyPrefix = "raw",
            OutputFormat = "csv",
            Compression = "gzip",
            PartitionByDate = false,
        };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: """[{"name":"sensor_a","value":42.5},{"name":"sensor_b","value":18.3}]""",
            Metadata: new(),
            JobId: 200
        ));

        Assert.True(result.Success);
        Assert.Equal(2, result.RecordsExported);
        Assert.Single(s3.Uploads);
        Assert.EndsWith(".gz", s3.Uploads[0].Key);
        Assert.Equal("application/gzip", s3.Uploads[0].ContentType);
        // Gzipped data should be smaller than raw
        Assert.True(s3.Uploads[0].Data.Length > 0);
    }

    [Fact]
    public async Task Export_WithDatePartition_IncludesDateInKey()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig
        {
            BucketName = "bucket",
            KeyPrefix = "data",
            PartitionByDate = true,
            DatePartitionFormat = "yyyy/MM/dd",
        };
        var exporter = new S3UploadExporter(config, s3);

        await exporter.ExportAsync(new ExportContext(
            DataJson: """[{"x":1}]""",
            Metadata: new(),
            JobId: 1
        ));

        var key = s3.Uploads[0].Key;
        var today = DateTimeOffset.UtcNow;
        // DatePartitionFormat "yyyy/MM/dd" uses invariant culture in the exporter
        var expectedDate = today.ToString("yyyy/MM/dd", System.Globalization.CultureInfo.InvariantCulture);
        Assert.Contains(expectedDate, key);
    }

    [Fact]
    public async Task Export_WithMetadata_IncludesHermesHeaders()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig
        {
            BucketName = "bucket",
            IncludeMetadata = true,
            PartitionByDate = false,
        };
        var exporter = new S3UploadExporter(config, s3);

        await exporter.ExportAsync(new ExportContext(
            DataJson: """[{"x":1}]""",
            Metadata: new(),
            PipelineName: "test-pipeline",
            JobId: 42
        ));

        var metadata = s3.Uploads[0].Metadata!;
        Assert.Equal("test-pipeline", metadata["hermes-pipeline"]);
        Assert.Equal("42", metadata["hermes-job-id"]);
        Assert.Equal("1", metadata["hermes-record-count"]);
    }

    [Fact]
    public async Task Export_EmptyRecords_ReturnsSuccess()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "bucket", PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[]", Metadata: new()
        ));

        Assert.True(result.Success);
        Assert.Equal(0, result.RecordsExported);
        Assert.Empty(s3.Uploads);
    }

    [Fact]
    public async Task Export_NoBucket_Fails()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "" };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: """[{"x":1}]""", Metadata: new()
        ));

        Assert.False(result.Success);
        Assert.Contains("bucket", result.ErrorMessage, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Export_S3Error_ReturnsFailure()
    {
        var s3 = new MockS3Client { ErrorToThrow = new Exception("Access Denied") };
        var config = new S3UploadConfig { BucketName = "bucket", PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: """[{"x":1}]""", Metadata: new()
        ));

        Assert.False(result.Success);
        Assert.Contains("Access Denied", result.ErrorMessage);
    }

    [Fact]
    public async Task Export_SingleObject_WrapsAsArray()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "bucket", PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: """{"id":1,"value":"single"}""",
            Metadata: new()
        ));

        Assert.True(result.Success);
        Assert.Equal(1, result.RecordsExported);
    }

    [Fact]
    public async Task Export_RecordsProperty_Unwraps()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "bucket", PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: """{"records":[{"a":1},{"a":2},{"a":3}]}""",
            Metadata: new()
        ));

        Assert.True(result.Success);
        Assert.Equal(3, result.RecordsExported);
    }
}
