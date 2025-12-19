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
@click.option("--no-hash", is_flag=True, help="Skip SHA256 hashing")
@click.option("--full", is_flag=True, help="Full scan (rehash all files)")
@click.option("--parse-nfo/--no-parse-nfo", default=True, help="Parse NFO files after scanning")
@click.pass_context
def scan(
    ctx: click.Context,
    path: str,
    label: str | None,
    no_hash: bool,
    full: bool,
    parse_nfo: bool,
) -> None:
    """Scan a directory for video files and NFO metadata."""
    db = get_db(ctx.obj["db_path"])
    scanner = Scanner(db)

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
        stats = scanner.scan_root(
            path,
            label=label,
            compute_hashes=not no_hash,
            incremental=not full,
        )

    console.print(f"\n[green]Scan complete![/green]")
    console.print(f"  Files scanned: {stats.files_scanned}")
    console.print(f"  Files added: {stats.files_added}")
    console.print(f"  Files updated: {stats.files_updated}")
    console.print(f"  Files hashed: {stats.files_hashed}")
    console.print(f"  NFOs found: {stats.nfos_found}")
    if stats.errors:
        console.print(f"  [red]Errors: {stats.errors}[/red]")

    # Parse NFO files
    if parse_nfo:
        root = db.get_root_by_path(str(Path(path).resolve()))
        if root:
            files_with_nfo = scanner.get_files_with_nfo(root["root_id"])
            if files_with_nfo:
                console.print(f"\nParsing {len(files_with_nfo)} NFO files...")
                parser = NFOParser(db)

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task("Parsing NFOs...", total=len(files_with_nfo))

                    parsed = 0
                    errors = 0
                    for file_info in files_with_nfo:
                        nfo_path = Path(file_info["root_path"]) / file_info["nfo_path"]
                        try:
                            parser.parse_and_save(file_info["file_id"], nfo_path)
                            parsed += 1
                        except Exception as e:
                            console.print(f"[red]Error parsing {nfo_path}: {e}[/red]")
                            errors += 1
                        progress.advance(task)

                console.print(f"[green]Parsed {parsed} NFO files[/green]")
                if errors:
                    console.print(f"[red]{errors} errors[/red]")

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
@click.pass_context
def duplicates(ctx: click.Context) -> None:
    """Find duplicate files by hash."""
    db = get_db(ctx.obj["db_path"])
    dups = db.find_duplicates()

    if not dups:
        console.print("[green]No duplicates found[/green]")
    else:
        console.print(f"[yellow]Found {len(dups)} groups of duplicates[/yellow]\n")

        for dup in dups:
            file_ids = [int(x) for x in dup["file_ids"].split(",")]
            console.print(f"[bold]Hash: {dup['sha256_hash'][:16]}... ({dup['copy_count']} copies)[/bold]")

            for fid in file_ids:
                row = db.fetchone(
                    """
                    SELECT r.root_path || '/' || mf.relative_path as path, mf.file_size
                    FROM media_files mf
                    JOIN roots r ON mf.root_id = r.root_id
                    WHERE mf.file_id = ?
                    """,
                    (fid,),
                )
                if row:
                    size_mb = row["file_size"] / (1024 * 1024)
                    console.print(f"  - {row['path']} ({size_mb:.1f} MB)")
            console.print()

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
