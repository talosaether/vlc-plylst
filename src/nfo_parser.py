"""NFO file parser for Emby/Kodi metadata."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree as ET

try:
    from lxml import etree as lxml_etree
    HAS_LXML = True
except ImportError:
    HAS_LXML = False

if TYPE_CHECKING:
    from .db import Database

# Standard NFO elements we recognize
STANDARD_ELEMENTS: frozenset[str] = frozenset({
    # Core identification
    "title", "originaltitle", "sorttitle",
    # Dates
    "year", "premiered", "releasedate", "dateadded",
    # Runtime & Description
    "runtime", "plot", "tagline", "outline",
    # Ratings
    "rating", "votes", "mpaa", "certification",
    # Collections
    "set", "collectionnumber",
    # Media paths
    "poster", "fanart", "thumb", "trailer",
    # Playback
    "playcount", "lastplayed",
    # Multi-value elements (handled separately)
    "genre", "tag", "country", "studio",
    "actor", "director", "credits", "writer",
    # External IDs
    "uniqueid", "id", "imdbid", "tmdbid", "tvdbid",
    # File info
    "fileinfo",
    # TV Show specific (ignored for now but recognized)
    "episode", "season", "showtitle", "aired",
})


@dataclass
class Actor:
    """Actor information from NFO."""

    name: str
    role: str | None = None
    thumb: str | None = None
    order: int = 0


@dataclass
class UniqueId:
    """External ID from NFO."""

    provider: str
    value: str
    is_default: bool = False


@dataclass
class FileInfoData:
    """Technical file information from NFO."""

    video_codec: str | None = None
    video_width: int | None = None
    video_height: int | None = None
    aspect_ratio: str | None = None
    video_bitrate: int | None = None
    framerate: float | None = None
    hdr_format: str | None = None
    audio_codec: str | None = None
    audio_channels: int | None = None
    audio_language: str | None = None
    container: str | None = None
    duration_ms: int | None = None


@dataclass
class NFOData:
    """Parsed NFO data."""

    # Source info
    nfo_checksum: str = ""

    # Core identification
    title: str | None = None
    originaltitle: str | None = None
    sorttitle: str | None = None

    # Dates
    year: int | None = None
    premiered: str | None = None
    releasedate: str | None = None
    dateadded: str | None = None

    # Runtime & Description
    runtime: int | None = None
    plot: str | None = None
    tagline: str | None = None
    outline: str | None = None

    # Ratings
    rating: float | None = None
    votes: int | None = None
    mpaa: str | None = None
    certification: str | None = None

    # Collections
    set_name: str | None = None
    set_order: int | None = None

    # Media paths
    poster_path: str | None = None
    fanart_path: str | None = None
    thumb_path: str | None = None
    trailer_url: str | None = None

    # Playback
    playcount: int | None = None
    lastplayed: str | None = None

    # Multi-value fields
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    studios: list[str] = field(default_factory=list)
    actors: list[Actor] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    writers: list[str] = field(default_factory=list)

    # External IDs
    unique_ids: list[UniqueId] = field(default_factory=list)

    # File info
    file_info: FileInfoData | None = None

    # Custom attributes (non-standard tags)
    custom_attributes: dict[str, list[str]] = field(default_factory=dict)


class NFOParser:
    """Parser for Emby/Kodi NFO files."""

    def __init__(self, db: Database):
        self.db = db

    def _get_text(self, element: ET.Element | None) -> str | None:
        """Get text content of an element, or None."""
        if element is None:
            return None
        text = element.text
        if text:
            return text.strip()
        return None

    def _get_int(self, element: ET.Element | None) -> int | None:
        """Get integer content of an element, or None."""
        text = self._get_text(element)
        if text:
            try:
                # Handle decimal numbers (e.g., "120.0" for runtime)
                return int(float(text))
            except ValueError:
                return None
        return None

    def _get_float(self, element: ET.Element | None) -> float | None:
        """Get float content of an element, or None."""
        text = self._get_text(element)
        if text:
            try:
                return float(text)
            except ValueError:
                return None
        return None

    def _parse_actor(self, actor_elem: ET.Element, order: int) -> Actor:
        """Parse an actor element."""
        return Actor(
            name=self._get_text(actor_elem.find("name")) or "Unknown",
            role=self._get_text(actor_elem.find("role")),
            thumb=self._get_text(actor_elem.find("thumb")),
            order=self._get_int(actor_elem.find("order")) or order,
        )

    def _parse_uniqueid(self, elem: ET.Element) -> UniqueId | None:
        """Parse a uniqueid element."""
        value = self._get_text(elem)
        if not value:
            return None

        provider = elem.get("type", "unknown")
        is_default = elem.get("default", "").lower() == "true"

        return UniqueId(provider=provider, value=value, is_default=is_default)

    def _parse_fileinfo(self, fileinfo_elem: ET.Element) -> FileInfoData:
        """Parse fileinfo element with video/audio stream data."""
        data = FileInfoData()

        streamdetails = fileinfo_elem.find("streamdetails")
        if streamdetails is None:
            return data

        # Video stream
        video = streamdetails.find("video")
        if video is not None:
            data.video_codec = self._get_text(video.find("codec"))
            data.video_width = self._get_int(video.find("width"))
            data.video_height = self._get_int(video.find("height"))
            data.aspect_ratio = self._get_text(video.find("aspect"))
            data.video_bitrate = self._get_int(video.find("bitrate"))

            # Try different framerate element names
            framerate = self._get_float(video.find("framerate"))
            if framerate is None:
                framerate = self._get_float(video.find("fps"))
            data.framerate = framerate

            # HDR detection
            hdr = self._get_text(video.find("hdrformat"))
            if hdr is None:
                hdr = self._get_text(video.find("hdr"))
            data.hdr_format = hdr

            # Duration
            duration = self._get_int(video.find("durationinseconds"))
            if duration:
                data.duration_ms = duration * 1000
            else:
                duration_ms = self._get_int(video.find("duration"))
                if duration_ms:
                    data.duration_ms = duration_ms

        # Audio stream (first one)
        audio = streamdetails.find("audio")
        if audio is not None:
            data.audio_codec = self._get_text(audio.find("codec"))
            data.audio_channels = self._get_int(audio.find("channels"))
            data.audio_language = self._get_text(audio.find("language"))

        return data

    def _parse_set(self, set_elem: ET.Element) -> tuple[str | None, int | None]:
        """Parse set/collection element."""
        # Could be simple text or structured with <name> child
        name_elem = set_elem.find("name")
        if name_elem is not None:
            name = self._get_text(name_elem)
        else:
            name = self._get_text(set_elem)

        order_elem = set_elem.find("index")
        order = self._get_int(order_elem) if order_elem is not None else None

        return name, order

    def parse_file(self, nfo_path: Path) -> NFOData:
        """Parse an NFO file and return structured data."""
        content = nfo_path.read_bytes()
        checksum = hashlib.md5(content).hexdigest()

        # Try to parse XML, handling malformed files
        try:
            # Try lxml first for better error recovery
            if HAS_LXML:
                parser = lxml_etree.XMLParser(recover=True, encoding="utf-8")
                root = lxml_etree.fromstring(content, parser=parser)
            else:
                # Fallback to stdlib
                root = ET.fromstring(content.decode("utf-8", errors="replace"))
        except ET.ParseError:
            # Try to extract what we can with regex
            return self._parse_malformed(content.decode("utf-8", errors="replace"), checksum)

        data = NFOData(nfo_checksum=checksum)

        # Track which elements we've processed
        processed_tags: set[str] = set()

        # Core identification
        data.title = self._get_text(root.find("title"))
        data.originaltitle = self._get_text(root.find("originaltitle"))
        data.sorttitle = self._get_text(root.find("sorttitle"))
        processed_tags.update(["title", "originaltitle", "sorttitle"])

        # Dates
        data.year = self._get_int(root.find("year"))
        data.premiered = self._get_text(root.find("premiered"))
        data.releasedate = self._get_text(root.find("releasedate"))
        data.dateadded = self._get_text(root.find("dateadded"))
        processed_tags.update(["year", "premiered", "releasedate", "dateadded"])

        # Runtime & Description
        data.runtime = self._get_int(root.find("runtime"))
        data.plot = self._get_text(root.find("plot"))
        data.tagline = self._get_text(root.find("tagline"))
        data.outline = self._get_text(root.find("outline"))
        processed_tags.update(["runtime", "plot", "tagline", "outline"])

        # Ratings
        data.rating = self._get_float(root.find("rating"))
        data.votes = self._get_int(root.find("votes"))
        data.mpaa = self._get_text(root.find("mpaa"))
        data.certification = self._get_text(root.find("certification"))
        processed_tags.update(["rating", "votes", "mpaa", "certification"])

        # Collections
        set_elem = root.find("set")
        if set_elem is not None:
            data.set_name, data.set_order = self._parse_set(set_elem)
        collectionnumber = self._get_int(root.find("collectionnumber"))
        if collectionnumber and data.set_order is None:
            data.set_order = collectionnumber
        processed_tags.update(["set", "collectionnumber"])

        # Media paths
        data.poster_path = self._get_text(root.find("poster"))
        data.fanart_path = self._get_text(root.find("fanart"))
        data.thumb_path = self._get_text(root.find("thumb"))
        data.trailer_url = self._get_text(root.find("trailer"))
        processed_tags.update(["poster", "fanart", "thumb", "trailer"])

        # Playback
        data.playcount = self._get_int(root.find("playcount"))
        data.lastplayed = self._get_text(root.find("lastplayed"))
        processed_tags.update(["playcount", "lastplayed"])

        # Multi-value: genres
        for elem in root.findall("genre"):
            text = self._get_text(elem)
            if text:
                data.genres.append(text)
        processed_tags.add("genre")

        # Multi-value: tags
        for elem in root.findall("tag"):
            text = self._get_text(elem)
            if text:
                data.tags.append(text)
        processed_tags.add("tag")

        # Multi-value: countries
        for elem in root.findall("country"):
            text = self._get_text(elem)
            if text:
                data.countries.append(text)
        processed_tags.add("country")

        # Multi-value: studios
        for elem in root.findall("studio"):
            text = self._get_text(elem)
            if text:
                data.studios.append(text)
        processed_tags.add("studio")

        # Multi-value: actors
        for i, elem in enumerate(root.findall("actor")):
            actor = self._parse_actor(elem, i)
            data.actors.append(actor)
        processed_tags.add("actor")

        # Multi-value: directors
        for elem in root.findall("director"):
            text = self._get_text(elem)
            if text:
                data.directors.append(text)
        processed_tags.add("director")

        # Multi-value: writers (both <credits> and <writer>)
        for elem in root.findall("credits"):
            text = self._get_text(elem)
            if text:
                data.writers.append(text)
        for elem in root.findall("writer"):
            text = self._get_text(elem)
            if text and text not in data.writers:
                data.writers.append(text)
        processed_tags.update(["credits", "writer"])

        # External IDs
        for elem in root.findall("uniqueid"):
            uid = self._parse_uniqueid(elem)
            if uid:
                data.unique_ids.append(uid)

        # Legacy ID fields
        imdbid = self._get_text(root.find("imdbid")) or self._get_text(root.find("id"))
        if imdbid and imdbid.startswith("tt"):
            data.unique_ids.append(UniqueId(provider="imdb", value=imdbid, is_default=True))
        tmdbid = self._get_text(root.find("tmdbid"))
        if tmdbid:
            data.unique_ids.append(UniqueId(provider="tmdb", value=tmdbid))
        tvdbid = self._get_text(root.find("tvdbid"))
        if tvdbid:
            data.unique_ids.append(UniqueId(provider="tvdb", value=tvdbid))
        processed_tags.update(["uniqueid", "id", "imdbid", "tmdbid", "tvdbid"])

        # File info
        fileinfo_elem = root.find("fileinfo")
        if fileinfo_elem is not None:
            data.file_info = self._parse_fileinfo(fileinfo_elem)
        processed_tags.add("fileinfo")

        # Collect custom attributes (non-standard tags)
        for elem in root:
            tag = elem.tag.lower()
            if tag not in processed_tags and tag not in STANDARD_ELEMENTS:
                text = self._get_text(elem)
                if text:
                    if tag not in data.custom_attributes:
                        data.custom_attributes[tag] = []
                    data.custom_attributes[tag].append(text)

        return data

    def _parse_malformed(self, content: str, checksum: str) -> NFOData:
        """Try to extract data from malformed NFO using regex."""
        data = NFOData(nfo_checksum=checksum)

        # Try to extract common fields with regex
        patterns = {
            "title": r"<title[^>]*>([^<]+)</title>",
            "year": r"<year[^>]*>(\d{4})</year>",
            "plot": r"<plot[^>]*>([^<]+)</plot>",
            "rating": r"<rating[^>]*>([\d.]+)</rating>",
        }

        for field, pattern in patterns.items():
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if field == "title":
                    data.title = value
                elif field == "year":
                    try:
                        data.year = int(value)
                    except ValueError:
                        pass
                elif field == "plot":
                    data.plot = value
                elif field == "rating":
                    try:
                        data.rating = float(value)
                    except ValueError:
                        pass

        return data

    def save_to_db(self, file_id: int, nfo_data: NFOData) -> None:
        """Save parsed NFO data to database."""
        # Clear existing links for this file
        self.db.clear_file_links(file_id)

        # Save main metadata
        metadata_fields = {
            "title": nfo_data.title,
            "originaltitle": nfo_data.originaltitle,
            "sorttitle": nfo_data.sorttitle,
            "year": nfo_data.year,
            "premiered": nfo_data.premiered,
            "releasedate": nfo_data.releasedate,
            "dateadded": nfo_data.dateadded,
            "runtime": nfo_data.runtime,
            "plot": nfo_data.plot,
            "tagline": nfo_data.tagline,
            "outline": nfo_data.outline,
            "rating": nfo_data.rating,
            "votes": nfo_data.votes,
            "mpaa": nfo_data.mpaa,
            "certification": nfo_data.certification,
            "set_name": nfo_data.set_name,
            "set_order": nfo_data.set_order,
            "poster_path": nfo_data.poster_path,
            "fanart_path": nfo_data.fanart_path,
            "thumb_path": nfo_data.thumb_path,
            "trailer_url": nfo_data.trailer_url,
            "playcount": nfo_data.playcount,
            "lastplayed": nfo_data.lastplayed,
            "nfo_checksum": nfo_data.nfo_checksum,
        }
        # Remove None values
        metadata_fields = {k: v for k, v in metadata_fields.items() if v is not None}
        if metadata_fields:
            self.db.upsert_metadata(file_id, **metadata_fields)

        # Save genres
        for genre in nfo_data.genres:
            genre_id = self.db.get_or_create_genre(genre)
            self.db.link_genre(file_id, genre_id)

        # Save tags
        for tag in nfo_data.tags:
            tag_id = self.db.get_or_create_tag(tag)
            self.db.link_tag(file_id, tag_id)

        # Save countries
        for country in nfo_data.countries:
            country_id = self.db.get_or_create_country(country)
            self.db.link_country(file_id, country_id)

        # Save studios
        for i, studio in enumerate(nfo_data.studios):
            studio_id = self.db.get_or_create_studio(studio)
            self.db.link_studio(file_id, studio_id, order=i)

        # Save actors
        for actor in nfo_data.actors:
            person_id = self.db.get_or_create_person(actor.name, actor.thumb)
            self.db.link_actor(
                file_id, person_id,
                role=actor.role,
                order=actor.order,
                thumb_url=actor.thumb,
            )

        # Save directors
        for i, director in enumerate(nfo_data.directors):
            person_id = self.db.get_or_create_person(director)
            self.db.link_director(file_id, person_id, order=i)

        # Save writers
        for i, writer in enumerate(nfo_data.writers):
            person_id = self.db.get_or_create_person(writer)
            self.db.link_writer(file_id, person_id, order=i)

        # Save external IDs
        for uid in nfo_data.unique_ids:
            self.db.upsert_external_id(
                file_id, uid.provider, uid.value, uid.is_default
            )

        # Save file info
        if nfo_data.file_info:
            fi = nfo_data.file_info
            file_info_fields = {
                "video_codec": fi.video_codec,
                "video_width": fi.video_width,
                "video_height": fi.video_height,
                "aspect_ratio": fi.aspect_ratio,
                "video_bitrate": fi.video_bitrate,
                "framerate": fi.framerate,
                "hdr_format": fi.hdr_format,
                "audio_codec": fi.audio_codec,
                "audio_channels": fi.audio_channels,
                "audio_language": fi.audio_language,
                "container": fi.container,
                "duration_ms": fi.duration_ms,
            }
            file_info_fields = {k: v for k, v in file_info_fields.items() if v is not None}
            if file_info_fields:
                self.db.upsert_file_info(file_id, **file_info_fields)

        # Save custom attributes
        for attr_name, values in nfo_data.custom_attributes.items():
            is_multi = len(values) > 1
            attr_def_id = self.db.get_or_create_custom_attr_def(
                attr_name, attr_type="text", is_multivalue=is_multi
            )
            for value in values:
                self.db.add_custom_attribute(file_id, attr_def_id, value)

    def parse_and_save(self, file_id: int, nfo_path: Path) -> NFOData:
        """Parse NFO file and save to database."""
        nfo_data = self.parse_file(nfo_path)
        self.save_to_db(file_id, nfo_data)
        return nfo_data
