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
