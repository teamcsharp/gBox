"""Bloody Roar (USA) PSX unlock-on-load: bounded, offline, evidence-first probe harness.

Request #2062 (cc661f0125f0427d). This module does NOT claim any verified unlock.
It provides the reproducible first milestone required by the engineering queue
(next_stage = inventory / study-title / magic-census):

  1. Locate the owned build image (CHD v4/v5 or raw MODE2/2352 BIN) and stream-hash it.
  2. List the ISO9660 tree (bounded member count) and identify the PS-X EXE.
  3. Run a magic/string census over the EXE head to seed the unlock-target hunt
     (hidden/unlock/gallery gate strings) as explicit hypotheses.

Every artifact it emits is labelled as a hypothesis, not a verified target.
Live runtime writes (gbox.tools write_memory/freeze_memory/cheats) are intentionally
NOT invoked here; a launchable session on an authorized idle worker plus operator
acceptance is required before any memory write (see request #2062 report).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

GAME_ID = "2f24bd9f137c142f"
TITLE = "Bloody Roar (USA)"
PLATFORM = "psx"
# Known disc label from the set naming convention; confirmed against the files at
# runtime, never copied as authority.
EXPECTED_SLUS = "SLUS_007.02"
MAX_MEMBERS = 4096          # bounded walk
STR_MIN, STR_MAX = 4, 64    # ASCII census window
BLOCK = 1 << 20

# Candidate substrings that historically gate unlock menus in PSX fighting games.
CENSUS_PATTERNS = [
    r"[Aa]nimal.?[Ff]ight", r"[Hh]idden", r"[Uu]nlock", r"[Cc]lear",
    r"[Ss]ecret", r"CONCEPT", r"[Gg]allery", r"[Mm]useum", r"[Oo]ptime",
    r"BEAST", r"[Mm]aster", r"[Ee]xtra", r"[Cc]ostume",
]


def sha256_stream(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(BLOCK):
            h.update(chunk)
    return h.hexdigest()


def find_owned_image(cache_root: Path) -> dict:
    """Locate the owned Bloody Roar image in the gBox cache (bounded search)."""
    cache_root = Path(cache_root)
    hits = []
    for cand in (cache_root / GAME_ID, cache_root / "psx" / GAME_ID):
        if cand.is_dir():
            hits.extend(sorted(p for p in cand.iterdir()
                               if p.suffix.lower() in {".chd", ".bin", ".cue"}))
    for name in ("bloody roar", "bloody_roar", "bloodyroar"):
        hits.extend(p for p in cache_root.rglob(f"*{name}*")
                    if p.suffix.lower() in {".chd", ".bin"})
    if not hits:
        return {"found": False, "game_id": GAME_ID,
                "next_step": "image absent from local cache; provision via the "
                             "/mnt/gbox hyperspin PSX tree or a Windows-kiosk scan"}
    image = hits[0]
    return {"found": True, "game_id": GAME_ID, "path": str(image),
            "bytes": image.stat().st_size, "sha256": sha256_stream(image)}


def census_bytes(data: bytes) -> dict:
    """Bounded ASCII + magic census of one member's bytes (hypothesis seed only)."""
    strings = []
    for m in re.finditer(rb"[\x20-\x7e]{%d,%d}" % (STR_MIN, STR_MAX), data):
        s = m.group().decode("ascii")
        if any(re.search(p, s) for p in CENSUS_PATTERNS):
            strings.append({"offset": m.start(), "text": s})
        if len(strings) >= 256:
            break
    magic_hits = {}
    for magic in (b"\x82\x49", b"\x50\x53\x45", b"PSF", b"\x00\x10\x80"):
        i = data.find(magic)
        if i >= 0:
            magic_hits[magic.hex()] = i
    return {"bytes": len(data), "candidate_strings": strings, "magic_first_offsets": magic_hits}


def _open_disc(path: Path):
    """Return (disc, kind); disc exposes .files/.read/.close or None for manual frames."""
    from . import psxdisc
    suffix = path.suffix.lower()
    if suffix == ".bin":
        return psxdisc.RawBin(str(path), writable=False), "raw-bin"
    if suffix != ".chd":
        raise ValueError(f"unsupported image type {suffix}")
    import struct
    with path.open("rb") as f:
        ver = struct.unpack_from(">I", f.read(16), 12)[0]
    if ver == 4:
        return psxdisc.PSXDisc(str(path)), "chd-v4"
    if ver == 5:
        from .chd import _FrameSource
        from .formats import iso9660
        src = _FrameSource(str(path))

        def data(lba: int) -> bytes:
            s = src.read(lba)
            return s[24:24 + 2048] if s[15] == 2 else s[16:16 + 2048]

        pvd = data(16)
        if pvd[1:6] != b"CD001":
            raise ValueError("no ISO9660 PVD in CHD v5")
        root = pvd[156:156 + 34]
        files: dict[str, tuple[int, int]] = {}
        for parts, rec, _d in iso9660.walk(iso9660.sector_reader(data),
                                           int.from_bytes(root[2:6], "little"),
                                           int.from_bytes(root[10:14], "little")):
            if not rec.is_dir:
                files["".join(p + "/" for p in parts) + rec.name] = (rec.lba, rec.size)

        class _V5:
            def __init__(self):
                self.files = files

            def read(self, name, offset=0, size=None):
                lba, length = self.files[name]
                size = length - offset if size is None else size
                first, last = offset // 2048, (offset + size + 2047) // 2048
                buf = b"".join(data(lba + i) for i in range(first, last))
                return buf[offset - first * 2048: offset - first * 2048 + size]

            def close(self):
                pass

        return _V5(), "chd-v5"
    raise ValueError(f"CHD v{ver}: no reader")


def inspect_image(image: Path, exe_name: str = EXPECTED_SLUS) -> dict:
    """Inventory the owned build: ISO9660 listing, EXE identity, census of the EXE head.

    Raises on unreadable/unhandled containers so the caller records the exact error.
    """
    path = Path(image)
    disc, kind = _open_disc(path)
    files = {name: {"lba": lba, "bytes": size}
             for name, (lba, size) in sorted(disc.files.items())[:MAX_MEMBERS]}
    exe = None
    needle = exe_name.upper()
    for name in files:
        if needle in name.upper().replace("\\", "/"):
            exe = name
            break
    result = {"image": str(path), "kind": kind, "member_count": len(files),
              "members": files, "exe_member": exe, "verified": False,
              "gameplay_verified": False,
              "note": "inventory only; census hits are hypotheses, not verified unlock flags"}
    if exe:
        head = disc.read(exe, 0, min(files[exe]["bytes"], 1 << 20))
        result["exe_head_census"] = census_bytes(head)
        result["exe_sha256"] = hashlib.sha256(head).hexdigest()
    disc.close()
    return result


def save_manifest(manifest: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{GAME_ID}-inventory.json"
    p.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return p
