#!/usr/bin/env python3
"""Hermes FTP/SFTP Collector Plugin.

Collects files from FTP/FTPS/SFTP servers with comprehensive
directory traversal, pattern matching, completion checks,
and resilience features.

Supports:
- FTP (plain), FTPS (TLS), SFTP (SSH)
- Recursive directory traversal with depth control
- Date-based folder patterns (yyyyMMdd, yyyy/MM/dd, etc.)
- Regex file filtering + size/age constraints
- Discovery modes: ALL, LATEST, BATCH, ALL_NEW
- Completion checks: MARKER_FILE, SIZE_STABLE
- Post-collection: KEEP, DELETE, MOVE, RENAME
- Exponential backoff retry + circuit breaker
- Checksum verification (SHA-256)
"""

from __future__ import annotations

import ftplib
import hashlib
import io
import json
import os
import random
import re
import ssl
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Plugin Protocol helpers
# ---------------------------------------------------------------------------

def send_message(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def log(message: str, level: str = "INFO") -> None:
    send_message({"type": "LOG", "level": level, "message": message})

def output(data: Any) -> None:
    send_message({"type": "OUTPUT", "data": data})

def error(message: str, code: str = "PLUGIN_ERROR") -> None:
    send_message({"type": "ERROR", "code": code, "message": message})

def done(summary: dict[str, Any]) -> None:
    send_message({"type": "DONE", "summary": summary})

def status(progress: float) -> None:
    send_message({"type": "STATUS", "progress": progress})

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RemoteFile:
    """Represents a file discovered on the remote server."""
    path: str
    name: str
    size: int
    modified: datetime
    is_dir: bool = False

@dataclass
class DownloadResult:
    """Result of a single file download."""
    remote_path: str
    local_data: bytes
    size: int
    checksum: str
    success: bool = True
    error_message: str = ""

@dataclass
class CircuitBreakerState:
    """Circuit breaker state tracker."""
    failure_count: int = 0
    state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    last_failure_time: float = 0.0
    threshold: int = 5
    recovery_seconds: int = 300

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.threshold > 0:
            self.state = "OPEN"
            log(f"Circuit breaker OPEN after {self.failure_count} failures", "WARN")

    def record_success(self) -> None:
        if self.state == "HALF_OPEN":
            log("Circuit breaker CLOSED (probe succeeded)", "INFO")
        self.failure_count = 0
        self.state = "CLOSED"

    def can_execute(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_seconds:
                self.state = "HALF_OPEN"
                log("Circuit breaker HALF_OPEN (attempting probe)", "INFO")
                return True
            return False
        return True  # HALF_OPEN

@dataclass
class CollectorStats:
    """Execution statistics."""
    files_discovered: int = 0
    files_downloaded: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    bytes_downloaded: int = 0
    directories_scanned: int = 0
    retry_count: int = 0
    errors: list[str] = field(default_factory=list)

# ---------------------------------------------------------------------------
# FTP/SFTP Connection Abstraction
# ---------------------------------------------------------------------------

class FTPConnection:
    """Wraps ftplib.FTP / FTP_TLS for FTP and FTPS connections."""

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.protocol = settings.get("protocol", "FTP")
        self.host = settings["host"]
        self.port = settings.get("port", 0)
        self.username = settings.get("username", "anonymous")
        self.password = settings.get("password", "")
        self.passive = settings.get("passive_mode", True)
        self.conn_timeout = settings.get("connection_timeout_seconds", 30)
        self.data_timeout = settings.get("data_timeout_seconds", 60)
        self._ftp: Optional[ftplib.FTP] = None

    def _default_port(self) -> int:
        if self.port > 0:
            return self.port
        return 990 if self.protocol == "FTPS" else 21

    def connect(self) -> None:
        """Establish FTP/FTPS connection."""
        port = self._default_port()
        log(f"Connecting to {self.protocol}://{self.host}:{port}")

        if self.protocol == "FTPS":
            ctx = ssl.create_default_context()
            self._ftp = ftplib.FTP_TLS(context=ctx, timeout=self.conn_timeout)
        else:
            self._ftp = ftplib.FTP(timeout=self.conn_timeout)

        self._ftp.connect(self.host, port)
        self._ftp.login(self.username, self.password)

        if self.protocol == "FTPS" and isinstance(self._ftp, ftplib.FTP_TLS):
            self._ftp.prot_p()  # Enable data channel encryption

        if self.passive:
            self._ftp.set_pasv(True)

        log(f"Connected successfully to {self.host}:{port}")

    def disconnect(self) -> None:
        if self._ftp:
            try:
                self._ftp.quit()
            except Exception:
                try:
                    self._ftp.close()
                except Exception:
                    pass
            self._ftp = None

    def list_directory(self, path: str) -> list[RemoteFile]:
        """List files and directories in the given path."""
        assert self._ftp is not None
        entries: list[RemoteFile] = []
        lines: list[str] = []

        try:
            self._ftp.cwd(path)
            self._ftp.retrlines("MLSD", lines.append)
        except ftplib.error_perm:
            # Fallback to LIST if MLSD not supported
            try:
                self._ftp.retrlines("LIST", lines.append)
                return self._parse_list_output(lines, path)
            except ftplib.error_perm as e:
                log(f"Permission denied listing {path}: {e}", "WARN")
                return []

        for line in lines:
            entry = self._parse_mlsd_entry(line, path)
            if entry:
                entries.append(entry)

        return entries

    def _parse_mlsd_entry(self, line: str, parent: str) -> Optional[RemoteFile]:
        """Parse MLSD response line."""
        parts = line.split(";")
        if not parts:
            return None

        name = parts[-1].strip()
        if name in (".", ".."):
            return None

        facts: dict[str, str] = {}
        for part in parts[:-1]:
            if "=" in part:
                k, v = part.strip().split("=", 1)
                facts[k.lower()] = v

        is_dir = facts.get("type", "").lower() in ("dir", "cdir", "pdir")
        size = int(facts.get("size", "0")) if not is_dir else 0
        modify = facts.get("modify", "")
        mtime = self._parse_ftp_time(modify) if modify else datetime.now(timezone.utc)
        full_path = str(PurePosixPath(parent) / name)

        return RemoteFile(path=full_path, name=name, size=size, modified=mtime, is_dir=is_dir)

    def _parse_list_output(self, lines: list[str], parent: str) -> list[RemoteFile]:
        """Fallback parser for LIST command output (Unix ls -l format)."""
        entries: list[RemoteFile] = []
        for line in lines:
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            name = parts[8]
            if name in (".", ".."):
                continue
            is_dir = line.startswith("d")
            size = int(parts[4]) if not is_dir else 0
            full_path = str(PurePosixPath(parent) / name)
            entries.append(RemoteFile(
                path=full_path, name=name, size=size,
                modified=datetime.now(timezone.utc), is_dir=is_dir,
            ))
        return entries

    def _parse_ftp_time(self, timestr: str) -> datetime:
        """Parse FTP MLSD modify timestamp (YYYYMMDDHHmmSS)."""
        try:
            return datetime.strptime(timestr[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            return datetime.now(timezone.utc)

    def download(self, remote_path: str) -> bytes:
        """Download a file and return its contents."""
        assert self._ftp is not None
        buf = io.BytesIO()
        self._ftp.retrbinary(f"RETR {remote_path}", buf.write)
        return buf.getvalue()

    def rename(self, from_path: str, to_path: str) -> None:
        assert self._ftp is not None
        self._ftp.rename(from_path, to_path)

    def delete(self, path: str) -> None:
        assert self._ftp is not None
        self._ftp.delete(path)

    def mkdir(self, path: str) -> None:
        assert self._ftp is not None
        try:
            self._ftp.mkd(path)
        except ftplib.error_perm:
            pass  # Directory may already exist

    def file_size(self, path: str) -> int:
        assert self._ftp is not None
        return self._ftp.size(path) or 0

    @property
    def is_connected(self) -> bool:
        if not self._ftp:
            return False
        try:
            self._ftp.voidcmd("NOOP")
            return True
        except Exception:
            return False


class SFTPConnection:
    """SFTP connection via paramiko (if available) or subprocess fallback."""

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.host = settings["host"]
        self.port = settings.get("port", 0) or 22
        self.username = settings.get("username", "")
        self.password = settings.get("password", "")
        self.key_path = settings.get("private_key_path", "")
        self.key_passphrase = settings.get("private_key_passphrase", "")
        self.conn_timeout = settings.get("connection_timeout_seconds", 30)
        self.host_key_checking = settings.get("host_key_checking", True)
        self._transport = None
        self._sftp = None

    def connect(self) -> None:
        try:
            import paramiko
        except ImportError:
            raise RuntimeError("paramiko is required for SFTP. Install: pip install paramiko")

        log(f"Connecting to SFTP://{self.host}:{self.port}")

        self._transport = paramiko.Transport((self.host, self.port))
        self._transport.connect(
            username=self.username,
            password=self.password if self.password else None,
            pkey=self._load_key() if self.key_path else None,
        )
        self._sftp = paramiko.SFTPClient.from_transport(self._transport)
        log(f"Connected successfully to SFTP {self.host}:{self.port}")

    def _load_key(self):
        import paramiko
        passphrase = self.key_passphrase or None
        for key_class in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                return key_class.from_private_key_file(self.key_path, password=passphrase)
            except Exception:
                continue
        raise ValueError(f"Unable to load private key from {self.key_path}")

    def disconnect(self) -> None:
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
        self._sftp = None
        self._transport = None

    def list_directory(self, path: str) -> list[RemoteFile]:
        assert self._sftp is not None
        entries: list[RemoteFile] = []
        try:
            for attr in self._sftp.listdir_attr(path):
                if attr.filename in (".", ".."):
                    continue
                import stat as stat_mod
                is_dir = stat_mod.S_ISDIR(attr.st_mode) if attr.st_mode else False
                mtime = datetime.fromtimestamp(attr.st_mtime or 0, tz=timezone.utc)
                full_path = str(PurePosixPath(path) / attr.filename)
                entries.append(RemoteFile(
                    path=full_path, name=attr.filename,
                    size=attr.st_size or 0, modified=mtime, is_dir=is_dir,
                ))
        except PermissionError:
            log(f"Permission denied listing {path}", "WARN")
        except FileNotFoundError:
            log(f"Directory not found: {path}", "ERROR")
        return entries

    def download(self, remote_path: str) -> bytes:
        assert self._sftp is not None
        buf = io.BytesIO()
        self._sftp.getfo(remote_path, buf)
        return buf.getvalue()

    def rename(self, from_path: str, to_path: str) -> None:
        assert self._sftp is not None
        self._sftp.rename(from_path, to_path)

    def delete(self, path: str) -> None:
        assert self._sftp is not None
        self._sftp.remove(path)

    def mkdir(self, path: str) -> None:
        assert self._sftp is not None
        try:
            self._sftp.mkdir(path)
        except IOError:
            pass

    def file_size(self, path: str) -> int:
        assert self._sftp is not None
        return self._sftp.stat(path).st_size or 0

    @property
    def is_connected(self) -> bool:
        return self._transport is not None and self._transport.is_active()


# ---------------------------------------------------------------------------
# Core Collector Logic
# ---------------------------------------------------------------------------

class FTPSFTPCollector:
    """Main collector orchestrating discovery, filtering, download."""

    def __init__(self, settings: dict[str, Any], recipe: dict[str, Any]):
        self.settings = settings
        self.recipe = recipe
        self.stats = CollectorStats()
        self.circuit_breaker = CircuitBreakerState(
            threshold=settings.get("circuit_breaker_threshold", 5),
            recovery_seconds=settings.get("circuit_breaker_recovery_seconds", 300),
        )
        self._conn: Optional[FTPConnection | SFTPConnection] = None
        self._seen_files: set[str] = set()

    def _create_connection(self) -> FTPConnection | SFTPConnection:
        protocol = self.settings.get("protocol", "FTP")
        if protocol == "SFTP":
            return SFTPConnection(self.settings)
        return FTPConnection(self.settings)

    def _connect_with_retry(self) -> None:
        """Connect with exponential backoff retry."""
        max_attempts = self.settings.get("retry_max_attempts", 5)
        base_delay = self.settings.get("retry_base_delay_seconds", 2.0)
        max_delay = self.settings.get("retry_max_delay_seconds", 300)

        for attempt in range(max_attempts + 1):
            if not self.circuit_breaker.can_execute():
                raise ConnectionError(
                    f"Circuit breaker OPEN — too many consecutive failures. "
                    f"Recovery in {self.circuit_breaker.recovery_seconds}s."
                )

            try:
                self._conn = self._create_connection()
                self._conn.connect()
                self.circuit_breaker.record_success()
                return
            except Exception as e:
                self.circuit_breaker.record_failure()
                self.stats.retry_count += 1

                if attempt == max_attempts:
                    raise ConnectionError(
                        f"Failed to connect after {max_attempts + 1} attempts: {e}"
                    ) from e

                delay = min(base_delay * (2 ** attempt), max_delay)
                jitter = delay * random.uniform(-0.25, 0.25)
                actual_delay = max(0.1, delay + jitter)
                log(f"Connection attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {actual_delay:.1f}s", "WARN")
                time.sleep(actual_delay)

    def _ensure_connected(self) -> None:
        """Reconnect if connection was lost."""
        if self._conn and self._conn.is_connected:
            return
        log("Connection lost, reconnecting...", "WARN")
        self._connect_with_retry()

    def _with_retry(self, operation: str, func, *args, **kwargs):
        """Execute an operation with retry on transient failures."""
        max_attempts = self.settings.get("retry_max_attempts", 5)
        base_delay = self.settings.get("retry_base_delay_seconds", 2.0)
        max_delay = self.settings.get("retry_max_delay_seconds", 300)

        for attempt in range(max_attempts + 1):
            try:
                self._ensure_connected()
                return func(*args, **kwargs)
            except (ConnectionError, OSError, EOFError) as e:
                self.stats.retry_count += 1
                if attempt == max_attempts:
                    raise
                delay = min(base_delay * (2 ** attempt), max_delay)
                jitter = delay * random.uniform(-0.25, 0.25)
                actual_delay = max(0.1, delay + jitter)
                log(f"{operation} attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {actual_delay:.1f}s", "WARN")
                time.sleep(actual_delay)
                # Force reconnect
                if self._conn:
                    self._conn.disconnect()
                    self._conn = None

    # ----- Directory Traversal -----

    def discover_files(self) -> list[RemoteFile]:
        """Discover files according to recipe configuration."""
        remote_path = self.recipe.get("remote_path", "/")
        recursive = self.recipe.get("recursive", False)
        max_depth = self.recipe.get("max_depth", -1) if recursive else 0

        log(f"Scanning {remote_path} (recursive={recursive}, max_depth={max_depth})")

        all_files: list[RemoteFile] = []
        self._scan_directory(remote_path, all_files, current_depth=0, max_depth=max_depth)

        log(f"Discovered {len(all_files)} files in {self.stats.directories_scanned} directories")
        self.stats.files_discovered = len(all_files)

        # Apply filters
        filtered = self._apply_filters(all_files)
        log(f"After filtering: {len(filtered)} files")

        # Apply ordering
        filtered = self._apply_ordering(filtered)

        # Apply discovery mode
        selected = self._apply_discovery_mode(filtered)
        log(f"Selected {len(selected)} files for collection")

        return selected

    def _scan_directory(self, path: str, results: list[RemoteFile],
                        current_depth: int, max_depth: int) -> None:
        """Recursively scan directory tree."""
        # Depth check
        if max_depth >= 0 and current_depth > max_depth:
            return

        # Folder pattern check
        folder_pattern = self.recipe.get("folder_pattern", {})
        if folder_pattern.get("enabled", False) and current_depth > 0:
            if not self._matches_folder_pattern(path, folder_pattern):
                return

        # List directory
        try:
            entries = self._with_retry(
                f"list {path}",
                lambda: self._conn.list_directory(path),
            )
        except Exception as e:
            log(f"Failed to list {path}: {e}", "ERROR")
            self.stats.errors.append(f"list:{path}:{e}")
            return

        self.stats.directories_scanned += 1

        for entry in entries:
            if entry.is_dir:
                # Recurse into subdirectory
                self._scan_directory(entry.path, results, current_depth + 1, max_depth)
            else:
                results.append(entry)

    def _matches_folder_pattern(self, path: str, pattern_config: dict) -> bool:
        """Check if a folder path matches the date-based pattern."""
        fmt = pattern_config.get("format", "yyyyMMdd")
        lookback_days = pattern_config.get("lookback_days", 7)
        tz_name = pattern_config.get("timezone", "UTC")

        now = datetime.now(timezone.utc)
        folder_name = PurePosixPath(path).name

        # Generate valid date strings for the lookback window
        for day_offset in range(lookback_days + 1):
            target_date = now - timedelta(days=day_offset)
            date_str = self._format_date(target_date, fmt)
            if folder_name == date_str or path.endswith(date_str):
                return True

        return False

    @staticmethod
    def _format_date(dt: datetime, fmt: str) -> str:
        """Convert datetime to folder name using Java-style format string."""
        py_fmt = (fmt
                  .replace("yyyy", "%Y")
                  .replace("MM", "%m")
                  .replace("dd", "%d")
                  .replace("HH", "%H")
                  .replace("mm", "%M")
                  .replace("ss", "%S"))
        return dt.strftime(py_fmt)

    # ----- Filtering -----

    def _apply_filters(self, files: list[RemoteFile]) -> list[RemoteFile]:
        """Apply file filter rules from recipe."""
        ff = self.recipe.get("file_filter", {})
        filename_regex = ff.get("filename_regex", ".*")
        path_regex = ff.get("path_regex", "")
        min_size = ff.get("min_size_bytes", 0)
        max_size = ff.get("max_size_bytes", 0)
        max_age_hours = ff.get("max_age_hours", 0)
        exclude_patterns = ff.get("exclude_patterns", [])
        exclude_zero = ff.get("exclude_zero_byte", True)

        # Compile patterns
        try:
            fn_re = re.compile(filename_regex)
        except re.error:
            log(f"Invalid filename_regex: {filename_regex}, using .*", "WARN")
            fn_re = re.compile(".*")

        path_re = None
        if path_regex:
            try:
                path_re = re.compile(path_regex)
            except re.error:
                log(f"Invalid path_regex: {path_regex}, ignoring", "WARN")

        exclude_res = []
        for pat in exclude_patterns:
            try:
                exclude_res.append(re.compile(pat))
            except re.error:
                log(f"Invalid exclude pattern: {pat}, ignoring", "WARN")

        now = datetime.now(timezone.utc)
        result: list[RemoteFile] = []

        for f in files:
            # Zero-byte check
            if exclude_zero and f.size == 0:
                self.stats.files_skipped += 1
                continue

            # Filename regex
            if not fn_re.search(f.name):
                self.stats.files_skipped += 1
                continue

            # Path regex
            if path_re and not path_re.search(f.path):
                self.stats.files_skipped += 1
                continue

            # Exclude patterns
            excluded = False
            for excl in exclude_res:
                if excl.search(f.name):
                    excluded = True
                    break
            if excluded:
                self.stats.files_skipped += 1
                continue

            # Size filter
            if min_size > 0 and f.size < min_size:
                self.stats.files_skipped += 1
                continue
            if max_size > 0 and f.size > max_size:
                self.stats.files_skipped += 1
                continue

            # Age filter
            if max_age_hours > 0:
                age = (now - f.modified).total_seconds() / 3600
                if age > max_age_hours:
                    self.stats.files_skipped += 1
                    continue

            result.append(f)

        return result

    # ----- Ordering -----

    def _apply_ordering(self, files: list[RemoteFile]) -> list[RemoteFile]:
        ordering = self.recipe.get("ordering", "NEWEST_FIRST")
        if ordering == "NEWEST_FIRST":
            return sorted(files, key=lambda f: f.modified, reverse=True)
        elif ordering == "OLDEST_FIRST":
            return sorted(files, key=lambda f: f.modified)
        elif ordering == "NAME_ASC":
            return sorted(files, key=lambda f: f.name)
        elif ordering == "NAME_DESC":
            return sorted(files, key=lambda f: f.name, reverse=True)
        return files

    # ----- Discovery Mode -----

    def _apply_discovery_mode(self, files: list[RemoteFile]) -> list[RemoteFile]:
        mode = self.recipe.get("discovery_mode", "ALL_NEW")

        if mode == "LATEST":
            return files[:1] if files else []
        elif mode == "BATCH":
            batch_size = self.recipe.get("batch_size", 100)
            return files[:batch_size]
        elif mode == "ALL_NEW":
            new_files = [f for f in files if f.path not in self._seen_files]
            for f in new_files:
                self._seen_files.add(f.path)
            return new_files
        else:  # ALL
            return files

    # ----- Completion Check -----

    def _check_completion(self, file: RemoteFile) -> bool:
        """Check if a file is complete and ready for collection."""
        cc = self.recipe.get("completion_check", {})
        strategy = cc.get("strategy", "NONE")

        if strategy == "NONE":
            return True

        if strategy == "MARKER_FILE":
            suffix = cc.get("marker_suffix", ".done")
            marker_path = file.path + suffix
            try:
                self._conn.file_size(marker_path)
                return True
            except Exception:
                log(f"Marker file not found: {marker_path}, skipping {file.name}", "DEBUG")
                return False

        if strategy == "SIZE_STABLE":
            stable_seconds = cc.get("stable_seconds", 10)
            try:
                size1 = self._conn.file_size(file.path)
                time.sleep(stable_seconds)
                size2 = self._conn.file_size(file.path)
                if size1 == size2:
                    return True
                log(f"File {file.name} still changing ({size1}→{size2}), skipping", "DEBUG")
                return False
            except Exception as e:
                log(f"Size check failed for {file.name}: {e}", "WARN")
                return False

        return True

    # ----- Download -----

    def download_file(self, file: RemoteFile) -> Optional[DownloadResult]:
        """Download a single file with retry and checksum."""
        try:
            data = self._with_retry(
                f"download {file.name}",
                lambda: self._conn.download(file.path),
            )
        except Exception as e:
            self.stats.files_failed += 1
            self.stats.errors.append(f"download:{file.path}:{e}")
            log(f"Failed to download {file.path}: {e}", "ERROR")
            return DownloadResult(
                remote_path=file.path, local_data=b"", size=0,
                checksum="", success=False, error_message=str(e),
            )

        checksum = hashlib.sha256(data).hexdigest()

        # Verify checksum if enabled
        if self.recipe.get("checksum_verification", True):
            try:
                data2 = self._with_retry(
                    f"verify {file.name}",
                    lambda: self._conn.download(file.path),
                )
                checksum2 = hashlib.sha256(data2).hexdigest()
                if checksum != checksum2:
                    log(f"Checksum mismatch for {file.name}: {checksum} != {checksum2}", "WARN")
                    # Use second download (more recent)
                    data = data2
                    checksum = checksum2
            except Exception as e:
                log(f"Checksum verification failed for {file.name}: {e}", "WARN")

        self.stats.files_downloaded += 1
        self.stats.bytes_downloaded += len(data)

        return DownloadResult(
            remote_path=file.path, local_data=data,
            size=len(data), checksum=checksum,
        )

    # ----- Post-Collection Action -----

    def _post_action(self, file: RemoteFile) -> None:
        """Execute post-collection action on the remote file."""
        pa = self.recipe.get("post_action", {})
        action = pa.get("action", "KEEP")

        if action == "KEEP":
            return

        try:
            if action == "DELETE":
                self._with_retry(f"delete {file.name}", lambda: self._conn.delete(file.path))
                log(f"Deleted remote file: {file.path}", "DEBUG")

            elif action == "MOVE":
                target_dir = pa.get("move_target", "/archive")
                conflict = pa.get("conflict_resolution", "TIMESTAMP")
                target_path = str(PurePosixPath(target_dir) / file.name)

                # Handle conflict
                if conflict == "TIMESTAMP":
                    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                    stem = PurePosixPath(file.name).stem
                    suffix = PurePosixPath(file.name).suffix
                    target_path = str(PurePosixPath(target_dir) / f"{stem}_{ts}{suffix}")

                self._with_retry(f"mkdir {target_dir}", lambda: self._conn.mkdir(target_dir))
                self._with_retry(f"move {file.name}", lambda: self._conn.rename(file.path, target_path))
                log(f"Moved: {file.path} → {target_path}", "DEBUG")

            elif action == "RENAME":
                suffix = pa.get("rename_suffix", ".processed")
                new_path = file.path + suffix
                self._with_retry(f"rename {file.name}", lambda: self._conn.rename(file.path, new_path))
                log(f"Renamed: {file.path} → {new_path}", "DEBUG")

        except Exception as e:
            log(f"Post-action {action} failed for {file.path}: {e}", "WARN")
            self.stats.errors.append(f"post_action:{file.path}:{e}")

    # ----- Main Execute -----

    def execute(self) -> dict[str, Any]:
        """Run the full collection cycle."""
        try:
            self._connect_with_retry()
        except ConnectionError as e:
            error(str(e), "CONNECTION_ERROR")
            return self._build_summary()

        try:
            status(0.1)
            files = self.discover_files()
            status(0.3)

            if not files:
                log("No files to collect")
                status(1.0)
                return self._build_summary()

            total = len(files)
            for idx, file in enumerate(files):
                progress = 0.3 + (0.6 * (idx / total))
                status(progress)

                # Completion check
                if not self._check_completion(file):
                    self.stats.files_skipped += 1
                    continue

                # Download
                result = self.download_file(file)
                if result and result.success:
                    # Emit output
                    output({
                        "remote_path": result.remote_path,
                        "filename": file.name,
                        "size": result.size,
                        "checksum": result.checksum,
                        "modified": file.modified.isoformat(),
                        "content_base64_length": len(result.local_data),
                    })

                    # Post-action
                    self._post_action(file)

            status(1.0)

        except Exception as e:
            error(f"Collection failed: {e}", "COLLECTION_ERROR")
            self.stats.errors.append(f"execute:{e}")

        finally:
            if self._conn:
                self._conn.disconnect()

        return self._build_summary()

    def _build_summary(self) -> dict[str, Any]:
        return {
            "files_discovered": self.stats.files_discovered,
            "files_downloaded": self.stats.files_downloaded,
            "files_skipped": self.stats.files_skipped,
            "files_failed": self.stats.files_failed,
            "bytes_downloaded": self.stats.bytes_downloaded,
            "directories_scanned": self.stats.directories_scanned,
            "retry_count": self.stats.retry_count,
            "errors": self.stats.errors[:20],  # Limit error list
        }


# ---------------------------------------------------------------------------
# Plugin entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    settings: dict[str, Any] = {}
    recipe: dict[str, Any] = {}

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = msg.get("type")

        if msg_type == "CONFIGURE":
            settings = msg.get("settings", msg.get("config", {}))
            recipe = msg.get("recipe", {})
            protocol = settings.get("protocol", "FTP")
            host = settings.get("host", "?")
            log(f"Configured FTP/SFTP collector: {protocol}://{host}")

        elif msg_type == "EXECUTE":
            # Merge any execution-time overrides
            exec_recipe = msg.get("recipe", recipe) or recipe
            if not exec_recipe:
                exec_recipe = msg.get("config", recipe)

            if not settings.get("host"):
                error("No host configured", "CONFIG_ERROR")
                done({"files_downloaded": 0})
                continue

            collector = FTPSFTPCollector(settings, exec_recipe)
            summary = collector.execute()
            done(summary)


if __name__ == "__main__":
    main()
