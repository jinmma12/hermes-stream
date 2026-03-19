# Hermes FTP/SFTP UI Help Content

## 1. Purpose

This document provides UI-ready help content for the current Hermes FTP/SFTP collector.

It is intended for:

- inline help panels
- tooltip expansion content
- example drawers
- markdown help tabs in the recipe editor

This content reflects current behavior and current tests.

## 2. Short Intro

Hermes FTP/SFTP collection is controlled by four ideas:

1. where scanning starts
2. how deep Hermes traverses folders
3. which files are accepted
4. when a file is considered safe to collect

In Hermes today, FTP/SFTP collection is mainly regex-driven.

Use:

- `remote_path`
- `recursive`
- `max_depth`
- `folder_pattern`
- `filename_regex`
- `path_regex`
- `exclude_patterns`
- `completion_check`

Do not assume shell glob patterns like `**/*.csv` are the main selection model here.

## 3. Help Panel: Settings Tab

### 3.1 Instance

`Name`

- Human-readable name for this collector stage.
- Use something operators can recognize quickly.
- Example: `Vendor A Daily SFTP Intake`

`Enabled`

- Turns this stage on or off without deleting the configuration.

`On Error`

- `STOP`: stop the pipeline stage on failure
- `SKIP`: skip the failing item
- `RETRY`: retry according to runtime or stage retry settings

`Retry Count`

- Stage-level retry count before Hermes gives up on the item.

### 3.2 Connection

`Protocol`

- `FTP`, `FTPS`, or `SFTP`

`Host`

- Server name or IP address.

`Port`

- Typical defaults:
  - FTP: `21`
  - FTPS: `990`
  - SFTP: `22`

`Username`

- Account used to connect to the remote server.

`Password`

- Used for password-based login.

`Private Key Path`

- Used for SFTP key-based authentication.

`Passive Mode`

- Relevant for FTP/FTPS.
- Often required behind firewalls or NAT.

`Host Key Checking`

- Relevant for SFTP.
- Should stay enabled in production when possible.

### 3.3 Runtime Policy

`Poll Interval`

- How often Hermes scans for new files.
- Examples: `30s`, `5m`, `1h`

`Connection Timeout`

- Max wait time for initial connection.

`Data Timeout`

- Max wait time for listing or transferring data.

`Max Concurrent Downloads`

- Number of simultaneous downloads.

`Retry Max Attempts`

- Retries for transient connection or transfer failures.

`Circuit Breaker`

- Prevents rapid repeated failures against unstable sources.

## 4. Help Panel: Properties Tab

### 4.1 Traversal

`Remote Path`

- Root directory where scanning starts.
- Hermes only sees files under this path.

Examples:

- `/data`
- `/data/incoming`
- `/plant/lineA`

`Recursive`

- If enabled, Hermes enters subdirectories below `remote_path`.

`Max Depth`

- Controls how deep Hermes traverses when recursion is enabled.

Values:

- `0`: root only
- `1`: root + immediate child folders
- `2`: two levels down
- `-1`: unlimited

### 4.2 Folder Pattern

Use this only for date-based folder structures.

Examples:

- `/data/20260319/`
- `/data/2026/03/19/`
- `/data/topicA/20260319/`

`Date Folders`

- Enables date-folder filtering.

`Date Format`

- Examples:
  - `yyyyMMdd`
  - `yyyy/MM/dd`
  - `yyyy-MM-dd`

`Lookback Days`

- Hermes scans folders within this date window.

`Timezone`

- Used to calculate the current date window correctly.

### 4.3 File Filter

`Filename Regex`

- Matches file names only.

Examples:

- `.*\.csv$`
- `data_\d{8}\.json$`
- `sensor_.*`

`Path Regex`

- Matches the full remote path.

Examples:

- `.*/equipment_[A-Z]+/.*`
- `.*/2026/03/.*`

`Min Size / Max Size`

- Use to prevent collecting empty, partial, or unexpectedly large files.

`Max Age`

- Ignore files older than the configured number of hours.

`Exclude Patterns`

- Deny list.
- Common patterns:
  - `\.tmp$`
  - `^\.`
  - `\.bak$`

`Exclude Empty`

- Skip zero-byte files.

### 4.4 Collection

`Ordering`

- `NEWEST_FIRST`
- `OLDEST_FIRST`
- `NAME_ASC`
- `NAME_DESC`

`Discovery Mode`

- `ALL`: every matching file
- `LATEST`: only the newest file
- `BATCH`: up to `batch_size` files
- `ALL_NEW`: only not-yet-seen files

`Batch Size`

- Used in `BATCH` mode.

### 4.5 Completion

Use completion checks when files may still be in progress.

`NONE`

- Collect immediately.

`MARKER_FILE`

- Collect only when a companion marker exists.
- Example: `report.csv.done`

`SIZE_STABLE`

- Collect only after file size stops changing for the configured duration.

### 4.6 Post-Collection

`KEEP`

- Leave the file in place.

`DELETE`

- Remove the file after successful collection.

`MOVE`

- Move the file to another directory such as `/archive`.

`RENAME`

- Rename the file, typically with a suffix such as `.processed`.

## 5. Ready-To-Render Example Cards

### Card 1: Flat Drop Folder

Use when files arrive in one known directory and only CSV files matter.

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

### Card 2: Recursive Equipment Tree

Use when equipment folders sit below a shared root.

```json
{
  "remote_path": "/data",
  "recursive": true,
  "max_depth": -1,
  "file_filter": {
    "filename_regex": "sensor_.*\\.csv$",
    "path_regex": ".*/equipment_[A-Z]+/.*"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Card 3: Recent Date Folders

Use when source folders are partitioned by date.

```json
{
  "remote_path": "/data",
  "recursive": true,
  "folder_pattern": {
    "enabled": true,
    "format": "yyyyMMdd",
    "lookback_days": 7,
    "timezone": "UTC"
  },
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Card 4: Wait For Marker File

Use when upstream writes `.done` after upload completes.

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

### Card 5: Batch Pickup

Use when many files arrive and Hermes should process them gradually.

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.json$"
  },
  "discovery_mode": "BATCH",
  "batch_size": 100
}
```

## 6. Suggested “Selection Summary” Template

The UI can generate a summary like this:

```text
Start from /data
Traverse recursively with max depth -1
Accept file names matching sensor_.*\.csv$
Accept only paths matching .*/equipment_[A-Z]+/.*
Exclude .tmp, hidden files, and .bak
Require marker file suffix .done
Select only not-yet-seen files
```

## 7. Suggested “Pattern Help” Block

Use this exact language or something close to it:

```text
FTP/SFTP selection in Hermes is regex-based.

- Filename Regex matches file names only.
- Path Regex matches the full remote path.
- Recursive + Max Depth control folder traversal.
- Folder Pattern is for date-based folders.
- Completion Check prevents collecting partial files.
```

## 8. Suggested “Operator Warnings” Block

```text
- ALL mode may repeatedly pick up the same files.
- ALL_NEW depends on collector state and should be validated carefully in restart scenarios.
- Marker-file mode is safer than immediate pickup when upstream writes slowly.
- Use Path Regex when folder structure matters.
- Use Filename Regex when only file naming matters.
```

## 9. Suggested UI Work Order

If Claude implements help features, the recommended order is:

1. render this markdown in a Help tab
2. add example cards / presets
3. add selection summary
4. add sample path preview

