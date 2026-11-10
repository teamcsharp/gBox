"""Player/character model paths: the Dreamcast names PSO tools use, and where the GameCube disc actually keeps them.

`gbox.pso_player` was written against the Dreamcast layout, which stores character parts as
``PSO/PL<C>BDY00.NJ``, ``PSO/PL<C>HED<NN>.NJ``, ``PSO/PL<C>NJ.BML`` and ``PSO/PL<C>TEX.AFS``. The GameCube disc
``GPOE8P`` has **no ``PSO/`` directory at all**: the same parts sit flat at the root, lower-case, with the class letter
kept:

===========================  ======================================  =====================
Dreamcast (what the code uses)  GameCube (what the disc has)          meaning
===========================  ======================================  =====================
``PSO/PLABDY00.NJ``          ``plAbdy00.nj``                         body mesh
``PSO/PLAHED03.NJ``          ``plAhed03.nj``                         head mesh
``PSO/PLANJ.BML``            ``plAnj.bml``                           the pack holding body + heads
``PSO/PLATEX.AFS``           ``plAtex.afs``                          the texture archive
===========================  ======================================  =====================

That mismatch is why `pso_player.build` fails on this disc: it asks for a path that does not exist. `gc_path` is the
translation, and `read_part` tries the GameCube name first and falls back to the Dreamcast one so the same code works on
both layouts.
"""
from __future__ import annotations


def gc_path(path: str) -> str:
    """Translate a Dreamcast-era PSO path to the GameCube disc's flat, lower-case name.

    ``PSO/PLCHED00.NJ`` -> ``plChed00.nj``. Anything that is not a ``PSO/PL*`` path is only stripped of its directory and
    lower-cased, which is right for the GameCube layout and harmless as a fallback.
    """
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    if name.upper().startswith("PL") and len(name) > 3:
        # PL + class letter + remainder; the class letter keeps its case on the disc
        cls = name[2]
        return f"pl{cls}{name[3:].lower()}"
    return name.lower()


def dc_path(path: str) -> str:
    """The inverse: ``plChed00.nj`` -> ``PSO/PLCHED00.NJ`` (for anyone who still needs the old name)."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower().startswith("pl") and len(name) > 3:
        cls = name[2].upper()
        return f"PSO/PL{cls}{name[3:].upper()}"
    return f"PSO/{name.upper()}"


def read_part(disc, path: str) -> bytes:
    """Read a character part from whichever name the disc actually has.

    Tries the GameCube name first, then the name as given (which is what a Dreamcast rip needs), and raises a
    ``FileNotFoundError`` that names both candidates when neither exists -- so a wrong class letter is obvious rather
    than mysterious.
    """
    candidates = []
    for candidate in (gc_path(path), path):
        if candidate not in candidates:
            candidates.append(candidate)
    last = None
    for candidate in candidates:
        try:
            return disc.read(candidate)
        except Exception as exc:                      # noqa: BLE001 - the point is to try the next name
            last = exc
    raise FileNotFoundError(f"no character part for {path!r} (tried {candidates}): {last}")


def class_parts(cls: str, head: int = 0) -> dict:
    """The four part paths for a class letter, in GameCube form: body, head, pack, textures."""
    return {"body": gc_path(f"PSO/PL{cls}BDY00.NJ"),
            "head": gc_path(f"PSO/PL{cls}HED{head:02d}.NJ"),
            "pack": gc_path(f"PSO/PL{cls}NJ.BML"),
            "textures": gc_path(f"PSO/PL{cls}TEX.AFS")}


# --- NJCM byte order: the Dreamcast packs are little-endian, the GameCube ones are not --------------------------
#
# The chunk framing stays little-endian on both platforms (the size field is read `<I` everywhere), but the node/vertex
# payload became **big-endian** on GameCube. `ninja.NJ` defaults to little-endian, which is right for a Dreamcast rip and
# wrong here: on `plCbdy00.nj` the root model offset is `30 10 00 00`-style bytes and reading them little-endian gave
# 0x30100000, a 806 MB offset into a 24 KB file.
#
# The probe below reads that one field both ways and believes whichever lands inside the chunk.

import struct


def njcm_payload(data: bytes) -> bytes:
    """The NJCM chunk's payload (after the 8-byte magic+size framing)."""
    o = data.find(b"NJCM")
    if o < 0:
        raise ValueError("no NJCM chunk")
    size = struct.unpack_from("<I", data, o + 4)[0]
    return data[o + 8:o + 8 + size]


def njcm_is_big_endian(data: bytes) -> bool:
    """True when an NJCM's node payload is big-endian, which is what every GameCube pack in this game uses."""
    payload = njcm_payload(data)
    if len(payload) < 8:
        raise ValueError("NJCM payload too short to hold a root node")
    model_be = struct.unpack_from(">I", payload, 4)[0]
    model_le = struct.unpack_from("<I", payload, 4)[0]
    in_range_be = 8 <= model_be < len(payload)
    in_range_le = 8 <= model_le < len(payload)
    if in_range_be and not in_range_le:
        return True
    if in_range_le and not in_range_be:
        return False
    return model_be < model_le          # both plausible: the smaller offset is the real one


def nj(data: bytes, *, be: bool | None = None):
    """Parse an NJCM with the right byte order, without the caller having to know which platform it came from."""
    from . import ninja
    if be is None:
        be = njcm_is_big_endian(data)
    return ninja.NJ(data, be=be)


def nj_part(disc, path: str, *, be: bool | None = None):
    """Read a character part from whichever name the disc has and parse it with the right byte order."""
    return nj(read_part(disc, path), be=be)
