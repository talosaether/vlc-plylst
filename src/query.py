"""Query builder for media filtering."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3
    from .db import Database


class SortOrder(Enum):
    """Sort order options."""

    TITLE_ASC = "title_asc"
    TITLE_DESC = "title_desc"
    YEAR_ASC = "year_asc"
    YEAR_DESC = "year_desc"
    RATING_ASC = "rating_asc"
    RATING_DESC = "rating_desc"
    RUNTIME_ASC = "runtime_asc"
    RUNTIME_DESC = "runtime_desc"
    SIZE_ASC = "size_asc"
    SIZE_DESC = "size_desc"
    ADDED_ASC = "added_asc"
    ADDED_DESC = "added_desc"
    RANDOM = "random"


@dataclass
class QueryFilter:
    """Filter criteria for media queries."""

    # Text search
    title: str | None = None
    plot: str | None = None

    # Year filters
    year: int | None = None
    year_min: int | None = None
    year_max: int | None = None

    # Rating filters
    rating_min: float | None = None
    rating_max: float | None = None

    # Runtime filters (minutes)
    runtime_min: int | None = None
    runtime_max: int | None = None

    # Multi-value filters (any match)
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    studios: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)

    # Collection/set filter
    set_name: str | None = None

    # Technical filters
    min_width: int | None = None  # e.g., 1920 for HD, 3840 for 4K
    video_codec: str | None = None
    hdr_only: bool = False

    # External ID filters
    has_imdb: bool | None = None
    imdb_id: str | None = None

    # Custom attribute filters
    custom_attrs: dict[str, str] = field(default_factory=dict)

    # Root filter
    root_id: int | None = None

    # Sorting
    sort: SortOrder = SortOrder.TITLE_ASC

    # Pagination
    limit: int = 100
    offset: int = 0


class QueryBuilder:
    """Build SQL queries from filter criteria."""

    def __init__(self, db: Database):
        self.db = db

    def _sort_clause(self, sort: SortOrder) -> str:
        """Generate ORDER BY clause."""
        sort_map = {
            SortOrder.TITLE_ASC: "COALESCE(v.title, v.filename) ASC",
            SortOrder.TITLE_DESC: "COALESCE(v.title, v.filename) DESC",
            SortOrder.YEAR_ASC: "v.year ASC NULLS LAST",
            SortOrder.YEAR_DESC: "v.year DESC NULLS LAST",
            SortOrder.RATING_ASC: "v.rating ASC NULLS LAST",
            SortOrder.RATING_DESC: "v.rating DESC NULLS LAST",
            SortOrder.RUNTIME_ASC: "v.runtime ASC NULLS LAST",
            SortOrder.RUNTIME_DESC: "v.runtime DESC NULLS LAST",
            SortOrder.SIZE_ASC: "v.file_size ASC",
            SortOrder.SIZE_DESC: "v.file_size DESC",
            SortOrder.ADDED_ASC: "mf.first_seen ASC",
            SortOrder.ADDED_DESC: "mf.first_seen DESC",
            SortOrder.RANDOM: "RANDOM()",
        }
        return sort_map.get(sort, "COALESCE(v.title, v.filename) ASC")

    def build_query(self, filters: QueryFilter) -> tuple[str, list[Any]]:
        """
        Build SQL query from filters.

        Returns:
            Tuple of (sql_query, parameters)
        """
        conditions: list[str] = []
        params: list[Any] = []
        joins: list[str] = []

        # Base query with media files join (for first_seen access)
        base = """
            SELECT DISTINCT v.*, mf.first_seen
            FROM v_media_full v
            JOIN media_files mf ON v.file_id = mf.file_id
        """

        # Title search
        if filters.title:
            conditions.append(
                "(v.title LIKE ? OR v.originaltitle LIKE ? OR v.filename LIKE ?)"
            )
            pattern = f"%{filters.title}%"
            params.extend([pattern, pattern, pattern])

        # Plot search
        if filters.plot:
            conditions.append("v.plot LIKE ?")
            params.append(f"%{filters.plot}%")

        # Year filters
        if filters.year:
            conditions.append("v.year = ?")
            params.append(filters.year)
        if filters.year_min:
            conditions.append("v.year >= ?")
            params.append(filters.year_min)
        if filters.year_max:
            conditions.append("v.year <= ?")
            params.append(filters.year_max)

        # Rating filters
        if filters.rating_min is not None:
            conditions.append("v.rating >= ?")
            params.append(filters.rating_min)
        if filters.rating_max is not None:
            conditions.append("v.rating <= ?")
            params.append(filters.rating_max)

        # Runtime filters
        if filters.runtime_min is not None:
            conditions.append("v.runtime >= ?")
            params.append(filters.runtime_min)
        if filters.runtime_max is not None:
            conditions.append("v.runtime <= ?")
            params.append(filters.runtime_max)

        # Genre filter (case-insensitive)
        if filters.genres:
            joins.append("""
                JOIN media_genres mg ON v.file_id = mg.file_id
                JOIN genres g ON mg.genre_id = g.genre_id
            """)
            genre_conditions = " OR ".join("LOWER(g.name) = LOWER(?)" for _ in filters.genres)
            conditions.append(f"({genre_conditions})")
            params.extend(filters.genres)

        # Tag filter (case-insensitive)
        if filters.tags:
            joins.append("""
                JOIN media_tags mt ON v.file_id = mt.file_id
                JOIN tags t ON mt.tag_id = t.tag_id
            """)
            tag_conditions = " OR ".join("LOWER(t.name) = LOWER(?)" for _ in filters.tags)
            conditions.append(f"({tag_conditions})")
            params.extend(filters.tags)

        # Actor filter
        if filters.actors:
            joins.append("""
                JOIN media_actors ma ON v.file_id = ma.file_id
                JOIN people pa ON ma.person_id = pa.person_id
            """)
            actor_conditions = " OR ".join("pa.name LIKE ?" for _ in filters.actors)
            conditions.append(f"({actor_conditions})")
            params.extend([f"%{a}%" for a in filters.actors])

        # Director filter
        if filters.directors:
            joins.append("""
                JOIN media_directors md ON v.file_id = md.file_id
                JOIN people pd ON md.person_id = pd.person_id
            """)
            director_conditions = " OR ".join("pd.name LIKE ?" for _ in filters.directors)
            conditions.append(f"({director_conditions})")
            params.extend([f"%{d}%" for d in filters.directors])

        # Studio filter (case-insensitive)
        if filters.studios:
            joins.append("""
                JOIN media_studios ms ON v.file_id = ms.file_id
                JOIN studios s ON ms.studio_id = s.studio_id
            """)
            studio_conditions = " OR ".join("LOWER(s.name) LIKE LOWER(?)" for _ in filters.studios)
            conditions.append(f"({studio_conditions})")
            params.extend([f"%{s}%" for s in filters.studios])

        # Country filter (case-insensitive)
        if filters.countries:
            joins.append("""
                JOIN media_countries mc ON v.file_id = mc.file_id
                JOIN countries c ON mc.country_id = c.country_id
            """)
            country_conditions = " OR ".join("LOWER(c.name) LIKE LOWER(?)" for _ in filters.countries)
            conditions.append(f"({country_conditions})")
            params.extend([f"%{c}%" for c in filters.countries])

        # Set/collection filter
        if filters.set_name:
            conditions.append("v.set_name LIKE ?")
            params.append(f"%{filters.set_name}%")

        # Technical filters
        if filters.min_width:
            conditions.append("v.video_width >= ?")
            params.append(filters.min_width)
        if filters.video_codec:
            conditions.append("v.video_codec LIKE ?")
            params.append(f"%{filters.video_codec}%")
        if filters.hdr_only:
            joins.append("JOIN file_info fi_hdr ON v.file_id = fi_hdr.file_id")
            conditions.append("fi_hdr.hdr_format IS NOT NULL")

        # IMDB filter
        if filters.has_imdb is not None:
            if filters.has_imdb:
                joins.append("""
                    JOIN external_ids ei_imdb ON v.file_id = ei_imdb.file_id
                        AND ei_imdb.provider = 'imdb'
                """)
            else:
                conditions.append("""
                    NOT EXISTS (
                        SELECT 1 FROM external_ids ei
                        WHERE ei.file_id = v.file_id AND ei.provider = 'imdb'
                    )
                """)
        if filters.imdb_id:
            joins.append("""
                JOIN external_ids ei_imdb_val ON v.file_id = ei_imdb_val.file_id
                    AND ei_imdb_val.provider = 'imdb'
            """)
            conditions.append("ei_imdb_val.external_id = ?")
            params.append(filters.imdb_id)

        # Custom attribute filters
        for attr_name, attr_value in filters.custom_attrs.items():
            alias = f"ca_{attr_name}"
            joins.append(f"""
                JOIN custom_attributes {alias} ON v.file_id = {alias}.file_id
                JOIN custom_attribute_defs {alias}_def ON {alias}.attr_def_id = {alias}_def.attr_def_id
                    AND {alias}_def.attr_name = ?
            """)
            params.append(attr_name)
            conditions.append(f"{alias}.attr_value LIKE ?")
            params.append(f"%{attr_value}%")

        # Root filter
        if filters.root_id:
            conditions.append("mf.root_id = ?")
            params.append(filters.root_id)

        # Build final query
        sql = base + " ".join(joins)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += f" ORDER BY {self._sort_clause(filters.sort)}"
        sql += " LIMIT ? OFFSET ?"
        params.extend([filters.limit, filters.offset])

        return sql, params

    def execute(self, filters: QueryFilter) -> list[sqlite3.Row]:
        """Execute query and return results."""
        sql, params = self.build_query(filters)
        return self.db.fetchall(sql, params)

    def count(self, filters: QueryFilter) -> int:
        """Count matching results (ignoring pagination)."""
        sql, params = self.build_query(filters)

        # Wrap in COUNT query, remove LIMIT/OFFSET
        count_sql = f"SELECT COUNT(*) as count FROM ({sql.rsplit('LIMIT', 1)[0]}) sub"
        count_params = params[:-2]  # Remove limit and offset

        row = self.db.fetchone(count_sql, count_params)
        return row["count"] if row else 0


def parse_filter_string(filter_str: str) -> QueryFilter:
    """
    Parse a human-friendly filter string into QueryFilter.

    Examples:
        "year:2024 genre:action rating:>7"
        "actor:cruise director:nolan"
        "title:inception year:2010-2020"

    Returns:
        QueryFilter populated from the filter string
    """
    filters = QueryFilter()
    parts = filter_str.split()

    for part in parts:
        if ":" not in part:
            # Treat as title search
            if filters.title:
                filters.title += " " + part
            else:
                filters.title = part
            continue

        key, value = part.split(":", 1)
        key = key.lower()

        if key == "title":
            filters.title = value
        elif key == "year":
            if value.startswith(">"):
                filters.year_min = int(value[1:])
            elif value.startswith("<"):
                filters.year_max = int(value[1:])
            elif "-" in value:
                # Range
                start, end = value.split("-", 1)
                if start:
                    filters.year_min = int(start)
                if end:
                    filters.year_max = int(end)
            else:
                filters.year = int(value)
        elif key == "rating":
            if value.startswith(">"):
                filters.rating_min = float(value[1:])
            elif value.startswith("<"):
                filters.rating_max = float(value[1:])
            else:
                filters.rating_min = float(value)
        elif key == "runtime":
            if value.startswith(">"):
                filters.runtime_min = int(value[1:])
            elif value.startswith("<"):
                filters.runtime_max = int(value[1:])
        elif key == "genre":
            filters.genres.append(value)
        elif key == "tag":
            filters.tags.append(value)
        elif key == "actor":
            filters.actors.append(value)
        elif key == "director":
            filters.directors.append(value)
        elif key == "studio":
            filters.studios.append(value)
        elif key == "country":
            filters.countries.append(value)
        elif key == "set" or key == "collection":
            filters.set_name = value
        elif key == "codec":
            filters.video_codec = value
        elif key == "resolution":
            if value.lower() in ("4k", "uhd"):
                filters.min_width = 3840
            elif value.lower() in ("hd", "1080p"):
                filters.min_width = 1920
            elif value.lower() == "720p":
                filters.min_width = 1280
        elif key == "hdr":
            filters.hdr_only = value.lower() in ("true", "yes", "1")
        elif key == "sort":
            try:
                filters.sort = SortOrder(value.lower())
            except ValueError:
                pass
        elif key == "limit":
            filters.limit = int(value)
        else:
            # Treat as custom attribute
            filters.custom_attrs[key] = value

    return filters
