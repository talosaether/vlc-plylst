# vlc-plylst

Media asset vacuum and VLC playlist generator with Emby/Kodi NFO metadata support.

Recursively scan video libraries, hash files for deduplication, parse NFO metadata into SQLite, and generate filtered VLC playlists.

## Features

- **Recursive scanning** for 30+ video formats (mp4, mkv, avi, mov, etc.)
- **SHA256 hashing** for duplicate detection
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

### Scan a media library

```bash
vlc-plylst scan /path/to/movies --label "Movies"
vlc-plylst scan /path/to/tv --label "TV Shows"
```

Options:
- `--label, -l` - Friendly name for this library root
- `--no-hash` - Skip SHA256 hashing (faster scan)
- `--full` - Full rescan (rehash all files)
- `--no-parse-nfo` - Skip NFO parsing

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
| `year:` | `year:2024` or `year:2020-2024` | Exact year or range |
| `rating:` | `rating:>7` or `rating:<5` | Minimum/maximum rating |
| `runtime:` | `runtime:<120` | Runtime in minutes |
| `genre:` | `genre:action` | Filter by genre |
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

### Other commands

```bash
# Library statistics
vlc-plylst stats

# Find duplicates by hash
vlc-plylst duplicates

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
vlc-plylst> help
```

## Database

Default location: `~/.vlc-plylst/media.db`

Override with: `vlc-plylst --db /path/to/custom.db <command>`

### Schema overview

| Table | Purpose |
|-------|---------|
| `roots` | Library root directories |
| `media_files` | Video files with hash, paths, scan tracking |
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
