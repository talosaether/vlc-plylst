"""File system scanner with NFO detection."""

from __future__ import annotations

import os
from dataclasses import dataclass
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

# Default minimum file size (100 MB) - skip smaller files as likely extras/trailers
DEFAULT_MIN_SIZE_MB = 100

# Directory names to skip (case-insensitive)
SKIP_DIRECTORIES: frozenset[str] = frozenset({
    "trailers", "trailer",
    "extras", "extra",
    "featurettes", "featurette",
    "behind the scenes", "behindthescenes",
    "deleted scenes", "deletedscenes",
    "interviews", "interview",
    "shorts", "short",
    "samples", "sample",
    "specials",
    "bonus",
    "promos", "promo",
    "scenes",
    "other",
})

# Filename patterns to skip (case-insensitive, checked as substrings)
SKIP_FILENAME_PATTERNS: tuple[str, ...] = (
    "-trailer",
    ".trailer",
    "_trailer",
    "-sample",
    ".sample",
    "_sample",
    "-short",
    "-featurette",
    "-interview",
    "-extra",
    "-deleted",
    "-promo",
    "-behindthescenes",
    "-scene",
)


@dataclass
class ScanStats:
    """Statistics for a scan operation."""

    files_scanned: int = 0
    files_added: int = 0
    files_updated: int = 0
    files_skipped: int = 0
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
        min_size_mb: int = DEFAULT_MIN_SIZE_MB,
    ):
        self.db = db
        self.progress_callback = progress_callback
        self.min_size_bytes = min_size_mb * 1024 * 1024
        self._current_scan_version = 0
        self._last_scanned: datetime | None = None

    def _report_progress(self, progress: ScanProgress) -> None:
        """Report progress if callback is set."""
        if self.progress_callback:
            self.progress_callback(progress)

    def _is_video_file(self, path: Path) -> bool:
        """Check if path is a video file."""
        return path.suffix.lower() in VIDEO_EXTENSIONS

    def _should_skip_directory(self, dir_name: str) -> bool:
        """Check if directory should be skipped (trailers, extras, etc.)."""
        return dir_name.lower() in SKIP_DIRECTORIES

    def _should_skip_file(self, filename: str, file_size: int) -> bool:
        """Check if file should be skipped based on name patterns or size."""
        # Skip small files
        if file_size < self.min_size_bytes:
            return True

        # Skip files matching trailer/extra patterns
        filename_lower = filename.lower()
        for pattern in SKIP_FILENAME_PATTERNS:
            if pattern in filename_lower:
                return True

        return False

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

    def _should_skip_unchanged_dir(self, dirpath: str) -> bool:
        """Check if directory can be skipped (unchanged since last scan)."""
        if self._last_scanned is None:
            return False
        try:
            dir_mtime = datetime.fromtimestamp(os.path.getmtime(dirpath))
            return dir_mtime < self._last_scanned
        except OSError:
            return False

    def discover_files(self, root_path: Path) -> tuple[list[FileInfo], int, int]:
        """Discover all video files in a directory tree.

        Returns:
            Tuple of (list of FileInfo, count of skipped files, count of skipped dirs)
        """
        files: list[FileInfo] = []
        skipped = 0
        skipped_dirs = 0

        for dirpath, dirnames, filenames in os.walk(root_path):
            # Filter out directories we want to skip (modifies in-place to prevent descent)
            dirnames[:] = [d for d in dirnames if not self._should_skip_directory(d)]

            # Skip unchanged directories (but not the root itself)
            if dirpath != str(root_path) and self._should_skip_unchanged_dir(dirpath):
                skipped_dirs += 1
                dirnames.clear()  # Don't descend
                continue

            for filename in filenames:
                file_path = Path(dirpath) / filename

                if not self._is_video_file(file_path):
                    continue

                try:
                    stat = file_path.stat()

                    # Skip small files and files matching skip patterns
                    if self._should_skip_file(filename, stat.st_size):
                        skipped += 1
                        continue

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

        return files, skipped, skipped_dirs

    def scan_root(
        self,
        root_path: str | Path,
        label: str | None = None,
    ) -> ScanStats:
        """
        Scan a root directory for video files.

        Args:
            root_path: Path to scan
            label: Optional label for this root

        Returns:
            ScanStats with scan results
        """
        root_path = Path(root_path).resolve()
        if not root_path.is_dir():
            raise ValueError(f"Not a directory: {root_path}")

        stats = ScanStats()

        # Get or create root
        root_id = self.db.upsert_root(str(root_path), label)

        # Get last scan time for incremental optimization
        root_record = self.db.get_root(root_id)
        if root_record and root_record["last_scanned"]:
            self._last_scanned = datetime.fromisoformat(root_record["last_scanned"])
        else:
            self._last_scanned = None

        # Create scan session
        scan_id = self.db.create_scan_session(root_id, scan_type="index")

        # Increment scan version for orphan detection
        self._current_scan_version = (
            self.db.fetchone(
                "SELECT COALESCE(MAX(scan_version), 0) + 1 as v FROM media_files WHERE root_id = ?",
                (root_id,),
            )["v"]
        )

        # Phase 1: Discover files
        self._report_progress(ScanProgress(phase="scanning", current_file=str(root_path)))

        files, skipped, skipped_dirs = self.discover_files(root_path)
        stats.files_skipped = skipped
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

        # Phase 3: Mark missing files
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
