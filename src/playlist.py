"""Playlist generation and management."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    import sqlite3
    from .db import Database
    from .query import QueryFilter


class PlaylistGenerator:
    """Generate VLC-compatible playlists."""

    def __init__(self, db: Database):
        self.db = db

    def _format_duration(self, runtime_minutes: int | None) -> int:
        """Convert runtime in minutes to seconds for M3U."""
        if runtime_minutes:
            return runtime_minutes * 60
        return -1  # Unknown duration

    def _get_display_title(self, row: sqlite3.Row) -> str:
        """Get display title for a media file."""
        title = row["title"] or row["filename"]
        if row["year"]:
            return f"{title} ({row['year']})"
        return title

    def _resolve_path(
        self,
        full_path: str,
        relative_path: str,
        path_prefix: str | None,
        prepend_path: str | None,
    ) -> str:
        """Apply path-prefix or prepend-path transformation."""
        if path_prefix:
            return f"{path_prefix.rstrip('/')}/{relative_path}"
        if prepend_path:
            # Keep the full original path; prepend the new prefix.
            sep = "" if full_path.startswith("/") else "/"
            return f"{prepend_path.rstrip('/')}{sep}{full_path}"
        return full_path

    def generate_m3u8(
        self,
        file_ids: list[int] | None = None,
        playlist_id: int | None = None,
        query_results: list[sqlite3.Row] | None = None,
        path_prefix: str | None = None,
        prepend_path: str | None = None,
        include_metadata: bool = True,
    ) -> str:
        """
        Generate M3U8 playlist content.

        path_prefix replaces the scan root with a new prefix (e.g. an SMB share
        that exposes the root directly). prepend_path keeps the original
        absolute path intact and just prepends the new prefix (e.g. an SMB
        share that exposes the parent of the scan root). Pass at most one.
        """
        lines = ["#EXTM3U"]

        # Get items based on input
        if query_results is not None:
            items = query_results
        elif playlist_id is not None:
            items = self.db.get_playlist_items(playlist_id)
        elif file_ids is not None:
            # Fetch full info for each file ID
            items = []
            for fid in file_ids:
                rows = self.db.fetchall(
                    "SELECT * FROM v_media_full WHERE file_id = ?", (fid,)
                )
                items.extend(rows)
        else:
            return "#EXTM3U\n"

        for row in items:
            full_path = self._resolve_path(
                row["full_path"], row["relative_path"], path_prefix, prepend_path
            )

            if include_metadata:
                duration = self._format_duration(row["runtime"])
                title = self._get_display_title(row)
                lines.append(f"#EXTINF:{duration},{title}")

            lines.append(full_path)

        return "\n".join(lines) + "\n"

    def generate_xspf(
        self,
        file_ids: list[int] | None = None,
        playlist_id: int | None = None,
        query_results: list[sqlite3.Row] | None = None,
        path_prefix: str | None = None,
        prepend_path: str | None = None,
        playlist_title: str = "VLC Playlist",
    ) -> str:
        """
        Generate XSPF (XML) playlist content.

        See generate_m3u8 for path_prefix vs prepend_path semantics.
        """
        # Get items
        if query_results is not None:
            items = query_results
        elif playlist_id is not None:
            items = self.db.get_playlist_items(playlist_id)
        elif file_ids is not None:
            items = []
            for fid in file_ids:
                rows = self.db.fetchall(
                    "SELECT * FROM v_media_full WHERE file_id = ?", (fid,)
                )
                items.extend(rows)
        else:
            items = []

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<playlist xmlns="http://xspf.org/ns/0/" version="1">',
            f"  <title>{self._escape_xml(playlist_title)}</title>",
            "  <trackList>",
        ]

        for row in items:
            full_path = self._resolve_path(
                row["full_path"], row["relative_path"], path_prefix, prepend_path
            )

            title = self._get_display_title(row)
            duration_ms = (row["runtime"] or 0) * 60 * 1000

            # If full_path already has a URI scheme (smb://, http://, ftp://, ...),
            # preserve it. Otherwise wrap with file://. In both cases, percent-
            # encode only characters that would actually break the URI — keep
            # '/', ':' (Windows drives, host:port), and '@' (user@host) intact.
            if "://" in full_path:
                scheme, _, rest = full_path.partition("://")
                file_uri = f"{scheme}://{quote(rest, safe='/:@')}"
            else:
                file_uri = "file://" + quote(full_path, safe="/:@")

            lines.append("    <track>")
            lines.append(f"      <location>{file_uri}</location>")
            lines.append(f"      <title>{self._escape_xml(title)}</title>")
            if duration_ms > 0:
                lines.append(f"      <duration>{duration_ms}</duration>")
            if row["plot"]:
                lines.append(f"      <annotation>{self._escape_xml(row['plot'][:500])}</annotation>")
            lines.append("    </track>")

        lines.extend([
            "  </trackList>",
            "</playlist>",
        ])

        return "\n".join(lines)

    def _escape_xml(self, text: str) -> str:
        """Escape special XML characters."""
        if not text:
            return ""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    def save_playlist(
        self,
        output_path: Path | str,
        file_ids: list[int] | None = None,
        playlist_id: int | None = None,
        query_results: list[sqlite3.Row] | None = None,
        path_prefix: str | None = None,
        prepend_path: str | None = None,
        format: str = "m3u8",
        limit: int | None = None,
    ) -> tuple[Path, int]:
        """Save playlist to file. See generate_m3u8 for path_prefix /
        prepend_path semantics."""
        output_path = Path(output_path)

        # Apply limit to playlist items if exporting by playlist_id
        if playlist_id is not None and query_results is None and file_ids is None:
            items = self.db.get_playlist_items(playlist_id)
            if limit:
                items = items[:limit]
            query_results = items

        if format.lower() == "xspf":
            content = self.generate_xspf(
                file_ids=file_ids,
                playlist_id=None,  # Already loaded above
                query_results=query_results,
                path_prefix=path_prefix,
                prepend_path=prepend_path,
                playlist_title=output_path.stem,
            )
        else:
            content = self.generate_m3u8(
                file_ids=file_ids,
                playlist_id=None,  # Already loaded above
                query_results=query_results,
                path_prefix=path_prefix,
                prepend_path=prepend_path,
            )

        output_path.write_text(content, encoding="utf-8")

        # Count items
        item_count = len(file_ids or query_results or [])
        return output_path, item_count

    def create_smart_playlist(
        self,
        name: str,
        filter_string: str,
        description: str | None = None,
    ) -> int:
        """
        Create a smart playlist that dynamically generates from a query.

        Args:
            name: Playlist name
            filter_string: Filter string (see query.parse_filter_string)
            description: Optional description

        Returns:
            playlist_id
        """
        return self.db.create_playlist(
            name=name,
            description=description,
            is_smart=True,
            smart_query=filter_string,
        )

    def create_static_playlist(
        self,
        name: str,
        file_ids: list[int],
        description: str | None = None,
    ) -> int:
        """
        Create a static playlist with specific files.

        Args:
            name: Playlist name
            file_ids: List of file IDs to include
            description: Optional description

        Returns:
            playlist_id
        """
        playlist_id = self.db.create_playlist(
            name=name,
            description=description,
            is_smart=False,
        )

        for position, file_id in enumerate(file_ids):
            self.db.add_to_playlist(playlist_id, file_id, position)

        return playlist_id

    def export_smart_playlist(
        self,
        playlist_id: int,
        output_path: Path | str,
        path_prefix: str | None = None,
        prepend_path: str | None = None,
        format: str = "m3u8",
        limit: int | None = None,
    ) -> tuple[Path, int]:
        """Export a smart playlist by re-running its query (or load static
        items). See generate_m3u8 for path_prefix / prepend_path semantics."""
        from .query import QueryBuilder, parse_filter_string

        playlist = self.db.fetchone(
            "SELECT * FROM playlists WHERE playlist_id = ?", (playlist_id,)
        )

        if not playlist:
            raise ValueError(f"Playlist {playlist_id} not found")

        if playlist["is_smart"] and playlist["smart_query"]:
            filters = parse_filter_string(playlist["smart_query"])
            if limit:
                filters.limit = limit
            query_builder = QueryBuilder(self.db)
            results = query_builder.execute(filters)
        else:
            results = self.db.get_playlist_items(playlist_id)
            if limit:
                results = results[:limit]

        return self.save_playlist(
            output_path=output_path,
            query_results=results,
            path_prefix=path_prefix,
            prepend_path=prepend_path,
            format=format,
        )
