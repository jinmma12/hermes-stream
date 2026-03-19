# Hermes FTP/SFTP Operator Guide

## 1. Purpose

This guide explains how to use the current Hermes FTP/SFTP collector as it exists today.

It is not a future design document.
It is a practical operator guide based on:

- the current plugin contract
- the current UI
- the current Python reference implementation
- the current test coverage

Primary references:

- `docs/FTP_SFTP_COLLECTOR_CONFIG_SPEC.md`
- `plugins/community-examples/ftp-sftp-collector/hermes-plugin.json`
- `plugins/community-examples/ftp-sftp-collector/main.py`
- `backend/tests/collection/test_ftp_collector_e2e.py`
- `backend/tests/collection/test_folder_traversal.py`
- `backend/tests/collection/test_file_matching.py`

## 2. Mental Model

The current Hermes FTP/SFTP collector does not use separate `folder_path` and `file_path` fields.

Instead, collection is controlled by a combination of:

- `remote_path`: where scanning starts
- `recursive`: whether Hermes enters subfolders
- `max_depth`: how far Hermes descends
- `folder_pattern`: optional date-folder restriction
- `file_filter.filename_regex`: file name matching
- `file_filter.path_regex`: full remote path matching
- `file_filter.exclude_patterns`: deny list
- `completion_check`: partial-file protection
- `discovery_mode`: how many matching files are selected

This means:

- folder selection is mostly `remote_path + recursive + max_depth + folder_pattern + path_regex`
- file selection is mostly `filename_regex + exclude_patterns + size/age filters`

## 3. What The Current Fields Mean

### 3.1 Traversal

- `remote_path`
  - Root directory Hermes starts scanning from.
  - Example: `/data`, `/data/incoming`, `/plant/lineA`

- `recursive`
  - `false`: only scan files directly under `remote_path`
  - `true`: enter subdirectories

- `max_depth`
  - Only relevant when `recursive=true`
  - `0`: root only
  - `1`: root + immediate child directories
  - `2`: root + two levels down
  - `-1`: unlimited

### 3.2 Folder Pattern

`folder_pattern` is not a general folder wildcard.
It is a date-folder selector.

Use it when your remote structure is date-oriented, such as:

- `/data/20260319/`
- `/data/2026/03/19/`
- `/data/topicA/20260319/`

Fields:

- `enabled`
- `format`
- `lookback_days`
- `timezone`

### 3.3 File Filter

- `filename_regex`
  - Matches against file name only
  - Example: `.*\.csv$`

- `path_regex`
  - Matches against the full remote path
  - Example: `.*/equipment_[A-Z]+/.*`

- `exclude_patterns`
  - Deny rules
  - Current implementation treats these primarily as file-name exclusions

- `min_size_bytes`
- `max_size_bytes`
- `max_age_hours`
- `exclude_zero_byte`

### 3.4 Discovery Mode

- `ALL`
  - Every matching file every poll

- `LATEST`
  - Only the newest matching file

- `BATCH`
  - Up to `batch_size` files

- `ALL_NEW`
  - Only files not previously seen by the current collector state

Operational default:

- use `ALL_NEW` unless you intentionally need replay-like repeated pickup

### 3.5 Completion Check

- `NONE`
  - Pick files immediately

- `MARKER_FILE`
  - Require companion marker file such as `.done`

- `SIZE_STABLE`
  - Require file size to stop changing for `stable_seconds`

### 3.6 Post-Collection Action

- `KEEP`
- `DELETE`
- `MOVE`
- `RENAME`

This controls what Hermes does to the remote file after a successful collection.

## 4. Important Limits In The Current Implementation

These are important for operators.

### 4.1 Regex, Not Glob

The FTP/SFTP collector currently works primarily with regex.

Examples:

- valid: `.*\.csv$`
- valid: `sensor_.*\.json$`
- valid: `.*/equipment_[A-Z]+/.*`

Do not assume shell-style glob syntax like `**/*.csv` is natively supported in the FTP/SFTP collector recipe.

If you want “glob-like” behavior, express it with:

- `recursive=true`
- `max_depth`
- regex filters

### 4.2 No Dedicated Folder Include/Exclude Regex Fields

There is no first-class field today for:

- `folder_include_regex`
- `folder_exclude_regex`
- `folder_glob`

If you need folder-based restriction, use:

- `remote_path`
- `max_depth`
- `folder_pattern`
- `path_regex`

### 4.3 No Multi-Root Recipe

One recipe assumes one `remote_path`.

If you need to collect from multiple unrelated roots, create multiple collector instances or multiple pipeline stages.

### 4.4 `ALL_NEW` Is State-Sensitive

`ALL_NEW` depends on the collector's seen-file state.

Operators should treat this as useful, but not yet as a fully proven cluster-safe persisted guarantee across all runtime modes.

## 5. Recommended Usage Patterns

### Pattern A: Fixed Folder, Fixed Extension

Use when:

- one vendor drops files into a single folder
- file names are consistent

Example:

```json
{
  "remote_path": "/data/incoming",
  "recursive": false,
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Pattern B: Recursive Tree, Same File Pattern Everywhere

Use when:

- the source has multiple subfolders
- you want all matching files below a root

Example:

```json
{
  "remote_path": "/data/incoming",
  "recursive": true,
  "max_depth": -1,
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Pattern C: Limit Depth

Use when:

- folder trees are deep
- you only want top levels

Example:

```json
{
  "remote_path": "/plant",
  "recursive": true,
  "max_depth": 2,
  "file_filter": {
    "filename_regex": ".*\\.json$"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Pattern D: Only Equipment Folders

Use when:

- the hierarchy is mixed
- only some subpaths are relevant

Example:

```json
{
  "remote_path": "/data",
  "recursive": true,
  "max_depth": -1,
  "file_filter": {
    "filename_regex": ".*\\.csv$",
    "path_regex": ".*/equipment_[A-Z]+/.*"
  },
  "discovery_mode": "ALL"
}
```

### Pattern E: File Name Convention

Use when:

- file names carry semantics
- you need exact date or prefix rules

Example:

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": "data_\\d{8}\\.csv$"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Pattern F: Date Folder Collection

Use when:

- sources are partitioned by date
- you only want recent dates

Example:

```json
{
  "remote_path": "/data",
  "recursive": true,
  "folder_pattern": {
    "enabled": true,
    "format": "yyyyMMdd",
    "lookback_days": 3,
    "timezone": "UTC"
  },
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Pattern G: Industrial Topic + Date Structure

Use when:

- source shape is `/topic/yyyyMMdd/file`
- all topics are valid

Example:

```json
{
  "remote_path": "/data",
  "recursive": true,
  "max_depth": -1,
  "folder_pattern": {
    "enabled": true,
    "format": "yyyyMMdd",
    "lookback_days": 7,
    "timezone": "Asia/Seoul"
  },
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "BATCH",
  "batch_size": 100
}
```

### Pattern H: Exclude Temporary and Hidden Files

Use when:

- uploaders leave temp files
- hidden files or backups exist

Example:

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.csv$",
    "exclude_patterns": ["\\.tmp$", "^\\.", "\\.bak$"],
    "exclude_zero_byte": true
  },
  "discovery_mode": "ALL_NEW"
}
```

### Pattern I: Wait For Marker File

Use when:

- upstream system writes data first, then completion marker

Example:

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": "^[^.]*\\.csv$"
  },
  "completion_check": {
    "strategy": "MARKER_FILE",
    "marker_suffix": ".done"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Pattern J: Latest File Only

Use when:

- only the newest file matters
- old files are irrelevant

Example:

```json
{
  "remote_path": "/data",
  "recursive": true,
  "max_depth": -1,
  "file_filter": {
    "filename_regex": ".*\\.json$"
  },
  "ordering": "NEWEST_FIRST",
  "discovery_mode": "LATEST"
}
```

## 6. Sample Scenarios Operators Can Use Today

These scenarios are already representable with the current design.

1. Collect root-level CSV files from a vendor drop folder
2. Recursively collect all JSON files below a plant root
3. Collect only the first two levels of a reference-data tree
4. Collect only equipment-specific subpaths using `path_regex`
5. Collect files whose names follow `sensor_*.csv`
6. Collect only recent date partitions using `folder_pattern`
7. Collect all topic/date folders under a shared root
8. Skip hidden files, `.tmp`, and `.bak`
9. Skip zero-byte placeholders
10. Restrict by size range
11. Restrict by age window
12. Pick only the newest file
13. Pick up to `N` files each cycle with `BATCH`
14. Pick unseen files with `ALL_NEW`
15. Wait for `.done` marker files
16. Wait until file size is stable
17. Move collected files into an archive folder
18. Rename collected files with a suffix
19. Delete collected files after successful collection
20. Combine traversal + regex + completion + post-action in one recipe

## 7. What Is Already Tested

Current test coverage is strong on the Python reference layer.

### 7.1 FTP Collector E2E

Main file:

- `backend/tests/collection/test_ftp_collector_e2e.py`

Coverage includes:

- recursive traversal
- limited depth
- date folder pattern
- file name regex
- path regex
- exclude patterns
- size and age filtering
- ordering
- discovery mode
- marker file completion check
- no completion check
- combined scenarios

### 7.2 Folder Traversal Unit Coverage

Main file:

- `backend/tests/collection/test_folder_traversal.py`

Coverage includes:

- date folder structures
- nested year/month/day structures
- depth handling
- empty directories
- hidden directories
- symlink handling
- folder deletion during traversal
- large folder counts
- unusual path names

### 7.3 File Matching Unit Coverage

Main file:

- `backend/tests/collection/test_file_matching.py`

Coverage includes:

- glob-like helper matching tests
- regex matching tests
- size filters
- age filters
- exclude patterns
- completion checks
- post-collection actions
- discovery modes

### 7.4 Pipeline Recipe Passing

Main file:

- `backend/tests/test_pipeline_e2e_flow.py`

Coverage includes:

- collector recipe passed through pipeline orchestration

## 8. What The UI Currently Supports

The current UI supports practical editing, but not full operator guidance.

### 8.1 What Exists

- `Settings` tab:
  - instance
  - connection
  - runtime policy

- `Properties` tab:
  - traversal
  - folder pattern
  - file filter
  - collection
  - completion
  - post-collection

- `JSON Config Editor`
  - current recipe JSON is editable directly

- field tooltips
  - derived from schema descriptions or fallback definitions

### 8.2 What Does Not Yet Exist

- dedicated operator help tab
- markdown manual viewer
- inline scenario examples
- match preview
- sample path tester
- “why was this file included/excluded” explainer

## 9. UI Design Proposal For Operators

This is not a new collector design.
It is a better operator UX on top of the current collector behavior.

### 9.1 Add An “Examples” Section

At the top of the `Properties` tab, add a preset selector.

Recommended presets:

- Root CSV pickup
- Recursive CSV tree
- Recent date folders
- Equipment folders only
- Latest file only
- Marker-file based collection
- Batch collection
- Archive-after-collect

Behavior:

- choosing a preset fills the recipe form and JSON editor

### 9.2 Add A “Selection Summary” Panel

Show a generated explanation from current form values.

Example text:

- Start scanning from `/data`
- Traverse recursively with unlimited depth
- Only accept files matching `sensor_.*\.csv$`
- Only accept paths matching `.*/equipment_[A-Z]+/.*`
- Exclude `.tmp`, hidden files, and `.bak`
- Wait for `.done` marker files
- Select only unseen files

This is the fastest way to reduce operator confusion.

### 9.3 Add A “Pattern Help” Panel

Short help content:

- `filename_regex` applies to file name only
- `path_regex` applies to full remote path
- FTP/SFTP collector uses regex, not shell glob
- `folder_pattern` is only for date-oriented folders
- use `recursive + max_depth` for tree control

### 9.4 Add “Sample Paths” Validation

Operators should be able to paste example paths:

- `/data/equipment_A/20260319/sensor_01.csv`
- `/data/logs/debug.tmp`

The UI should show:

- matched
- excluded
- reason

### 9.5 Add Basic / Advanced Toggle

Basic mode:

- `remote_path`
- `recursive`
- `max_depth`
- `filename_regex`
- `discovery_mode`

Advanced mode:

- `path_regex`
- `exclude_patterns`
- `size/age`
- `completion_check`
- `post_action`
- raw JSON editor

## 10. Suggested Help Content For The UI

This text can be rendered as markdown in a future help panel.

### 10.1 `remote_path`

Start directory for scanning.
Hermes only sees files under this path.

### 10.2 `recursive`

Enable when files may exist in subdirectories.
Disable when the drop folder is flat and predictable.

### 10.3 `max_depth`

Use this to avoid scanning excessively deep trees.

- `0`: root only
- `1`: root + one level
- `-1`: unlimited

### 10.4 `filename_regex`

Filter by file name only.

Examples:

- `.*\.csv$`
- `data_\d{8}\.json$`
- `sensor_.*`

### 10.5 `path_regex`

Filter by full remote path.

Examples:

- `.*/equipment_[A-Z]+/.*`
- `.*/2026/03/.*`

### 10.6 `folder_pattern`

Use only when your folder names are date-based.

Examples:

- `yyyyMMdd`
- `yyyy/MM/dd`
- `yyyy-MM-dd`

### 10.7 `completion_check`

Use `MARKER_FILE` when upstream writes a completion file.
Use `SIZE_STABLE` when no marker exists but files grow over time.

### 10.8 `discovery_mode`

- `ALL`: everything every time
- `LATEST`: newest only
- `BATCH`: up to N files
- `ALL_NEW`: only not-yet-seen files

## 11. Recommended Next Documentation Work

If Hermes wants operators to use this reliably, the next docs should be:

1. `docs/FTP_SFTP_RECIPE_EXAMPLES.md`
2. `docs/FTP_SFTP_UI_HELP_CONTENT.md`
3. `docs/CONNECTOR_CONFIG_MODEL.md`

## 12. Recommended Claude Follow-Up

Claude should read this file before changing FTP/SFTP UX or runtime behavior.

Specifically:

- do not redesign the collector around imaginary fields not in the current runtime
- preserve the current tested behavior
- improve operator guidance, examples, and preview UX first
- make clear in the UI that FTP/SFTP uses regex-based selection, not shell glob
