"""Interactive REPL for media queries."""

from __future__ import annotations

import readline
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from .db import Database

from .query import QueryBuilder, QueryFilter, SortOrder, parse_filter_string
from .playlist import PlaylistGenerator

console = Console()

HELP_TEXT = """
[bold]VLC Playlist Generator - Interactive Mode[/bold]

[cyan]Query Commands:[/cyan]
  search <filter>     Search media (e.g., search year:2024 genre:action)
  count <filter>      Count matching results
  show <id>           Show details for a file

[cyan]Filter Syntax:[/cyan]
  title:<text>        Search by title
  year:<year>         Filter by year (or year:2020-2024 for range)
  rating:>7           Minimum rating
  runtime:<120        Maximum runtime in minutes
  genre:<name>        Filter by genre
  actor:<name>        Filter by actor
  director:<name>     Filter by director
  studio:<name>       Filter by studio
  country:<name>      Filter by country
  set:<name>          Filter by collection/set
  codec:<name>        Filter by video codec
  resolution:4k       Filter by resolution (4k, hd, 720p)
  hdr:true            HDR content only
  sort:<order>        Sort order (title_asc, year_desc, rating_desc, random)
  limit:<n>           Limit results

[cyan]Playlist Commands:[/cyan]
  export <file> <filter>   Export filtered results to playlist
  playlist list            List saved playlists
  playlist create <name> <filter>   Create smart playlist
  playlist export <id> <file>       Export saved playlist

[cyan]Other Commands:[/cyan]
  stats               Show library statistics
  duplicates          Find duplicate files
  roots               List library roots
  help                Show this help
  quit / exit         Exit REPL
"""


class MediaREPL:
    """Interactive REPL for media queries."""

    def __init__(self, db: Database):
        self.db = db
        self.query_builder = QueryBuilder(db)
        self.playlist_gen = PlaylistGenerator(db)
        self.last_results: list = []

    def cmd_search(self, args: str) -> None:
        """Execute search command."""
        if not args:
            console.print("[yellow]Usage: search <filter>[/yellow]")
            console.print("Example: search year:2024 genre:action rating:>7")
            return

        filters = parse_filter_string(args)
        results = self.query_builder.execute(filters)
        self.last_results = results

        if not results:
            console.print("[yellow]No results found[/yellow]")
            return

        self._display_results(results)

    def cmd_count(self, args: str) -> None:
        """Count matching results."""
        if not args:
            console.print("[yellow]Usage: count <filter>[/yellow]")
            return

        filters = parse_filter_string(args)
        count = self.query_builder.count(filters)
        console.print(f"[green]{count} matching files[/green]")

    def cmd_show(self, args: str) -> None:
        """Show details for a file."""
        try:
            file_id = int(args)
        except ValueError:
            console.print("[red]Usage: show <file_id>[/red]")
            return

        # Get basic info
        row = self.db.fetchone("SELECT * FROM v_media_full WHERE file_id = ?", (file_id,))
        if not row:
            console.print(f"[red]File {file_id} not found[/red]")
            return

        console.print(f"\n[bold]{row['title'] or row['filename']}[/bold]")
        console.print(f"[dim]ID: {file_id}[/dim]\n")

        # Basic info
        info_table = Table(show_header=False, box=None)
        info_table.add_column("Key", style="cyan")
        info_table.add_column("Value")

        info_table.add_row("Path", row["full_path"])
        if row["year"]:
            info_table.add_row("Year", str(row["year"]))
        if row["rating"]:
            info_table.add_row("Rating", f"{row['rating']:.1f}")
        if row["runtime"]:
            info_table.add_row("Runtime", f"{row['runtime']} minutes")
        if row["mpaa"]:
            info_table.add_row("MPAA", row["mpaa"])
        if row["set_name"]:
            info_table.add_row("Collection", row["set_name"])

        console.print(info_table)

        # Plot
        if row["plot"]:
            console.print(f"\n[dim]{row['plot'][:500]}{'...' if len(row['plot']) > 500 else ''}[/dim]")

        # Technical info
        if row["video_codec"] or row["video_width"]:
            console.print("\n[bold]Technical:[/bold]")
            tech = []
            if row["video_width"] and row["video_height"]:
                tech.append(f"{row['video_width']}x{row['video_height']}")
            if row["video_codec"]:
                tech.append(row["video_codec"])
            if row["audio_codec"]:
                tech.append(row["audio_codec"])
            console.print("  " + " | ".join(tech))

        # Genres
        genres = self.db.fetchall(
            """
            SELECT g.name FROM media_genres mg
            JOIN genres g ON mg.genre_id = g.genre_id
            WHERE mg.file_id = ?
            """,
            (file_id,),
        )
        if genres:
            console.print("\n[bold]Genres:[/bold] " + ", ".join(g["name"] for g in genres))

        # Actors
        actors = self.db.fetchall(
            """
            SELECT p.name, ma.role FROM media_actors ma
            JOIN people p ON ma.person_id = p.person_id
            WHERE ma.file_id = ?
            ORDER BY ma.display_order
            LIMIT 10
            """,
            (file_id,),
        )
        if actors:
            console.print("\n[bold]Cast:[/bold]")
            for a in actors:
                if a["role"]:
                    console.print(f"  - {a['name']} as {a['role']}")
                else:
                    console.print(f"  - {a['name']}")

        # Directors
        directors = self.db.fetchall(
            """
            SELECT p.name FROM media_directors md
            JOIN people p ON md.person_id = p.person_id
            WHERE md.file_id = ?
            """,
            (file_id,),
        )
        if directors:
            console.print("\n[bold]Director(s):[/bold] " + ", ".join(d["name"] for d in directors))

        # External IDs
        ext_ids = self.db.fetchall(
            "SELECT provider, external_id FROM external_ids WHERE file_id = ?",
            (file_id,),
        )
        if ext_ids:
            console.print("\n[bold]External IDs:[/bold]")
            for eid in ext_ids:
                console.print(f"  - {eid['provider']}: {eid['external_id']}")

        # Custom attributes
        custom = self.db.get_custom_attributes(file_id)
        if custom:
            console.print("\n[bold]Custom Attributes:[/bold]")
            for ca in custom:
                console.print(f"  - {ca['attr_name']}: {ca['attr_value']}")

        console.print()

    def cmd_export(self, args: str) -> None:
        """Export to playlist."""
        parts = shlex.split(args)
        if len(parts) < 2:
            console.print("[yellow]Usage: export <output_file> <filter>[/yellow]")
            console.print("Example: export action_movies.m3u8 genre:action year:>2020")
            return

        output_file = parts[0]
        filter_str = " ".join(parts[1:])

        filters = parse_filter_string(filter_str)
        filters.limit = 10000  # Higher limit for exports
        results = self.query_builder.execute(filters)

        if not results:
            console.print("[yellow]No matching files to export[/yellow]")
            return

        fmt = "xspf" if output_file.endswith(".xspf") else "m3u8"
        self.playlist_gen.save_playlist(
            output_path=output_file,
            query_results=results,
            format=fmt,
        )
        console.print(f"[green]Exported {len(results)} items to {output_file}[/green]")

    def cmd_playlist(self, args: str) -> None:
        """Playlist management commands."""
        parts = shlex.split(args) if args else []
        if not parts:
            console.print("[yellow]Usage: playlist <list|create|export> ...[/yellow]")
            return

        subcmd = parts[0].lower()

        if subcmd == "list":
            playlists = self.db.list_playlists()
            if not playlists:
                console.print("[yellow]No playlists[/yellow]")
            else:
                table = Table(title="Playlists")
                table.add_column("ID")
                table.add_column("Name")
                table.add_column("Type")
                table.add_column("Query/Items")

                for p in playlists:
                    ptype = "Smart" if p["is_smart"] else "Static"
                    query = p["smart_query"] or "-"
                    table.add_row(str(p["playlist_id"]), p["name"], ptype, query[:40])

                console.print(table)

        elif subcmd == "create":
            if len(parts) < 3:
                console.print("[yellow]Usage: playlist create <name> <filter>[/yellow]")
                return
            name = parts[1]
            filter_str = " ".join(parts[2:])
            pid = self.playlist_gen.create_smart_playlist(name, filter_str)
            console.print(f"[green]Created smart playlist '{name}' (ID: {pid})[/green]")

        elif subcmd == "export":
            if len(parts) < 3:
                console.print("[yellow]Usage: playlist export <id> <output_file>[/yellow]")
                return
            try:
                pid = int(parts[1])
            except ValueError:
                console.print("[red]Invalid playlist ID[/red]")
                return
            output_file = parts[2]
            fmt = "xspf" if output_file.endswith(".xspf") else "m3u8"
            self.playlist_gen.export_smart_playlist(pid, output_file, format=fmt)
            console.print(f"[green]Exported playlist to {output_file}[/green]")

        else:
            console.print(f"[red]Unknown playlist command: {subcmd}[/red]")

    def cmd_stats(self, args: str) -> None:
        """Show library statistics."""
        stats = self.db.get_library_stats()

        table = Table(title="Library Statistics", show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        size_gb = stats["total_size_bytes"] / (1024 ** 3)
        table.add_row("Total files", str(stats["total_files"]))
        table.add_row("Total size", f"{size_gb:.2f} GB")
        table.add_row("Hashed files", str(stats["hashed_files"]))
        table.add_row("Files with NFO", str(stats["files_with_nfo"]))
        table.add_row("Duplicate groups", str(stats["duplicate_groups"]))
        table.add_row("Genres", str(stats["total_genres"]))
        table.add_row("People", str(stats["total_people"]))

        console.print(table)

    def cmd_duplicates(self, args: str) -> None:
        """Find duplicate files."""
        dups = self.db.find_duplicates()
        if not dups:
            console.print("[green]No duplicates found[/green]")
            return

        console.print(f"[yellow]{len(dups)} duplicate groups[/yellow]\n")
        for dup in dups[:10]:  # Show first 10
            file_ids = [int(x) for x in dup["file_ids"].split(",")]
            console.print(f"[bold]Hash: {dup['sha256_hash'][:16]}... ({dup['copy_count']} copies)[/bold]")
            for fid in file_ids:
                row = self.db.fetchone(
                    "SELECT full_path FROM v_media_full WHERE file_id = ?", (fid,)
                )
                if row:
                    console.print(f"  - {row['full_path']}")
            console.print()

    def cmd_roots(self, args: str) -> None:
        """List library roots."""
        roots = self.db.list_roots()
        if not roots:
            console.print("[yellow]No library roots configured[/yellow]")
            return

        table = Table(title="Library Roots")
        table.add_column("ID")
        table.add_column("Path")
        table.add_column("Label")
        table.add_column("Last Scanned")

        for r in roots:
            table.add_row(
                str(r["root_id"]),
                r["root_path"],
                r["label"] or "-",
                r["last_scanned"][:19] if r["last_scanned"] else "Never",
            )

        console.print(table)

    def _display_results(self, results: list) -> None:
        """Display search results in a table."""
        table = Table(title=f"Results ({len(results)} items)")
        table.add_column("ID", style="dim", width=6)
        table.add_column("Title", max_width=40)
        table.add_column("Year", justify="right", width=6)
        table.add_column("Rating", justify="right", width=6)
        table.add_column("Runtime", justify="right", width=8)

        for row in results:
            table.add_row(
                str(row["file_id"]),
                (row["title"] or row["filename"])[:40],
                str(row["year"]) if row["year"] else "-",
                f"{row['rating']:.1f}" if row["rating"] else "-",
                f"{row['runtime']}m" if row["runtime"] else "-",
            )

        console.print(table)

    def run(self) -> None:
        """Run the REPL loop."""
        console.print(HELP_TEXT)
        console.print("[dim]Type 'help' for commands, 'quit' to exit[/dim]\n")

        # Setup readline history
        history_file = Path.home() / ".vlc-plylst_history"
        try:
            readline.read_history_file(history_file)
        except FileNotFoundError:
            pass

        while True:
            try:
                line = input("[bold cyan]vlc-plylst>[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye![/dim]")
                break

            if not line:
                continue

            # Parse command and args
            parts = line.split(None, 1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            if cmd in ("quit", "exit", "q"):
                console.print("[dim]Goodbye![/dim]")
                break
            elif cmd == "help":
                console.print(HELP_TEXT)
            elif cmd == "search":
                self.cmd_search(args)
            elif cmd == "count":
                self.cmd_count(args)
            elif cmd == "show":
                self.cmd_show(args)
            elif cmd == "export":
                self.cmd_export(args)
            elif cmd == "playlist":
                self.cmd_playlist(args)
            elif cmd == "stats":
                self.cmd_stats(args)
            elif cmd == "duplicates":
                self.cmd_duplicates(args)
            elif cmd == "roots":
                self.cmd_roots(args)
            else:
                # Try as a search query
                self.cmd_search(line)

        # Save history
        try:
            readline.write_history_file(history_file)
        except OSError:
            pass


def start_repl(db: Database) -> None:
    """Start the interactive REPL."""
    repl = MediaREPL(db)
    repl.run()
