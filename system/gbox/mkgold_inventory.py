"""Mortal Kombat Gold (Dreamcast) inventory: disc layout, the roster in the executable's character-ID order, and each
character's model (.GEO), texture page (.IMG), sound bank (.KAT) and bio/ending movie (.SFD) files.

MK Gold is Eurocom's port of the MK4 engine. Every model and texture container on the disc starts with the magic
"0.1v", a u32 total size and a u32 record count, then 20 zero bytes (a 0x20-byte header):

* .GEO: count x 32-byte records {u16 flags, u16 n, u32 rel, 24 bytes}. A record whose flags have bit 0x80 set
  carries inline 2D sprite data. For every other record `rel` is self-relative: its data starts at
  (record + 4) + rel. The rule holds on all 149 GEO files of T-9701N V1.006. A main character model has 30-44
  flag-1 part records, usually one part list stored twice (Kitana 2 x 15, Liu Kang 2 x 17; Kung Lao's copies
  differ slightly). A 12-byte container (magic, size 12, count 0) is an empty placeholder: VS_NS_GE, because
  Reiko has no versus-screen art.
* .IMG: count x {32-byte record (u16 width, u16 height, ...), width*height 16-bit texels}. Character pages are
  one 512x256 page; stages hold two 512x512 pages.

1ST_READ.BIN (SH-4, loaded at 0x8C010000) holds the tables that tie them together. They are found here by content,
not fixed addresses: the 24 roster names in character-ID order (23 = "belokk", cut, no assets), the movie table
(attract movies, then 23 bio and 23 ending pointers, NULL where a character has none), the sound-bank list
(fx, menu, then 23 ch_*.kat in ID order) and the 20-byte GEO/IMG load table.

The 2- and 3-letter character codes are internal: NS is Reiko, NNS is Noob Saibot, ME is Kai, SB is Sonya,
WG is Fujin, JC is Johnny Cage and JX is Jax. They come from the bio movie table aligned with the roster names.
Noob has no bio movie, so his code is the one character model set left over.

    python -m gbox.mkgold_inventory DISC.gdi --sha256 <owned CHD sha256> --out manifest.json
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path

KEY = 0x8C010000                      # 1ST_READ.BIN load address
MAGIC = b"0.1v"                       # every .GEO / .IMG container
HEADER = RECORD = 0x20
STUB = 12                             # empty placeholder container: magic, size 12, count 0
SPRITE = 0x80                         # GEO record flag: inline 2D sprite data, no data offset
GEO_ENTRY = 20                        # 1ST_READ GEO/IMG load-table record: geo*, img*, id<<16|slot, 0, 0
VARIANTS = ("a", "e", "g", "m", "fat", "fat2", "vs")   # costumes a/e/g, select sprite m, fatality sets, versus


def ip_info(sector0: bytes) -> dict:
    """Dreamcast IP.BIN header fields (first 256 bytes of the high-density area)."""
    f = lambda a, b: sector0[a:b].decode("latin-1").strip()
    return {"hardware": f(0, 16), "maker": f(16, 32), "device": f(32, 48), "area": f(48, 56),
            "peripherals": f(56, 64), "product": f(64, 74), "version": f(74, 80), "date": f(80, 96),
            "boot": f(96, 112), "company": f(112, 128), "title": f(128, 256)}


# ------------------------------------------------------------------ "0.1v" containers

def container(data: bytes) -> tuple[int, int]:
    """(total size, record count) of a "0.1v" GEO/IMG container; ValueError when the header doesn't hold."""
    if len(data) < STUB or data[:4] != MAGIC:
        raise ValueError("not a 0.1v GEO/IMG container")
    size, count = struct.unpack_from("<II", data, 4)
    if size != len(data):
        raise ValueError(f"header size {size} != file size {len(data)}")
    if size == STUB and count == 0:
        return size, 0
    if size < HEADER or any(data[12:HEADER]):
        raise ValueError("short header or non-zero header padding")
    return size, count


def geo_records(data: bytes) -> list[dict]:
    """[{index, flags, n, offset, bytes}] of a .GEO file. offset/bytes are absent on inline sprite records; bytes
    runs to the next record's data (or the end of the file)."""
    size, count = container(data)
    if size == STUB:
        return []
    table_end = HEADER + count * RECORD
    if table_end > size:
        raise ValueError(f"{count} records overrun a {size}-byte file")
    recs = []
    for i in range(count):
        at = HEADER + i * RECORD
        flags, n, rel = struct.unpack_from("<HHI", data, at)
        rec = {"index": i, "flags": flags, "n": n}
        if not flags & SPRITE:
            off = at + 4 + rel
            if not table_end <= off < size:
                raise ValueError(f"record {i}: data offset 0x{off:x} outside 0x{table_end:x}..0x{size:x}")
            rec["offset"] = off
        recs.append(rec)
    starts = sorted({r["offset"] for r in recs if "offset" in r})
    end = dict(zip(starts, starts[1:] + [size]))
    for r in recs:
        if "offset" in r:
            r["bytes"] = end[r["offset"]] - r["offset"]
    return recs


def img_pages(data: bytes) -> list[dict]:
    """[{index, width, height, offset, bytes}] of a .IMG file: each page is a 32-byte record + 16-bit texels."""
    size, count = container(data)
    if size == STUB:
        return []
    o, pages = HEADER, []
    for i in range(count):
        if o + RECORD > size:
            raise ValueError(f"page {i}: record past the end of the file")
        w, h = struct.unpack_from("<HH", data, o)
        n = w * h * 2
        if not w or not h or o + RECORD + n > size:
            raise ValueError(f"page {i}: {w}x{h} texels overrun the file")
        page: dict = {"index": i, "width": w, "height": h, "offset": o + RECORD, "bytes": n}
        if any(data[o + 4:o + RECORD]):
            page["record"] = data[o + 4:o + RECORD].hex()
        pages.append(page)
        o += RECORD + n
    if o != size:
        raise ValueError(f"{size - o} bytes left after {count} texture pages")
    return pages


# ------------------------------------------------------------------ tables in 1ST_READ.BIN

class Exe:
    def __init__(self, data: bytes, key: int = KEY):
        self.d, self.key = data, key

    def u32(self, off: int) -> int:
        return struct.unpack_from("<I", self.d, off)[0]

    def cstr(self, addr: int) -> str | None:
        o = addr - self.key
        if not 0 <= o < len(self.d):
            return None
        e = self.d.find(b"\0", o, o + 80)
        if e <= o or not all(32 <= c < 127 for c in self.d[o:e]):
            return None
        return self.d[o:e].decode("ascii")

    def addr_of(self, s: str) -> int | None:
        """Address of the NUL-terminated string s that starts right after a NUL."""
        pat, o = s.encode() + b"\0", -1
        while True:
            o = self.d.find(pat, o + 1)
            if o < 0:
                return None
            if o == 0 or self.d[o - 1] == 0:
                return self.key + o

    def refs(self, addr: int) -> list[int]:
        """Word-aligned file offsets holding the pointer addr."""
        pat, out, o = struct.pack("<I", addr), [], -1
        while True:
            o = self.d.find(pat, o + 1)
            if o < 0:
                return out
            if o % 4 == 0:
                out.append(o)

    def strings(self, pattern: str) -> dict[int, str]:
        """{address: text} of every NUL-terminated string (preceded by a NUL) matching the regex pattern."""
        rx = re.compile(rb"(?<=\x00)(" + pattern.encode() + rb")\x00")
        return {self.key + m.start(1): m.group(1).decode() for m in rx.finditer(self.d)}

    def string_list(self, off: int, ok) -> list[str]:
        out = []
        while off + 4 <= len(self.d):
            s = self.cstr(self.u32(off))
            if s is None or not ok(s):
                break
            out.append(s)
            off += 4
        return out

    def anchored_list(self, first: str, ok) -> tuple[int | None, list[str]]:
        """The longest pointer list that starts with a pointer to the string `first`."""
        a, best = self.addr_of(first), (None, [])
        for r in self.refs(a) if a else []:
            got = self.string_list(r, ok)
            if len(got) > len(best[1]):
                best = (r, got)
        return best

    def pointer_table(self, targets: dict[int, str], max_null: int = 1) -> tuple[int | None, list]:
        """Longest run of words pointing at `targets`, allowing up to max_null NULL words between two hits:
        (file offset, [text or None])."""
        refs = sorted(o for a in targets for o in self.refs(a))
        best, cur = [], []
        for o in refs:
            if cur:
                gap = range(cur[-1][0] + 4, o, 4)
                if len(gap) > max_null or any(self.u32(x) for x in gap):
                    best, cur = max(best, cur, key=len), []
                else:
                    cur += [(x, None) for x in gap]
            cur.append((o, targets[self.u32(o)]))
        best = max(best, cur, key=len)
        return (best[0][0] if best else None), [t for _, t in best]


def exe_tables(exe: bytes, key: int = KEY) -> dict:
    x = Exe(exe, key)
    hexa = lambda off: None if off is None else f"0x{key + off:08X}"
    off, names = x.anchored_list("scorpion", lambda s: re.fullmatch(r"[a-z][a-z ]*", s) is not None)
    out = {"roster": {"addr": hexa(off), "names": names}}
    off, banks = x.anchored_list("fx.kat", lambda s: s.endswith(".kat"))
    out["sound_banks"] = {"addr": hexa(off), "names": banks}
    off, movies = x.pointer_table(x.strings(r"[a-z0-9_]{1,8}\.sfd"))
    out["movies"] = {"addr": hexa(off), "entries": movies}
    geos, imgs = x.strings(r"[a-z0-9_]{1,8}\.geo"), x.strings(r"[a-z0-9_]{1,8}\.img")
    hits = sorted(o for a in geos for o in x.refs(a) if o + GEO_ENTRY <= len(exe) and x.u32(o + 4) in imgs)
    best, cur = [], []
    for o in hits:
        if cur and o - cur[-1] != GEO_ENTRY:
            best, cur = max(best, cur, key=len), []
        cur.append(o)
    best = max(best, cur, key=len)
    entries = []
    for o in best:
        g, i, v, e1, e2 = struct.unpack_from("<5I", exe, o)
        e = {"geo": geos[g], "img": imgs[i], "id": v >> 16, "slot": v & 0xFFFF}
        if e1 or e2:
            e["extra"] = [e1, e2]
        entries.append(e)
    out["geo_table"] = {"addr": hexa(best[0] if best else None), "stride": GEO_ENTRY, "entries": entries}
    return out


# ------------------------------------------------------------------ roster

def stem(code: str, variant: str | None = None) -> str:
    """8.3 stem of a character model file: kl -> KL_GEO, (nns, a) -> NNS_A_GE, (kl, vs) -> VS_KL_GE."""
    s = f"{code}_geo" if variant is None else f"vs_{code}_geo" if variant == "vs" else f"{code}_{variant}_geo"
    return s[:8].upper()


def split_movies(entries: list) -> tuple[list, list, list]:
    """(attract, bio, ending) sections of the movie table; bio and ending are indexed by character ID."""
    first_bio = next(i for i, s in enumerate(entries) if s and s.startswith("mvbio"))
    first_end = next(i for i, s in enumerate(entries) if s and s.startswith("mvend"))
    bio = entries[first_bio:first_end]
    return entries[:first_bio], bio, (entries[first_end:] + [None] * len(bio))[:len(bio)]


def assign_codes(names: list[str], bios: list, banks: list[str], disc: set[str]) -> list[dict]:
    """Per roster slot {id, name, code, code_source, sound_bank}. A code comes from the bio movie (mvbio<code>.sfd);
    a playable slot without one (it has a sound bank) takes the only leftover character model set, i.e. a
    <code>_GEO.GEO that also has an alternate <code>_A_GEO costume."""
    chars = []
    for i, name in enumerate(names):
        m = re.fullmatch(r"mvbio([a-z0-9]+)\.sfd", (bios[i] if i < len(bios) else None) or "")
        chars.append({"id": i, "name": name, "code": m.group(1) if m else None,
                      "code_source": "bio movie table" if m else None,
                      "sound_bank": banks[i] if i < len(banks) else None})
    sets = {n[:-8].lower() for n in disc if n.endswith("_GEO.GEO")}
    sets = {c for c in sets if f"{stem(c, 'a')}.GEO" in disc}
    left = sorted(sets - {c["code"] for c in chars})
    open_ = [c for c in chars if c["code"] is None and c["sound_bank"]]
    if len(left) == 1 and len(open_) == 1:
        open_[0].update(code=left[0], code_source="elimination: the only model set without a bio movie")
    return chars


def track_spans(tracks) -> list[tuple[int, int]]:
    """[(first LBA, end LBA)] of each data track of a GDRom."""
    return [(s, s + Path(p).stat().st_size // z) for s, z, p in tracks]


def file_room(files: dict[str, tuple[int, int]], spans: list[tuple[int, int]]) -> dict[str, dict]:
    """{name: {lba, track, room}}: room is the bytes a rewritten file may use in place, up to the next file's LBA
    or the end of its data track."""
    items = sorted(files.items(), key=lambda kv: kv[1][0])
    out = {}
    for j, (name, (lba, size)) in enumerate(items):
        track = next(((s, e) for s, e in spans if s <= lba < e), (lba, lba + (size + 2047) // 2048))
        limit = track[1]
        if j + 1 < len(items):
            limit = min(limit, max(items[j + 1][1][0], lba + (size + 2047) // 2048))
        out[name] = {"lba": lba, "track": track[0], "room": (limit - lba) * 2048}
    return out


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def model_info(read, s: str, disc: set[str], room: dict) -> dict:
    geo = read(f"{s}.GEO")
    recs = geo_records(geo)
    info = {"geo": f"{s}.GEO", "geo_bytes": len(geo), "geo_room": room[f"{s}.GEO"]["room"],
            "geo_lba": room[f"{s}.GEO"]["lba"], "geo_sha256": _sha(geo), "records": len(recs),
            "record_flags": {f"0x{k:x}": v for k, v in sorted(Counter(r["flags"] for r in recs).items())},
            "mesh_counts": [r["n"] for r in recs if r["flags"] == 1]}
    if f"{s}.IMG" in disc:
        img = read(f"{s}.IMG")
        info.update(img=f"{s}.IMG", img_bytes=len(img), img_room=room[f"{s}.IMG"]["room"],
                    img_sha256=_sha(img), pages=[[p["width"], p["height"]] for p in img_pages(img)])
    return info


def inventory(gdi: str | Path, source_sha256: str | None = None) -> dict:
    from .gdrom import GDRom
    g = GDRom(gdi)
    hd = min(t[0] for t in g.tracks if t[0] >= 45000)
    ip = ip_info(g.sector(hd))
    exe = g.read(ip["boot"] or "1ST_READ.BIN")
    tabs = exe_tables(exe)
    attract, bios, ends = split_movies(tabs["movies"]["entries"])
    banks = [b for b in tabs["sound_banks"]["names"] if b.startswith("ch_")]
    disc = set(g.files)
    room = file_room(g.files, track_spans(g.tracks))
    chars, claimed, problems = assign_codes(tabs["roster"]["names"], bios, banks, disc), set(), []
    for c in chars:
        i = c["id"]
        c["bio_movie"] = bios[i] if i < len(bios) else None
        c["ending_movie"] = ends[i] if i < len(ends) else None
        if c["sound_bank"] and c["sound_bank"].upper() in disc:
            kat = g.read(c["sound_bank"].upper())
            c["sound_bank_bytes"], c["sound_bank_sha256"] = len(kat), _sha(kat)
        c["models"] = {}
        for v in (None,) + VARIANTS:
            s = stem(c["code"], v) if c["code"] else None
            if s and f"{s}.GEO" in disc:
                try:
                    c["models"][v or "main"] = model_info(g.read, s, disc, room)
                except ValueError as e:
                    problems.append(f"{s}: {e}")
                claimed.add(s)
    others, kinds = {}, Counter(n.rsplit(".", 1)[-1] for n in disc)
    for n in sorted(disc):
        if n.endswith(".GEO") and n[:-4] not in claimed:
            try:
                recs = geo_records(g.read(n))
                others[n[:-4]] = {"records": len(recs), "bytes": g.files[n][1],
                                  "record_flags": dict(Counter(f"0x{r['flags']:x}" for r in recs))}
            except ValueError as e:
                problems.append(f"{n}: {e}")
        if n.endswith(".IMG"):
            try:
                img_pages(g.read(n))
            except ValueError as e:
                problems.append(f"{n}: {e}")
    playable = [c for c in chars if c["models"]]
    return {
        "game": "Mortal Kombat Gold", "platform": "dreamcast", "source_sha256": source_sha256, "ip": ip,
        "tracks": [{"lba": s, "sector": z, "file": Path(p).name, "sectors": e - s}
                   for (s, z, p), (_, e) in zip(g.tracks, track_spans(g.tracks))],
        "file_count": len(disc), "kinds": dict(sorted(kinds.items())),
        "executable": {"name": ip["boot"], "size": len(exe), "sha256": _sha(exe), "load_address": f"0x{KEY:08X}",
                       "tables": {k: {kk: vv for kk, vv in t.items() if kk in ("addr", "stride")} | {
                           "count": len(t.get("names") or t.get("entries") or [])} for k, t in tabs.items()},
                       "geo_table": tabs["geo_table"]["entries"]},
        "attract_movies": attract,
        "roster_count": len(chars), "playable_count": len(playable),
        "characters": chars, "other_models": others, "problems": problems,
        "formats": {"GEO": "0.1v header (magic, u32 size, u32 count, 20 zero) + count x 32-byte {u16 flags, u16 n, "
                           "u32 rel (data at record+4+rel; inline when flags&0x80), 24 bytes}",
                    "IMG": "0.1v header + count x {32-byte record (u16 w, u16 h, ...), w*h 16-bit texels}",
                    "KAT": "Dreamcast Audio64 sound bank (fx/menu + one per character)",
                    "SFD": "Sofdec movies (attract, character bios, endings)"},
    }


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--sha256", help="sha256 of the owned source (CHD) to record")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    text = json.dumps(inventory(a.gdi, a.sha256), indent=1)
    if a.out:
        Path(a.out).write_text(text)
    else:
        print(text)


if __name__ == "__main__":
    sys.exit(main())
