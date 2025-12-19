-- ============================================================================
-- MEDIA ASSET VACUUM SYSTEM - SQLite Schema
-- ============================================================================
-- Database: SQLite with WAL mode for concurrent reads
-- ============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

-- ============================================================================
-- SECTION 1: ROOT DIRECTORIES (Library Sources)
-- ============================================================================

CREATE TABLE IF NOT EXISTS roots (
    root_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    root_path       TEXT NOT NULL UNIQUE,
    label           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    last_scanned    TEXT,
    is_active       INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_roots_path ON roots(root_path);

-- ============================================================================
-- SECTION 2: MEDIA FILES (Core Video Table)
-- ============================================================================

CREATE TABLE IF NOT EXISTS media_files (
    file_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id         INTEGER NOT NULL,
    relative_path   TEXT NOT NULL,
    filename        TEXT NOT NULL,

    -- File identification
    sha256_hash     TEXT,
    file_size       INTEGER,
    file_mtime      TEXT,

    -- Scan tracking
    first_seen      TEXT DEFAULT (datetime('now')),
    last_seen       TEXT DEFAULT (datetime('now')),
    last_hashed     TEXT,
    scan_version    INTEGER DEFAULT 0,

    -- NFO status
    nfo_path        TEXT,
    nfo_mtime       TEXT,
    nfo_parsed_at   TEXT,

    -- Status flags
    is_missing      INTEGER DEFAULT 0,
    is_duplicate    INTEGER DEFAULT 0,

    FOREIGN KEY (root_id) REFERENCES roots(root_id) ON DELETE CASCADE,
    UNIQUE(root_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_media_hash ON media_files(sha256_hash);
CREATE INDEX IF NOT EXISTS idx_media_root ON media_files(root_id);
CREATE INDEX IF NOT EXISTS idx_media_missing ON media_files(is_missing);
CREATE INDEX IF NOT EXISTS idx_media_filename ON media_files(filename);

-- ============================================================================
-- SECTION 3: NFO METADATA (Parsed Emby/Kodi Data)
-- ============================================================================

CREATE TABLE IF NOT EXISTS media_metadata (
    metadata_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL UNIQUE,

    -- Core identification
    title           TEXT,
    originaltitle   TEXT,
    sorttitle       TEXT,

    -- Dates
    year            INTEGER,
    premiered       TEXT,
    releasedate     TEXT,
    dateadded       TEXT,

    -- Runtime & Description
    runtime         INTEGER,
    plot            TEXT,
    tagline         TEXT,
    outline         TEXT,

    -- Ratings & Certification
    rating          REAL,
    votes           INTEGER,
    mpaa            TEXT,
    certification   TEXT,

    -- Collections
    set_name        TEXT,
    set_order       INTEGER,

    -- Media paths (relative to video file)
    poster_path     TEXT,
    fanart_path     TEXT,
    thumb_path      TEXT,
    trailer_url     TEXT,

    -- Playback info
    playcount       INTEGER DEFAULT 0,
    lastplayed      TEXT,

    -- Source NFO checksum for change detection
    nfo_checksum    TEXT,

    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_metadata_title ON media_metadata(title);
CREATE INDEX IF NOT EXISTS idx_metadata_year ON media_metadata(year);
CREATE INDEX IF NOT EXISTS idx_metadata_rating ON media_metadata(rating);
CREATE INDEX IF NOT EXISTS idx_metadata_set ON media_metadata(set_name);

-- ============================================================================
-- SECTION 4: EXTERNAL IDs (IMDB, TMDB, TVDB, etc.)
-- ============================================================================

CREATE TABLE IF NOT EXISTS external_ids (
    extid_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL,
    provider        TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    is_default      INTEGER DEFAULT 0,

    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE,
    UNIQUE(file_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_extid_provider ON external_ids(provider, external_id);

-- ============================================================================
-- SECTION 5: MULTI-VALUE LOOKUP TABLES
-- ============================================================================

-- Genres
CREATE TABLE IF NOT EXISTS genres (
    genre_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS media_genres (
    file_id         INTEGER NOT NULL,
    genre_id        INTEGER NOT NULL,
    PRIMARY KEY (file_id, genre_id),
    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE,
    FOREIGN KEY (genre_id) REFERENCES genres(genre_id) ON DELETE CASCADE
);

-- Tags
CREATE TABLE IF NOT EXISTS tags (
    tag_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS media_tags (
    file_id         INTEGER NOT NULL,
    tag_id          INTEGER NOT NULL,
    PRIMARY KEY (file_id, tag_id),
    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
);

-- Countries
CREATE TABLE IF NOT EXISTS countries (
    country_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE COLLATE NOCASE,
    iso_code        TEXT
);

CREATE TABLE IF NOT EXISTS media_countries (
    file_id         INTEGER NOT NULL,
    country_id      INTEGER NOT NULL,
    PRIMARY KEY (file_id, country_id),
    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE,
    FOREIGN KEY (country_id) REFERENCES countries(country_id) ON DELETE CASCADE
);

-- Studios
CREATE TABLE IF NOT EXISTS studios (
    studio_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS media_studios (
    file_id         INTEGER NOT NULL,
    studio_id       INTEGER NOT NULL,
    display_order   INTEGER DEFAULT 0,
    PRIMARY KEY (file_id, studio_id),
    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE,
    FOREIGN KEY (studio_id) REFERENCES studios(studio_id) ON DELETE CASCADE
);

-- ============================================================================
-- SECTION 6: PEOPLE (Actors, Directors, Writers)
-- ============================================================================

CREATE TABLE IF NOT EXISTS people (
    person_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    thumb_url       TEXT,
    imdb_id         TEXT,
    tmdb_id         TEXT,
    UNIQUE(name, imdb_id)
);

CREATE INDEX IF NOT EXISTS idx_people_name ON people(name COLLATE NOCASE);

-- Actors with role information
CREATE TABLE IF NOT EXISTS media_actors (
    actor_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL,
    person_id       INTEGER NOT NULL,
    role            TEXT,
    display_order   INTEGER DEFAULT 0,
    thumb_url       TEXT,
    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE,
    FOREIGN KEY (person_id) REFERENCES people(person_id) ON DELETE CASCADE,
    UNIQUE(file_id, person_id, role)
);

CREATE INDEX IF NOT EXISTS idx_actors_person ON media_actors(person_id);

-- Directors
CREATE TABLE IF NOT EXISTS media_directors (
    file_id         INTEGER NOT NULL,
    person_id       INTEGER NOT NULL,
    display_order   INTEGER DEFAULT 0,
    PRIMARY KEY (file_id, person_id),
    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE,
    FOREIGN KEY (person_id) REFERENCES people(person_id) ON DELETE CASCADE
);

-- Writers
CREATE TABLE IF NOT EXISTS media_writers (
    file_id         INTEGER NOT NULL,
    person_id       INTEGER NOT NULL,
    display_order   INTEGER DEFAULT 0,
    PRIMARY KEY (file_id, person_id),
    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE,
    FOREIGN KEY (person_id) REFERENCES people(person_id) ON DELETE CASCADE
);

-- ============================================================================
-- SECTION 7: FILE INFO (Technical Metadata)
-- ============================================================================

CREATE TABLE IF NOT EXISTS file_info (
    fileinfo_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL UNIQUE,

    -- Video stream
    video_codec     TEXT,
    video_width     INTEGER,
    video_height    INTEGER,
    aspect_ratio    TEXT,
    video_bitrate   INTEGER,
    framerate       REAL,
    hdr_format      TEXT,

    -- Audio stream (primary)
    audio_codec     TEXT,
    audio_channels  INTEGER,
    audio_language  TEXT,

    -- Container
    container       TEXT,
    duration_ms     INTEGER,

    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fileinfo_resolution ON file_info(video_width, video_height);
CREATE INDEX IF NOT EXISTS idx_fileinfo_codec ON file_info(video_codec);

-- Audio streams (multiple per file)
CREATE TABLE IF NOT EXISTS audio_streams (
    stream_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL,
    stream_index    INTEGER NOT NULL,
    codec           TEXT,
    channels        INTEGER,
    language        TEXT,
    is_default      INTEGER DEFAULT 0,
    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE
);

-- Subtitle streams
CREATE TABLE IF NOT EXISTS subtitle_streams (
    stream_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL,
    stream_index    INTEGER NOT NULL,
    codec           TEXT,
    language        TEXT,
    is_default      INTEGER DEFAULT 0,
    is_forced       INTEGER DEFAULT 0,
    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE
);

-- ============================================================================
-- SECTION 8: CUSTOM ATTRIBUTES (Key-Value Store)
-- ============================================================================

CREATE TABLE IF NOT EXISTS custom_attribute_defs (
    attr_def_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    attr_name       TEXT NOT NULL UNIQUE,
    attr_type       TEXT DEFAULT 'text',
    is_multivalue   INTEGER DEFAULT 0,
    first_seen      TEXT DEFAULT (datetime('now')),
    occurrence_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS custom_attributes (
    attr_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL,
    attr_def_id     INTEGER NOT NULL,
    attr_value      TEXT,
    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE,
    FOREIGN KEY (attr_def_id) REFERENCES custom_attribute_defs(attr_def_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_custom_attrs_file ON custom_attributes(file_id);
CREATE INDEX IF NOT EXISTS idx_custom_attrs_def ON custom_attributes(attr_def_id);
CREATE INDEX IF NOT EXISTS idx_custom_attrs_value ON custom_attributes(attr_value);

-- ============================================================================
-- SECTION 9: SCAN HISTORY & AUDIT
-- ============================================================================

CREATE TABLE IF NOT EXISTS scan_sessions (
    scan_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id         INTEGER,
    started_at      TEXT DEFAULT (datetime('now')),
    finished_at     TEXT,
    files_scanned   INTEGER DEFAULT 0,
    files_added     INTEGER DEFAULT 0,
    files_updated   INTEGER DEFAULT 0,
    files_removed   INTEGER DEFAULT 0,
    nfos_parsed     INTEGER DEFAULT 0,
    errors_count    INTEGER DEFAULT 0,
    scan_type       TEXT,
    scan_options    TEXT,
    FOREIGN KEY (root_id) REFERENCES roots(root_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS scan_errors (
    error_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id         INTEGER NOT NULL,
    file_path       TEXT,
    error_type      TEXT,
    error_message   TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (scan_id) REFERENCES scan_sessions(scan_id) ON DELETE CASCADE
);

-- ============================================================================
-- SECTION 10: PLAYLISTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS playlists (
    playlist_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    is_smart        INTEGER DEFAULT 0,
    smart_query     TEXT
);

CREATE TABLE IF NOT EXISTS playlist_items (
    item_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id     INTEGER NOT NULL,
    file_id         INTEGER NOT NULL,
    position        INTEGER NOT NULL,
    added_at        TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (playlist_id) REFERENCES playlists(playlist_id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES media_files(file_id) ON DELETE CASCADE,
    UNIQUE(playlist_id, position)
);

CREATE INDEX IF NOT EXISTS idx_playlist_items ON playlist_items(playlist_id, position);

-- ============================================================================
-- SECTION 11: USEFUL VIEWS
-- ============================================================================

-- Full media view with basic metadata
CREATE VIEW IF NOT EXISTS v_media_full AS
SELECT
    mf.file_id,
    r.root_path,
    mf.relative_path,
    r.root_path || '/' || mf.relative_path AS full_path,
    mf.filename,
    mf.sha256_hash,
    mf.file_size,
    mm.title,
    mm.originaltitle,
    mm.year,
    mm.runtime,
    mm.rating,
    mm.plot,
    mm.mpaa,
    mm.set_name,
    fi.video_codec,
    fi.video_width,
    fi.video_height,
    fi.audio_codec
FROM media_files mf
JOIN roots r ON mf.root_id = r.root_id
LEFT JOIN media_metadata mm ON mf.file_id = mm.file_id
LEFT JOIN file_info fi ON mf.file_id = fi.file_id
WHERE mf.is_missing = 0;

-- Duplicates view
CREATE VIEW IF NOT EXISTS v_duplicates AS
SELECT
    sha256_hash,
    COUNT(*) as copy_count,
    GROUP_CONCAT(file_id) as file_ids
FROM media_files
WHERE sha256_hash IS NOT NULL
GROUP BY sha256_hash
HAVING COUNT(*) > 1;

-- Files needing rescan
CREATE VIEW IF NOT EXISTS v_needs_rescan AS
SELECT
    mf.file_id,
    r.root_path || '/' || mf.relative_path AS full_path,
    mf.file_mtime,
    mf.last_hashed
FROM media_files mf
JOIN roots r ON mf.root_id = r.root_id
WHERE mf.is_missing = 0
  AND (mf.last_hashed IS NULL OR mf.file_mtime > mf.last_hashed);

-- ============================================================================
-- SECTION 12: TRIGGERS
-- ============================================================================

-- Update playlist timestamp when items change
CREATE TRIGGER IF NOT EXISTS trg_playlist_updated
AFTER INSERT ON playlist_items
BEGIN
    UPDATE playlists
    SET updated_at = datetime('now')
    WHERE playlist_id = NEW.playlist_id;
END;

-- Track custom attribute usage
CREATE TRIGGER IF NOT EXISTS trg_custom_attr_count
AFTER INSERT ON custom_attributes
BEGIN
    UPDATE custom_attribute_defs
    SET occurrence_count = occurrence_count + 1
    WHERE attr_def_id = NEW.attr_def_id;
END;
