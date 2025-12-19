"""File system scanner with hashing and NFO detection."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .db import Database

# All supported video extensions
VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    # Common formats
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    # MPEG variants
    ".mpeg", ".mpg", ".mpe", ".m2v", ".m2p", ".m2ts", ".mts",
    # Broadcast/DVD
    ".ts", ".vob", ".ifo",
    # Other
    ".ogv", ".ogg", ".3gp", ".3g2", ".f4v", ".divx", ".xvid",
    ".rm", ".rmvb", ".asf", ".dv", ".mxf",
})

# Hash buffer size (64KB)
HASH_BUFFER_SIZE = 65536


@dataclass
class ScanStats:
    """Statistics for a scan operation."""

    files_scanned: int = 0
    files_added: int = 0
    files_updated: int = 0
    files_hashed: int = 0
    nfos_found: int = 0
    errors: int = 0
    bytes_scanned: int = 0


@dataclass
class ScanProgress:
    """Progress information for callbacks."""

    current_file: str = ""
    files_processed: int = 0
    total_files: int | None = None
    bytes_processed: int = 0
    total_bytes: int | None = None
    phase: str = "scanning"  # scanning, hashing, parsing


ProgressCallback = Callable[[ScanProgress], None]


@dataclass
class FileInfo:
    """Information about a discovered file."""

    path: Path
    relative_path: str
    filename: str
    size: int
    mtime: str
    nfo_path: Path | None = None
    nfo_mtime: str | None = None


class Scanner:
    """Recursive directory scanner for video files."""

    def __init__(
        self,
        db: Database,
        progress_callback: ProgressCallback | None = None,
    ):
        self.db = db
        self.progress_callback = progress_callback
        self._current_scan_version = 0

    def _report_progress(self, progress: ScanProgress) -> None:
        """Report progress if callback is set."""
        if self.progress_callback:
            self.progress_callback(progress)

    def _is_video_file(self, path: Path) -> bool:
        """Check if path is a video file."""
        return path.suffix.lower() in VIDEO_EXTENSIONS

    def _get_nfo_path(self, video_path: Path) -> Path | None:
        """Find NFO file for a video (same basename)."""
        nfo_path = video_path.with_suffix(".nfo")
        if nfo_path.exists():
            return nfo_path
        return None

    def _get_file_mtime(self, path: Path) -> str:
        """Get file modification time as ISO string."""
        mtime = os.path.getmtime(path)
        return datetime.fromtimestamp(mtime).isoformat()

    def discover_files(self, root_path: Path) -> list[FileInfo]:
        """Discover all video files in a directory tree."""
        files: list[FileInfo] = []

        for dirpath, _dirnames, filenames in os.walk(root_path):
            for filename in filenames:
                file_path = Path(dirpath) / filename

                if not self._is_video_file(file_path):
                    continue

                try:
                    stat = file_path.stat()
                    relative = file_path.relative_to(root_path)

                    nfo_path = self._get_nfo_path(file_path)
                    nfo_mtime = None
                    if nfo_path:
                        nfo_mtime = self._get_file_mtime(nfo_path)

                    files.append(
                        FileInfo(
                            path=file_path,
                            relative_path=str(relative),
                            filename=filename,
                            size=stat.st_size,
                            mtime=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            nfo_path=nfo_path,
                            nfo_mtime=nfo_mtime,
                        )
                    )
                except OSError:
                    continue  # Skip files we can't stat

        return files

    def compute_sha256(self, file_path: Path) -> str:
        """Compute SHA256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(HASH_BUFFER_SIZE):
                sha256.update(chunk)
        return sha256.hexdigest()

    def scan_root(
        self,
        root_path: str | Path,
        label: str | None = None,
        compute_hashes: bool = True,
        incremental: bool = True,
    ) -> ScanStats:
        """
        Scan a root directory for video files.

        Args:
            root_path: Path to scan
            label: Optional label for this root
            compute_hashes: Whether to compute file hashes
            incremental: Only hash new/changed files if True

        Returns:
            ScanStats with scan results
        """
        root_path = Path(root_path).resolve()
        if not root_path.is_dir():
            raise ValueError(f"Not a directory: {root_path}")

        stats = ScanStats()

        # Get or create root
        root_id = self.db.upsert_root(str(root_path), label)

        # Create scan session
        scan_id = self.db.create_scan_session(
            root_id, scan_type="incremental" if incremental else "full"
        )

        # Increment scan version for orphan detection
        self._current_scan_version = (
            self.db.fetchone(
                "SELECT COALESCE(MAX(scan_version), 0) + 1 as v FROM media_files WHERE root_id = ?",
                (root_id,),
            )["v"]
        )

        # Phase 1: Discover files
        self._report_progress(ScanProgress(phase="scanning", current_file=str(root_path)))

        files = self.discover_files(root_path)
        total_bytes = sum(f.size for f in files)

        self._report_progress(
            ScanProgress(
                phase="scanning",
                total_files=len(files),
                total_bytes=total_bytes,
            )
        )

        # Phase 2: Process files
        for i, file_info in enumerate(files):
            try:
                self._report_progress(
                    ScanProgress(
                        phase="indexing",
                        current_file=file_info.relative_path,
                        files_processed=i,
                        total_files=len(files),
                        bytes_processed=stats.bytes_scanned,
                        total_bytes=total_bytes,
                    )
                )

                # Check if file already exists
                existing = self.db.get_media_file_by_path(root_id, file_info.relative_path)

                # Upsert file record
                file_id = self.db.upsert_media_file(
                    root_id=root_id,
                    relative_path=file_info.relative_path,
                    filename=file_info.filename,
                    file_size=file_info.size,
                    file_mtime=file_info.mtime,
                    scan_version=self._current_scan_version,
                )

                if existing is None:
                    stats.files_added += 1
                else:
                    stats.files_updated += 1

                # Update NFO info if found
                if file_info.nfo_path:
                    nfo_relative = str(file_info.nfo_path.relative_to(root_path))
                    self.db.update_nfo_info(file_id, nfo_relative, file_info.nfo_mtime)
                    stats.nfos_found += 1

                stats.files_scanned += 1
                stats.bytes_scanned += file_info.size

            except Exception as e:
                self.db.log_scan_error(
                    scan_id, file_info.relative_path, "index", str(e)
                )
                stats.errors += 1

        # Phase 3: Compute hashes for new/changed files
        if compute_hashes:
            files_to_hash = self.db.get_files_needing_hash(root_id, limit=10000)

            if not incremental:
                # Full scan - hash all files
                files_to_hash = self.db.fetchall(
                    "SELECT * FROM media_files WHERE root_id = ? AND is_missing = 0",
                    (root_id,),
                )

            for i, row in enumerate(files_to_hash):
                file_path = root_path / row["relative_path"]

                self._report_progress(
                    ScanProgress(
                        phase="hashing",
                        current_file=row["relative_path"],
                        files_processed=i,
                        total_files=len(files_to_hash),
                    )
                )

                try:
                    file_hash = self.compute_sha256(file_path)
                    self.db.update_file_hash(row["file_id"], file_hash)
                    stats.files_hashed += 1
                except Exception as e:
                    self.db.log_scan_error(
                        scan_id, row["relative_path"], "hash", str(e)
                    )
                    stats.errors += 1

        # Phase 4: Mark missing files
        missing_count = self.db.mark_files_missing(root_id, self._current_scan_version)

        # Update scan session
        self.db.finish_scan_session(
            scan_id,
            files_scanned=stats.files_scanned,
            files_added=stats.files_added,
            files_updated=stats.files_updated,
            files_removed=missing_count,
            nfos_parsed=0,  # Parsing happens separately
            errors_count=stats.errors,
        )

        # Update root last_scanned
        self.db.update_root_scan_time(root_id)

        return stats

    def get_files_with_nfo(self, root_id: int | None = None) -> list[dict]:
        """Get all files that have NFO files needing parsing."""
        if root_id:
            rows = self.db.fetchall(
                """
                SELECT mf.*, r.root_path
                FROM media_files mf
                JOIN roots r ON mf.root_id = r.root_id
                WHERE mf.root_id = ?
                  AND mf.nfo_path IS NOT NULL
                  AND mf.is_missing = 0
                  AND (mf.nfo_parsed_at IS NULL OR mf.nfo_mtime > mf.nfo_parsed_at)
                """,
                (root_id,),
            )
        else:
            rows = self.db.fetchall(
                """
                SELECT mf.*, r.root_path
                FROM media_files mf
                JOIN roots r ON mf.root_id = r.root_id
                WHERE mf.nfo_path IS NOT NULL
                  AND mf.is_missing = 0
                  AND (mf.nfo_parsed_at IS NULL OR mf.nfo_mtime > mf.nfo_parsed_at)
                """
            )

        return [dict(row) for row in rows]
