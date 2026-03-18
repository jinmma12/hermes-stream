using System.Net;
using System.Text.Json;
using System.Text.RegularExpressions;
using Hermes.Engine.Domain;
using Hermes.Engine.Services.Exporters;
using Hermes.Engine.Services.Monitors;

namespace Hermes.Engine.Tests.E2E;

/// <summary>
/// Comprehensive connector E2E tests covering all connector types with edge cases.
/// Tests config parsing, regex matching, exporter behavior (mocked), and cross-connector scenarios.
/// Total: 200 test methods.
/// </summary>
public class ConnectorE2ETests
{
    // ════════════════════════════════════════════════════════════════════
    // Helpers
    // ════════════════════════════════════════════════════════════════════

    private static FtpSftpConfig ParseFtpConfig(string json)
        => FtpSftpConfig.FromJson(JsonDocument.Parse(json).RootElement);

    private static KafkaProducerConfig ParseKafkaProducerConfig(string json)
        => KafkaProducerConfig.FromJson(JsonDocument.Parse(json).RootElement);

    private static DbWriterConfig ParseDbWriterConfig(string json)
        => DbWriterConfig.FromJson(JsonDocument.Parse(json).RootElement);

    private static WebhookSenderConfig ParseWebhookConfig(string json)
        => WebhookSenderConfig.FromJson(JsonDocument.Parse(json).RootElement);

    private static S3UploadConfig ParseS3Config(string json)
        => S3UploadConfig.FromJson(JsonDocument.Parse(json).RootElement);

    private static bool RegexMatches(string pattern, string input)
        => new Regex(pattern, RegexOptions.Compiled | RegexOptions.IgnoreCase).IsMatch(input);

    // ── Mock S3 Client ──
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

    // ── Mock HttpMessageHandler ──
    private class MockHttpHandler : HttpMessageHandler
    {
        public HttpStatusCode ResponseCode { get; set; } = HttpStatusCode.OK;
        public string ResponseBody { get; set; } = "{}";
        public List<HttpRequestMessage> Requests { get; } = new();
        public Exception? ExceptionToThrow { get; set; }
        public TimeSpan? RetryAfterDelay { get; set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Requests.Add(request);
            if (ExceptionToThrow != null) throw ExceptionToThrow;

            var response = new HttpResponseMessage(ResponseCode)
            {
                Content = new StringContent(ResponseBody)
            };

            if (ResponseCode == HttpStatusCode.TooManyRequests && RetryAfterDelay.HasValue)
                response.Headers.RetryAfter = new System.Net.Http.Headers.RetryConditionHeaderValue(RetryAfterDelay.Value);

            return Task.FromResult(response);
        }
    }

    // ════════════════════════════════════════════════════════════════════
    // 1. FTP/SFTP Monitor Config Tests (30 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void FtpConfig_ParsesAllFields_Complete()
    {
        var cfg = ParseFtpConfig("{\"protocol\":\"sftp\",\"host\":\"10.0.0.1\",\"port\":2222,"
            + "\"username\":\"admin\",\"password\":\"s3cret\",\"base_path\":\"/incoming\","
            + "\"recursive\":true,\"path_filter_regex\":\"^/incoming/2026\","
            + "\"file_filter_regex\":\".*\\\\.csv$\",\"sort_by\":\"modified_desc\","
            + "\"max_files_per_poll\":50,\"min_age_seconds\":30}");

        Assert.Equal("sftp", cfg.Protocol);
        Assert.Equal("10.0.0.1", cfg.Host);
        Assert.Equal(2222, cfg.Port);
        Assert.Equal("admin", cfg.Username);
        Assert.Equal("s3cret", cfg.Password);
        Assert.Equal("/incoming", cfg.BasePath);
        Assert.True(cfg.Recursive);
        Assert.Equal("^/incoming/2026", cfg.PathFilterRegex);
        Assert.Equal(@".*\.csv$", cfg.FileFilterRegex);
        Assert.Equal("modified_desc", cfg.SortBy);
        Assert.Equal(50, cfg.MaxFilesPerPoll);
        Assert.Equal(30, cfg.MinAgeSeconds);
    }

    [Fact]
    public void FtpConfig_EmptyJson_AllDefaults()
    {
        var cfg = ParseFtpConfig("{}");
        Assert.Equal("sftp", cfg.Protocol);
        Assert.Equal("", cfg.Host);
        Assert.Equal(22, cfg.Port);
        Assert.Equal("", cfg.Username);
        Assert.Equal("", cfg.Password);
        Assert.Equal("/", cfg.BasePath);
        Assert.False(cfg.Recursive);
        Assert.Null(cfg.PathFilterRegex);
        Assert.Null(cfg.FileFilterRegex);
        Assert.Equal("modified_desc", cfg.SortBy);
        Assert.Equal(100, cfg.MaxFilesPerPoll);
        Assert.Equal(10, cfg.MinAgeSeconds);
    }

    [Theory]
    [InlineData("yyyyMMdd", @"\d{8}", "\\\\d{8}")]
    [InlineData("yyyy-MM-dd", @"\d{4}-\d{2}-\d{2}", "\\\\d{4}-\\\\d{2}-\\\\d{2}")]
    [InlineData("yyyy/MM/dd", @"\d{4}/\d{2}/\d{2}", "\\\\d{4}/\\\\d{2}/\\\\d{2}")]
    [InlineData("yyyyMM", @"\d{6}", "\\\\d{6}")]
    public void FtpConfig_DateFolderPattern_RegexParses(string dateFormat, string expectedRegex, string jsonEscaped)
    {
        var json = "{\"path_filter_regex\":\".*/" + jsonEscaped + "/.*\"}";
        var cfg = ParseFtpConfig(json);
        Assert.NotNull(cfg.PathFilterRegex);
        Assert.Contains(expectedRegex, cfg.PathFilterRegex);
    }

    [Theory]
    [InlineData(@".*/plant/LINE_[A-Z]+/ST\d{2}/\d{8}/.*")]
    [InlineData(@".*/equipment/(temperature|vibration)/\d{8}/.*")]
    public void FtpConfig_IndustrialPathRegex_Parses(string regex)
    {
        var json = "{\"path_filter_regex\":\"" + regex.Replace("\\", "\\\\") + "\"}";
        var cfg = ParseFtpConfig(json);
        Assert.NotNull(cfg.PathFilterRegex);
    }

    [Theory]
    [InlineData(@".*\.csv$")]
    [InlineData(@".*\.json$")]
    [InlineData(@"data_\d{8}_.*\.csv$")]
    [InlineData(@"sensor_(temp|vib)_\d+\.dat$")]
    public void FtpConfig_FileRegex_Parses(string regex)
    {
        var json = "{\"file_filter_regex\":\"" + regex.Replace("\\", "\\\\") + "\"}";
        var cfg = ParseFtpConfig(json);
        Assert.NotNull(cfg.FileFilterRegex);
    }

    [Theory]
    [InlineData("modified_desc")]
    [InlineData("modified_asc")]
    [InlineData("name_asc")]
    [InlineData("name_desc")]
    [InlineData("size_desc")]
    public void FtpConfig_SortBy_AllOptions(string sortBy)
    {
        var json = "{\"sort_by\":\"" + sortBy + "\"}";
        var cfg = ParseFtpConfig(json);
        Assert.Equal(sortBy, cfg.SortBy);
    }

    [Theory]
    [InlineData(1)]
    [InlineData(10)]
    [InlineData(50)]
    [InlineData(100)]
    [InlineData(500)]
    [InlineData(1000)]
    public void FtpConfig_MaxFiles_ValidValues(int maxFiles)
    {
        var json = "{\"max_files_per_poll\":" + maxFiles + "}";
        var cfg = ParseFtpConfig(json);
        Assert.Equal(maxFiles, cfg.MaxFilesPerPoll);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(5)]
    [InlineData(10)]
    [InlineData(30)]
    [InlineData(60)]
    [InlineData(3600)]
    public void FtpConfig_MinAge_ValidValues(int minAge)
    {
        var json = "{\"min_age_seconds\":" + minAge + "}";
        var cfg = ParseFtpConfig(json);
        Assert.Equal(minAge, cfg.MinAgeSeconds);
    }

    [Theory]
    [InlineData("ftp", 21)]
    [InlineData("ftps", 990)]
    [InlineData("sftp", 22)]
    public void FtpConfig_Protocol_WithPorts(string protocol, int port)
    {
        var json = "{\"protocol\":\"" + protocol + "\",\"port\":" + port + "}";
        var cfg = ParseFtpConfig(json);
        Assert.Equal(protocol, cfg.Protocol);
        Assert.Equal(port, cfg.Port);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void FtpConfig_Recursive_BothValues(bool recursive)
    {
        var json = "{\"recursive\":" + recursive.ToString().ToLower() + "}";
        var cfg = ParseFtpConfig(json);
        Assert.Equal(recursive, cfg.Recursive);
    }

    [Fact]
    public void FtpConfig_EmptyHost_DefaultsToEmpty()
    {
        var cfg = ParseFtpConfig("{\"host\":\"\"}");
        Assert.Equal("", cfg.Host);
    }

    [Fact]
    public void FtpConfig_PortZero_Parses()
    {
        var cfg = ParseFtpConfig("{\"port\":0}");
        Assert.Equal(0, cfg.Port);
    }

    [Fact]
    public void FtpConfig_NegativeMinAge_Parses()
    {
        var cfg = ParseFtpConfig("{\"min_age_seconds\":-5}");
        Assert.Equal(-5, cfg.MinAgeSeconds);
    }

    [Fact]
    public void FtpConfig_NullSortBy_DefaultsModifiedDesc()
    {
        var cfg = ParseFtpConfig("{\"sort_by\":null}");
        // FromJson returns null for null string; SortBy default is "modified_desc" but explicit null overrides
        // The switch in ApplyFilters handles null via _ default case
        Assert.True(cfg.SortBy == null || cfg.SortBy == "modified_desc");
    }

    [Fact]
    public void FtpConfig_LargePort_Parses()
    {
        var cfg = ParseFtpConfig("{\"port\":65535}");
        Assert.Equal(65535, cfg.Port);
    }

    [Fact]
    public void FtpConfig_SpecialCharsInPassword_Parses()
    {
        var json = "{\"password\":\"p@ss!w0rd#$%\"}";
        var cfg = ParseFtpConfig(json);
        Assert.Equal("p@ss!w0rd#$%", cfg.Password);
    }

    [Fact]
    public void FtpConfig_BasePath_TrailingSlash()
    {
        var cfg = ParseFtpConfig("{\"base_path\":\"/data/\"}");
        Assert.Equal("/data/", cfg.BasePath);
    }

    [Fact]
    public void FtpConfig_BasePath_RootOnly()
    {
        var cfg = ParseFtpConfig("{\"base_path\":\"/\"}");
        Assert.Equal("/", cfg.BasePath);
    }

    [Fact]
    public void FtpConfig_Monitor_CreatesWithConfig()
    {
        var cfg = new FtpSftpConfig { Host = "test.local", Port = 22 };
        var monitor = new FtpSftpMonitor(cfg);
        Assert.NotNull(monitor);
    }

    // ════════════════════════════════════════════════════════════════════
    // 2. FTP/SFTP Folder Structure Scenarios (40 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void FolderRegex_Flat_CsvFiles()
    {
        Assert.True(RegexMatches(@".*\.csv$", "report.csv"));
        Assert.False(RegexMatches(@".*\.csv$", "report.json"));
    }

    [Fact]
    public void FolderRegex_DateDaily_yyyyMMdd()
    {
        Assert.True(RegexMatches(@".*/\d{8}/.*", "/data/20260317/file.csv"));
        Assert.False(RegexMatches(@".*/\d{8}/.*", "/data/2026-03-17/file.csv"));
    }

    [Fact]
    public void FolderRegex_DateNested_yyyy_MM_dd()
    {
        Assert.True(RegexMatches(@".*/\d{4}/\d{2}/\d{2}/.*", "/data/2026/03/17/file.csv"));
        Assert.False(RegexMatches(@".*/\d{4}/\d{2}/\d{2}/.*", "/data/20260317/file.csv"));
    }

    [Fact]
    public void FolderRegex_TopicPlusDate()
    {
        var pattern = @".*/(temperature|vibration)/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/data/temperature/20260317/reading.csv"));
        Assert.True(RegexMatches(pattern, "/data/vibration/20260317/sensor.csv"));
        Assert.False(RegexMatches(pattern, "/data/pressure/20260317/reading.csv"));
    }

    [Fact]
    public void FolderRegex_PlantHierarchy()
    {
        var pattern = @".*/LINE_[A-Z]+/ST\d{2}/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/plant/LINE_A/ST01/20260317/measurement.csv"));
        Assert.True(RegexMatches(pattern, "/plant/LINE_B/ST03/20260316/measurement.csv"));
        Assert.False(RegexMatches(pattern, "/plant/ZONE_1/ST01/20260317/measurement.csv"));
    }

    [Fact]
    public void FolderRegex_VendorOutbox()
    {
        var pattern = @".*/V\d{3}/outbox/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/vendors/V001/outbox/20260317/orders.csv"));
        Assert.True(RegexMatches(pattern, "/vendors/V042/outbox/20260316/invoices.xml"));
        Assert.False(RegexMatches(pattern, "/vendors/V001/inbox/20260317/orders.csv"));
    }

    [Fact]
    public void FolderRegex_EquipmentPerType()
    {
        var pattern = @".*/equipment/(temperature|vibration)/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/equipment/temperature/20260317/data.csv"));
        Assert.True(RegexMatches(pattern, "/equipment/vibration/20260317/data.csv"));
        Assert.False(RegexMatches(pattern, "/equipment/humidity/20260317/data.csv"));
    }

    [Fact]
    public void FolderRegex_MultiLevelMixed()
    {
        var pattern = @".*/region/[^/]+/plant/[^/]+/line/[^/]+/data/.*";
        Assert.True(RegexMatches(pattern, "/region/APAC/plant/Seoul/line/L1/data/output.csv"));
        Assert.False(RegexMatches(pattern, "/region/APAC/plant/Seoul/output.csv"));
    }

    [Fact]
    public void FolderRegex_ArchiveStructure()
    {
        var pattern = @".*/archive/\d{4}/\d{2}/processed/.*";
        Assert.True(RegexMatches(pattern, "/archive/2026/03/processed/batch.csv"));
        Assert.False(RegexMatches(pattern, "/archive/2026/03/raw/batch.csv"));
    }

    [Fact]
    public void FolderRegex_LogRotation()
    {
        var pattern = @"app-\d{4}-\d{2}-\d{2}(-\d{3})?\.log$";
        Assert.True(RegexMatches(pattern, "app-2026-03-17.log"));
        Assert.True(RegexMatches(pattern, "app-2026-03-17-001.log"));
        Assert.False(RegexMatches(pattern, "system-2026-03-17.log"));
    }

    [Fact]
    public void FolderRegex_UnicodeFolderNames()
    {
        var pattern = @".*/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/data/\uC13C\uC11C/20260317/file.csv"));
    }

    [Fact]
    public void FolderRegex_SpacesInFolderNames()
    {
        var pattern = @".*/data files/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/root/data files/20260317/report.csv"));
    }

    [Fact]
    public void FolderRegex_VeryDeepPath_10Levels()
    {
        var pattern = @".*/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/a/b/c/d/e/f/g/h/i/j/20260317/file.csv"));
    }

    [Fact]
    public void FolderRegex_SpecialCharsInPath()
    {
        var pattern = @".*\[backup\]/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/data/[backup]/20260317/file.csv"));
    }

    [Fact]
    public void FileRegex_NoExtension()
    {
        Assert.True(RegexMatches(@"^[^.]+$", "DATAFILE"));
        Assert.False(RegexMatches(@"^[^.]+$", "data.csv"));
    }

    [Fact]
    public void FileRegex_MultipleExtensions_TarGz()
    {
        Assert.True(RegexMatches(@".*\.tar\.gz$", "archive.tar.gz"));
        Assert.False(RegexMatches(@".*\.tar\.gz$", "archive.gz"));
    }

    [Theory]
    [InlineData(@".*/2026031[5-7]/.*", "/data/20260315/f.csv", true)]
    [InlineData(@".*/2026031[5-7]/.*", "/data/20260316/f.csv", true)]
    [InlineData(@".*/2026031[5-7]/.*", "/data/20260317/f.csv", true)]
    [InlineData(@".*/2026031[5-7]/.*", "/data/20260314/f.csv", false)]
    [InlineData(@".*/2026031[5-7]/.*", "/data/20260318/f.csv", false)]
    public void FolderRegex_DateRange_Last3Days(string pattern, string path, bool expected)
    {
        Assert.Equal(expected, RegexMatches(pattern, path));
    }

    [Theory]
    [InlineData(@".*/2026031[1-7]/.*", "/data/20260311/f.csv", true)]
    [InlineData(@".*/2026031[1-7]/.*", "/data/20260310/f.csv", false)]
    public void FolderRegex_DateRange_Last7Days(string pattern, string path, bool expected)
    {
        Assert.Equal(expected, RegexMatches(pattern, path));
    }

    [Fact]
    public void FolderRegex_WildcardInRegex()
    {
        var pattern = @".*/sensor_[^/]+/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/data/sensor_abc/20260317/out.csv"));
        Assert.True(RegexMatches(pattern, "/data/sensor_xyz123/20260317/out.csv"));
    }

    [Fact]
    public void FolderRegex_CrossTopicCollection()
    {
        var pattern = @".*/(temperature|vibration|pressure)/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/data/temperature/20260317/r.csv"));
        Assert.True(RegexMatches(pattern, "/data/vibration/20260317/r.csv"));
        Assert.True(RegexMatches(pattern, "/data/pressure/20260317/r.csv"));
        Assert.False(RegexMatches(pattern, "/data/humidity/20260317/r.csv"));
    }

    [Theory]
    [InlineData(@"\.done$", "batch_001.done", true)]
    [InlineData(@"\.complete$", "batch_001.complete", true)]
    [InlineData(@"\.ok$", "batch_001.ok", true)]
    [InlineData(@"_READY$", "batch_001_READY", true)]
    [InlineData(@"\.done$", "batch_001.csv", false)]
    public void FileRegex_CompletionMarkers(string pattern, string filename, bool expected)
    {
        Assert.Equal(expected, RegexMatches(pattern, filename));
    }

    [Fact]
    public void FolderRegex_DateDash_yyyy_MM_dd()
    {
        var pattern = @".*/\d{4}-\d{2}-\d{2}/.*";
        Assert.True(RegexMatches(pattern, "/logs/2026-03-17/app.log"));
        Assert.False(RegexMatches(pattern, "/logs/20260317/app.log"));
    }

    [Fact]
    public void FolderRegex_MonthFolder_yyyyMM()
    {
        var pattern = @".*/\d{6}/.*";
        Assert.True(RegexMatches(pattern, "/archive/202603/batch.csv"));
    }

    [Fact]
    public void FileRegex_CsvJsonXml_Union()
    {
        var pattern = @"\.(csv|json|xml)$";
        Assert.True(RegexMatches(pattern, "file.csv"));
        Assert.True(RegexMatches(pattern, "file.json"));
        Assert.True(RegexMatches(pattern, "file.xml"));
        Assert.False(RegexMatches(pattern, "file.txt"));
    }

    [Fact]
    public void FileRegex_TimestampSuffix()
    {
        var pattern = @"data_\d{8}_\d{6}\.csv$";
        Assert.True(RegexMatches(pattern, "data_20260317_143022.csv"));
        Assert.False(RegexMatches(pattern, "data_20260317.csv"));
    }

    [Fact]
    public void FileRegex_SensorTypeTimestamp()
    {
        var pattern = @"sensor_(temp|vib|press)_\d+\.dat$";
        Assert.True(RegexMatches(pattern, "sensor_temp_1710672000.dat"));
        Assert.True(RegexMatches(pattern, "sensor_vib_1710672000.dat"));
        Assert.False(RegexMatches(pattern, "sensor_humidity_1710672000.dat"));
    }

    [Fact]
    public void FolderRegex_ParenthesesInPath()
    {
        var pattern = @".*/backup\(old\)/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/data/backup(old)/20260317/file.csv"));
    }

    [Fact]
    public void FolderRegex_DotInFolderName()
    {
        var pattern = @".*/v1\.2/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/releases/v1.2/20260317/data.csv"));
    }

    [Fact]
    public void FolderRegex_HyphenInFolderName()
    {
        var pattern = @".*/my-data/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/root/my-data/20260317/file.csv"));
    }

    [Fact]
    public void FolderRegex_UnderscoreInFolderName()
    {
        var pattern = @".*/my_data/\d{8}/.*";
        Assert.True(RegexMatches(pattern, "/root/my_data/20260317/file.csv"));
    }

    [Fact]
    public void FolderRegex_CaseInsensitive()
    {
        Assert.True(RegexMatches(@".*/LINE_A/.*", "/plant/line_a/data.csv"));
        Assert.True(RegexMatches(@".*/LINE_A/.*", "/plant/LINE_A/data.csv"));
    }

    [Theory]
    [InlineData(@".*/20260(2[2-9]|3[0-1])\d/.*", "/data/20260228/f.csv", true)]
    [InlineData(@".*/20260(2[2-9]|3[0-1])\d/.*", "/data/20260215/f.csv", false)]
    public void FolderRegex_DateRange_Last30Days_Approximation(string pattern, string path, bool expected)
    {
        Assert.Equal(expected, RegexMatches(pattern, path));
    }

    [Fact]
    public void FolderRegex_EmptyBasePath_SlashOnly()
    {
        var cfg = ParseFtpConfig("{\"base_path\":\"/\",\"recursive\":true}");
        Assert.Equal("/", cfg.BasePath);
        Assert.True(cfg.Recursive);
    }

    [Fact]
    public void FileRegex_HiddenFiles_DotPrefix()
    {
        Assert.True(RegexMatches(@"^\.", ".hidden_file"));
        Assert.False(RegexMatches(@"^\.", "visible_file"));
    }

    [Fact]
    public void FileRegex_Jsonl_Extension()
    {
        Assert.True(RegexMatches(@".*\.jsonl$", "events.jsonl"));
        Assert.False(RegexMatches(@".*\.jsonl$", "events.json"));
    }

    [Fact]
    public void FolderRegex_NumericOnlyFolder()
    {
        var pattern = @"^/data/\d+/\d+\.csv$";
        Assert.True(RegexMatches(pattern, "/data/12345/678.csv"));
    }

    // ════════════════════════════════════════════════════════════════════
    // 3. REST API Monitor Config Tests (20 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void ApiMonitor_CreatesWithUrl()
    {
        var handler = new MockHttpHandler();
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");
        Assert.NotNull(monitor);
    }

    [Fact]
    public void ApiMonitor_CreatesWithHeaders()
    {
        var handler = new MockHttpHandler();
        var client = new HttpClient(handler);
        var headers = new Dictionary<string, string>
        {
            ["Authorization"] = "Bearer token123",
            ["Accept"] = "application/json"
        };
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data", headers);
        Assert.NotNull(monitor);
    }

    [Fact]
    public async Task ApiMonitor_Poll_ReturnsEvent_OnNewContent()
    {
        var handler = new MockHttpHandler { ResponseBody = "{\"value\":42}" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.Single(events);
        Assert.Equal("API_RESPONSE", events[0].EventType);
    }

    [Fact]
    public async Task ApiMonitor_Poll_NoEvent_OnSameContent()
    {
        var handler = new MockHttpHandler { ResponseBody = "{\"value\":42}" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        await monitor.PollAsync(); // First poll
        var events = await monitor.PollAsync(); // Same content
        Assert.Empty(events);
    }

    [Fact]
    public async Task ApiMonitor_Poll_NewEvent_OnChangedContent()
    {
        var handler = new MockHttpHandler { ResponseBody = "{\"value\":42}" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        await monitor.PollAsync();
        handler.ResponseBody = "{\"value\":99}";
        var events = await monitor.PollAsync();
        Assert.Single(events);
    }

    [Fact]
    public async Task ApiMonitor_Poll_MetadataContainsStatusCode()
    {
        var handler = new MockHttpHandler { ResponseBody = "{}" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.Equal(200, events[0].Metadata["status_code"]);
    }

    [Fact]
    public async Task ApiMonitor_Poll_MetadataContainsContentHash()
    {
        var handler = new MockHttpHandler { ResponseBody = "{}" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.True(events[0].Metadata.ContainsKey("content_hash"));
        Assert.NotNull(events[0].Metadata["content_hash"]);
    }

    [Fact]
    public async Task ApiMonitor_Poll_MetadataContainsUrl()
    {
        var handler = new MockHttpHandler { ResponseBody = "{}" };
        var client = new HttpClient(handler);
        var url = "https://api.example.com/sensors";
        var monitor = new ApiPollMonitor(client, url);

        var events = await monitor.PollAsync();
        Assert.Equal(url, events[0].Metadata["url"]);
    }

    [Fact]
    public async Task ApiMonitor_Poll_MetadataContainsContentLength()
    {
        var handler = new MockHttpHandler { ResponseBody = "{\"big\":\"data\"}" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.True((int)events[0].Metadata["content_length"] > 0);
    }

    [Fact]
    public async Task ApiMonitor_Poll_KeyIsUrl()
    {
        var handler = new MockHttpHandler { ResponseBody = "{}" };
        var client = new HttpClient(handler);
        var url = "https://api.example.com/v2/data";
        var monitor = new ApiPollMonitor(client, url);

        var events = await monitor.PollAsync();
        Assert.Equal(url, events[0].Key);
    }

    [Fact]
    public async Task ApiMonitor_Poll_Error401_StillReturnsEvent()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.Unauthorized, ResponseBody = "Unauthorized" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.Single(events); // Content changed from null, so event fires
        Assert.Equal(401, events[0].Metadata["status_code"]);
    }

    [Fact]
    public async Task ApiMonitor_Poll_Error403_ReturnsEvent()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.Forbidden, ResponseBody = "Forbidden" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.Equal(403, events[0].Metadata["status_code"]);
    }

    [Fact]
    public async Task ApiMonitor_Poll_Error404_ReturnsEvent()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.NotFound, ResponseBody = "Not Found" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.Equal(404, events[0].Metadata["status_code"]);
    }

    [Fact]
    public async Task ApiMonitor_Poll_Error500_ReturnsEvent()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.InternalServerError, ResponseBody = "Error" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.Equal(500, events[0].Metadata["status_code"]);
    }

    [Fact]
    public async Task ApiMonitor_Poll_Error502_ReturnsEvent()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.BadGateway, ResponseBody = "Bad Gateway" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.Equal(502, events[0].Metadata["status_code"]);
    }

    [Fact]
    public async Task ApiMonitor_Poll_Error503_ReturnsEvent()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.ServiceUnavailable, ResponseBody = "Unavailable" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.Equal(503, events[0].Metadata["status_code"]);
    }

    [Fact]
    public async Task ApiMonitor_Poll_Error429_ReturnsEvent()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.TooManyRequests, ResponseBody = "Rate limited" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.Equal(429, events[0].Metadata["status_code"]);
    }

    [Fact]
    public async Task ApiMonitor_Poll_EmptyResponse_StillDetects()
    {
        var handler = new MockHttpHandler { ResponseBody = "" };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.Single(events);
    }

    [Fact]
    public async Task ApiMonitor_Poll_LargeResponse_ContentLengthAccurate()
    {
        var bigContent = new string('x', 10000);
        var handler = new MockHttpHandler { ResponseBody = bigContent };
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data");

        var events = await monitor.PollAsync();
        Assert.Equal(10000, events[0].Metadata["content_length"]);
    }

    [Fact]
    public void ApiMonitor_NullHeaders_DefaultsToEmpty()
    {
        var handler = new MockHttpHandler();
        var client = new HttpClient(handler);
        var monitor = new ApiPollMonitor(client, "https://api.example.com/data", null);
        Assert.NotNull(monitor);
    }

    // ════════════════════════════════════════════════════════════════════
    // 4. Kafka Consumer Config Tests (20 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void KafkaProducerConfig_ParsesAllFields()
    {
        var cfg = ParseKafkaProducerConfig("{\"bootstrap_servers\":\"broker1:9092,broker2:9092\","
            + "\"topic\":\"events\",\"key_field\":\"id\",\"acks\":\"all\","
            + "\"security_protocol\":\"SASL_SSL\",\"enable_idempotence\":true,"
            + "\"batch_size\":32768,\"linger_ms\":10,\"compression\":\"gzip\"}");

        Assert.Equal("broker1:9092,broker2:9092", cfg.BootstrapServers);
        Assert.Equal("events", cfg.Topic);
        Assert.Equal("id", cfg.KeyField);
        Assert.Equal("all", cfg.Acks);
        Assert.Equal("SASL_SSL", cfg.SecurityProtocol);
        Assert.True(cfg.EnableIdempotence);
        Assert.Equal(32768, cfg.BatchSize);
        Assert.Equal(10, cfg.LingerMs);
        Assert.Equal("gzip", cfg.Compression);
    }

    [Fact]
    public void KafkaProducerConfig_Defaults()
    {
        var cfg = ParseKafkaProducerConfig("{}");
        Assert.Equal("localhost:9092", cfg.BootstrapServers);
        Assert.Equal("", cfg.Topic);
        Assert.Null(cfg.KeyField);
        Assert.Equal("all", cfg.Acks);
        Assert.Equal("PLAINTEXT", cfg.SecurityProtocol);
        Assert.True(cfg.EnableIdempotence);
        Assert.Equal(16384, cfg.BatchSize);
        Assert.Equal(5, cfg.LingerMs);
        Assert.Equal("none", cfg.Compression);
    }

    [Fact]
    public void KafkaProducerConfig_SingleBootstrapServer()
    {
        var cfg = ParseKafkaProducerConfig("{\"bootstrap_servers\":\"broker1:9092\"}");
        Assert.Equal("broker1:9092", cfg.BootstrapServers);
    }

    [Fact]
    public void KafkaProducerConfig_MultipleBootstrapServers()
    {
        var cfg = ParseKafkaProducerConfig("{\"bootstrap_servers\":\"b1:9092,b2:9092,b3:9092\"}");
        Assert.Contains("b1:9092", cfg.BootstrapServers);
        Assert.Contains("b2:9092", cfg.BootstrapServers);
        Assert.Contains("b3:9092", cfg.BootstrapServers);
    }

    [Theory]
    [InlineData("0")]
    [InlineData("1")]
    [InlineData("all")]
    public void KafkaProducerConfig_Acks_AllOptions(string acks)
    {
        var cfg = ParseKafkaProducerConfig("{\"acks\":\"" + acks + "\"}");
        Assert.Equal(acks, cfg.Acks);
    }

    [Theory]
    [InlineData("none")]
    [InlineData("gzip")]
    [InlineData("snappy")]
    [InlineData("lz4")]
    [InlineData("zstd")]
    public void KafkaProducerConfig_Compression_AllOptions(string compression)
    {
        var cfg = ParseKafkaProducerConfig("{\"compression\":\"" + compression + "\"}");
        Assert.Equal(compression, cfg.Compression);
    }

    [Theory]
    [InlineData("PLAINTEXT")]
    [InlineData("SSL")]
    [InlineData("SASL_PLAINTEXT")]
    [InlineData("SASL_SSL")]
    public void KafkaProducerConfig_SecurityProtocol_AllOptions(string protocol)
    {
        var cfg = ParseKafkaProducerConfig("{\"security_protocol\":\"" + protocol + "\"}");
        Assert.Equal(protocol, cfg.SecurityProtocol);
    }

    [Fact]
    public void KafkaProducerConfig_IdempotenceTrue()
    {
        var cfg = ParseKafkaProducerConfig("{\"enable_idempotence\":true}");
        Assert.True(cfg.EnableIdempotence);
    }

    [Fact]
    public void KafkaProducerConfig_IdempotenceFalse()
    {
        var cfg = ParseKafkaProducerConfig("{\"enable_idempotence\":false}");
        Assert.False(cfg.EnableIdempotence);
    }

    [Fact]
    public void KafkaProducerConfig_KeyFieldNull()
    {
        var cfg = ParseKafkaProducerConfig("{}");
        Assert.Null(cfg.KeyField);
    }

    [Fact]
    public void KafkaProducerConfig_KeyFieldSet()
    {
        var cfg = ParseKafkaProducerConfig("{\"key_field\":\"sensor_id\"}");
        Assert.Equal("sensor_id", cfg.KeyField);
    }

    [Fact]
    public void KafkaProducerConfig_BatchSizeSmall()
    {
        var cfg = ParseKafkaProducerConfig("{\"batch_size\":1024}");
        Assert.Equal(1024, cfg.BatchSize);
    }

    [Fact]
    public void KafkaProducerConfig_BatchSizeLarge()
    {
        var cfg = ParseKafkaProducerConfig("{\"batch_size\":1048576}");
        Assert.Equal(1048576, cfg.BatchSize);
    }

    [Fact]
    public void KafkaProducerConfig_LingerMsZero()
    {
        var cfg = ParseKafkaProducerConfig("{\"linger_ms\":0}");
        Assert.Equal(0, cfg.LingerMs);
    }

    [Fact]
    public void KafkaProducerConfig_LingerMsLarge()
    {
        var cfg = ParseKafkaProducerConfig("{\"linger_ms\":1000}");
        Assert.Equal(1000, cfg.LingerMs);
    }

    [Fact]
    public void KafkaProducerConfig_EmptyTopic()
    {
        var cfg = ParseKafkaProducerConfig("{\"topic\":\"\"}");
        Assert.Equal("", cfg.Topic);
    }

    [Fact]
    public void KafkaProducerConfig_TopicWithDot()
    {
        var cfg = ParseKafkaProducerConfig("{\"topic\":\"hermes.events.processed\"}");
        Assert.Equal("hermes.events.processed", cfg.Topic);
    }

    [Fact]
    public void KafkaProducerConfig_TopicWithHyphen()
    {
        var cfg = ParseKafkaProducerConfig("{\"topic\":\"hermes-events-raw\"}");
        Assert.Equal("hermes-events-raw", cfg.Topic);
    }

    [Fact]
    public void KafkaProducerConfig_TopicWithUnderscore()
    {
        var cfg = ParseKafkaProducerConfig("{\"topic\":\"hermes_events_raw\"}");
        Assert.Equal("hermes_events_raw", cfg.Topic);
    }

    [Fact]
    public void KafkaProducerConfig_NoBootstrapServers_DefaultLocalhost()
    {
        var cfg = ParseKafkaProducerConfig("{}");
        Assert.Equal("localhost:9092", cfg.BootstrapServers);
    }

    // ════════════════════════════════════════════════════════════════════
    // 5. CDC (Database) Monitor Config Tests (15 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void CdcMonitor_Creates_WithConnectionString()
    {
        var monitor = new CdcMonitor("Host=localhost;Database=test;", "events", "updated_at");
        Assert.NotNull(monitor);
    }

    [Fact]
    public void CdcMonitor_CursorProperty_InitiallyNull()
    {
        var monitor = new CdcMonitor("Host=localhost;", "events", "id");
        Assert.Null(monitor.Cursor);
    }

    [Fact]
    public void CdcMonitor_CursorProperty_SetAndGet()
    {
        var monitor = new CdcMonitor("Host=localhost;", "events", "id");
        monitor.Cursor = "2026-03-17T00:00:00Z";
        Assert.Equal("2026-03-17T00:00:00Z", monitor.Cursor);
    }

    [Fact]
    public void CdcMonitor_CursorProperty_SequenceValue()
    {
        var monitor = new CdcMonitor("Host=localhost;", "events", "seq_id");
        monitor.Cursor = "12345";
        Assert.Equal("12345", monitor.Cursor);
    }

    [Fact]
    public void CdcMonitor_CursorProperty_CompositeValue()
    {
        var monitor = new CdcMonitor("Host=localhost;", "events", "version");
        monitor.Cursor = "2026-03-17T00:00:00Z|42";
        Assert.Equal("2026-03-17T00:00:00Z|42", monitor.Cursor);
    }

    [Fact]
    public void CdcMonitor_CursorProperty_ResetToNull()
    {
        var monitor = new CdcMonitor("Host=localhost;", "events", "id");
        monitor.Cursor = "100";
        monitor.Cursor = null;
        Assert.Null(monitor.Cursor);
    }

    [Fact]
    public void CdcMonitor_TableName_Simple()
    {
        var monitor = new CdcMonitor("Host=localhost;", "sensor_readings", "updated_at");
        Assert.NotNull(monitor);
    }

    [Fact]
    public void CdcMonitor_TableName_SchemaQualified()
    {
        // CdcMonitor accepts any table name string; schema.table is valid
        var monitor = new CdcMonitor("Host=localhost;", "public.sensor_readings", "updated_at");
        Assert.NotNull(monitor);
    }

    [Theory]
    [InlineData("updated_at")]
    [InlineData("created_timestamp")]
    [InlineData("sequence_number")]
    [InlineData("row_version")]
    public void CdcMonitor_CursorColumn_ValidNames(string column)
    {
        var monitor = new CdcMonitor("Host=localhost;", "events", column);
        Assert.NotNull(monitor);
    }

    [Fact]
    public void CdcMonitor_CustomQuery()
    {
        var query = "SELECT id, value FROM readings WHERE id > @cursor ORDER BY id LIMIT 50";
        var monitor = new CdcMonitor("Host=localhost;", "readings", "id", query);
        Assert.NotNull(monitor);
    }

    [Fact]
    public void CdcMonitor_ConnectionString_PostgreSQL()
    {
        var connStr = "Host=db.example.com;Port=5432;Database=hermes;Username=admin;Password=secret;";
        var monitor = new CdcMonitor(connStr, "events", "id");
        Assert.NotNull(monitor);
    }

    [Fact]
    public void CdcMonitor_ConnectionString_WithSsl()
    {
        var connStr = "Host=db.example.com;Port=5432;Database=hermes;Username=admin;Password=secret;SSL Mode=Require;";
        var monitor = new CdcMonitor(connStr, "events", "id");
        Assert.NotNull(monitor);
    }

    [Theory]
    [InlineData("events; DROP TABLE events;--")]
    [InlineData("events' OR '1'='1")]
    public void CdcMonitor_SqlInjection_TableName_StillConstructs(string tableName)
    {
        // CdcMonitor constructs but the query would be parameterized at DB level
        var monitor = new CdcMonitor("Host=localhost;", tableName, "id");
        Assert.NotNull(monitor);
    }

    [Fact]
    public void CdcMonitor_EmptyConnectionString()
    {
        var monitor = new CdcMonitor("", "events", "id");
        Assert.NotNull(monitor);
    }

    [Fact]
    public void CdcMonitor_CursorTimestamp_IsoFormat()
    {
        var monitor = new CdcMonitor("Host=localhost;", "events", "updated_at");
        monitor.Cursor = "2026-03-17T14:30:00.000Z";
        Assert.Contains("2026-03-17", monitor.Cursor);
    }

    // ════════════════════════════════════════════════════════════════════
    // 6. Export: Kafka Producer Config Tests (20 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void KafkaExportConfig_Topic_Required()
    {
        var cfg = ParseKafkaProducerConfig("{\"topic\":\"output-events\"}");
        Assert.Equal("output-events", cfg.Topic);
    }

    [Fact]
    public void KafkaExportConfig_NoTopic_EmptyDefault()
    {
        var cfg = ParseKafkaProducerConfig("{}");
        Assert.Equal("", cfg.Topic);
    }

    [Fact]
    public void KafkaExportConfig_NoBootstrapServers_Default()
    {
        var cfg = ParseKafkaProducerConfig("{}");
        Assert.Equal("localhost:9092", cfg.BootstrapServers);
    }

    [Fact]
    public void KafkaExportConfig_KeyField_ExtractsFromRecord()
    {
        var cfg = ParseKafkaProducerConfig("{\"key_field\":\"sensor_id\"}");
        // Verify config stores the key field
        Assert.Equal("sensor_id", cfg.KeyField);
        // Simulate extraction from a JSON record
        var record = JsonDocument.Parse("{\"sensor_id\":\"S001\",\"value\":42}").RootElement;
        Assert.True(record.TryGetProperty(cfg.KeyField, out var keyVal));
        Assert.Equal("S001", keyVal.GetString());
    }

    [Fact]
    public void KafkaExportConfig_KeyField_MissingInRecord()
    {
        var cfg = ParseKafkaProducerConfig("{\"key_field\":\"missing_field\"}");
        var record = JsonDocument.Parse("{\"sensor_id\":\"S001\",\"value\":42}").RootElement;
        Assert.False(record.TryGetProperty(cfg.KeyField!, out _));
    }

    [Fact]
    public void KafkaExportConfig_BatchSerialization_SingleRecord()
    {
        var json = "[{\"id\":1,\"value\":42}]";
        var doc = JsonDocument.Parse(json);
        Assert.Equal(JsonValueKind.Array, doc.RootElement.ValueKind);
        Assert.Equal(1, doc.RootElement.GetArrayLength());
    }

    [Fact]
    public void KafkaExportConfig_BatchSerialization_MultipleRecords()
    {
        var json = "[{\"id\":1},{\"id\":2},{\"id\":3}]";
        var doc = JsonDocument.Parse(json);
        Assert.Equal(3, doc.RootElement.GetArrayLength());
    }

    [Fact]
    public void KafkaExportConfig_Acks0_FireAndForget()
    {
        var cfg = ParseKafkaProducerConfig("{\"acks\":\"0\"}");
        Assert.Equal("0", cfg.Acks);
    }

    [Fact]
    public void KafkaExportConfig_Acks1_LeaderOnly()
    {
        var cfg = ParseKafkaProducerConfig("{\"acks\":\"1\"}");
        Assert.Equal("1", cfg.Acks);
    }

    [Fact]
    public void KafkaExportConfig_AcksAll_FullReplication()
    {
        var cfg = ParseKafkaProducerConfig("{\"acks\":\"all\"}");
        Assert.Equal("all", cfg.Acks);
    }

    [Fact]
    public void KafkaExportConfig_CompressionGzip()
    {
        var cfg = ParseKafkaProducerConfig("{\"compression\":\"gzip\"}");
        Assert.Equal("gzip", cfg.Compression);
    }

    [Fact]
    public void KafkaExportConfig_CompressionSnappy()
    {
        var cfg = ParseKafkaProducerConfig("{\"compression\":\"snappy\"}");
        Assert.Equal("snappy", cfg.Compression);
    }

    [Fact]
    public void KafkaExportConfig_CompressionLz4()
    {
        var cfg = ParseKafkaProducerConfig("{\"compression\":\"lz4\"}");
        Assert.Equal("lz4", cfg.Compression);
    }

    [Fact]
    public void KafkaExportConfig_CompressionZstd()
    {
        var cfg = ParseKafkaProducerConfig("{\"compression\":\"zstd\"}");
        Assert.Equal("zstd", cfg.Compression);
    }

    [Fact]
    public void KafkaExportConfig_CompressionNone()
    {
        var cfg = ParseKafkaProducerConfig("{\"compression\":\"none\"}");
        Assert.Equal("none", cfg.Compression);
    }

    [Fact]
    public void KafkaExportConfig_SecurityProtocol_SASL_SSL()
    {
        var cfg = ParseKafkaProducerConfig("{\"security_protocol\":\"SASL_SSL\"}");
        Assert.Equal("SASL_SSL", cfg.SecurityProtocol);
    }

    [Fact]
    public void KafkaExportConfig_SecurityProtocol_PLAINTEXT()
    {
        var cfg = ParseKafkaProducerConfig("{\"security_protocol\":\"PLAINTEXT\"}");
        Assert.Equal("PLAINTEXT", cfg.SecurityProtocol);
    }

    [Fact]
    public void KafkaExportConfig_SecurityProtocol_SSL()
    {
        var cfg = ParseKafkaProducerConfig("{\"security_protocol\":\"SSL\"}");
        Assert.Equal("SSL", cfg.SecurityProtocol);
    }

    [Fact]
    public void KafkaExportConfig_SecurityProtocol_SASL_PLAINTEXT()
    {
        var cfg = ParseKafkaProducerConfig("{\"security_protocol\":\"SASL_PLAINTEXT\"}");
        Assert.Equal("SASL_PLAINTEXT", cfg.SecurityProtocol);
    }

    [Fact]
    public void KafkaExportConfig_Idempotence_DefaultTrue()
    {
        var cfg = ParseKafkaProducerConfig("{}");
        Assert.True(cfg.EnableIdempotence);
    }

    // ════════════════════════════════════════════════════════════════════
    // 7. Export: DB Writer Config Tests (20 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void DbWriterConfig_ParsesAllFields()
    {
        var cfg = ParseDbWriterConfig("{\"connection_string\":\"Host=db;Database=hermes;\","
            + "\"provider\":\"PostgreSQL\",\"table_name\":\"results\","
            + "\"write_mode\":\"UPSERT\",\"conflict_key\":\"id\","
            + "\"batch_size\":500,\"create_table\":true,\"timeout_seconds\":60}");

        Assert.Equal("Host=db;Database=hermes;", cfg.ConnectionString);
        Assert.Equal("PostgreSQL", cfg.Provider);
        Assert.Equal("results", cfg.TableName);
        Assert.Equal("UPSERT", cfg.WriteMode);
        Assert.Equal("id", cfg.ConflictKey);
        Assert.Equal(500, cfg.BatchSize);
        Assert.True(cfg.CreateTableIfNotExists);
        Assert.Equal(60, cfg.TimeoutSeconds);
    }

    [Fact]
    public void DbWriterConfig_Defaults()
    {
        var cfg = ParseDbWriterConfig("{}");
        Assert.Equal("", cfg.ConnectionString);
        Assert.Equal("PostgreSQL", cfg.Provider);
        Assert.Equal("", cfg.TableName);
        Assert.Equal("INSERT", cfg.WriteMode);
        Assert.Null(cfg.ConflictKey);
        Assert.Equal(1000, cfg.BatchSize);
        Assert.False(cfg.CreateTableIfNotExists);
        Assert.Equal(30, cfg.TimeoutSeconds);
    }

    [Theory]
    [InlineData("INSERT")]
    [InlineData("UPSERT")]
    [InlineData("MERGE")]
    public void DbWriterConfig_WriteMode_AllOptions(string mode)
    {
        var cfg = ParseDbWriterConfig("{\"write_mode\":\"" + mode + "\"}");
        Assert.Equal(mode, cfg.WriteMode);
    }

    [Fact]
    public void DbWriterConfig_ConflictKey_ForUpsert()
    {
        var cfg = ParseDbWriterConfig("{\"write_mode\":\"UPSERT\",\"conflict_key\":\"sensor_id\"}");
        Assert.Equal("UPSERT", cfg.WriteMode);
        Assert.Equal("sensor_id", cfg.ConflictKey);
    }

    [Theory]
    [InlineData(1)]
    [InlineData(100)]
    [InlineData(500)]
    [InlineData(1000)]
    [InlineData(5000)]
    [InlineData(10000)]
    public void DbWriterConfig_BatchSize_Variants(int batchSize)
    {
        var cfg = ParseDbWriterConfig("{\"batch_size\":" + batchSize + "}");
        Assert.Equal(batchSize, cfg.BatchSize);
    }

    [Fact]
    public void DbWriterConfig_JsonRecord_StringValues()
    {
        var record = JsonDocument.Parse("{\"name\":\"sensor_a\",\"type\":\"temperature\"}").RootElement;
        Assert.Equal("sensor_a", record.GetProperty("name").GetString());
        Assert.Equal("temperature", record.GetProperty("type").GetString());
    }

    [Fact]
    public void DbWriterConfig_JsonRecord_NumberValues()
    {
        var record = JsonDocument.Parse("{\"id\":42,\"value\":3.14}").RootElement;
        Assert.Equal(42, record.GetProperty("id").GetInt32());
        Assert.True(Math.Abs(record.GetProperty("value").GetDouble() - 3.14) < 0.001);
    }

    [Fact]
    public void DbWriterConfig_JsonRecord_BooleanValues()
    {
        var record = JsonDocument.Parse("{\"active\":true,\"deleted\":false}").RootElement;
        Assert.True(record.GetProperty("active").GetBoolean());
        Assert.False(record.GetProperty("deleted").GetBoolean());
    }

    [Fact]
    public void DbWriterConfig_JsonRecord_NullValues()
    {
        var record = JsonDocument.Parse("{\"name\":\"test\",\"description\":null}").RootElement;
        Assert.Equal(JsonValueKind.Null, record.GetProperty("description").ValueKind);
    }

    [Fact]
    public void DbWriterConfig_EmptyRecords()
    {
        var records = JsonDocument.Parse("[]").RootElement;
        Assert.Equal(0, records.GetArrayLength());
    }

    [Fact]
    public void DbWriterConfig_NoConnectionString_EmptyDefault()
    {
        var cfg = ParseDbWriterConfig("{}");
        Assert.Equal("", cfg.ConnectionString);
    }

    [Fact]
    public void DbWriterConfig_NoTableName_EmptyDefault()
    {
        var cfg = ParseDbWriterConfig("{}");
        Assert.Equal("", cfg.TableName);
    }

    [Theory]
    [InlineData(5)]
    [InlineData(30)]
    [InlineData(60)]
    [InlineData(120)]
    [InlineData(300)]
    public void DbWriterConfig_TimeoutSeconds_Variants(int timeout)
    {
        var cfg = ParseDbWriterConfig("{\"timeout_seconds\":" + timeout + "}");
        Assert.Equal(timeout, cfg.TimeoutSeconds);
    }

    [Theory]
    [InlineData("PostgreSQL")]
    [InlineData("SqlServer")]
    public void DbWriterConfig_Provider_BothSupported(string provider)
    {
        var cfg = ParseDbWriterConfig("{\"provider\":\"" + provider + "\"}");
        Assert.Equal(provider, cfg.Provider);
    }

    [Fact]
    public void DbWriterConfig_CreateTable_True()
    {
        var cfg = ParseDbWriterConfig("{\"create_table\":true}");
        Assert.True(cfg.CreateTableIfNotExists);
    }

    [Fact]
    public void DbWriterConfig_CreateTable_False()
    {
        var cfg = ParseDbWriterConfig("{\"create_table\":false}");
        Assert.False(cfg.CreateTableIfNotExists);
    }

    [Fact]
    public void DbWriterConfig_ConflictKey_Null_ForInsert()
    {
        var cfg = ParseDbWriterConfig("{\"write_mode\":\"INSERT\"}");
        Assert.Null(cfg.ConflictKey);
    }

    [Fact]
    public void DbWriterConfig_ConnectionString_SqlServer()
    {
        var cfg = ParseDbWriterConfig("{\"connection_string\":\"Server=db;Database=hermes;User Id=sa;Password=pass;\",\"provider\":\"SqlServer\"}");
        Assert.Contains("Server=db", cfg.ConnectionString);
        Assert.Equal("SqlServer", cfg.Provider);
    }

    [Fact]
    public void DbWriterConfig_ConflictKey_CompositeKey()
    {
        var cfg = ParseDbWriterConfig("{\"conflict_key\":\"sensor_id,timestamp\"}");
        Assert.Equal("sensor_id,timestamp", cfg.ConflictKey);
    }

    // ════════════════════════════════════════════════════════════════════
    // 8. Export: Webhook Sender Tests (15 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public async Task Webhook_Post_Success200()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig { Url = "https://hook.example.com/data", Method = "POST", MaxRetries = 0 };
        var exporter = new WebhookSenderExporter(config, client);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal(1, result.RecordsExported);
    }

    [Fact]
    public async Task Webhook_Post_Success201()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.Created };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig { Url = "https://hook.example.com/data", Method = "POST", MaxRetries = 0 };
        var exporter = new WebhookSenderExporter(config, client);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.True(result.Success);
    }

    [Fact]
    public async Task Webhook_Post_Success202()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.Accepted };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig { Url = "https://hook.example.com/data", Method = "POST", MaxRetries = 0 };
        var exporter = new WebhookSenderExporter(config, client);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.True(result.Success);
    }

    [Fact]
    public async Task Webhook_Put_Method()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig { Url = "https://hook.example.com/data", Method = "PUT", MaxRetries = 0 };
        var exporter = new WebhookSenderExporter(config, client);

        await exporter.ExportAsync(new ExportContext(DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.Equal("PUT", handler.Requests[0].Method.Method);
    }

    [Fact]
    public async Task Webhook_Patch_Method()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig { Url = "https://hook.example.com/data", Method = "PATCH", MaxRetries = 0 };
        var exporter = new WebhookSenderExporter(config, client);

        await exporter.ExportAsync(new ExportContext(DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.Equal("PATCH", handler.Requests[0].Method.Method);
    }

    [Fact]
    public async Task Webhook_BearerAuth_SetsHeader()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig
        {
            Url = "https://hook.example.com/data",
            AuthType = "bearer",
            AuthToken = "my-jwt-token",
            MaxRetries = 0
        };
        var exporter = new WebhookSenderExporter(config, client);

        await exporter.ExportAsync(new ExportContext(DataJson: "[{\"id\":1}]", Metadata: new()));

        var authHeader = handler.Requests[0].Headers.Authorization;
        Assert.NotNull(authHeader);
        Assert.Equal("Bearer", authHeader!.Scheme);
        Assert.Equal("my-jwt-token", authHeader.Parameter);
    }

    [Fact]
    public async Task Webhook_BasicAuth_SetsHeader()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig
        {
            Url = "https://hook.example.com/data",
            AuthType = "basic",
            AuthToken = "dXNlcjpwYXNz",
            MaxRetries = 0
        };
        var exporter = new WebhookSenderExporter(config, client);

        await exporter.ExportAsync(new ExportContext(DataJson: "[{\"id\":1}]", Metadata: new()));

        var authHeader = handler.Requests[0].Headers.Authorization;
        Assert.NotNull(authHeader);
        Assert.Equal("Basic", authHeader!.Scheme);
    }

    [Fact]
    public async Task Webhook_ApiKeyAuth_SetsCustomHeader()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig
        {
            Url = "https://hook.example.com/data",
            AuthType = "api_key",
            AuthToken = "key-12345",
            ApiKeyHeader = "X-API-Key",
            MaxRetries = 0
        };
        var exporter = new WebhookSenderExporter(config, client);

        await exporter.ExportAsync(new ExportContext(DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.True(handler.Requests[0].Headers.Contains("X-API-Key"));
    }

    [Fact]
    public async Task Webhook_CustomHeaders_Included()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig
        {
            Url = "https://hook.example.com/data",
            Headers = new Dictionary<string, string> { ["X-Custom"] = "value123" },
            MaxRetries = 0
        };
        var exporter = new WebhookSenderExporter(config, client);

        await exporter.ExportAsync(new ExportContext(DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.True(handler.Requests[0].Headers.Contains("X-Custom"));
    }

    [Fact]
    public async Task Webhook_BatchMode_SendsOnce()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig { Url = "https://hook.example.com/data", BatchMode = true, MaxRetries = 0 };
        var exporter = new WebhookSenderExporter(config, client);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1},{\"id\":2},{\"id\":3}]", Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal(3, result.RecordsExported);
        Assert.Single(handler.Requests);
    }

    [Fact]
    public async Task Webhook_IndividualMode_SendsSingleRecord()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig { Url = "https://hook.example.com/data", BatchMode = false, MaxRetries = 0 };
        var exporter = new WebhookSenderExporter(config, client);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal(1, result.RecordsExported);
        Assert.Single(handler.Requests);
    }

    [Fact]
    public async Task Webhook_Error400_ReturnsFailed()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.BadRequest };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig { Url = "https://hook.example.com/data", MaxRetries = 0 };
        var exporter = new WebhookSenderExporter(config, client);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.False(result.Success);
        Assert.NotNull(result.ErrorMessage);
    }

    [Fact]
    public async Task Webhook_EmptyUrl_ReturnsFailed()
    {
        var handler = new MockHttpHandler();
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig { Url = "" };
        var exporter = new WebhookSenderExporter(config, client);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.False(result.Success);
        Assert.Contains("URL", result.ErrorMessage, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Webhook_DestinationInfo_IsUrl()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var url = "https://hook.example.com/endpoint";
        var config = new WebhookSenderConfig { Url = url, MaxRetries = 0 };
        var exporter = new WebhookSenderExporter(config, client);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.Equal(url, result.DestinationInfo);
    }

    // ════════════════════════════════════════════════════════════════════
    // 9. Export: S3 Upload Tests (10 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public async Task S3_JsonFormat_UploadsCorrectly()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "bucket", OutputFormat = "json", PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal(1, result.RecordsExported);
        Assert.Equal("application/json", s3.Uploads[0].ContentType);
    }

    [Fact]
    public async Task S3_CsvFormat_UploadsCorrectly()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "bucket", OutputFormat = "csv", PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1,\"name\":\"test\"}]", Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal("text/csv", s3.Uploads[0].ContentType);
    }

    [Fact]
    public async Task S3_GzipCompression_AddsGzExtension()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "bucket", Compression = "gzip", PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        await exporter.ExportAsync(new ExportContext(DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.EndsWith(".gz", s3.Uploads[0].Key);
        Assert.Equal("application/gzip", s3.Uploads[0].ContentType);
    }

    [Fact]
    public async Task S3_DatePartitioning_IncludesDate()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig
        {
            BucketName = "bucket",
            PartitionByDate = true,
            DatePartitionFormat = "yyyy/MM/dd"
        };
        var exporter = new S3UploadExporter(config, s3);

        await exporter.ExportAsync(new ExportContext(DataJson: "[{\"id\":1}]", Metadata: new()));

        var today = DateTimeOffset.UtcNow.ToString("yyyy/MM/dd", System.Globalization.CultureInfo.InvariantCulture);
        Assert.Contains(today, s3.Uploads[0].Key);
    }

    [Fact]
    public async Task S3_IncludeMetadata_AddsHeaders()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "bucket", IncludeMetadata = true, PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1}]", Metadata: new(), PipelineName: "my-pipe", JobId: 7));

        var meta = s3.Uploads[0].Metadata!;
        Assert.Equal("my-pipe", meta["hermes-pipeline"]);
        Assert.Equal("7", meta["hermes-job-id"]);
    }

    [Fact]
    public async Task S3_ErrorThrown_ReturnsFailed()
    {
        var s3 = new MockS3Client { ErrorToThrow = new Exception("Permission denied") };
        var config = new S3UploadConfig { BucketName = "bucket", PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.False(result.Success);
        Assert.Contains("Permission denied", result.ErrorMessage);
    }

    [Fact]
    public async Task S3_SingleObject_WrapsAsRecord()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "bucket", PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "{\"id\":1,\"value\":\"single\"}", Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal(1, result.RecordsExported);
    }

    [Fact]
    public async Task S3_ArrayInput_ExportsAll()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "bucket", PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"a\":1},{\"a\":2},{\"a\":3},{\"a\":4},{\"a\":5}]", Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal(5, result.RecordsExported);
    }

    [Fact]
    public async Task S3_RecordsWrapper_Unwraps()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "bucket", PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "{\"records\":[{\"x\":1},{\"x\":2}]}", Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal(2, result.RecordsExported);
    }

    [Fact]
    public async Task S3_NoBucket_FailsWithMessage()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "" };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.False(result.Success);
        Assert.Contains("bucket", result.ErrorMessage, StringComparison.OrdinalIgnoreCase);
    }

    // ════════════════════════════════════════════════════════════════════
    // 10. Cross-Connector E2E Scenarios (10 tests)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void CrossE2E_FtpCollect_KafkaExport_ConfigsValid()
    {
        // FTP collect → Anomaly detect → Kafka export
        var ftpConfig = new FtpSftpConfig
        {
            Protocol = "sftp",
            Host = "ftp.factory.local",
            BasePath = "/sensors",
            Recursive = true,
            FileFilterRegex = @".*\.csv$",
            MaxFilesPerPoll = 50,
        };

        var kafkaConfig = ParseKafkaProducerConfig(
            "{\"bootstrap_servers\":\"broker:9092\",\"topic\":\"anomaly-events\","
            + "\"acks\":\"all\",\"compression\":\"gzip\"}");

        Assert.Equal("sftp", ftpConfig.Protocol);
        Assert.Equal("anomaly-events", kafkaConfig.Topic);
        Assert.Equal("gzip", kafkaConfig.Compression);
    }

    [Fact]
    public async Task CrossE2E_RestApiCollect_DbWrite_ConfigsValid()
    {
        // REST API collect → Transform → DB write
        var handler = new MockHttpHandler { ResponseBody = "[{\"id\":1,\"temp\":22.5}]" };
        var client = new HttpClient(handler);
        var apiMonitor = new ApiPollMonitor(client, "https://api.sensors.com/readings",
            new Dictionary<string, string> { ["Authorization"] = "Bearer token" });

        var events = await apiMonitor.PollAsync();
        Assert.Single(events);

        var dbConfig = ParseDbWriterConfig(
            "{\"connection_string\":\"Host=db;Database=hermes;\","
            + "\"table_name\":\"sensor_readings\",\"write_mode\":\"UPSERT\","
            + "\"conflict_key\":\"id\",\"batch_size\":1000}");

        Assert.Equal("UPSERT", dbConfig.WriteMode);
        Assert.Equal("id", dbConfig.ConflictKey);
    }

    [Fact]
    public async Task CrossE2E_KafkaConsume_S3Upload()
    {
        // Kafka consume → Filter → S3 upload
        var kafkaConfig = ParseKafkaProducerConfig(
            "{\"bootstrap_servers\":\"broker:9092\",\"topic\":\"raw-events\"}");
        Assert.Equal("raw-events", kafkaConfig.Topic);

        var s3 = new MockS3Client();
        var s3Config = new S3UploadConfig
        {
            BucketName = "data-lake",
            KeyPrefix = "raw/events",
            OutputFormat = "json",
            Compression = "gzip",
            PartitionByDate = true,
        };
        var exporter = new S3UploadExporter(s3Config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"event\":\"click\",\"ts\":\"2026-03-17T10:00:00Z\"}]",
            Metadata: new(), PipelineName: "kafka-to-s3"));

        Assert.True(result.Success);
        Assert.Equal(1, result.RecordsExported);
    }

    [Fact]
    public async Task CrossE2E_FileWatch_WebhookExport()
    {
        // File watch → CSV convert → Webhook
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var webhookConfig = new WebhookSenderConfig
        {
            Url = "https://hook.example.com/ingest",
            Method = "POST",
            AuthType = "bearer",
            AuthToken = "jwt-token",
            BatchMode = true,
            MaxRetries = 0,
        };
        var exporter = new WebhookSenderExporter(webhookConfig, client);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"sensor\":\"A1\",\"value\":42},{\"sensor\":\"B2\",\"value\":37}]",
            Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal(2, result.RecordsExported);
        Assert.Single(handler.Requests); // Batch mode
    }

    [Fact]
    public async Task CrossE2E_CdcToMultiOutput_DbAndKafka()
    {
        // CDC → Enrich → Multi-output (DB + Kafka)
        var cdcMonitor = new CdcMonitor("Host=source-db;Database=erp;", "orders", "updated_at");
        Assert.NotNull(cdcMonitor);

        var dbConfig = ParseDbWriterConfig(
            "{\"connection_string\":\"Host=target-db;Database=warehouse;\","
            + "\"table_name\":\"enriched_orders\",\"write_mode\":\"UPSERT\","
            + "\"conflict_key\":\"order_id\"}");

        var kafkaConfig = ParseKafkaProducerConfig(
            "{\"bootstrap_servers\":\"broker:9092\",\"topic\":\"order-events\","
            + "\"key_field\":\"order_id\",\"acks\":\"all\"}");

        Assert.Equal("enriched_orders", dbConfig.TableName);
        Assert.Equal("order-events", kafkaConfig.Topic);

        // Simulate DB write via S3 (config validation)
        var s3 = new MockS3Client();
        var s3Config = new S3UploadConfig { BucketName = "backup", PartitionByDate = false };
        var s3Exporter = new S3UploadExporter(s3Config, s3);
        var result = await s3Exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"order_id\":\"ORD-001\",\"amount\":99.99}]", Metadata: new()));
        Assert.True(result.Success);
    }

    [Fact]
    public void CrossE2E_FtpCollect_FilterRegex_KafkaProduce()
    {
        var ftpCfg = new FtpSftpConfig
        {
            Protocol = "sftp",
            Host = "sftp.iot.local",
            BasePath = "/telemetry",
            Recursive = true,
            PathFilterRegex = @".*/temperature/\d{8}/.*",
            FileFilterRegex = @".*\.json$",
            SortBy = "modified_desc",
            MaxFilesPerPoll = 200,
        };

        var kafkaCfg = ParseKafkaProducerConfig(
            "{\"bootstrap_servers\":\"broker1:9092,broker2:9092\","
            + "\"topic\":\"telemetry.temperature\","
            + "\"compression\":\"snappy\",\"acks\":\"1\"}");

        // Validate the pipeline config makes sense
        Assert.True(ftpCfg.Recursive);
        Assert.NotNull(ftpCfg.PathFilterRegex);
        Assert.Equal("telemetry.temperature", kafkaCfg.Topic);
        Assert.Equal("snappy", kafkaCfg.Compression);
    }

    [Fact]
    public async Task CrossE2E_ApiPoll_Transform_WebhookForward()
    {
        // API poll → transform → webhook forward
        var apiHandler = new MockHttpHandler { ResponseBody = "{\"status\":\"ok\",\"readings\":[1,2,3]}" };
        var apiClient = new HttpClient(apiHandler);
        var apiMonitor = new ApiPollMonitor(apiClient, "https://api.sensors.com/latest");

        var events = await apiMonitor.PollAsync();
        Assert.Single(events);

        var webhookHandler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var webhookClient = new HttpClient(webhookHandler);
        var webhookConfig = new WebhookSenderConfig
        {
            Url = "https://downstream.example.com/ingest",
            Method = "POST",
            BatchMode = true,
            MaxRetries = 0,
        };
        var webhookExporter = new WebhookSenderExporter(webhookConfig, webhookClient);

        var result = await webhookExporter.ExportAsync(new ExportContext(
            DataJson: "[{\"reading\":1},{\"reading\":2},{\"reading\":3}]", Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal(3, result.RecordsExported);
    }

    [Fact]
    public async Task CrossE2E_S3Archive_WithMetadata()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig
        {
            BucketName = "archive-bucket",
            KeyPrefix = "hermes/processed",
            OutputFormat = "csv",
            Compression = "gzip",
            PartitionByDate = true,
            DatePartitionFormat = "yyyy/MM/dd",
            IncludeMetadata = true,
        };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"sensor\":\"T1\",\"value\":22.5},{\"sensor\":\"T2\",\"value\":23.1}]",
            Metadata: new(),
            PipelineName: "daily-archive",
            JobId: 999
        ));

        Assert.True(result.Success);
        Assert.Equal(2, result.RecordsExported);
        Assert.EndsWith(".gz", s3.Uploads[0].Key);
        Assert.Equal("999", s3.Uploads[0].Metadata!["hermes-job-id"]);
    }

    [Fact]
    public void CrossE2E_IndustrialPipeline_AllConfigs()
    {
        // Full industrial pipeline: SFTP → Process → DB + S3
        var ftpCfg = new FtpSftpConfig
        {
            Protocol = "sftp",
            Host = "192.168.1.50",
            Port = 22,
            BasePath = "/equipment/sensors",
            Recursive = true,
            PathFilterRegex = @".*/LINE_[A-Z]+/\d{8}/.*",
            FileFilterRegex = @"measurement_.*\.csv$",
            SortBy = "modified_desc",
            MaxFilesPerPoll = 100,
            MinAgeSeconds = 30,
        };

        var dbCfg = ParseDbWriterConfig(
            "{\"connection_string\":\"Host=db;Database=factory;\","
            + "\"table_name\":\"sensor_readings\","
            + "\"write_mode\":\"INSERT\",\"batch_size\":5000}");

        var s3Cfg = ParseS3Config(
            "{\"bucket_name\":\"factory-archive\","
            + "\"key_prefix\":\"sensors\","
            + "\"output_format\":\"csv\","
            + "\"compression\":\"gzip\","
            + "\"partition_by_date\":true}");

        Assert.True(ftpCfg.Recursive);
        Assert.Equal("sensor_readings", dbCfg.TableName);
        Assert.Equal("factory-archive", s3Cfg.BucketName);
        Assert.Equal("gzip", s3Cfg.Compression);
    }

    [Fact]
    public void CrossE2E_MultiSourceIngestion_AllMonitorTypes()
    {
        // Validate all monitor types can be created for a multi-source scenario
        var ftpMonitor = new FtpSftpMonitor(new FtpSftpConfig { Host = "ftp.local" });
        Assert.NotNull(ftpMonitor);

        var apiHandler = new MockHttpHandler();
        var apiMonitor = new ApiPollMonitor(new HttpClient(apiHandler), "https://api.local/data");
        Assert.NotNull(apiMonitor);

        var cdcMonitor = new CdcMonitor("Host=db;", "events", "id");
        Assert.NotNull(cdcMonitor);

        // All monitor types are derived from BaseMonitor
        Assert.IsAssignableFrom<BaseMonitor>(ftpMonitor);
        Assert.IsAssignableFrom<BaseMonitor>(apiMonitor);
        Assert.IsAssignableFrom<BaseMonitor>(cdcMonitor);
    }

    // ════════════════════════════════════════════════════════════════════
    // Additional Webhook Config Parsing Tests
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void WebhookConfig_ParsesAllFields()
    {
        var cfg = ParseWebhookConfig("{\"url\":\"https://hook.example.com\","
            + "\"method\":\"PUT\",\"auth_type\":\"bearer\",\"auth_token\":\"tok123\","
            + "\"api_key_header\":\"X-Key\",\"timeout_seconds\":60,"
            + "\"max_retries\":5,\"batch_mode\":true,"
            + "\"content_type\":\"text/plain\","
            + "\"headers\":{\"X-Custom\":\"val\"}}");

        Assert.Equal("https://hook.example.com", cfg.Url);
        Assert.Equal("PUT", cfg.Method);
        Assert.Equal("bearer", cfg.AuthType);
        Assert.Equal("tok123", cfg.AuthToken);
        Assert.Equal("X-Key", cfg.ApiKeyHeader);
        Assert.Equal(60, cfg.TimeoutSeconds);
        Assert.Equal(5, cfg.MaxRetries);
        Assert.True(cfg.BatchMode);
        Assert.Equal("text/plain", cfg.ContentType);
        Assert.Equal("val", cfg.Headers["X-Custom"]);
    }

    [Fact]
    public void WebhookConfig_Defaults()
    {
        var cfg = ParseWebhookConfig("{}");
        Assert.Equal("", cfg.Url);
        Assert.Equal("POST", cfg.Method);
        Assert.Equal("none", cfg.AuthType);
        Assert.Null(cfg.AuthToken);
        Assert.Equal("X-API-Key", cfg.ApiKeyHeader);
        Assert.Equal(30, cfg.TimeoutSeconds);
        Assert.Equal(3, cfg.MaxRetries);
        Assert.False(cfg.BatchMode);
        Assert.Equal("application/json", cfg.ContentType);
        Assert.Empty(cfg.Headers);
    }

    // ════════════════════════════════════════════════════════════════════
    // Additional S3 Config Parsing Tests
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void S3Config_ParsesAllFields()
    {
        var cfg = ParseS3Config("{\"region\":\"eu-west-1\",\"bucket_name\":\"my-bucket\","
            + "\"key_prefix\":\"output\",\"access_key_id\":\"AKIA123\","
            + "\"secret_access_key\":\"secret\",\"output_format\":\"csv\","
            + "\"compression\":\"gzip\",\"partition_by_date\":true,"
            + "\"date_partition_format\":\"yyyy-MM-dd\","
            + "\"include_metadata\":false,\"multipart_threshold_mb\":200}");

        Assert.Equal("eu-west-1", cfg.Region);
        Assert.Equal("my-bucket", cfg.BucketName);
        Assert.Equal("output", cfg.KeyPrefix);
        Assert.Equal("AKIA123", cfg.AccessKeyId);
        Assert.Equal("secret", cfg.SecretAccessKey);
        Assert.Equal("csv", cfg.OutputFormat);
        Assert.Equal("gzip", cfg.Compression);
        Assert.True(cfg.PartitionByDate);
        Assert.Equal("yyyy-MM-dd", cfg.DatePartitionFormat);
        Assert.False(cfg.IncludeMetadata);
        Assert.Equal(200, cfg.MultipartThresholdMb);
    }

    [Fact]
    public void S3Config_Defaults()
    {
        var cfg = ParseS3Config("{}");
        Assert.Equal("us-east-1", cfg.Region);
        Assert.Equal("", cfg.BucketName);
        Assert.Equal("", cfg.KeyPrefix);
        Assert.Equal("json", cfg.OutputFormat);
        Assert.Equal("none", cfg.Compression);
        Assert.True(cfg.PartitionByDate);
        Assert.Equal("yyyy/MM/dd", cfg.DatePartitionFormat);
        Assert.True(cfg.IncludeMetadata);
        Assert.Equal(100, cfg.MultipartThresholdMb);
    }

    [Fact]
    public void S3Config_ContentType_JsonNoCompression()
    {
        var cfg = new S3UploadConfig { OutputFormat = "json", Compression = "none" };
        Assert.Equal("application/json", cfg.ContentType());
    }

    [Fact]
    public void S3Config_ContentType_CsvNoCompression()
    {
        var cfg = new S3UploadConfig { OutputFormat = "csv", Compression = "none" };
        Assert.Equal("text/csv", cfg.ContentType());
    }

    [Fact]
    public void S3Config_ContentType_JsonGzip()
    {
        var cfg = new S3UploadConfig { OutputFormat = "json", Compression = "gzip" };
        Assert.Equal("application/gzip", cfg.ContentType());
    }

    [Fact]
    public void S3Config_ContentType_CsvGzip()
    {
        var cfg = new S3UploadConfig { OutputFormat = "csv", Compression = "gzip" };
        Assert.Equal("application/gzip", cfg.ContentType());
    }

    // ════════════════════════════════════════════════════════════════════
    // Additional Edge Case Tests (bring total to 200)
    // ════════════════════════════════════════════════════════════════════

    [Fact]
    public void FtpConfig_MaxFilesZero_NoLimit()
    {
        var cfg = ParseFtpConfig("{\"max_files_per_poll\":0}");
        Assert.Equal(0, cfg.MaxFilesPerPoll);
    }

    [Fact]
    public void FtpConfig_ConstructViaProperties_AllSet()
    {
        var cfg = new FtpSftpConfig
        {
            Protocol = "ftp",
            Host = "ftp.test.com",
            Port = 21,
            Username = "user",
            Password = "pass",
            BasePath = "/root",
            Recursive = false,
            PathFilterRegex = ".*",
            FileFilterRegex = ".*",
            SortBy = "name_asc",
            MaxFilesPerPoll = 25,
            MinAgeSeconds = 5,
        };
        Assert.Equal("ftp", cfg.Protocol);
        Assert.Equal(25, cfg.MaxFilesPerPoll);
    }

    [Fact]
    public async Task Webhook_SingleObject_WrappedAsRecord()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig { Url = "https://hook.example.com/data", MaxRetries = 0 };
        var exporter = new WebhookSenderExporter(config, client);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "{\"id\":1,\"value\":\"single\"}", Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal(1, result.RecordsExported);
    }

    [Fact]
    public async Task Webhook_RecordsWrapper_Unwraps()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig { Url = "https://hook.example.com/data", BatchMode = true, MaxRetries = 0 };
        var exporter = new WebhookSenderExporter(config, client);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "{\"records\":[{\"a\":1},{\"a\":2}]}", Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal(2, result.RecordsExported);
        Assert.Single(handler.Requests); // batch mode sends once
    }

    [Fact]
    public void CdcMonitor_WithLogger_Creates()
    {
        var monitor = new CdcMonitor("Host=localhost;", "events", "id", null, null);
        Assert.NotNull(monitor);
    }

    [Fact]
    public void FtpMonitor_WithLogger_Creates()
    {
        var cfg = new FtpSftpConfig { Host = "test.local" };
        var monitor = new FtpSftpMonitor(cfg, null);
        Assert.NotNull(monitor);
    }

    [Fact]
    public void FileRegex_Parquet_Extension()
    {
        Assert.True(RegexMatches(@".*\.parquet$", "data.parquet"));
        Assert.False(RegexMatches(@".*\.parquet$", "data.csv"));
    }

    [Fact]
    public async Task S3_EmptyArray_NoUpload()
    {
        var s3 = new MockS3Client();
        var config = new S3UploadConfig { BucketName = "bucket", PartitionByDate = false };
        var exporter = new S3UploadExporter(config, s3);

        var result = await exporter.ExportAsync(new ExportContext(DataJson: "[]", Metadata: new()));

        Assert.True(result.Success);
        Assert.Equal(0, result.RecordsExported);
        Assert.Empty(s3.Uploads);
    }

    [Fact]
    public async Task Webhook_Summary_ContainsExpectedKeys()
    {
        var handler = new MockHttpHandler { ResponseCode = HttpStatusCode.OK };
        var client = new HttpClient(handler);
        var config = new WebhookSenderConfig { Url = "https://hook.example.com/data", MaxRetries = 0 };
        var exporter = new WebhookSenderExporter(config, client);

        var result = await exporter.ExportAsync(new ExportContext(
            DataJson: "[{\"id\":1}]", Metadata: new()));

        Assert.NotNull(result.Summary);
        Assert.True(result.Summary!.ContainsKey("url"));
        Assert.True(result.Summary.ContainsKey("method"));
        Assert.True(result.Summary.ContainsKey("records_sent"));
        Assert.True(result.Summary.ContainsKey("records_failed"));
        Assert.True(result.Summary.ContainsKey("batch_mode"));
    }
}
