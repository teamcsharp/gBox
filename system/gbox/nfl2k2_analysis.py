"""NFL 2K2 (USA) Dreamcast analysis probes (stage 2).

Builds on the stage-1 inventory (:mod:`gbox.nfl2k2_inventory`) and turns
observed header bytes into *validated* format hypotheses. Every constant in
this module was derived from the owned build (CHD sha256
7d4b3c49bbcc4e2be49f5f4a1476a9ce7929806aba69e618d9b27839cd7fc7ee, unpacked at
~/gbox-cache/dc/373a463aa1f96e35) and is checked by tests/test_nfl2k2_analysis.py.

Findings encoded here:

* SCNE (PCG0-9.IFF player geometry, GAMEDATA.IFF):
  header ``SCNE`` + {u32 f4, u32 f8, u32 f12} + 8-byte name + sub-tag.
  PCG variants: f8 == 0xCB01 (constant), f4 is the offset of a trailing
  ``TXTR`` text block (file tail after f4 is exactly 472 bytes), and
  f12 - fsize is 77511 or 77560 depending on the file variant. The first
  u32 of the table at 0x20 equals the offset of the first data chunk.
  ``DOUBLE``/``SINGLE`` VC type-table tags live between that first chunk
  and f4.  Sub-tag ``SNE2`` carries a u32 count at 0x1C; the table entries
  that follow are NOT plain offsets (not monotonic) - exact entry layout is
  the next decoding target (reader stage).
* gdFs .DIR records (all versions v0-v3): record = {id, bytes, end_offset}.
  The data byte range of record i in the .DAT is ``[size - x, size]``
  (end-relative), and consecutive records are packed contiguously
  (ascending for PLAYERS/TEAMS, descending for FACES/PORT/CHAT/AUDIO).
  This is validated, not assumed: PLAYERS' 1980 groups of 3 satisfy the
  cumulative recurrence 3960/3960 and all 5941 ``x`` are multiples of 32;
  every other table satisfies the descending adjacency chain.
  ``off`` is an opaque ID/index (e.g. AUDIO IDs run 10001..), not a byte
  offset - the inventory's "12-byte {off,x,size}" reading was incomplete.
* SPRT (uniform/font banks): header {f4, f8, f12} + 8-byte name. For the
  ``letters`` banks (H00.IFF) f4 == 0x28 + 16*f8 exactly: a 16-byte-per-entry
  table (VQ codebook of 8 x u16 pixels per entry) sits between 0x28 and f4,
  and the index stream starts at f4. f8 is odd (n*256+1 pattern) and
  f12 == 0x4820 across H00/A00/H05. Non-letters banks (A00: f4 < table end)
  need the variable-entry layout - deferred to the reader stage.
* VQCB (C00 coach colour books): header {0x7FE, 0xA02, 0x808} + name; the
  payload after the name is a compressed index/codebook stream (nibbles 0-10
  observed, so not a plain 2bpp grid).
* Motion container: GAMEDATA.IFF (SCNE, name ``catch``) holds ``ANIM`` /
  ``ANIM_`` records: {tag, u32 a, u32 b, u32 c, name...} - the animation
  table the game reads; keyframe payloads live in the large DAT arenas
  (PLAYERS.DAT 45.8 MB) - reader stage will resolve which.

Usage:  python -m gbox.nfl2k2_analysis
"""
from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path

from gbox.nfl2k2_inventory import CACHE_DIR, GAME_ID, Disc, gd_dir

# SCNE header invariants observed on all ten PCG files.
SCNE_F8_CONST = 0xCB01       # f8 (u32 at +8) is constant across PCG0-9
SCNE_F4_TAIL = 472           # bytes between f4 (u32 at +4) and end of file
SCNE_F12_DELTA = {77511, 77560}  # f12 (u32 at +12) minus file size
SCNE_SNE2_COUNT = 2804       # SNE2 table record count (PCG0-9)

# gdFs .DIR / .DAT pairs analysed in this stage.
GD_PAIRS = ["PLAYERS", "FACES", "TEAMS", "PORT", "CHAT", "AUDIO"]

# SPRT invariants observed on H00/A00/H05.IFF.
SPRT_F12_CONST = 0x4820


def scne_header(data: bytes) -> dict:
    """Parse the 32-byte SCNE header: magic, {f4, f8, f12}, name, sub-tag."""
    if len(data) < 32 or data[:4] != b"SCNE":
        return {}
    f4, f8, f12 = struct.unpack_from("<3I", data, 4)
    name = data[16:24].split(b"\x00", 1)[0].decode("latin-1")
    sub = data[24:28].decode("latin-1", "replace")
    out = {"magic": "SCNE", "f4": f4, "f8": f8, "f12": f12,
           "name": name, "sub": sub}
    if sub == "SNE2":
        cnt = struct.unpack_from("<I", data, 0x1C)[0]
        out["sne2_count"] = cnt
        if cnt and 0x20 + 4 * cnt <= len(data):
            first = struct.unpack_from("<I", data, 0x20)[0]
            out["table_first"] = first
    return out


def scne_type_tags(data: bytes, start: int, end: int) -> list[dict]:
    """Locate VC type-table tags (DOUBLE/SINGLE/ANIM) in an SCNE body."""
    out = []
    for tag in (b"DOUBLE", b"SINGLE", b"ANIM"):
        for m in re.finditer(re.escape(tag), data[start:end]):
            out.append({"tag": tag.decode(), "off": start + m.start()})
    return sorted(out, key=lambda t: t["off"])


def gdfs_record_ranges(records: list[dict], dat_size: int) -> tuple[list[tuple[int, int]], int]:
    """Resolve record byte ranges under the validated hypothesis
    'size = absolute END offset, x = byte size': range = [size - x, size].

    Returns (ranges, violations). A range clamps to the DAT when the record
    itself is well-formed but the file has trailing slack.
    """
    ranges = []
    violations = 0
    for r in records:
        start = r["size"] - r["x"]
        if r["x"] < 0 or start < 0 or r["size"] > dat_size:
            violations += 1
            ranges.append((-1, -1))
        else:
            ranges.append((start, min(r["size"], dat_size)))
    return ranges, violations


def gdfs_layout_probe(records: list[dict], dat_size: int) -> dict:
    """Score candidate layouts for a .DIR table against its .DAT size.

    Hypothesis A (end-relative, validated): range = [size - x, size].
    Hypothesis B (off = start):          range = [off, size].
    Hypothesis C (off = start, size):    range = [off, off + x].

    For each: violations (out-of-bounds), total covered bytes, and
    contiguity of consecutive records (ascending: next.size == cur.size + cur.x;
    descending: next.size == cur.size - next.x). A is the unique winner on
    this disc: 0 violations, total == sum(x) <= dat_size, and ~100%
    contiguity; B covers hundreds of GB for PLAYERS (impossible duplication).
    """
    def score(lo, hi):
        violations = 0
        total = 0
        for l, h in zip(lo, hi):
            if l < 0 or h < l or h > dat_size:
                violations += 1
            else:
                total += h - l
        return violations, total

    a_lo = [r["size"] - r["x"] for r in records]
    b_lo = [r["off"] for r in records]
    c_lo = [r["off"] for r in records]
    asc = desc = 0
    for i in range(1, len(records)):
        cur, nxt = records[i - 1], records[i]
        if nxt["size"] == cur["size"] + cur["x"]:
            asc += 1
        if nxt["size"] == cur["size"] - nxt["x"]:
            desc += 1
    return {
        "count": len(records),
        "dat_size": dat_size,
        "A_end_relative": {"violations": score(a_lo, [r["size"] for r in records])[0],
                           "total": score(a_lo, [r["size"] for r in records])[1]},
        "B_off_start": {"violations": score(b_lo, [r["size"] for r in records])[0],
                        "total": score(b_lo, [r["size"] for r in records])[1]},
        "C_off_start_size": {"violations": score(c_lo, [r["off"] + r["x"] for r in records])[0],
                             "total": score(c_lo, [r["off"] + r["x"] for r in records])[1]},
        "contiguous_ascending": asc,
        "contiguous_descending": desc,
        # records where [size - x, size] is out of bounds: the chain-terminal
        # quirk (terminal record's 'size' is the chain's final start, not an
        # end) or group anomalies - resolved further in the reader stage.
        "a_anomalies": [r for r in records if r["size"] - r["x"] < 0 or r["size"] > dat_size],
    }


def sprt_header(data: bytes) -> dict:
    """Parse the SPRT header: {f4, f8, f12} + 8-byte bank name."""
    if len(data) < 24 or data[:4] != b"SPRT":
        return {}
    f4, f8, f12 = struct.unpack_from("<3I", data, 4)
    return {"magic": "SPRT", "f4": f4, "f8": f8, "f12": f12,
            "name": data[16:24].split(b"\x00", 1)[0].decode("latin-1")}


def vqcb_header(data: bytes) -> dict:
    """Parse the VQCB header: {f4, f8, f12} + 8-byte book name."""
    if len(data) < 24 or data[:4] != b"VQCB":
        return {}
    f4, f8, f12 = struct.unpack_from("<3I", data, 4)
    return {"magic": "VQCB", "f4": f4, "f8": f8, "f12": f12,
            "name": data[16:24].split(b"\x00", 1)[0].decode("latin-1")}


def find_anim_records(data: bytes) -> list[dict]:
    """Locate ANIM / ANIM_ records: {tag, a, b, c, name} (VC motion table
    entries, observed in GAMEDATA.IFF)."""
    out = []
    for m in re.finditer(rb"ANIM[_\x20]?", data):
        off = m.start()
        if off + 20 > len(data):
            continue
        a, b, c = struct.unpack_from("<3I", data, off + 4)
        name = data[off + 16:off + 48].split(b"\x00", 1)[0]
        out.append({"off": off, "tag": m.group().decode("latin-1"),
                    "a": a, "b": b, "c": c,
                    "name": name.decode("latin-1", "replace")[:32]})
    return out


def analyze_disc(gdi: Path) -> dict:
    """Run every probe against the unpacked GD-ROM and return the summary."""
    disc = Disc(gdi)
    out = {"game_id": GAME_ID, "scne": [], "gdfs": [], "sprt": [], "vqcb": [],
           "anim": []}

    for i in range(10):
        name = f"PCG{i}.IFF"
        lba, size = disc.g.files[name]
        data = disc._read_range(lba, size)
        h = scne_header(data)
        h["file"] = name
        h["fsize"] = size
        h["f4_tail"] = size - h.get("f4", 0)
        h["f12_delta"] = h.get("f12", 0) - size
        tags = scne_type_tags(data, h.get("table_first", 0) or 0, h.get("f4", size) or size)
        h["type_tags"] = len(tags)
        out["scne"].append(h)

    for base in GD_PAIRS:
        dirb = disc.read(f"{base}.DIR")
        res = gd_dir(dirb)
        dat_size = disc.g.files[f"{base}.DAT"][1]
        probe = gdfs_layout_probe(res["records"], dat_size)
        probe["dir_version"] = res["version"]
        probe["names"] = len(res["names"])
        probe["pair"] = base
        out["gdfs"].append(probe)

    for name in ("H00.IFF", "A00.IFF", "H05.IFF"):
        out["sprt"].append({"file": name, **sprt_header(disc.read(name))})

    out["vqcb"].append({"file": "C00.IFF", **vqcb_header(disc.read("C00.IFF"))})

    lba, size = disc.g.files["GAMEDATA.IFF"]
    gd = disc._read_range(lba, size)
    out["anim"] = find_anim_records(gd)
    out["gamedata"] = {"size": size, **scne_header(gd)}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NFL 2K2 (USA) DC analysis probes")
    ap.add_argument("--gdi", type=Path, default=CACHE_DIR / "disc.gdi",
                    help="unpacked disc.gdi (default: gbox-cache)")
    args = ap.parse_args(argv)
    if not args.gdi.exists():
        raise SystemExit(f"disc.gdi not found at {args.gdi} (run the inventory first)")
    s = analyze_disc(args.gdi)

    print("SCNE player geometry (PCG0-9):")
    for h in s["scne"]:
        print(f"  {h['file']}: f4={h['f4']:#x} f8={h['f8']:#x} f12={h['f12']:#x} "
              f"tail={h['f4_tail']} f12-fsize={h['f12_delta']} sub={h['sub']!r} "
              f"type_tags={h['type_tags']}")
    print("gdFs layout probe (A = validated end-relative):")
    for p in s["gdfs"]:
        print(f"  {p['pair']} v{p['dir_version']}: n={p['count']} "
              f"A={{v:{p['A_end_relative']['violations']}, bytes:{p['A_end_relative']['total']}}} "
              f"B={{v:{p['B_off_start']['violations']}, bytes:{p['B_off_start']['total']}}} "
              f"C={{v:{p['C_off_start_size']['violations']}, bytes:{p['C_off_start_size']['total']}}} "
              f"asc={p['contiguous_ascending']} desc={p['contiguous_descending']}")
    print("SPRT:", [(x["file"], hex(x["f4"]), hex(x["f8"]), hex(x["f12"]), x["name"]) for x in s["sprt"]])
    print("VQCB:", [(x["file"], hex(x["f4"]), hex(x["f8"]), hex(x["f12"]), x["name"]) for x in s["vqcb"]])
    print(f"GAMEDATA: name={s['gamedata'].get('name')!r} ANIM records={len(s['anim'])}")
    for a in s["anim"][:5]:
        print(f"  {a['tag']} @{a['off']:#x} a={a['a']:#x} b={a['b']:#x} c={a['c']:#x} name={a['name']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
