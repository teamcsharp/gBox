"""Online cover art for a library game (#1067): libretro-thumbnails by platform + title, or a picture the operator chose.

The library's own art folders stay the first source (gbox/catalog.py); a cover fetched here is stored under
gbox-data/art/<game_id>/<kind>.<ext> and wins over the library folders for that game.
"""
from __future__ import annotations

import re
import html
import http.client
import ipaddress
import json
import socket
import threading
import time
import unicodedata
from collections import OrderedDict
import urllib.parse
import urllib.error
import urllib.request

# gBox platform id -> libretro-thumbnails repository directory (https://thumbnails.libretro.com/<system>/<kind>/<name>.png)
SYSTEMS = {
    "3do": "The 3DO Company - 3DO", "3ds": "Nintendo - Nintendo 3DS", "amiga": "Commodore - Amiga", "arcade": "MAME",
    "arcade_fbneo": "FBNeo - Arcade Games", "arcade_hbmame": "MAME", "atari2600": "Atari - 2600", "atari7800": "Atari - 7800",
    "atari8": "Atari - 8-bit", "atarist": "Atari - ST", "c64": "Commodore - 64", "cdi": "Philips - CD-i",
    "coleco": "Coleco - ColecoVision", "cpc": "Amstrad - CPC", "dos": "DOS", "dreamcast": "Sega - Dreamcast",
    "fds": "Nintendo - Family Computer Disk System", "gamecube": "Nintendo - GameCube", "gamegear": "Sega - Game Gear",
    "gb": "Nintendo - Game Boy", "gba": "Nintendo - Game Boy Advance", "gbc": "Nintendo - Game Boy Color",
    "genesis": "Sega - Mega Drive - Genesis", "intellivision": "Mattel - Intellivision", "jaguar": "Atari - Jaguar",
    "lynx": "Atari - Lynx", "msx": "Microsoft - MSX", "n64": "Nintendo - Nintendo 64", "n64dd": "Nintendo - Nintendo 64DD",
    "naomi": "Sega - Naomi", "nds": "Nintendo - Nintendo DS", "neocd": "SNK - Neo Geo CD",
    "nes": "Nintendo - Nintendo Entertainment System", "ngp": "SNK - Neo Geo Pocket", "odyssey2": "Magnavox - Odyssey2",
    "pce": "NEC - PC Engine - TurboGrafx 16", "pcecd": "NEC - PC Engine CD - TurboGrafx-CD", "pcfx": "NEC - PC-FX",
    "pokemini": "Nintendo - Pokemon Mini", "ps2": "Sony - PlayStation 2", "ps3": "Sony - PlayStation 3",
    "psp": "Sony - PlayStation Portable", "psx": "Sony - PlayStation", "saturn": "Sega - Saturn", "sega32x": "Sega - 32X",
    "segacd": "Sega - Mega-CD - Sega CD", "sg1000": "Sega - SG-1000", "sms": "Sega - Master System - Mark III",
    "snes": "Nintendo - Super Nintendo Entertainment System", "supergrafx": "NEC - PC Engine SuperGrafx",
    "switch": "Nintendo - Switch", "vectrex": "GCE - Vectrex", "vic20": "Commodore - VIC-20",
    "virtualboy": "Nintendo - Virtual Boy", "wii": "Nintendo - Wii", "wiiu": "Nintendo - Wii U",
    "wonderswan": "Bandai - WonderSwan", "x68000": "Sharp - X68000", "xbox360": "Microsoft - Xbox 360",
    "zxspectrum": "Sinclair - ZX Spectrum",
}
KINDS = {"boxart": "Named_Boxarts", "snap": "Named_Snaps", "wheel": "Named_Titles"}
BASE = "https://thumbnails.libretro.com"
MAX_BYTES = 15 * 1024 * 1024
_TAGS = re.compile(r"\s*\((?:Rev|Disc|v\d|Beta|Proto|Sample|Demo)[^)]*\)", re.I)
PAGE_SIZE = 9
MAX_SEARCH_PAGES = 100
SEARCH_BATCH_LIMIT = 8
SEARCH_BYTES = 4 * 1024 * 1024
SEARCH_SECONDS = 25
SEARCH_CACHE_SECONDS = 300
_SEARCH_CACHE = OrderedDict()
_SEARCH_LOCK = threading.Lock()


class CoverSearchError(RuntimeError):
    """The configured image provider could not complete a cover search."""


def libretro_name(title: str) -> str:
    """The repository replaces every character of &*/:`<>?\\|\" in a game name with an underscore."""
    return re.sub(r'[&*/:`<>?\\|"]', "_", title).strip()


def candidates(title: str) -> list[str]:
    """Title spellings to try, most likely first: as stored; ': ' -> ' - ' (No-Intro subtitles); without the
    revision/disc tags; without any tag at all."""
    t = " ".join(title.split())
    out: list[str] = []
    for v in (t, t.replace(": ", " - "), _TAGS.sub("", t), _TAGS.sub("", t.replace(": ", " - ")), re.sub(r"\s*\([^)]*\)", "", t)):
        v = v.strip()
        if v and v not in out:
            out.append(v)
    return out


def urls(title: str, platform: str, kind: str = "boxart") -> list[str]:
    system, folder = SYSTEMS.get(platform or ""), KINDS.get(kind, "Named_Boxarts")
    if not system:
        return []
    return [f"{BASE}/{urllib.parse.quote(system)}/{folder}/{urllib.parse.quote(libretro_name(v))}.png"
            for v in candidates(title)]


def image_type(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _public_destination(url: str) -> tuple[str, list[str]]:
    """Reject credentials, unsafe schemes and any DNS answer outside the public Internet."""
    if not isinstance(url, str) or len(url) > 8192 or re.search(r"[\x00-\x20\x7f]", url):
        raise ValueError("picture URL contains whitespace or control characters")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
        host = parsed.hostname
    except ValueError as exc:
        raise ValueError("invalid picture URL") from exc
    if parsed.scheme.lower() not in ("http", "https") or not host:
        raise ValueError("only http(s) URLs can be fetched")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("picture URLs cannot contain credentials")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("invalid picture URL port")
    if "\\" in url or "%" in host or host.rstrip(".").lower() == "localhost" or host.lower().endswith(".localhost"):
        raise ValueError("picture URL must refer to a public Internet host")
    try:
        addresses = socket.getaddrinfo(host, port or (443 if parsed.scheme.lower() == "https" else 80),
                                       type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global or ipaddress.ip_address(row[4][0]).is_multicast
                                for row in addresses):
            raise ValueError("picture URL must refer to a public Internet host")
    except socket.gaierror as exc:
        raise ValueError("picture host could not be resolved") from exc
    normalized = urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, parsed.query, ""))
    return normalized, list(dict.fromkeys(row[4][0] for row in addresses))


def validate_public_url(url: str) -> str:
    """Validate a public image URL; fetch also pins its connection to the checked DNS answers."""
    return _public_destination(url)[0]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _pinned_connection(connection_type, addresses):
    def connection(host, **kwargs):
        result = connection_type(host, **kwargs)

        def connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
            last_error = None
            for ip in addresses:
                try:
                    return socket.create_connection((ip, address[1]), timeout, source_address)
                except OSError as exc:
                    last_error = exc
            raise last_error or OSError("No public picture host address was available")
        # Keep the original hostname for HTTP Host and TLS/SNI/certificate
        # verification, while preventing a second DNS lookup from rebinding it.
        result._create_connection = connect
        return result
    return connection


class _PinnedHTTP(urllib.request.HTTPHandler):
    def __init__(self, addresses):
        super().__init__()
        self.addresses = addresses

    def http_open(self, req):
        return self.do_open(_pinned_connection(http.client.HTTPConnection, self.addresses), req)


class _PinnedHTTPS(urllib.request.HTTPSHandler):
    def __init__(self, addresses):
        super().__init__()
        self.addresses = addresses

    def https_open(self, req):
        return self.do_open(_pinned_connection(http.client.HTTPSConnection, self.addresses), req,
                            context=self._context)


def fetch(url: str, timeout: float = 20) -> bytes:
    """Download one picture (http/https only, 15 MB cap, must be a PNG/JPEG/GIF/WebP)."""
    deadline = time.monotonic() + max(0.1, min(float(timeout), 30))
    # No ambient proxy credentials/cookies, and every redirect receives a new
    # public-address check before it can make a request.
    for attempt in range(6):
        url, addresses = _public_destination(url)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(),
                                              _PinnedHTTP(addresses), _PinnedHTTPS(addresses))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("picture download timed out")
        req = urllib.request.Request(url, headers={"User-Agent": "gBox/1.0 (cover art)"})
        try:
            response = opener.open(req, timeout=remaining)
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise
            target = exc.headers.get("Location")
            exc.close()
            if not target:
                raise ValueError("picture redirect has no destination") from None
            if attempt == 5:
                raise ValueError("picture URL redirected too many times") from None
            url = urllib.parse.urljoin(url, target)
            continue
        with response as r:
            length = r.headers.get("Content-Length")
            if length and int(length) > MAX_BYTES:
                raise ValueError("picture larger than 15 MB")
            chunks, size = [], 0
            while size <= MAX_BYTES:
                if time.monotonic() >= deadline:
                    raise TimeoutError("picture download timed out")
                chunk = r.read(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            data = b"".join(chunks)
        break
    if len(data) > MAX_BYTES:
        raise ValueError("picture larger than 15 MB")
    if not image_type(data):
        raise ValueError("the URL did not return a picture")
    return data


def _image_url(value):
    """Normalize a provider-returned URL; network validation happens when previewed/fetched."""
    if not isinstance(value, str) or len(value) > 8192 or re.search(r"[\x00-\x20\x7f]", value):
        return None
    if value.startswith("//"):
        value = "https:" + value
    try:
        parsed = urllib.parse.urlsplit(html.unescape(value))
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None \
                or parsed.password is not None or re.search(r"\.svg(?:$|[?#])", value, re.I):
            return None
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    except ValueError:
        return None


def _image_key(url):
    parsed = urllib.parse.urlsplit(url)
    query = sorted((k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
                   if not k.lower().startswith("utm_") and k.lower() not in ("gclid", "fbclid"))
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, urllib.parse.urlencode(query), ""))


def _vimm_url(url):
    host = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    return host == "vimm.net" or host.endswith(".vimm.net")


def _words(value):
    value = unicodedata.normalize("NFKD", urllib.parse.unquote(value)).encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z0-9]+", value))


def _versions(words):
    romans = {"i": 1, "ii": 2, "iii": 3, "lll": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
              "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15, "xvi": 16,
              "xvii": 17, "xviii": 18, "xix": 19, "xx": 20}
    return {romans[word] for word in words if word in romans} | {int(word) for word in words if word.isdigit() and 0 < int(word) <= 20}


def _result(row, query, source):
    if not isinstance(row, dict):
        return None
    url = _image_url(row.get("img_src"))
    if not url:
        return None
    source_url = _image_url(row.get("url")) or url
    if source == "vimm" and not (_vimm_url(source_url) or _vimm_url(url)):
        return None
    title = html.unescape(re.sub(r"<[^>]*>", "", str(row.get("title") or "")))[:240]
    # Some configured engines ignore the full query and return generic stock
    # pictures. Require title/URL evidence for at least two meaningful terms.
    terms = _words(re.sub(r"\bsite:\S+", "", query)) - {
        "a", "an", "the", "and", "or", "of", "for", "in", "on", "to", "game", "games", "video",
        "cover", "covers", "box", "boxart", "art", "artwork", "front", "back", "usa", "europe", "japan", "world",
    }
    if terms and len(terms & _words(title + " " + source_url + " " + url)) < min(2, len(terms)):
        return None
    versions = _versions(terms)
    if versions:
        observed = _versions(_words(title))
        requested_romans = _versions({word for word in terms if not word.isdigit()})
        title_romans = _versions({word for word in _words(title) if not word.isdigit()})
        if requested_romans and title_romans and not requested_romans.issubset(title_romans):
            return None
        # Opaque Pinterest IDs/image hashes are not evidence of a game version.
        if not observed and "/pin/" not in urllib.parse.urlsplit(source_url).path:
            observed = _versions(_words(urllib.parse.urlsplit(source_url).path))
        if not versions.issubset(observed):
            return None
    return {"url": url, "thumbnail": _image_url(row.get("thumbnail_src")) or url,
            "title": title or query, "source_url": source_url,
            "source": "Vimm's Lair" if source == "vimm" else urllib.parse.urlsplit(source_url).hostname}


def _search_page(searx_url, query, page, timeout):
    import httpx
    params = {"q": query, "format": "json", "categories": "images", "pageno": page,
              "safesearch": 1, "language": "en", "engines": "google images,bing images,pinterest,flickr"}
    try:
        with httpx.stream("GET", searx_url.rstrip("/") + "/search", params=params, timeout=timeout,
                          trust_env=False, follow_redirects=False) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > SEARCH_BYTES:
                    raise CoverSearchError("Image search response exceeded the 4 MB limit")
                chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise CoverSearchError("Image search returned an invalid result format")
        return payload
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            raise CoverSearchError("The image search provider refused JSON searches. Enable JSON in SearXNG search formats.") from exc
        raise CoverSearchError(f"Image search provider returned HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise CoverSearchError("Image search provider could not be reached or timed out. Check the configured SearXNG service.") from exc
    except (ValueError, UnicodeError) as exc:
        raise CoverSearchError("Image search provider returned unreadable JSON") from exc


def search(query: str, source: str = "web", page: int = 1, *, searx_url: str = "http://127.0.0.1:8081") -> dict:
    """Nine distinct images per page from actual accumulated provider batches."""
    query = " ".join(str(query).split())
    if not query or len(query) > 300:
        raise ValueError("cover search query must contain 1 to 300 characters")
    if source not in ("web", "vimm"):
        raise ValueError("cover search source must be web or vimm")
    if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= MAX_SEARCH_PAGES:
        raise ValueError(f"cover search page must be between 1 and {MAX_SEARCH_PAGES}")
    base = urllib.parse.urlsplit(searx_url)
    if base.scheme not in ("http", "https") or not base.hostname or base.username or base.password or base.query or base.fragment:
        raise CoverSearchError("A valid SearXNG service URL must be configured for cover search")
    key = (searx_url.rstrip("/"), source, query)
    now = time.monotonic()
    with _SEARCH_LOCK:
        for expired in [k for k, v in _SEARCH_CACHE.items() if now - v["created"] >= SEARCH_CACHE_SECONDS]:
            _SEARCH_CACHE.pop(expired)
        if key not in _SEARCH_CACHE:
            while len(_SEARCH_CACHE) >= 32:
                _SEARCH_CACHE.popitem(last=False)
            _SEARCH_CACHE[key] = {"created": now, "lock": threading.Lock(), "items": [], "seen": set(),
                                  "batches": set(), "next_batch": 1, "finished": False, "warnings": []}
        state = _SEARCH_CACHE[key]
        _SEARCH_CACHE.move_to_end(key)
    deadline, end = time.monotonic() + SEARCH_SECONDS, page * PAGE_SIZE
    with state["lock"]:
        while len(state["items"]) <= end and not state["finished"]:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or state["next_batch"] > SEARCH_BATCH_LIMIT:
                state["warnings"].append("Search limit reached. Refine the query to find more covers.")
                break
            provider_query = ("site:vimm.net " if source == "vimm" else "") + query
            try:
                payload = _search_page(searx_url, provider_query, state["next_batch"], min(12, remaining))
            except CoverSearchError as exc:
                if not state["items"]:
                    raise
                state["warnings"].append(str(exc))
                break
            rows = payload["results"]
            fingerprint = tuple(sorted({str(row.get("img_src")) for row in rows if isinstance(row, dict) and row.get("img_src")}))
            if not rows or fingerprint in state["batches"]:
                state["finished"] = True
                break
            state["batches"].add(fingerprint)
            state["next_batch"] += 1
            candidates = [item for row in rows if (item := _result(row, query, source))]
            candidates.sort(key=lambda item: not bool({"cover", "covers", "box", "boxart", "caratula"}
                                                       & _words(item["title"] + " " + item["source_url"])))
            for item in candidates:
                if item and (identity := _image_key(item["url"])) not in state["seen"]:
                    state["items"].append(item)
                    state["seen"].add(identity)
                    if len(state["items"]) >= MAX_SEARCH_PAGES * PAGE_SIZE + 1:
                        state["finished"] = True
                        break
            for failure in payload.get("unresponsive_engines") or []:
                if isinstance(failure, (list, tuple)) and len(failure) >= 2:
                    state["warnings"].append(f"{str(failure[0])[:60]}: {str(failure[1])[:120]}")
        items = state["items"][(page - 1) * PAGE_SIZE:end]
        warnings = list(dict.fromkeys(state["warnings"]))[:10]
        if not items:
            warnings.append("No matching Vimm's Lair images were returned by the search index. Try Web or another query."
                            if source == "vimm" else "No matching cover images were returned. Try a shorter title or another query.")
        more = len(state["items"]) > end and page < MAX_SEARCH_PAGES
        return {"query": query, "source": source, "page": page, "page_size": PAGE_SIZE, "items": items,
                "has_previous": page > 1, "has_next": more, "previous_page": page - 1 if page > 1 else None,
                "next_page": page + 1 if more else None, "warnings": warnings}


def find(title: str, platform: str, kind: str = "boxart", fetch=fetch) -> tuple[str | None, bytes | None, list[str]]:
    """(url, picture, tried): the first candidate that exists online, else (None, None, what was tried)."""
    tried: list[str] = []
    for u in urls(title, platform, kind):
        try:
            return u, fetch(u), tried
        except Exception as exc:                      # noqa: BLE001  (404, timeout, not an image: try the next spelling)
            tried.append(f"{u}: {type(exc).__name__}")
    return None, None, tried
