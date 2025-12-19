"""Database connection management and operations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from collections.abc import Sequence

# Path to schema.sql relative to this file
SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"

# Default database location
DEFAULT_DB_PATH = Path.home() / ".vlc-plylst" / "media.db"


class Database:
    """SQLite database manager with connection pooling and schema initialization."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            self._conn.row_factory = sqlite3.Row
            # Enable foreign keys and WAL mode
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def init_schema(self) -> None:
        """Initialize database schema from schema.sql."""
        schema_sql = SCHEMA_PATH.read_text()
        self.conn.executescript(schema_sql)
        self.conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        """Context manager for database transactions."""
        cursor = self.conn.cursor()
        try:
            yield cursor
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

    def execute(
        self, sql: str, params: Sequence[Any] | dict[str, Any] = ()
    ) -> sqlite3.Cursor:
        """Execute a single SQL statement."""
        return self.conn.execute(sql, params)

    def executemany(
        self, sql: str, params_seq: Sequence[Sequence[Any] | dict[str, Any]]
    ) -> sqlite3.Cursor:
        """Execute SQL statement for multiple parameter sets."""
        return self.conn.executemany(sql, params_seq)

    def fetchone(
        self, sql: str, params: Sequence[Any] | dict[str, Any] = ()
    ) -> sqlite3.Row | None:
        """Execute and fetch single row."""
        return self.conn.execute(sql, params).fetchone()

    def fetchall(
        self, sql: str, params: Sequence[Any] | dict[str, Any] = ()
    ) -> list[sqlite3.Row]:
        """Execute and fetch all rows."""
        return self.conn.execute(sql, params).fetchall()

    # =========================================================================
    # ROOT OPERATIONS
    # =========================================================================

    def upsert_root(
        self, root_path: str, label: str | None = None
    ) -> int:
        """Insert or update a root directory, returning root_id."""
        self.execute(
            """
            INSERT INTO roots (root_path, label)
            VALUES (?, ?)
            ON CONFLICT(root_path) DO UPDATE SET
                label = COALESCE(excluded.label, roots.label),
                is_active = 1
            """,
            (root_path, label),
        )
        self.conn.commit()
        row = self.fetchone("SELECT root_id FROM roots WHERE root_path = ?", (root_path,))
        return row["root_id"]

    def get_root(self, root_id: int) -> sqlite3.Row | None:
        """Get root by ID."""
        return self.fetchone("SELECT * FROM roots WHERE root_id = ?", (root_id,))

    def get_root_by_path(self, root_path: str) -> sqlite3.Row | None:
        """Get root by path."""
        return self.fetchone("SELECT * FROM roots WHERE root_path = ?", (root_path,))

    def list_roots(self, active_only: bool = True) -> list[sqlite3.Row]:
        """List all root directories."""
        if active_only:
            return self.fetchall("SELECT * FROM roots WHERE is_active = 1")
        return self.fetchall("SELECT * FROM roots")

    def update_root_scan_time(self, root_id: int) -> None:
        """Update last_scanned timestamp for a root."""
        self.execute(
            "UPDATE roots SET last_scanned = ? WHERE root_id = ?",
            (datetime.now().isoformat(), root_id),
        )
        self.conn.commit()

    # =========================================================================
    # MEDIA FILE OPERATIONS
    # =========================================================================

    def upsert_media_file(
        self,
        root_id: int,
        relative_path: str,
        filename: str,
        file_size: int,
        file_mtime: str,
        scan_version: int = 0,
    ) -> int:
        """Insert or update a media file, returning file_id."""
        now = datetime.now().isoformat()
        self.execute(
            """
            INSERT INTO media_files (root_id, relative_path, filename, file_size, file_mtime, scan_version, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(root_id, relative_path) DO UPDATE SET
                filename = excluded.filename,
                file_size = excluded.file_size,
                file_mtime = excluded.file_mtime,
                scan_version = excluded.scan_version,
                last_seen = excluded.last_seen,
                is_missing = 0
            """,
            (root_id, relative_path, filename, file_size, file_mtime, scan_version, now),
        )
        self.conn.commit()
        row = self.fetchone(
            "SELECT file_id FROM media_files WHERE root_id = ? AND relative_path = ?",
            (root_id, relative_path),
        )
        return row["file_id"]

    def get_media_file(self, file_id: int) -> sqlite3.Row | None:
        """Get media file by ID."""
        return self.fetchone("SELECT * FROM media_files WHERE file_id = ?", (file_id,))

    def get_media_file_by_path(
        self, root_id: int, relative_path: str
    ) -> sqlite3.Row | None:
        """Get media file by root and relative path."""
        return self.fetchone(
            "SELECT * FROM media_files WHERE root_id = ? AND relative_path = ?",
            (root_id, relative_path),
        )

    def update_file_hash(self, file_id: int, sha256_hash: str) -> None:
        """Update file hash and hash timestamp."""
        now = datetime.now().isoformat()
        self.execute(
            "UPDATE media_files SET sha256_hash = ?, last_hashed = ? WHERE file_id = ?",
            (sha256_hash, now, file_id),
        )
        self.conn.commit()

    def update_nfo_info(
        self, file_id: int, nfo_path: str, nfo_mtime: str
    ) -> None:
        """Update NFO file information."""
        now = datetime.now().isoformat()
        self.execute(
            """
            UPDATE media_files
            SET nfo_path = ?, nfo_mtime = ?, nfo_parsed_at = ?
            WHERE file_id = ?
            """,
            (nfo_path, nfo_mtime, now, file_id),
        )
        self.conn.commit()

    def mark_files_missing(self, root_id: int, scan_version: int) -> int:
        """Mark files not seen in current scan as missing. Returns count."""
        cursor = self.execute(
            """
            UPDATE media_files
            SET is_missing = 1
            WHERE root_id = ? AND scan_version < ? AND is_missing = 0
            """,
            (root_id, scan_version),
        )
        self.conn.commit()
        return cursor.rowcount

    def get_files_needing_hash(self, root_id: int, limit: int = 100) -> list[sqlite3.Row]:
        """Get files that need hashing (new or changed)."""
        return self.fetchall(
            """
            SELECT * FROM media_files
            WHERE root_id = ? AND is_missing = 0
              AND (last_hashed IS NULL OR file_mtime > last_hashed)
            LIMIT ?
            """,
            (root_id, limit),
        )

    def find_duplicates(self) -> list[sqlite3.Row]:
        """Find files with duplicate hashes."""
        return self.fetchall("SELECT * FROM v_duplicates")

    # =========================================================================
    # METADATA OPERATIONS
    # =========================================================================

    def upsert_metadata(self, file_id: int, **fields: Any) -> int:
        """Insert or update media metadata."""
        # Build dynamic upsert
        columns = ["file_id"] + list(fields.keys())
        placeholders = ["?"] * len(columns)
        values = [file_id] + list(fields.values())

        update_parts = [f"{k} = excluded.{k}" for k in fields.keys()]

        sql = f"""
            INSERT INTO media_metadata ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
            ON CONFLICT(file_id) DO UPDATE SET
                {', '.join(update_parts)}
        """
        self.execute(sql, values)
        self.conn.commit()

        row = self.fetchone(
            "SELECT metadata_id FROM media_metadata WHERE file_id = ?", (file_id,)
        )
        return row["metadata_id"]

    def get_metadata(self, file_id: int) -> sqlite3.Row | None:
        """Get metadata for a file."""
        return self.fetchone(
            "SELECT * FROM media_metadata WHERE file_id = ?", (file_id,)
        )

    # =========================================================================
    # LOOKUP TABLE OPERATIONS (Genres, Tags, etc.)
    # =========================================================================

    def _get_or_create_lookup(
        self, table: str, id_col: str, name_col: str, name: str
    ) -> int:
        """Get or create a lookup table entry, returning ID."""
        row = self.fetchone(
            f"SELECT {id_col} FROM {table} WHERE {name_col} = ?", (name,)
        )
        if row:
            return row[id_col]

        self.execute(f"INSERT INTO {table} ({name_col}) VALUES (?)", (name,))
        self.conn.commit()
        row = self.fetchone(
            f"SELECT {id_col} FROM {table} WHERE {name_col} = ?", (name,)
        )
        return row[id_col]

    def get_or_create_genre(self, name: str) -> int:
        """Get or create genre, returning genre_id."""
        return self._get_or_create_lookup("genres", "genre_id", "name", name)

    def get_or_create_tag(self, name: str) -> int:
        """Get or create tag, returning tag_id."""
        return self._get_or_create_lookup("tags", "tag_id", "name", name)

    def get_or_create_country(self, name: str) -> int:
        """Get or create country, returning country_id."""
        return self._get_or_create_lookup("countries", "country_id", "name", name)

    def get_or_create_studio(self, name: str) -> int:
        """Get or create studio, returning studio_id."""
        return self._get_or_create_lookup("studios", "studio_id", "name", name)

    def get_or_create_person(
        self, name: str, thumb_url: str | None = None
    ) -> int:
        """Get or create person, returning person_id."""
        row = self.fetchone(
            "SELECT person_id FROM people WHERE name = ? AND imdb_id IS NULL", (name,)
        )
        if row:
            return row["person_id"]

        self.execute(
            "INSERT INTO people (name, thumb_url) VALUES (?, ?)", (name, thumb_url)
        )
        self.conn.commit()
        row = self.fetchone(
            "SELECT person_id FROM people WHERE name = ? AND imdb_id IS NULL", (name,)
        )
        return row["person_id"]

    # =========================================================================
    # JUNCTION TABLE OPERATIONS
    # =========================================================================

    def link_genre(self, file_id: int, genre_id: int) -> None:
        """Link a file to a genre."""
        self.execute(
            "INSERT OR IGNORE INTO media_genres (file_id, genre_id) VALUES (?, ?)",
            (file_id, genre_id),
        )
        self.conn.commit()

    def link_tag(self, file_id: int, tag_id: int) -> None:
        """Link a file to a tag."""
        self.execute(
            "INSERT OR IGNORE INTO media_tags (file_id, tag_id) VALUES (?, ?)",
            (file_id, tag_id),
        )
        self.conn.commit()

    def link_country(self, file_id: int, country_id: int) -> None:
        """Link a file to a country."""
        self.execute(
            "INSERT OR IGNORE INTO media_countries (file_id, country_id) VALUES (?, ?)",
            (file_id, country_id),
        )
        self.conn.commit()

    def link_studio(self, file_id: int, studio_id: int, order: int = 0) -> None:
        """Link a file to a studio."""
        self.execute(
            """
            INSERT OR IGNORE INTO media_studios (file_id, studio_id, display_order)
            VALUES (?, ?, ?)
            """,
            (file_id, studio_id, order),
        )
        self.conn.commit()

    def link_actor(
        self,
        file_id: int,
        person_id: int,
        role: str | None = None,
        order: int = 0,
        thumb_url: str | None = None,
    ) -> None:
        """Link a file to an actor with role information."""
        self.execute(
            """
            INSERT OR REPLACE INTO media_actors (file_id, person_id, role, display_order, thumb_url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (file_id, person_id, role, order, thumb_url),
        )
        self.conn.commit()

    def link_director(self, file_id: int, person_id: int, order: int = 0) -> None:
        """Link a file to a director."""
        self.execute(
            """
            INSERT OR IGNORE INTO media_directors (file_id, person_id, display_order)
            VALUES (?, ?, ?)
            """,
            (file_id, person_id, order),
        )
        self.conn.commit()

    def link_writer(self, file_id: int, person_id: int, order: int = 0) -> None:
        """Link a file to a writer."""
        self.execute(
            """
            INSERT OR IGNORE INTO media_writers (file_id, person_id, display_order)
            VALUES (?, ?, ?)
            """,
            (file_id, person_id, order),
        )
        self.conn.commit()

    def clear_file_links(self, file_id: int) -> None:
        """Clear all junction table links for a file (before re-parsing NFO)."""
        tables = [
            "media_genres",
            "media_tags",
            "media_countries",
            "media_studios",
            "media_actors",
            "media_directors",
            "media_writers",
            "custom_attributes",
        ]
        for table in tables:
            self.execute(f"DELETE FROM {table} WHERE file_id = ?", (file_id,))
        self.conn.commit()

    # =========================================================================
    # EXTERNAL ID OPERATIONS
    # =========================================================================

    def upsert_external_id(
        self,
        file_id: int,
        provider: str,
        external_id: str,
        is_default: bool = False,
    ) -> None:
        """Insert or update an external ID."""
        self.execute(
            """
            INSERT INTO external_ids (file_id, provider, external_id, is_default)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(file_id, provider) DO UPDATE SET
                external_id = excluded.external_id,
                is_default = excluded.is_default
            """,
            (file_id, provider, external_id, 1 if is_default else 0),
        )
        self.conn.commit()

    # =========================================================================
    # CUSTOM ATTRIBUTE OPERATIONS
    # =========================================================================

    def get_or_create_custom_attr_def(
        self, attr_name: str, attr_type: str = "text", is_multivalue: bool = False
    ) -> int:
        """Get or create custom attribute definition."""
        row = self.fetchone(
            "SELECT attr_def_id FROM custom_attribute_defs WHERE attr_name = ?",
            (attr_name,),
        )
        if row:
            return row["attr_def_id"]

        self.execute(
            """
            INSERT INTO custom_attribute_defs (attr_name, attr_type, is_multivalue)
            VALUES (?, ?, ?)
            """,
            (attr_name, attr_type, 1 if is_multivalue else 0),
        )
        self.conn.commit()
        row = self.fetchone(
            "SELECT attr_def_id FROM custom_attribute_defs WHERE attr_name = ?",
            (attr_name,),
        )
        return row["attr_def_id"]

    def add_custom_attribute(
        self, file_id: int, attr_def_id: int, attr_value: str
    ) -> None:
        """Add a custom attribute value for a file."""
        self.execute(
            """
            INSERT INTO custom_attributes (file_id, attr_def_id, attr_value)
            VALUES (?, ?, ?)
            """,
            (file_id, attr_def_id, attr_value),
        )
        self.conn.commit()

    def get_custom_attributes(self, file_id: int) -> list[sqlite3.Row]:
        """Get all custom attributes for a file."""
        return self.fetchall(
            """
            SELECT cad.attr_name, cad.attr_type, ca.attr_value
            FROM custom_attributes ca
            JOIN custom_attribute_defs cad ON ca.attr_def_id = cad.attr_def_id
            WHERE ca.file_id = ?
            """,
            (file_id,),
        )

    # =========================================================================
    # FILE INFO OPERATIONS
    # =========================================================================

    def upsert_file_info(self, file_id: int, **fields: Any) -> None:
        """Insert or update file technical info."""
        columns = ["file_id"] + list(fields.keys())
        placeholders = ["?"] * len(columns)
        values = [file_id] + list(fields.values())

        update_parts = [f"{k} = excluded.{k}" for k in fields.keys()]

        sql = f"""
            INSERT INTO file_info ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
            ON CONFLICT(file_id) DO UPDATE SET
                {', '.join(update_parts)}
        """
        self.execute(sql, values)
        self.conn.commit()

    # =========================================================================
    # SCAN SESSION OPERATIONS
    # =========================================================================

    def create_scan_session(
        self, root_id: int | None = None, scan_type: str = "full"
    ) -> int:
        """Create a new scan session, returning scan_id."""
        self.execute(
            "INSERT INTO scan_sessions (root_id, scan_type) VALUES (?, ?)",
            (root_id, scan_type),
        )
        self.conn.commit()
        row = self.fetchone("SELECT last_insert_rowid() as scan_id")
        return row["scan_id"]

    def update_scan_session(self, scan_id: int, **stats: Any) -> None:
        """Update scan session statistics."""
        updates = ", ".join(f"{k} = ?" for k in stats.keys())
        values = list(stats.values()) + [scan_id]
        self.execute(f"UPDATE scan_sessions SET {updates} WHERE scan_id = ?", values)
        self.conn.commit()

    def finish_scan_session(self, scan_id: int, **stats: Any) -> None:
        """Mark scan session as finished with final statistics."""
        stats["finished_at"] = datetime.now().isoformat()
        self.update_scan_session(scan_id, **stats)

    def log_scan_error(
        self, scan_id: int, file_path: str, error_type: str, error_message: str
    ) -> None:
        """Log an error during scanning."""
        self.execute(
            """
            INSERT INTO scan_errors (scan_id, file_path, error_type, error_message)
            VALUES (?, ?, ?, ?)
            """,
            (scan_id, file_path, error_type, error_message),
        )
        self.conn.commit()

    # =========================================================================
    # PLAYLIST OPERATIONS
    # =========================================================================

    def create_playlist(
        self,
        name: str,
        description: str | None = None,
        is_smart: bool = False,
        smart_query: str | None = None,
    ) -> int:
        """Create a new playlist, returning playlist_id."""
        self.execute(
            """
            INSERT INTO playlists (name, description, is_smart, smart_query)
            VALUES (?, ?, ?, ?)
            """,
            (name, description, 1 if is_smart else 0, smart_query),
        )
        self.conn.commit()
        row = self.fetchone("SELECT last_insert_rowid() as playlist_id")
        return row["playlist_id"]

    def add_to_playlist(self, playlist_id: int, file_id: int, position: int) -> None:
        """Add a file to a playlist at the specified position."""
        self.execute(
            """
            INSERT INTO playlist_items (playlist_id, file_id, position)
            VALUES (?, ?, ?)
            """,
            (playlist_id, file_id, position),
        )
        self.conn.commit()

    def get_playlist_items(self, playlist_id: int) -> list[sqlite3.Row]:
        """Get all items in a playlist with full media info."""
        return self.fetchall(
            """
            SELECT v.*
            FROM playlist_items pi
            JOIN v_media_full v ON pi.file_id = v.file_id
            WHERE pi.playlist_id = ?
            ORDER BY pi.position
            """,
            (playlist_id,),
        )

    def list_playlists(self) -> list[sqlite3.Row]:
        """List all playlists."""
        return self.fetchall("SELECT * FROM playlists ORDER BY updated_at DESC")

    # =========================================================================
    # QUERY HELPERS
    # =========================================================================

    def search_media(
        self,
        title: str | None = None,
        year: int | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        rating_min: float | None = None,
        genres: list[str] | None = None,
        actors: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        """Search media with filters."""
        conditions = ["1=1"]
        params: list[Any] = []

        if title:
            conditions.append("(v.title LIKE ? OR v.originaltitle LIKE ?)")
            params.extend([f"%{title}%", f"%{title}%"])

        if year:
            conditions.append("v.year = ?")
            params.append(year)
        if year_min:
            conditions.append("v.year >= ?")
            params.append(year_min)
        if year_max:
            conditions.append("v.year <= ?")
            params.append(year_max)

        if rating_min:
            conditions.append("v.rating >= ?")
            params.append(rating_min)

        # Build base query
        sql = f"""
            SELECT DISTINCT v.*
            FROM v_media_full v
        """

        # Add genre joins if filtering by genre
        if genres:
            sql += """
                JOIN media_genres mg ON v.file_id = mg.file_id
                JOIN genres g ON mg.genre_id = g.genre_id
            """
            genre_placeholders = ", ".join("?" * len(genres))
            conditions.append(f"g.name IN ({genre_placeholders})")
            params.extend(genres)

        # Add actor joins if filtering by actor
        if actors:
            sql += """
                JOIN media_actors ma ON v.file_id = ma.file_id
                JOIN people p ON ma.person_id = p.person_id
            """
            actor_conditions = " OR ".join("p.name LIKE ?" for _ in actors)
            conditions.append(f"({actor_conditions})")
            params.extend([f"%{a}%" for a in actors])

        sql += f" WHERE {' AND '.join(conditions)}"
        sql += f" ORDER BY v.title LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        return self.fetchall(sql, params)

    def get_library_stats(self) -> dict[str, Any]:
        """Get library statistics."""
        stats = {}

        row = self.fetchone(
            "SELECT COUNT(*) as count, SUM(file_size) as size FROM media_files WHERE is_missing = 0"
        )
        stats["total_files"] = row["count"]
        stats["total_size_bytes"] = row["size"] or 0

        row = self.fetchone("SELECT COUNT(*) as count FROM media_files WHERE sha256_hash IS NOT NULL")
        stats["hashed_files"] = row["count"]

        row = self.fetchone(
            "SELECT COUNT(*) as count FROM media_files WHERE nfo_parsed_at IS NOT NULL"
        )
        stats["files_with_nfo"] = row["count"]

        row = self.fetchone("SELECT COUNT(*) as count FROM v_duplicates")
        stats["duplicate_groups"] = row["count"]

        row = self.fetchone("SELECT COUNT(*) as count FROM genres")
        stats["total_genres"] = row["count"]

        row = self.fetchone("SELECT COUNT(*) as count FROM people")
        stats["total_people"] = row["count"]

        return stats
