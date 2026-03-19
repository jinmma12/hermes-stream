# Hermes FTP/SFTP Recipe Examples

## 1. Purpose

This document gives ready-to-use FTP/SFTP recipe examples for current Hermes behavior.

Each example focuses on:

- what structure it assumes
- why it works
- what Hermes will collect

These examples are intended for:

- operators
- Claude implementation work
- future UI presets

## 2. Flat Folder Examples

### Example 1. Root CSV Files Only

Use when:

- files arrive directly under one drop folder
- no subdirectories matter

```json
{
  "remote_path": "/drop",
  "recursive": false,
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "ALL_NEW"
}
```

Collects:

- `/drop/a.csv`
- `/drop/b.csv`

Skips:

- `/drop/readme.txt`
- `/drop/subdir/data.csv`

### Example 2. Root JSON Files With Size Filter

```json
{
  "remote_path": "/drop",
  "recursive": false,
  "file_filter": {
    "filename_regex": ".*\\.json$",
    "min_size_bytes": 100
  },
  "discovery_mode": "ALL_NEW"
}
```

## 3. Recursive Tree Examples

### Example 3. Collect All CSV Files Recursively

```json
{
  "remote_path": "/data",
  "recursive": true,
  "max_depth": -1,
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Example 4. Collect Only Up To One Level Deep

```json
{
  "remote_path": "/data",
  "recursive": true,
  "max_depth": 1,
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "ALL_NEW"
}
```

Behavior:

- collects root files
- collects files in immediate child folders
- skips deeper nested folders

### Example 5. Collect Only Up To Two Levels Deep

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

## 4. File Name Pattern Examples

### Example 6. Sensor Prefix Files

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": "sensor_.*\\.csv$"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Example 7. Date-In-Name Files

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

### Example 8. Exact Extension Family

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.(csv|json)$"
  },
  "discovery_mode": "ALL_NEW"
}
```

## 5. Path-Based Filtering Examples

### Example 9. Equipment Folders Only

```json
{
  "remote_path": "/data",
  "recursive": true,
  "max_depth": -1,
  "file_filter": {
    "path_regex": ".*/equipment_[A-Z]+/.*",
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "ALL"
}
```

### Example 10. Collect Only 2026 March Paths

```json
{
  "remote_path": "/data",
  "recursive": true,
  "max_depth": -1,
  "file_filter": {
    "path_regex": ".*/2026/03/.*"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Example 11. Topic + Equipment Hybrid

```json
{
  "remote_path": "/plant",
  "recursive": true,
  "max_depth": -1,
  "file_filter": {
    "path_regex": ".*/topic_[A-Z]+/equipment_[A-Z0-9]+/.*",
    "filename_regex": "sensor_.*\\.csv$"
  },
  "discovery_mode": "ALL_NEW"
}
```

## 6. Date Folder Examples

### Example 12. Recent `yyyyMMdd` Partitions

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

### Example 13. Recent `yyyy/MM/dd` Partitions

```json
{
  "remote_path": "/data",
  "recursive": true,
  "max_depth": -1,
  "folder_pattern": {
    "enabled": true,
    "format": "yyyy/MM/dd",
    "lookback_days": 7,
    "timezone": "Asia/Seoul"
  },
  "file_filter": {
    "filename_regex": ".*\\.json$"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Example 14. Topic + Date Structure

```json
{
  "remote_path": "/data",
  "recursive": true,
  "max_depth": -1,
  "folder_pattern": {
    "enabled": true,
    "format": "yyyyMMdd",
    "lookback_days": 7,
    "timezone": "UTC"
  },
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "BATCH",
  "batch_size": 200
}
```

Use when the layout looks like:

- `/data/topicA/20260319/a.csv`
- `/data/topicB/20260319/b.csv`

## 7. Exclusion Examples

### Example 15. Exclude Temp, Hidden, and Backup

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

### Example 16. Skip Very Old Files

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.csv$",
    "max_age_hours": 24
  },
  "discovery_mode": "ALL_NEW"
}
```

### Example 17. Keep Only Medium-Sized Files

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "min_size_bytes": 100,
    "max_size_bytes": 10485760,
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "ALL_NEW"
}
```

## 8. Discovery Strategy Examples

### Example 18. Every Match Every Poll

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "ALL"
}
```

### Example 19. Newest File Only

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.json$"
  },
  "ordering": "NEWEST_FIRST",
  "discovery_mode": "LATEST"
}
```

### Example 20. Batch Of 50 Files

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.json$"
  },
  "ordering": "OLDEST_FIRST",
  "discovery_mode": "BATCH",
  "batch_size": 50
}
```

### Example 21. Unseen Files Only

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "discovery_mode": "ALL_NEW"
}
```

## 9. Completion Check Examples

### Example 22. Marker File `.done`

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

### Example 23. Marker File `.complete`

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.json$"
  },
  "completion_check": {
    "strategy": "MARKER_FILE",
    "marker_suffix": ".complete"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Example 24. Size Stable For 10 Seconds

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "completion_check": {
    "strategy": "SIZE_STABLE",
    "stable_seconds": 10
  },
  "discovery_mode": "ALL_NEW"
}
```

## 10. Post-Collection Examples

### Example 25. Keep Original Files

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "post_action": {
    "action": "KEEP"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Example 26. Move To Archive

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "post_action": {
    "action": "MOVE",
    "move_target": "/archive",
    "conflict_resolution": "TIMESTAMP"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Example 27. Rename After Collection

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "post_action": {
    "action": "RENAME",
    "rename_suffix": ".processed"
  },
  "discovery_mode": "ALL_NEW"
}
```

### Example 28. Delete After Collection

```json
{
  "remote_path": "/data",
  "recursive": true,
  "file_filter": {
    "filename_regex": ".*\\.csv$"
  },
  "post_action": {
    "action": "DELETE"
  },
  "discovery_mode": "ALL_NEW"
}
```

## 11. Composite Real-World Examples

### Example 29. Equipment CSV With Marker And Archive

```json
{
  "remote_path": "/equipment",
  "recursive": true,
  "max_depth": 1,
  "file_filter": {
    "filename_regex": "sensor_.*\\.csv$",
    "exclude_patterns": ["\\.bak$"],
    "exclude_zero_byte": true
  },
  "completion_check": {
    "strategy": "MARKER_FILE",
    "marker_suffix": ".done"
  },
  "post_action": {
    "action": "MOVE",
    "move_target": "/archive",
    "conflict_resolution": "TIMESTAMP"
  },
  "discovery_mode": "ALL"
}
```

### Example 30. Date-Partitioned JSON Intake

```json
{
  "remote_path": "/data",
  "recursive": true,
  "folder_pattern": {
    "enabled": true,
    "format": "yyyyMMdd",
    "lookback_days": 2,
    "timezone": "UTC"
  },
  "file_filter": {
    "filename_regex": ".*\\.json$",
    "exclude_zero_byte": true
  },
  "completion_check": {
    "strategy": "SIZE_STABLE",
    "stable_seconds": 10
  },
  "discovery_mode": "BATCH",
  "batch_size": 100
}
```

## 12. Suggested UI Preset Names

These example names are appropriate for a future UI preset list:

1. Root CSV Pickup
2. Recursive CSV Tree
3. Limited Depth Scan
4. Equipment Paths Only
5. Date-Named Files
6. Recent Date Folders
7. Topic + Date Tree
8. Exclude Temp and Hidden Files
9. Marker File Collection
10. Size Stable Collection
11. Latest File Only
12. Batch Collection
13. Archive After Collect
14. Rename After Collect
15. Delete After Collect

## 13. Suggested Claude Follow-Up

Claude should use these examples as:

- help tab content
- preset seeds
- JSON examples in documentation
- test/preview fixtures for sample-path matching UX
