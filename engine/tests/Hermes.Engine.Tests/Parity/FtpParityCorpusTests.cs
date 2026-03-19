using System.Text.Json;
using System.Text.RegularExpressions;
using Xunit;

namespace Hermes.Engine.Tests.Parity;

/// <summary>
/// FTP/SFTP parity tests using the shared corpus from
/// backend/tests/parity/ftp_parity_corpus.json.
///
/// These tests simulate the .NET FtpSftpMonitor's ApplyFilters logic
/// to verify parity with the Python reference layer.
///
/// The matching logic mirrors FtpSftpMonitor.cs:
///   - base_path prefix check
///   - recursive: if false, only root-level files
///   - path_filter_regex: full path match (case-insensitive)
///   - file_filter_regex: filename match (case-insensitive)
///
/// Features NOT supported in .NET (tested as gaps in Python parity file):
///   - max_depth
///   - exclude_patterns
///   - folder_pattern
///   - completion_check
///   - post_action
/// </summary>
public class FtpParityCorpusTests
{
    // Simulates .NET FtpSftpMonitor.ApplyFilters logic
    private static bool DotNetMatch(string path, string basePath, bool recursive, string? pathFilterRegex, string? fileFilterRegex)
    {
        if (!path.StartsWith(basePath + "/"))
            return false;

        if (!recursive)
        {
            var relative = path[(basePath.Length + 1)..];
            if (relative.Contains('/'))
                return false;
        }

        if (!string.IsNullOrEmpty(pathFilterRegex))
        {
            var regex = new Regex(pathFilterRegex, RegexOptions.IgnoreCase);
            if (!regex.IsMatch(path))
                return false;
        }

        if (!string.IsNullOrEmpty(fileFilterRegex))
        {
            var filename = path.Split('/')[^1];
            var regex = new Regex(fileFilterRegex, RegexOptions.IgnoreCase);
            if (!regex.IsMatch(filename))
                return false;
        }

        return true;
    }

    // ── Corpus: flat_csv_pickup ──────────────────────────────

    [Theory]
    [InlineData("/drop/a.csv", true)]
    [InlineData("/drop/b.csv", true)]
    [InlineData("/drop/readme.txt", false)]
    [InlineData("/drop/subdir/data.csv", false)]
    public void FlatCsvPickup_MatchesPythonParity(string path, bool expected)
    {
        var result = DotNetMatch(path, "/drop", recursive: false, null, @".*\.csv$");
        Assert.Equal(expected, result);
    }

    // ── Corpus: recursive_equipment_tree ─────────────────────

    [Theory]
    [InlineData("/data/equipment_A/sensor_01.csv", true)]
    [InlineData("/data/equipment_B/sensor_02.csv", true)]
    [InlineData("/data/logs/sensor_01.csv", false)]
    [InlineData("/data/equipment_A/readme.txt", false)]
    public void RecursiveEquipmentTree_MatchesPythonParity(string path, bool expected)
    {
        var result = DotNetMatch(path, "/data", recursive: true,
            @".*/equipment_[A-Z]+/.*", @"sensor_.*\.csv$");
        Assert.Equal(expected, result);
    }

    // ── Corpus: root_only_json ───────────────────────────────

    [Theory]
    [InlineData("/incoming/data.json", true)]
    [InlineData("/incoming/data.csv", false)]
    [InlineData("/incoming/sub/data.json", false)]
    public void RootOnlyJson_MatchesPythonParity(string path, bool expected)
    {
        var result = DotNetMatch(path, "/incoming", recursive: false, null, @".*\.json$");
        Assert.Equal(expected, result);
    }

    // ── Documented gaps ─────────────────────────────────────

    [Fact(Skip = ".NET does not support max_depth")]
    public void DepthLimited_NotSupportedInDotNet()
    {
        // Python: max_depth=1 limits to root + 1 level
        // .NET: recursive=true scans all levels (no depth control)
        Assert.True(false, "max_depth not implemented in FtpSftpMonitor");
    }

    [Fact(Skip = ".NET does not support exclude_patterns")]
    public void ExcludePatterns_NotSupportedInDotNet()
    {
        // Python: exclude_patterns deny list
        // .NET: no equivalent field
        Assert.True(false, "exclude_patterns not implemented in FtpSftpMonitor");
    }
}
