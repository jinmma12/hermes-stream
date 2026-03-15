using System.Text.Json;
using Microsoft.Extensions.Logging.Abstractions;
using Hermes.Engine.Services;

namespace Hermes.Engine.Tests.Phase3;

/// <summary>
/// Tests for Data Preview — sample data before pipeline activation.
/// References: Airbyte connection test, NiFi data provenance, dbt preview.
/// </summary>
public class DataPreviewTests : IDisposable
{
    private readonly string _tempDir;
    private readonly DataPreviewService _preview;

    public DataPreviewTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), $"hermes-preview-{Guid.NewGuid():N}");
        Directory.CreateDirectory(_tempDir);
        var schemaRegistry = new SchemaRegistry(NullLogger<SchemaRegistry>.Instance);
        _preview = new DataPreviewService(schemaRegistry, NullLogger<DataPreviewService>.Instance);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempDir)) Directory.Delete(_tempDir, true);
    }

    [Fact]
    public async Task PreviewCsv_ReturnsSampleRows()
    {
        var csv = "id,name,value,timestamp\n1,sensor-a,23.5,2026-03-15\n2,sensor-b,18.2,2026-03-15\n3,sensor-c,31.0,2026-03-15\n";
        var path = Path.Combine(_tempDir, "sensors.csv");
        await File.WriteAllTextAsync(path, csv);

        var result = await _preview.PreviewFileAsync(path);

        Assert.True(result.Success);
        Assert.Equal(3, result.SampleRows.Count);
        Assert.Equal(4, result.Columns.Count);
        Assert.Contains(result.Columns, c => c.Name == "id" && c.InferredType == "integer");
        Assert.Contains(result.Columns, c => c.Name == "name" && c.InferredType == "string");
        Assert.Contains(result.Columns, c => c.Name == "value" && c.InferredType == "number");
    }

    [Fact]
    public async Task PreviewCsv_LimitRows()
    {
        var lines = new List<string> { "id,value" };
        for (int i = 1; i <= 100; i++)
            lines.Add($"{i},{i * 1.5}");
        var path = Path.Combine(_tempDir, "large.csv");
        await File.WriteAllLinesAsync(path, lines);

        var result = await _preview.PreviewFileAsync(path, maxRows: 5);

        Assert.True(result.Success);
        Assert.Equal(5, result.SampleRows.Count);
        Assert.True(result.TotalRowsEstimate > 5);
    }

    [Fact]
    public async Task PreviewJson_ArrayOfObjects()
    {
        var json = JsonSerializer.Serialize(new[]
        {
            new { id = 1, name = "alpha", score = 95.5, active = true },
            new { id = 2, name = "beta", score = 87.3, active = false },
            new { id = 3, name = "gamma", score = 91.0, active = true },
        });

        var result = await _preview.PreviewJsonAsync(json);

        Assert.True(result.Success);
        Assert.Equal(3, result.SampleRows.Count);
        Assert.Equal(4, result.Columns.Count);
        Assert.NotNull(result.InferredSchemaJson);
    }

    [Fact]
    public async Task PreviewJson_SingleObject()
    {
        var json = JsonSerializer.Serialize(new { temperature = 22.5, humidity = 45, sensor = "S001" });

        var result = await _preview.PreviewJsonAsync(json);

        Assert.True(result.Success);
        Assert.Single(result.SampleRows);
    }

    [Fact]
    public async Task PreviewFile_NotFound_Error()
    {
        var result = await _preview.PreviewFileAsync("/nonexistent/file.csv");

        Assert.False(result.Success);
        Assert.Contains("not found", result.ErrorMessage!);
    }

    [Fact]
    public async Task PreviewFile_UnsupportedFormat()
    {
        var path = Path.Combine(_tempDir, "data.parquet");
        await File.WriteAllTextAsync(path, "binary data");

        var result = await _preview.PreviewFileAsync(path);

        Assert.False(result.Success);
        Assert.Contains("Unsupported", result.ErrorMessage!);
    }

    [Fact]
    public async Task PreviewCsv_InfersColumnTypes()
    {
        var csv = "count,ratio,name,active\n100,0.95,test,true\n200,0.87,check,false\n";
        var path = Path.Combine(_tempDir, "typed.csv");
        await File.WriteAllTextAsync(path, csv);

        var result = await _preview.PreviewFileAsync(path);

        Assert.True(result.Success);
        Assert.Contains(result.Columns, c => c.Name == "count" && c.InferredType == "integer");
        Assert.Contains(result.Columns, c => c.Name == "ratio" && c.InferredType == "number");
        Assert.Contains(result.Columns, c => c.Name == "name" && c.InferredType == "string");
        Assert.Contains(result.Columns, c => c.Name == "active" && c.InferredType == "boolean");
    }
}
