"""Metal Gear Solid: The Twin Snakes (GameCube, GGSEA4) - `stage.dat` container: read, and rebuild a stage in place.

The game runs Konami's MGS2 engine ported to the GameCube ("mgs2gcn", main code in shared/mgso.rel; disc files
`stage.dat`, `demo.dat`, `shared/face.dat` ...). docs/twin_snakes.md has the full inventory. Layout (big-endian,
measured on both owned USA discs):

* stage.dat header: u32 ?, u32 0x00010001, u16 stage count, u16 0xcccc, u32 ?, then `count` records of
  {char name[8], u32 sector}: the stage starts at sector * 0x800 inside stage.dat (114 stages on disc 1, 117 on
  disc 2: r_cmmn, r_sna (Snake's resident set), area01a .. area27b, demo* cut-scene stages, init, n_title ...).
* A stage: u32 row count, then rows {u32 key, u32 value}, padded to 0x800. Rows come in pages:
    {0x7f000000 | page, uncompressed size}  {0x7e000000 | compressed size, data offset}  file rows ...
    {0x7f000000, uncompressed size}
  The page data is one zlib stream (level 6, `78 9c`) at `0x800-aligned header end + data offset`; pages follow
  each other, each padded to 0x800 (shared/face.dat stores its pages raw: a row {0, size} opens the page). A file row is {type << 24 | strcode(name), offset in the uncompressed page};
  a file ends where the next one starts (or at the page end).
* strcode: Konami's 24-bit name hash (`strcode`): `snake_def` = 0xf7a622 (Snake's model), `sna_def` = 0x413aa8
  (his texture set). The type byte is the file kind: 0x0a model (.kms/.kmx), 0x13 texture set (.tri), 0x0c motion
  archive (.mar, "aRAM"), 0x06 script (.gcx, every stage's `scenerio`), 0x02 model companion, 0x0e/0x12/0x15 motion
  side tables, 0x07 collision (.hzx).

Rebuilding (`rebuild_stage`) recompresses only the pages whose files changed (level 9; the stock data is level 6
and recompresses byte for byte) and lays the pages out again from the first changed one. The stage must still fit
in its own sector span (up to the next stage's sector) so no other stage, file or FST entry moves; `StageTooBig`
says by how much it does not.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

STAGE_DAT = "stage.dat"
SECTOR = 0x800
PAGE = 0x7F
PACKED = 0x7E

# type byte -> what it is (extension as the engine's debug strings / data.cnf name them)
TYPES = {0x02: "model companion", 0x05: "font stub", 0x06: "gcx script", 0x07: "hzx collision", 0x0A: "kms model",
         0x0B: "?", 0x0C: "mar motion archive", 0x0E: "motion table", 0x11: "?", 0x12: "motion index",
         0x13: "tri texture set", 0x15: "motion header"}
MODEL, TEXTURES = 0x0A, 0x13


def strcode(name: str) -> int:
    """Konami's 24-bit name hash (MGS2 engine)."""
    h = 0
    for c in name.encode("latin-1"):
        h = ((h >> 19) | (h << 5)) & 0xFFFFFF
        h = (h + c) & 0xFFFFFF
    return h


class StageTooBig(ValueError):
    pass


@dataclass
class StageFile:
    page: int
    type: int
    hash: int
    offset: int
    data: bytes

    @property
    def key(self) -> tuple[int, int]:
        return (self.type, self.hash)


@dataclass
class Page:
    number: int
    data: bytes
    rows: list[tuple[int, int]]            # (type << 24 | hash, offset)
    packed: bytes = b""                    # the stock zlib stream (reused when the page is unchanged)
    raw: bool = False                      # stored uncompressed (face.dat): row {0, size} instead of 0x7f / 0x7e


@dataclass
class Stage:
    name: str
    sector: int
    span: int                              # bytes up to the next stage (or the end of stage.dat)
    pages: list[Page] = field(default_factory=list)
    trailer: list[tuple[int, int]] = field(default_factory=list)   # rows after the last page (zero padding rows)

    def files(self) -> list[StageFile]:
        out = []
        for p in self.pages:
            for j, (key, off) in enumerate(p.rows):
                end = p.rows[j + 1][1] if j + 1 < len(p.rows) else len(p.data)
                out.append(StageFile(p.number, key >> 24, key & 0xFFFFFF, off, p.data[off:end]))
        return out

    def find(self, hash_: int, type_: int | None = None) -> StageFile | None:
        return next((f for f in self.files() if f.hash == hash_ and (type_ is None or f.type == type_)), None)


def directory(head: bytes) -> list[tuple[str, int]]:
    """stage.dat's first bytes -> [(stage name, sector)] in directory order (names repeat: area99a twice)."""
    n = struct.unpack_from(">H", head, 8)[0]
    out = []
    for i in range(n):
        name, sec = struct.unpack_from(">8sI", head, 16 + 12 * i)
        out.append((name.rstrip(b"\0").decode("latin-1"), sec))
    return out


def dir_size(head: bytes) -> int:
    return 16 + 12 * struct.unpack_from(">H", head, 8)[0]


def parse_stage(blob: bytes, name: str = "", sector: int = 0, span: int | None = None) -> Stage:
    """One stage's bytes (from its sector; at least the whole span) -> Stage with decompressed pages."""
    n = struct.unpack_from(">I", blob, 0)[0]
    rows = [struct.unpack_from(">II", blob, 4 + 8 * k) for k in range(n)]
    hdr = (4 + 8 * n + SECTOR - 1) & ~(SECTOR - 1)
    st = Stage(name, sector, span if span is not None else len(blob))
    k, raw_off = 0, 0
    while k < n:
        key, val = rows[k]
        if key == 0 and val:                               # an uncompressed page (shared/face.dat)
            data = bytes(blob[hdr + raw_off: hdr + raw_off + val])
            raw_off += (val + SECTOR - 1) & ~(SECTOR - 1)
            k += 1
            frows = []
            while k < n and not (rows[k][0] >> 24 == PAGE and rows[k][0] & 0xFFFFFF == 0):
                frows.append(rows[k])
                k += 1
            k += 1
            st.pages.append(Page(len(st.pages), data, frows, b"", True))
        elif key >> 24 == PAGE and key & 0xFFFFFF:
            pk, off = rows[k + 1]
            if pk >> 24 != PACKED:
                raise ValueError(f"stage {name}: page {key & 0xffffff} has no packed-data row")
            packed = bytes(blob[hdr + off: hdr + off + (pk & 0xFFFFFF)])
            data = zlib.decompress(packed)
            if len(data) != val:
                raise ValueError(f"stage {name}: page {key & 0xffffff} inflates to {len(data)}, header says {val}")
            k += 2
            frows = []
            while k < n and not (rows[k][0] >> 24 == PAGE and rows[k][0] & 0xFFFFFF == 0):
                frows.append(rows[k])
                k += 1
            k += 1
            st.pages.append(Page(key & 0xFFFFFF, data, frows, packed))
        else:
            st.trailer.append((key, val))
            k += 1
    return st


def build_stage(st: Stage, changed: set[int] | None = None, level: int = 9) -> bytes:
    """Stage -> bytes (header + pages). Pages not in `changed` keep their stock zlib stream."""
    changed = set(changed or ())
    rows, blobs, off = [], [], 0
    for p in st.pages:
        if p.raw:
            rows += [(0, len(p.data))] + list(p.rows) + [(PAGE << 24, len(p.data))]
            pad = (-len(p.data)) % SECTOR
            blobs.append(p.data + bytes(pad))
            off += len(p.data) + pad
            continue
        packed = p.packed if (p.number not in changed and p.packed) else zlib.compress(p.data, level)
        rows += [((PAGE << 24) | p.number, len(p.data)), ((PACKED << 24) | len(packed), off)]
        rows += list(p.rows)
        rows.append((PAGE << 24, len(p.data)))
        pad = (-len(packed)) % SECTOR
        blobs.append(packed + bytes(pad))
        off += len(packed) + pad
    rows += st.trailer
    head = struct.pack(">I", len(rows)) + b"".join(struct.pack(">II", a, b) for a, b in rows)
    head += bytes((-len(head)) % SECTOR)
    return head + b"".join(blobs)


def replace_files(st: Stage, new: dict[tuple[int, int], bytes]) -> set[int]:
    """Swap file contents in their pages ({(type, hash): bytes}); later files of a page shift and their rows follow.
    Files are kept 0x20-aligned like the stock pages. -> the page numbers that changed."""
    touched = set()
    for p in st.pages:
        if not any((key >> 24, key & 0xFFFFFF) in new for key, _ in p.rows):
            continue
        parts, rows, off = [], [], 0
        for j, (key, o) in enumerate(p.rows):
            end = p.rows[j + 1][1] if j + 1 < len(p.rows) else len(p.data)
            data = new.get((key >> 24, key & 0xFFFFFF), p.data[o:end])
            data = data + bytes((-len(data)) % 0x20)
            rows.append((key, off))
            parts.append(data)
            off += len(data)
        p.rows, p.data = rows, b"".join(parts)
        touched.add(p.number)
    missing = set(new) - {(f.type, f.hash) for f in st.files()}
    if missing:
        raise KeyError(f"stage {st.name}: no file {', '.join(f'{t:02x}:{h:06x}' for t, h in sorted(missing))}")
    return touched


def rebuild_stage(st: Stage, new: dict[tuple[int, int], bytes], level: int = 9) -> bytes:
    """Replace files and rebuild; refuses a stage that no longer fits its sector span."""
    changed = replace_files(st, new)
    out = build_stage(st, changed, level)
    if len(out) > st.span:
        raise StageTooBig(f"stage {st.name} grows to {len(out)} bytes, its slot holds {st.span} "
                          f"({len(out) - st.span} over)")
    return out


class StageDat:
    """stage.dat read through any `read(offset, size)` (a GCDisc file or bytes); `stage(name)` decodes one stage."""

    def __init__(self, read, size: int):
        self._read, self.size = read, size
        head = read(0, 16)
        self.head = read(0, dir_size(head))
        self.entries = directory(self.head)

    @classmethod
    def from_bytes(cls, data: bytes) -> "StageDat":
        return cls(lambda o, n: data[o:o + n], len(data))

    @classmethod
    def from_disc(cls, disc) -> "StageDat":
        off, size = disc.files[STAGE_DAT]
        return cls(lambda o, n: disc._r(off + o, n), size)

    def names(self) -> list[str]:
        return [n for n, _ in self.entries]

    def span(self, i: int) -> tuple[int, int]:
        sec = self.entries[i][1]
        nxt = min([s for _, s in self.entries if s > sec] or [self.size // SECTOR])
        return sec * SECTOR, (nxt - sec) * SECTOR

    def index(self, name: str) -> int:
        return [n for n, _ in self.entries].index(name)

    def stage(self, which: str | int) -> Stage:
        i = which if isinstance(which, int) else self.index(which)
        off, span = self.span(i)
        return parse_stage(self._read(off, span), self.entries[i][0], self.entries[i][1], span)

    def stages_with(self, hash_: int, type_: int = MODEL) -> list[int]:
        """Directory indices of the stages holding this file (reads each stage's header only)."""
        out = []
        for i, (_n, _s) in enumerate(self.entries):
            off, span = self.span(i)
            if span <= 0:
                continue
            n = struct.unpack(">I", self._read(off, 4))[0]
            if not 0 < n < 0x4000:
                continue
            rows = self._read(off + 4, 8 * n)
            if any(struct.unpack_from(">I", rows, 8 * k)[0] == (type_ << 24 | hash_) for k in range(n)):
                out.append(i)
        return out
