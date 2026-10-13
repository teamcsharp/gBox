"""Online cover art for a library game (#1067): libretro-thumbnails by platform + title, or a picture the operator chose.

The library's own art folders stay the first source (gbox/catalog.py); a cover fetched here is stored under
gbox-data/art/<game_id>/<kind>.<ext> and wins over the library folders for that game.
"""
from __future__ import annotations

import re
import urllib.parse
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


def fetch(url: str, timeout: float = 20) -> bytes:
    """Download one picture (http/https only, 15 MB cap, must be a PNG/JPEG/GIF/WebP)."""
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("only http(s) URLs can be fetched")
    req = urllib.request.Request(url, headers={"User-Agent": "gBox/1.0 (cover art)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("picture larger than 15 MB")
    if not image_type(data):
        raise ValueError("the URL did not return a picture")
    return data


def find(title: str, platform: str, kind: str = "boxart", fetch=fetch) -> tuple[str | None, bytes | None, list[str]]:
    """(url, picture, tried): the first candidate that exists online, else (None, None, what was tried)."""
    tried: list[str] = []
    for u in urls(title, platform, kind):
        try:
            return u, fetch(u), tried
        except Exception as exc:                      # noqa: BLE001  (404, timeout, not an image: try the next spelling)
            tried.append(f"{u}: {type(exc).__name__}")
    return None, None, tried
