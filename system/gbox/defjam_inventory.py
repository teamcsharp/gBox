"""Def Jam: Vendetta PS2 (SLUS_206.39, VER 1.00 NTSC; AKI's PS2 wrestling engine): disc identity and data.bin index.

Evidence (owned quickswap-ps2 image, catalog id deabd11481aa5a0c, ISO 2216034304 bytes):

- SYSTEM.CNF boots ``cdrom0:\\SLUS_206.39;1`` VER 1.00 NTSC; ELF sha256 ELF_SHA256. The ELF opens ``data/data.bin``
  (string at file 0x189E30) and logs "load wrestler buffer %d ( id = %d )", "load arena buffer", "load audience buffer".
- data.bin file table: vaddr 0x256F40 (file 0x157F40), 293 x {u32 sector, u32 sectors}, contiguous from sector 0.
  Entry kinds by their first word: ``WRS `` fighter containers (198..255), ``TIM2`` portraits, ``PAK `` arenas,
  ``AUD `` crowds, ``PRM `` and ``WAZA`` move tables, and 0x00000080 GS texture packets (the same packet a WRS
  container carries in slot 18).
- Wrestler table: vaddr 0x27E100 (file 0x17F100), 32-byte records {char *name, char *short name, char *height,
  char *weight, u32 id, u32 id2, u32 id3, u32 data.bin index}. 59 named records map onto the 58 WRS buffers
  (Ludacris has two records on buffer 238), then four "Character A..D" placeholders (index 0) end it.
- WRS container: ``WRS ``, u32 size, f32 scale, u32 0, then 32 SELF-RELATIVE u32 slot offsets at 0x10 + 4*i
  (0xFFFFFFFF = empty). Slot names 0..7 come from the ELF's model debug dump (strings at file 0x18E531):
  SHADOW, BODY, BODY2, FACE, L HAND, R HAND, ALPHA1, ALPHA2. Slots 8..13 hold one 32-byte record per node of
  BODY/FACE/hands (their counts match the models' node counts: 42, 11 x 3, 13 x 2), 14..17 per-node keyed data,
  18 the fighter's GS texture packet. See gbox/defjam_models.py and docs/defjam_pipeline.md.

  python -m gbox.defjam_inventory <iso> [--json out.json] [--dump DIR [index ...]]
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

GAME_IDS = {"deabd11481aa5a0c": "Def Jam - Vendetta (USA) [PS2]"}
SERIAL = "SLUS_206.39"
VERSION = "1.00"
ELF_SHA256 = "d071213bce13a1fe8ef2f7b241f6cb1da20e66b78b7776f23299ce81b51cb28d"
DATA_NAME = "DATA/DATA.BIN"
FILE_TABLE_VADDR = 0x256F40
FILE_TABLE_COUNT = 293
WRESTLER_TABLE_VADDR = 0x27E100
WRESTLER_RECORD = 32
WRESTLER_MAX = 80                       # bound: the table holds 63 records on SLUS_206.39
WRS_FIRST, WRS_COUNT = 198, 58
WRS_MAGIC = b"WRS "
WRS_SLOTS = 32
WRS_HEADER = 0x90
SLOT_NAMES = {0: "shadow", 1: "body", 2: "body2", 3: "face", 4: "left_hand", 5: "right_hand", 6: "alpha1",
              7: "alpha2", 8: "body_nodes", 9: "face_nodes_1", 10: "face_nodes_2", 11: "face_nodes_3",
              12: "left_hand_nodes", 13: "right_hand_nodes", 14: "keyed_1", 15: "keyed_2", 16: "keyed_3",
              17: "keyed_4", 18: "texture"}
KINDS = {b"WRS ": "fighter", b"TIM2": "tim2", b"PAK ": "arena_pack", b"AUD ": "audience", b"PRM ": "prm",
         b"WAZA": "moves", b"\x80\0\0\0": "gs_texture"}


class FormatError(ValueError):
    pass


def _u32(b, o: int) -> int:
    if o < 0 or o + 4 > len(b):
        raise FormatError(f"read past end at 0x{o:x}")
    return struct.unpack_from("<I", b, o)[0]


# --- ISO9660 -----------------------------------------------------------------------------------------------
class Iso:
    """Minimal read-only ISO9660 reader (upper-case paths without ;1, e.g. ``DATA/DATA.BIN``)."""

    def __init__(self, path):
        self.path = Path(path)
        self.files: dict[str, tuple[int, int]] = {}
        with open(self.path, "rb") as f:
            f.seek(16 * 2048)
            pvd = f.read(2048)
            if pvd[1:6] != b"CD001":
                raise FormatError(f"{self.path.name}: no ISO9660 primary volume descriptor")
            root = pvd[156:190]
            self._walk(f, _u32(root, 2), _u32(root, 10), "", 0)

    def _walk(self, f, lba: int, size: int, prefix: str, depth: int):
        if depth > 8 or size > 1 << 20:
            return
        f.seek(lba * 2048)
        data = f.read(size)
        o = 0
        while o < len(data):
            n = data[o]
            if n == 0:
                o = (o // 2048 + 1) * 2048
                continue
            rec, o = data[o:o + n], o + n
            if len(rec) < 34:
                break
            name = rec[33:33 + rec[32]]
            if name in (b"\0", b"\1"):
                continue
            path = prefix + name.decode("latin-1").split(";")[0]
            if rec[25] & 2:
                self._walk(f, _u32(rec, 2), _u32(rec, 10), path + "/", depth + 1)
            else:
                self.files[path.upper()] = (_u32(rec, 2), _u32(rec, 10))

    def size(self, name: str) -> int:
        return self.files[name.upper()][1]

    def read(self, name: str, offset: int = 0, size: int | None = None) -> bytes:
        return self.read_many(name, [(offset, size)])[0]

    def read_many(self, name: str, spans) -> list[bytes]:
        """Several (offset, size) reads of one file through one handle (the ISO may sit on a slow share)."""
        lba, n = self.files[name.upper()]
        out = []
        with open(self.path, "rb") as f:
            for offset, size in spans:
                size = n - offset if size is None else size
                if offset < 0 or size < 0 or offset + size > n:
                    raise FormatError(f"{name}: read 0x{offset:x}+0x{size:x} outside 0x{n:x} bytes")
                f.seek(lba * 2048 + offset)
                out.append(f.read(size))
        return out


# --- ELF ---------------------------------------------------------------------------------------------------
def _segments(elf: bytes) -> list[tuple[int, int, int]]:
    if elf[:4] != b"\x7fELF" or len(elf) < 0x34:
        raise FormatError("boot file is not an ELF")
    phoff, = struct.unpack_from("<I", elf, 0x1C)
    phent, phnum = struct.unpack_from("<HH", elf, 0x2A)
    out = []
    for i in range(min(phnum, 32)):
        if phoff + i * phent + 20 > len(elf):
            break
        p_type, p_off, p_vaddr, _p_paddr, p_filesz = struct.unpack_from("<5I", elf, phoff + i * phent)
        if p_type == 1:
            out.append((p_off, p_vaddr, p_filesz))
    return out


def vaddr_offset(elf: bytes, vaddr: int) -> int:
    for off, va, size in _segments(elf):
        if va <= vaddr < va + size:
            return off + vaddr - va
    raise FormatError(f"vaddr 0x{vaddr:x} is not in a loaded ELF segment")


def _cstr(elf: bytes, vaddr: int, limit: int = 48) -> str | None:
    try:
        o = vaddr_offset(elf, vaddr)
    except FormatError:
        return None
    end = elf.find(b"\0", o, o + limit)
    s = elf[o:end] if end > o else b""
    return s.decode("latin-1") if s and all(32 <= c < 127 for c in s) else None


def _chain(elf: bytes, off: int) -> list[tuple[int, int]]:
    """{sector, sectors} pairs that start at sector 0 and stay contiguous."""
    ents, pos = [], 0
    while off + 8 <= len(elf) and len(ents) < 4096:
        sec, cnt = struct.unpack_from("<II", elf, off)
        if sec != pos or cnt == 0:
            break
        ents.append((sec, cnt))
        pos, off = pos + cnt, off + 8
    return ents


def _fits(ents, data_sectors: int) -> bool:
    end = ents[-1][0] + ents[-1][1] if ents else 0
    return len(ents) >= 16 and data_sectors - 16 <= end <= data_sectors


def file_table(elf: bytes, data_size: int, vaddr: int = FILE_TABLE_VADDR) -> list[tuple[int, int]]:
    """data.bin table: the pinned SLUS_206.39 address first, else the contiguous chain found by content."""
    sectors = (data_size + 2047) // 2048
    try:
        ents = _chain(elf, vaddr_offset(elf, vaddr))
    except FormatError:
        ents = []
    if _fits(ents, sectors):
        return ents
    for o in range(0, len(elf) - 16, 4):
        if elf[o:o + 4] == b"\0\0\0\0" and elf[o + 4:o + 8] != b"\0\0\0\0":
            ents = _chain(elf, o)
            if _fits(ents, sectors):
                return ents
    raise FormatError("no {sector, sectors} table in the ELF covers data.bin")


def wrestler_table(elf: bytes, vaddr: int = WRESTLER_TABLE_VADDR) -> list[dict]:
    """The ELF's wrestler records (name, short name, height, weight, ids, data.bin index); ends at the first
    record whose name pointer does not resolve to a printable string."""
    try:
        o = vaddr_offset(elf, vaddr)
    except FormatError:
        return []
    out = []
    for k in range(WRESTLER_MAX):
        p = o + k * WRESTLER_RECORD
        if p + WRESTLER_RECORD > len(elf):
            break
        w = struct.unpack_from("<8I", elf, p)
        name = _cstr(elf, w[0])
        if name is None:
            break
        out.append({"record": k, "name": name, "short": _cstr(elf, w[1]), "height": _cstr(elf, w[2]),
                    "weight": _cstr(elf, w[3]), "ids": [w[4], w[5], w[6]], "data_index": w[7]})
    return out


def fighter_names(elf: bytes) -> dict[int, dict]:
    """data.bin index -> {name, costume (1-based among that name's buffers), records}. Placeholder records (index 0,
    "NO DATA" height) are skipped."""
    by_index: dict[int, dict] = {}
    for r in wrestler_table(elf):
        if not WRS_FIRST <= r["data_index"] < WRS_FIRST + WRS_COUNT:
            continue
        e = by_index.setdefault(r["data_index"], {"name": r["name"], "short": r["short"], "height": r["height"],
                                                   "weight": r["weight"], "records": []})
        e["records"].append(r["record"])
    seen: dict[str, int] = {}
    for i in sorted(by_index):
        n = by_index[i]["name"]
        seen[n] = seen.get(n, 0) + 1
        by_index[i]["costume"] = seen[n]
    for i, e in by_index.items():
        e["costumes"] = seen[e["name"]]
    return by_index


# --- disc identity and the data.bin index ------------------------------------------------------------------
def identify(iso) -> dict:
    disc = iso if isinstance(iso, Iso) else Iso(iso)
    cnf = disc.read("SYSTEM.CNF").decode("latin-1") if "SYSTEM.CNF" in disc.files else ""
    kv = {k.strip().upper(): v.strip() for k, _, v in (ln.partition("=") for ln in cnf.splitlines()) if v}
    serial = kv.get("BOOT2", "").replace("\\", "/").rsplit("/", 1)[-1].split(";")[0].lstrip(":")
    out = {"serial": serial, "version": kv.get("VER"), "vmode": kv.get("VMODE"), "data_file": DATA_NAME,
           "exact_build": False, "files": 0, "wrestler_records": 0, "error": None}
    try:
        elf = disc.read(serial)
        out["elf_sha256"] = hashlib.sha256(elf).hexdigest()
        out["data_size"] = disc.size(DATA_NAME)
        table = file_table(elf, out["data_size"])
        pinned = _chain(elf, vaddr_offset(elf, FILE_TABLE_VADDR))
        out["files"] = len(table)
        out["file_table_vaddr"] = f"0x{FILE_TABLE_VADDR:x}" if pinned == table else None
        out["wrestler_records"] = len(wrestler_table(elf))
        out["exact_build"] = (serial == SERIAL and out["version"] == VERSION and out["elf_sha256"] == ELF_SHA256
                              and pinned == table and len(table) == FILE_TABLE_COUNT)
    except (KeyError, FormatError) as e:
        out["error"] = str(e)
    return out


def entries(disc: Iso, elf: bytes | None = None) -> list[dict]:
    """Every data.bin entry with its sector span and container kind (from the 4-byte magic); cached on the disc."""
    if getattr(disc, "_entries", None) is not None:
        return disc._entries
    table = file_table(elf if elf is not None else disc.read(SERIAL), disc.size(DATA_NAME))
    out = []
    heads = disc.read_many(DATA_NAME, [(sec * 2048, 4) for sec, _ in table])
    for i, ((sec, cnt), head) in enumerate(zip(table, heads)):
        out.append({"index": i, "sector": sec, "sectors": cnt, "offset": sec * 2048, "size": cnt * 2048,
                    "magic": head.hex(), "kind": KINDS.get(head, "data")})
    disc._entries = out
    return out


def parse_wrs(b: bytes) -> dict:
    """WRS container -> {size, scale, slots {i: {slot, name, start, end}}} (bounds-checked, slot-ordered)."""
    if b[:4] != WRS_MAGIC:
        raise FormatError("not a WRS fighter container")
    size = _u32(b, 4)
    if not WRS_HEADER <= size <= len(b):
        raise FormatError(f"WRS size 0x{size:x} outside 0x{WRS_HEADER:x}..0x{len(b):x}")
    starts = {}
    for i in range(WRS_SLOTS):
        rel = _u32(b, 0x10 + 4 * i)
        if rel == 0xFFFFFFFF:
            continue
        s = 0x10 + 4 * i + rel                                  # self-relative to the slot's table entry
        if not WRS_HEADER <= s < size:
            raise FormatError(f"slot {i} starts outside the container (0x{s:x})")
        starts[i] = s
    order = sorted(starts.items(), key=lambda kv: kv[1])
    if [i for i, _ in order] != sorted(starts):
        raise FormatError("WRS slot offsets are not in slot order")
    slots = {}
    for k, (i, s) in enumerate(order):
        end = order[k + 1][1] if k + 1 < len(order) else size
        slots[i] = {"slot": i, "name": SLOT_NAMES.get(i, f"slot{i}"), "start": s, "end": end}
    return {"size": size, "scale": struct.unpack_from("<f", b, 8)[0], "slots": slots}


def read_entry(disc: Iso, ent: dict) -> bytes:
    return disc.read(DATA_NAME, ent["offset"], ent["size"])


def inventory(iso) -> dict:
    """Identity, entry kinds and the 58 fighter containers with names and slot layout (no geometry decoding)."""
    disc = iso if isinstance(iso, Iso) else Iso(iso)
    ident = identify(disc)
    elf = disc.read(SERIAL)
    ents = entries(disc, elf)
    names = fighter_names(elf)
    kinds: dict[str, int] = {}
    for e in ents:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    fighters = []
    fents = [e for e in ents if e["kind"] == "fighter"]
    for e, b in zip(fents, disc.read_many(DATA_NAME, [(e["offset"], e["size"]) for e in fents])):
        rec = {"index": e["index"], "sector": e["sector"], "size": e["size"], **names.get(e["index"], {})}
        try:
            w = parse_wrs(b)
            rec.update(container_size=w["size"], container_sha256=hashlib.sha256(b[:w["size"]]).hexdigest(),
                       slots={s["name"]: [s["start"], s["end"] - s["start"]] for s in w["slots"].values()})
        except FormatError as err:
            rec["error"] = str(err)
        fighters.append(rec)
    return {"identity": ident, "kinds": kinds, "fighters": fighters,
            "other": [{k: e[k] for k in ("index", "sector", "sectors", "kind")} for e in ents if e["kind"] != "fighter"]}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m gbox.defjam_inventory", description=__doc__.split("\n")[0])
    ap.add_argument("iso")
    ap.add_argument("--json", help="write the full inventory here")
    ap.add_argument("--dump", help="write raw data.bin entries to this directory")
    ap.add_argument("index", nargs="*", type=int, help="entries to dump (default: the 58 fighters)")
    a = ap.parse_args(argv)
    inv = inventory(a.iso)
    if a.json:
        Path(a.json).write_text(json.dumps(inv, indent=1))
    print(json.dumps(inv["identity"], indent=1))
    print(json.dumps(inv["kinds"]))
    for f in inv["fighters"]:
        print(f"{f['index']:3d}  {f.get('name', '?'):18s} costume {f.get('costume', '?')}/{f.get('costumes', '?')}"
              f"  {f.get('container_size', 0):7d} bytes  {f.get('error', '')}")
    if a.dump:
        disc = Iso(a.iso)
        ents = entries(disc)
        out = Path(a.dump)
        out.mkdir(parents=True, exist_ok=True)
        for i in a.index or range(WRS_FIRST, WRS_FIRST + WRS_COUNT):
            e = ents[i]
            (out / f"{i:03d}_{e['kind']}.bin").write_bytes(read_entry(disc, e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
