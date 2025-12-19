"""Command-line interface for vlc-plylst."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from .db import Database, DEFAULT_DB_PATH
from .scanner import Scanner, ScanProgress
from .nfo_parser import NFOParser
from .query import QueryBuilder, QueryFilter, SortOrder, parse_filter_string
from .playlist import PlaylistGenerator

console = Console()


def get_db(db_path: str | None) -> Database:
    """Get database instance."""
    db = Database(db_path)
    db.init_schema()
    return db


@click.group()
@click.option("--db", "db_path", type=click.Path(), help=f"Database path (default: {DEFAULT_DB_PATH})")
@click.pass_context
def cli(ctx: click.Context, db_path: str | None) -> None:
    """VLC Playlist Generator - Media asset vacuum with NFO metadata support."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db_path


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option("--label", "-l", help="Label for this library root")
@click.option("--min-size", default=100, help="Minimum file size in MB (default: 100, skips trailers/extras)")
@click.option("--no-filter", is_flag=True, help="Disable filtering (include trailers, extras, small files)")
@click.pass_context
def scan(
    ctx: click.Context,
    path: str,
    label: str | None,
    min_size: int,
    no_filter: bool,
) -> None:
    """Scan a directory for video files (vacuum phase).

    Discovers video files and indexes them.
    Run 'parse' command afterwards to extract NFO metadata.
    """
    db = get_db(ctx.obj["db_path"])
    scanner = Scanner(db, min_size_mb=0 if no_filter else min_size)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning...", total=None)

        def on_progress(p: ScanProgress) -> None:
            desc = f"[{p.phase}] {p.current_file[:50]}..." if len(p.current_file) > 50 else f"[{p.phase}] {p.current_file}"
            if p.total_files:
                progress.update(task, description=desc, total=p.total_files, completed=p.files_processed)
            else:
                progress.update(task, description=desc)

        scanner.progress_callback = on_progress
        stats = scanner.scan_root(path, label=label)

    console.print(f"\n[green]Scan complete![/green]")
    console.print(f"  Files scanned: {stats.files_scanned}")
    console.print(f"  Files added: {stats.files_added}")
    console.print(f"  Files updated: {stats.files_updated}")
    console.print(f"  NFOs found: {stats.nfos_found}")
    if stats.files_skipped:
        console.print(f"  [dim]Files skipped (trailers/extras/small): {stats.files_skipped}[/dim]")
    if stats.errors:
        console.print(f"  [red]Errors: {stats.errors}[/red]")

    if stats.nfos_found > 0:
        console.print(f"\n[dim]Run 'vlc-plylst parse' to extract metadata from NFO files[/dim]")

    db.close()


@cli.command()
@click.option("--root", "-r", type=int, help="Only parse NFOs for specific root ID")
@click.option("--force", "-f", is_flag=True, help="Re-parse all NFOs (not just new/changed)")
@click.option("--limit", "-n", type=int, help="Limit number of NFOs to parse")
@click.pass_context
def parse(
    ctx: click.Context,
    root: int | None,
    force: bool,
    limit: int | None,
) -> None:
    """Parse NFO metadata for indexed files.

    Extracts metadata (title, year, genres, actors, etc.) from NFO files
    for videos that were previously indexed with 'scan'.
    """
    db = get_db(ctx.obj["db_path"])
    scanner = Scanner(db)
    parser = NFOParser(db)

    # Get files with NFOs needing parsing
    if force:
        # Get all files with NFO paths
        if root:
            files = db.fetchall(
                """
                SELECT mf.*, r.root_path
                FROM media_files mf
                JOIN roots r ON mf.root_id = r.root_id
                WHERE mf.root_id = ? AND mf.nfo_path IS NOT NULL AND mf.is_missing = 0
                """,
                (root,),
            )
        else:
            files = db.fetchall(
                """
                SELECT mf.*, r.root_path
                FROM media_files mf
                JOIN roots r ON mf.root_id = r.root_id
                WHERE mf.nfo_path IS NOT NULL AND mf.is_missing = 0
                """
            )
        files = [dict(f) for f in files]
    else:
        files = scanner.get_files_with_nfo(root)

    if limit:
        files = files[:limit]

    if not files:
        console.print("[yellow]No NFO files to parse[/yellow]")
        if not force:
            console.print("[dim]Use --force to re-parse all NFOs[/dim]")
        db.close()
        return

    console.print(f"Parsing {len(files)} NFO files...")

    parsed = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Parsing...", total=len(files))

        for file_info in files:
            nfo_path = Path(file_info["root_path"]) / file_info["nfo_path"]
            progress.update(task, description=f"Parsing {file_info['filename'][:40]}")

            try:
                parser.parse_and_save(file_info["file_id"], nfo_path)
                parsed += 1
            except Exception as e:
                console.print(f"[red]Error: {file_info['filename']}: {e}[/red]")
                errors += 1

            progress.advance(task)

    console.print(f"\n[green]Parsed {parsed} NFO files[/green]")
    if errors:
        console.print(f"[red]{errors} errors[/red]")

    # Show summary
    stats = db.get_library_stats()
    console.print(f"\n[dim]Library now has: {stats['total_genres']} genres, {stats['total_people']} people[/dim]")

    db.close()


@cli.command()
@click.option("--title", "-t", help="Search by title")
@click.option("--year", "-y", type=int, help="Filter by year")
@click.option("--year-min", type=int, help="Minimum year")
@click.option("--year-max", type=int, help="Maximum year")
@click.option("--rating", "-r", type=float, help="Minimum rating")
@click.option("--genre", "-g", multiple=True, help="Filter by genre (can repeat)")
@click.option("--actor", "-a", multiple=True, help="Filter by actor (can repeat)")
@click.option("--director", "-d", multiple=True, help="Filter by director (can repeat)")
@click.option("--query", "-q", help="Filter string (e.g., 'year:2024 genre:action rating:>7')")
@click.option("--sort", "-s", type=click.Choice([s.value for s in SortOrder]), default="title_asc")
@click.option("--limit", "-n", type=int, default=50, help="Max results")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def search(
    ctx: click.Context,
    title: str | None,
    year: int | None,
    year_min: int | None,
    year_max: int | None,
    rating: float | None,
    genre: tuple[str, ...],
    actor: tuple[str, ...],
    director: tuple[str, ...],
    query: str | None,
    sort: str,
    limit: int,
    as_json: bool,
) -> None:
    """Search and filter media files."""
    db = get_db(ctx.obj["db_path"])

    # Build filters
    if query:
        filters = parse_filter_string(query)
    else:
        filters = QueryFilter()

    # Override with explicit options
    if title:
        filters.title = title
    if year:
        filters.year = year
    if year_min:
        filters.year_min = year_min
    if year_max:
        filters.year_max = year_max
    if rating:
        filters.rating_min = rating
    if genre:
        filters.genres = list(genre)
    if actor:
        filters.actors = list(actor)
    if director:
        filters.directors = list(director)

    filters.sort = SortOrder(sort)
    filters.limit = limit

    query_builder = QueryBuilder(db)
    results = query_builder.execute(filters)

    if as_json:
        import json
        output = [dict(row) for row in results]
        click.echo(json.dumps(output, indent=2, default=str))
    else:
        if not results:
            console.print("[yellow]No results found[/yellow]")
        else:
            table = Table(title=f"Search Results ({len(results)} items)")
            table.add_column("ID", style="dim")
            table.add_column("Title")
            table.add_column("Year", justify="right")
            table.add_column("Rating", justify="right")
            table.add_column("Runtime", justify="right")
            table.add_column("Path", style="dim")

            for row in results:
                runtime = f"{row['runtime']}m" if row["runtime"] else "-"
                rating_str = f"{row['rating']:.1f}" if row["rating"] else "-"
                table.add_row(
                    str(row["file_id"]),
                    row["title"] or row["filename"],
                    str(row["year"]) if row["year"] else "-",
                    rating_str,
                    runtime,
                    row["relative_path"][:40] + "..." if len(row["relative_path"]) > 40 else row["relative_path"],
                )

            console.print(table)

    db.close()


@cli.command()
@click.argument("output", type=click.Path())
@click.option("--query", "-q", help="Filter string for media selection")
@click.option("--ids", help="Comma-separated file IDs")
@click.option("--playlist-id", "-p", type=int, help="Export existing playlist by ID")
@click.option("--path-prefix", help="Replace root paths with this prefix")
@click.option("--format", "-f", type=click.Choice(["m3u8", "xspf"]), default="m3u8")
@click.pass_context
def export(
    ctx: click.Context,
    output: str,
    query: str | None,
    ids: str | None,
    playlist_id: int | None,
    path_prefix: str | None,
    format: str,
) -> None:
    """Export a playlist to M3U8 or XSPF format."""
    db = get_db(ctx.obj["db_path"])
    generator = PlaylistGenerator(db)

    file_ids = None
    query_results = None

    if ids:
        file_ids = [int(i.strip()) for i in ids.split(",")]
    elif query:
        filters = parse_filter_string(query)
        query_builder = QueryBuilder(db)
        query_results = query_builder.execute(filters)
    elif playlist_id:
        pass  # Will use playlist_id directly
    else:
        console.print("[red]Must specify --query, --ids, or --playlist-id[/red]")
        db.close()
        sys.exit(1)

    output_path = generator.save_playlist(
        output_path=output,
        file_ids=file_ids,
        playlist_id=playlist_id,
        query_results=query_results,
        path_prefix=path_prefix,
        format=format,
    )

    item_count = len(file_ids or query_results or db.get_playlist_items(playlist_id) if playlist_id else [])
    console.print(f"[green]Exported {item_count} items to {output_path}[/green]")

    db.close()


@cli.group()
def playlist() -> None:
    """Manage playlists."""
    pass


@playlist.command("list")
@click.pass_context
def playlist_list(ctx: click.Context) -> None:
    """List all playlists."""
    db = get_db(ctx.obj["db_path"])
    playlists = db.list_playlists()

    if not playlists:
        console.print("[yellow]No playlists found[/yellow]")
    else:
        table = Table(title="Playlists")
        table.add_column("ID", style="dim")
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Description")
        table.add_column("Updated")

        for p in playlists:
            ptype = "Smart" if p["is_smart"] else "Static"
            table.add_row(
                str(p["playlist_id"]),
                p["name"],
                ptype,
                (p["description"] or "-")[:30],
                p["updated_at"][:10] if p["updated_at"] else "-",
            )

        console.print(table)

    db.close()


@playlist.command("create")
@click.argument("name")
@click.option("--query", "-q", help="Filter string for smart playlist")
@click.option("--ids", help="Comma-separated file IDs for static playlist")
@click.option("--description", "-d", help="Playlist description")
@click.pass_context
def playlist_create(
    ctx: click.Context,
    name: str,
    query: str | None,
    ids: str | None,
    description: str | None,
) -> None:
    """Create a new playlist."""
    db = get_db(ctx.obj["db_path"])
    generator = PlaylistGenerator(db)

    if query:
        playlist_id = generator.create_smart_playlist(name, query, description)
        console.print(f"[green]Created smart playlist '{name}' (ID: {playlist_id})[/green]")
    elif ids:
        file_ids = [int(i.strip()) for i in ids.split(",")]
        playlist_id = generator.create_static_playlist(name, file_ids, description)
        console.print(f"[green]Created static playlist '{name}' with {len(file_ids)} items (ID: {playlist_id})[/green]")
    else:
        console.print("[red]Must specify --query for smart playlist or --ids for static playlist[/red]")
        db.close()
        sys.exit(1)

    db.close()


@cli.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show library statistics."""
    db = get_db(ctx.obj["db_path"])
    library_stats = db.get_library_stats()

    console.print("\n[bold]Library Statistics[/bold]\n")

    # Format file size
    size_gb = library_stats["total_size_bytes"] / (1024 ** 3)

    table = Table(show_header=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total files", str(library_stats["total_files"]))
    table.add_row("Total size", f"{size_gb:.2f} GB")
    table.add_row("Hashed files", str(library_stats["hashed_files"]))
    table.add_row("Files with NFO", str(library_stats["files_with_nfo"]))
    table.add_row("Duplicate groups", str(library_stats["duplicate_groups"]))
    table.add_row("Genres", str(library_stats["total_genres"]))
    table.add_row("People", str(library_stats["total_people"]))

    console.print(table)

    # List roots
    roots = db.list_roots()
    if roots:
        console.print("\n[bold]Library Roots[/bold]\n")
        root_table = Table()
        root_table.add_column("ID", style="dim")
        root_table.add_column("Path")
        root_table.add_column("Label")
        root_table.add_column("Last Scanned")

        for root in roots:
            root_table.add_row(
                str(root["root_id"]),
                root["root_path"],
                root["label"] or "-",
                root["last_scanned"][:19] if root["last_scanned"] else "Never",
            )

        console.print(root_table)

    db.close()


@cli.command()
@click.argument("category", type=click.Choice(["genres", "actors", "directors", "studios", "countries", "tags", "years", "sets"]), required=False)
@click.pass_context
def browse(ctx: click.Context, category: str | None) -> None:
    """Browse available genres, actors, directors, etc."""
    db = get_db(ctx.obj["db_path"])

    if category is None:
        # Show summary of all categories
        console.print("\n[bold]Available Categories[/bold]\n")

        categories = [
            ("genres", "SELECT COUNT(*) as c FROM genres"),
            ("actors", "SELECT COUNT(DISTINCT person_id) as c FROM media_actors"),
            ("directors", "SELECT COUNT(DISTINCT person_id) as c FROM media_directors"),
            ("studios", "SELECT COUNT(*) as c FROM studios"),
            ("countries", "SELECT COUNT(*) as c FROM countries"),
            ("tags", "SELECT COUNT(*) as c FROM tags"),
            ("years", "SELECT COUNT(DISTINCT year) as c FROM media_metadata WHERE year IS NOT NULL"),
            ("sets", "SELECT COUNT(DISTINCT set_name) as c FROM media_metadata WHERE set_name IS NOT NULL"),
        ]

        table = Table()
        table.add_column("Category")
        table.add_column("Count", justify="right")
        table.add_column("Command")

        for name, sql in categories:
            row = db.fetchone(sql)
            count = row["c"] if row else 0
            table.add_row(name, str(count), f"vlc-plylst browse {name}")

        console.print(table)
        console.print("\n[dim]Use 'vlc-plylst browse <category>' to see values[/dim]")

    elif category == "genres":
        rows = db.fetchall("""
            SELECT g.name, COUNT(mg.file_id) as count
            FROM genres g
            LEFT JOIN media_genres mg ON g.genre_id = mg.genre_id
            GROUP BY g.genre_id
            ORDER BY count DESC
        """)
        table = Table(title="Genres")
        table.add_column("Genre")
        table.add_column("Files", justify="right")
        for r in rows:
            table.add_row(r["name"], str(r["count"]))
        console.print(table)

    elif category == "actors":
        rows = db.fetchall("""
            SELECT p.name, COUNT(ma.file_id) as count
            FROM people p
            JOIN media_actors ma ON p.person_id = ma.person_id
            GROUP BY p.person_id
            ORDER BY count DESC
            LIMIT 50
        """)
        table = Table(title="Top 50 Actors")
        table.add_column("Actor")
        table.add_column("Files", justify="right")
        for r in rows:
            table.add_row(r["name"], str(r["count"]))
        console.print(table)

    elif category == "directors":
        rows = db.fetchall("""
            SELECT p.name, COUNT(md.file_id) as count
            FROM people p
            JOIN media_directors md ON p.person_id = md.person_id
            GROUP BY p.person_id
            ORDER BY count DESC
            LIMIT 50
        """)
        table = Table(title="Top 50 Directors")
        table.add_column("Director")
        table.add_column("Files", justify="right")
        for r in rows:
            table.add_row(r["name"], str(r["count"]))
        console.print(table)

    elif category == "studios":
        rows = db.fetchall("""
            SELECT s.name, COUNT(ms.file_id) as count
            FROM studios s
            LEFT JOIN media_studios ms ON s.studio_id = ms.studio_id
            GROUP BY s.studio_id
            ORDER BY count DESC
        """)
        table = Table(title="Studios")
        table.add_column("Studio")
        table.add_column("Files", justify="right")
        for r in rows:
            table.add_row(r["name"], str(r["count"]))
        console.print(table)

    elif category == "countries":
        rows = db.fetchall("""
            SELECT c.name, COUNT(mc.file_id) as count
            FROM countries c
            LEFT JOIN media_countries mc ON c.country_id = mc.country_id
            GROUP BY c.country_id
            ORDER BY count DESC
        """)
        table = Table(title="Countries")
        table.add_column("Country")
        table.add_column("Files", justify="right")
        for r in rows:
            table.add_row(r["name"], str(r["count"]))
        console.print(table)

    elif category == "tags":
        rows = db.fetchall("""
            SELECT t.name, COUNT(mt.file_id) as count
            FROM tags t
            LEFT JOIN media_tags mt ON t.tag_id = mt.tag_id
            GROUP BY t.tag_id
            ORDER BY count DESC
        """)
        table = Table(title="Tags")
        table.add_column("Tag")
        table.add_column("Files", justify="right")
        for r in rows:
            table.add_row(r["name"], str(r["count"]))
        console.print(table)

    elif category == "years":
        rows = db.fetchall("""
            SELECT year, COUNT(*) as count
            FROM media_metadata
            WHERE year IS NOT NULL
            GROUP BY year
            ORDER BY year DESC
        """)
        table = Table(title="Years")
        table.add_column("Year")
        table.add_column("Files", justify="right")
        for r in rows:
            table.add_row(str(r["year"]), str(r["count"]))
        console.print(table)

    elif category == "sets":
        rows = db.fetchall("""
            SELECT set_name, COUNT(*) as count
            FROM media_metadata
            WHERE set_name IS NOT NULL
            GROUP BY set_name
            ORDER BY count DESC
        """)
        table = Table(title="Collections/Sets")
        table.add_column("Set Name")
        table.add_column("Files", justify="right")
        for r in rows:
            table.add_row(r["set_name"], str(r["count"]))
        console.print(table)

    db.close()


@cli.command()
@click.pass_context
def refresh(ctx: click.Context) -> None:
    """Rescan all roots and parse changed NFOs.

    Efficiently updates your library by:
    - Scanning all known roots (skips unchanged directories)
    - Parsing new or modified NFO files
    """
    db = get_db(ctx.obj["db_path"])

    roots = db.list_roots()
    if not roots:
        console.print("[yellow]No library roots configured[/yellow]")
        console.print("[dim]Use 'vlc-plylst scan <path>' to add a library[/dim]")
        db.close()
        return

    total_scanned = 0
    total_added = 0
    total_updated = 0
    total_nfos = 0
    total_parsed = 0

    scanner = Scanner(db)
    parser = NFOParser(db)

    # Scan each root
    for root in roots:
        console.print(f"\n[bold]Scanning: {root['label'] or root['root_path']}[/bold]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Scanning...", total=None)

            def on_progress(p: ScanProgress) -> None:
                desc = f"[{p.phase}] {p.current_file[:50]}..." if len(p.current_file) > 50 else f"[{p.phase}] {p.current_file}"
                if p.total_files:
                    progress.update(task, description=desc, total=p.total_files, completed=p.files_processed)
                else:
                    progress.update(task, description=desc)

            scanner.progress_callback = on_progress
            stats = scanner.scan_root(root["root_path"], label=root["label"])

        total_scanned += stats.files_scanned
        total_added += stats.files_added
        total_updated += stats.files_updated
        total_nfos += stats.nfos_found

    # Parse changed NFOs
    files_to_parse = scanner.get_files_with_nfo()
    if files_to_parse:
        console.print(f"\n[bold]Parsing {len(files_to_parse)} NFO files...[/bold]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Parsing...", total=len(files_to_parse))

            for file_info in files_to_parse:
                nfo_path = Path(file_info["root_path"]) / file_info["nfo_path"]
                progress.update(task, description=f"Parsing {file_info['filename'][:40]}")

                try:
                    parser.parse_and_save(file_info["file_id"], nfo_path)
                    total_parsed += 1
                except Exception:
                    pass  # Errors logged elsewhere

                progress.advance(task)

    # Summary
    console.print(f"\n[green]Refresh complete![/green]")
    console.print(f"  Roots scanned: {len(roots)}")
    console.print(f"  Files found: {total_scanned}")
    if total_added:
        console.print(f"  New files: {total_added}")
    if total_updated:
        console.print(f"  Updated files: {total_updated}")
    if total_parsed:
        console.print(f"  NFOs parsed: {total_parsed}")

    db.close()


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without deleting")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def prune(ctx: click.Context, dry_run: bool, yes: bool) -> None:
    """Remove files marked as missing and their metadata.

    Files become "missing" when they're not found during a scan
    (deleted from disk, moved, or filtered out by new scan settings).
    """
    db = get_db(ctx.obj["db_path"])

    # Count missing files
    row = db.fetchone("SELECT COUNT(*) as count FROM media_files WHERE is_missing = 1")
    missing_count = row["count"] if row else 0

    if missing_count == 0:
        console.print("[green]No missing files to prune[/green]")
        db.close()
        return

    console.print(f"Found [yellow]{missing_count}[/yellow] missing files")

    if dry_run:
        # Show some examples
        examples = db.fetchall(
            "SELECT filename, relative_path FROM media_files WHERE is_missing = 1 LIMIT 10"
        )
        console.print("\n[dim]Examples of files to be pruned:[/dim]")
        for ex in examples:
            console.print(f"  - {ex['relative_path']}")
        if missing_count > 10:
            console.print(f"  [dim]... and {missing_count - 10} more[/dim]")
        console.print("\n[dim]Run without --dry-run to delete[/dim]")
        db.close()
        return

    # Confirm unless -y
    if not yes:
        if not click.confirm(f"Delete {missing_count} files and their metadata?"):
            console.print("[dim]Cancelled[/dim]")
            db.close()
            return

    # Do the prune
    counts = db.prune_missing_files()

    console.print(f"\n[green]Pruned {counts['files']} files[/green]")
    if counts.get("metadata", 0) > 0:
        console.print(f"  Metadata records: {counts['metadata']}")
    if counts.get("genre_links", 0) > 0:
        console.print(f"  Genre links: {counts['genre_links']}")
    if counts.get("actor_links", 0) > 0:
        console.print(f"  Actor links: {counts['actor_links']}")

    db.close()


@cli.command()
@click.pass_context
def repl(ctx: click.Context) -> None:
    """Start interactive query mode."""
    from .repl import start_repl
    db = get_db(ctx.obj["db_path"])
    start_repl(db)
    db.close()


def main() -> None:
    """Entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
