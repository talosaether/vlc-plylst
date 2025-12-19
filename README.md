# vlc-plylst

Media asset vacuum and VLC playlist generator with Emby/Kodi NFO metadata support.

Recursively scan video libraries, parse NFO metadata into SQLite, and generate filtered VLC playlists.

## Features

- **Fast scanning** for 30+ video formats (mp4, mkv, avi, mov, etc.)
- **Smart filtering** - auto-skips trailers, extras, samples, and small files
- **NFO parsing** for Emby/Kodi metadata (title, year, plot, actors, genres, etc.)
- **Custom attributes** - automatically discovers non-standard NFO tags
- **Normalized schema** - junction tables for genres, actors, directors, studios, countries, tags
- **Portable paths** - stores root + relative paths for library relocation
- **Query engine** with human-friendly filter syntax
- **Playlist export** to M3U8 or XSPF formats
- **Interactive REPL** for exploring your library

## Installation

```bash
# Clone the repo
git clone git@github.com:talosaether/vlc-plylst.git
cd vlc-plylst

# Install with uv (recommended)
uv venv && uv pip install -e .

# Or with pip
python -m venv .venv && source .venv/bin/activate && pip install -e .
```

## Usage

### Workflow

```bash
# Initial setup: scan and parse
vlc-plylst scan /path/to/movies --label "Movies"
vlc-plylst parse

# Daily use: refresh all libraries (smart - skips unchanged dirs)
vlc-plylst refresh

# Browse/Search/Export
vlc-plylst browse genres
vlc-plylst search -q "genre:action year:>2020"
vlc-plylst export playlist.m3u8 -q "genre:action"
```

### Scan (vacuum phase)

```bash
vlc-plylst scan /path/to/movies --label "Movies"
vlc-plylst scan /path/to/tv --label "TV Shows"
```

Options:
- `--label, -l` - Friendly name for this library root
- `--min-size N` - Minimum file size in MB (default: 100, skips trailers/extras)
- `--no-filter` - Disable filtering (include trailers, extras, small files)

By default, scan skips:
- Files under 100MB
- Directories named: trailers, extras, featurettes, samples, etc.
- Files with patterns: -trailer, -sample, -featurette, etc.

### Parse (metadata extraction)

```bash
# Parse new/changed NFOs
vlc-plylst parse

# Re-parse all NFOs
vlc-plylst parse --force

# Parse specific root only
vlc-plylst parse --root 1

# Test with limited files
vlc-plylst parse --limit 10
```

### Browse available metadata

```bash
# See all categories
vlc-plylst browse

# List specific category
vlc-plylst browse genres
vlc-plylst browse actors
vlc-plylst browse directors
vlc-plylst browse studios
vlc-plylst browse years
vlc-plylst browse sets
```

### Search media

```bash
# Using options
vlc-plylst search --genre Action --year-min 2020 --rating 7.0

# Using filter string syntax
vlc-plylst search -q "year:2020-2024 genre:action rating:>7 actor:cruise"

# Output as JSON
vlc-plylst search -q "genre:horror" --json
```

### Filter syntax

| Filter | Example | Description |
|--------|---------|-------------|
| `title:` | `title:inception` | Search by title |
| `year:` | `year:2024`, `year:>2020`, `year:2020-2024` | Exact, min, or range |
| `rating:` | `rating:>7` or `rating:<5` | Minimum/maximum rating |
| `runtime:` | `runtime:<120` | Runtime in minutes |
| `genre:` | `genre:action` | Filter by genre |
| `tag:` | `tag:watched` | Filter by tag |
| `actor:` | `actor:cruise` | Filter by actor name |
| `director:` | `director:nolan` | Filter by director |
| `studio:` | `studio:warner` | Filter by studio |
| `country:` | `country:usa` | Filter by country |
| `set:` | `set:marvel` | Filter by collection |
| `codec:` | `codec:hevc` | Filter by video codec |
| `resolution:` | `resolution:4k` | 4k, hd, or 720p |
| `hdr:` | `hdr:true` | HDR content only |
| `sort:` | `sort:rating_desc` | Sort order |

Sort options: `title_asc`, `title_desc`, `year_asc`, `year_desc`, `rating_asc`, `rating_desc`, `runtime_asc`, `runtime_desc`, `random`

### Export playlists

```bash
# Export from query
vlc-plylst export action_movies.m3u8 -q "genre:action year:>2020"

# Export with path substitution (for network shares)
vlc-plylst export movies.m3u8 -q "rating:>8" --path-prefix "smb://nas/movies"

# Export as XSPF (includes more metadata)
vlc-plylst export movies.xspf -q "genre:scifi" --format xspf
```

### Manage playlists

```bash
# Create a smart playlist (dynamic)
vlc-plylst playlist create "Best of 2024" -q "year:2024 rating:>7"

# List saved playlists
vlc-plylst playlist list

# Export saved playlist
vlc-plylst playlist export 1 best2024.m3u8
```

### Maintenance commands

```bash
# Refresh all libraries (rescan + reparse changed NFOs)
vlc-plylst refresh

# Library statistics
vlc-plylst stats

# Remove files marked as missing (filtered out, deleted, moved)
vlc-plylst prune --dry-run    # Preview what would be deleted
vlc-plylst prune              # Delete with confirmation
vlc-plylst prune -y           # Delete without confirmation

# Interactive mode
vlc-plylst repl
```

### Interactive REPL

```
$ vlc-plylst repl

vlc-plylst> search genre:action year:>2020
vlc-plylst> show 42
vlc-plylst> export action.m3u8 genre:action rating:>7
vlc-plylst> stats
vlc-plylst> roots
vlc-plylst> help
```

## Database

Default location: `~/.vlc-plylst/media.db`

Override with: `vlc-plylst --db /path/to/custom.db <command>`

### Schema overview

| Table | Purpose |
|-------|---------|
| `roots` | Library root directories |
| `media_files` | Video files with paths, scan tracking |
| `media_metadata` | Parsed NFO data (title, year, plot, etc.) |
| `genres`, `media_genres` | Genre lookup + junction |
| `people`, `media_actors` | People + actor roles |
| `media_directors`, `media_writers` | Director/writer links |
| `studios`, `media_studios` | Studio lookup + junction |
| `countries`, `media_countries` | Country lookup + junction |
| `tags`, `media_tags` | Tag lookup + junction |
| `external_ids` | IMDB, TMDB, TVDB identifiers |
| `file_info` | Technical metadata (codec, resolution) |
| `custom_attribute_defs`, `custom_attributes` | Custom NFO tags |
| `playlists`, `playlist_items` | Saved playlists |
| `scan_sessions`, `scan_errors` | Scan history |

## NFO Support

Parses standard Emby/Kodi NFO elements:

- **Core**: title, originaltitle, sorttitle, year, premiered, runtime, plot, tagline
- **Ratings**: rating, votes, mpaa, certification
- **People**: actor (with role), director, writer/credits
- **Categories**: genre, tag, country, studio
- **Collections**: set (name + order)
- **External IDs**: uniqueid (imdb, tmdb, tvdb)
- **Technical**: fileinfo (codec, resolution, audio streams)
- **Custom**: Any non-standard tags are stored as custom attributes

## License

MIT
