"""Def Jam: Vendetta PS2 (SLUS_206.39, VER 1.00 NTSC): native data.bin + WRS fighter-model reader (#1305).

Evidence from the owned quickswap-ps2 image (staged ISO sha256 08c611af...5d3f):

- SYSTEM.CNF boots ``cdrom0:\\SLUS_206.39;1`` VER 1.00 NTSC. The ELF opens ``data/data.bin`` (string at file
  0x189E30) and logs "load wrestler buffer %d ( id = %d )", "load arena buffer", "load audience buffer".
- The ELF holds the data.bin file table at vaddr 0x256F40 (file 0x157F40): 293 x {u32 sector, u32 sectors},
  contiguous from sector 0. Entries 198..255 are the 58 ``WRS `` fighter containers; the rest are TIM2 photos,
  ``PAK `` arenas, ``AUD `` crowds, ``PRM `` and ``WAZA`` move tables.
- WRS container: ``WRS ``, u32 size, f32 scale, u32 0, then 32 SELF-RELATIVE u32 slot offsets at 0x10 + 4*i
  (0xFFFFFFFF = empty). The ELF's model debug dump names the first eight slots SHADOW, BODY, BODY2, FACE,
  L HAND, R HAND, ALPHA1, ALPHA2 (strings from file 0x18E531).
- Model slot: u32 geometry offset, u32 geometry size, u32 node count, then 0x190-byte node records from +0x20
  (inverse bind 4x4 at +0, bind 4x4 at +0x40; row vectors, translation in row 3), padded to 0x80, then a VIF
  stream of UNPACK V4-32 batches (FLG set) separated by FLUSH/MSCALF. A batch is a header qword
  {n_single, n_weighted, n_strips, flags & 0x8000}, n_single x {ST q=1, N w=1, P w=1}, n_weighted x
  {ST, N, P, W = (u32 matrix a, f32 weight a, u32 matrix b, f32 weight b)}, then u32 triangle strips
  {length, length x VU qword address (double-buffer base 0/0x100/0x200/0x300 + qword offset)}.
- BODY/BODY2 positions are model-space bind pose (y-up, about 22 units tall). BODY2 fills the same volume as BODY
  (a denser alternate body), so it is written to its own GLB. FACE and the hands are bone-local parts; they are
  only placed when their own root bind matrix lands them on the body (head on top, hands at the arm ends). On
  SLUS_206.39 that root bind is identity, so they stay out of the export until the attach bone is decoded.
- SHADOW (batch flags 0x8003) and ALPHA1/ALPHA2 (no node-record header) use other layouts and are reported only.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import numpy as np

SERIAL = "SLUS_206.39"
VERSION = "1.00"
DATA_NAME = "DATA/DATA.BIN"
FILE_TABLE_VADDR = 0x256F40
FILE_TABLE_COUNT = 293
WRS_FIRST, WRS_COUNT = 198, 58
WRS_MAGIC = b"WRS "
WRS_SLOTS = 32
NODE_SIZE = 0x190
SLOT_NAMES = {0: "shadow", 1: "body", 2: "body2", 3: "face", 4: "left_hand", 5: "right_hand", 6: "alpha1",
              7: "alpha2"}
MODEL_SLOTS = tuple(SLOT_NAMES)
MODEL_SPACE = (1, 2)
ATTACHMENTS = (3, 4, 5)
MIN_WINDING = 0.85
KINDS = {b"WRS ": "fighter", b"TIM2": "tim2", b"PAK ": "arena_pack", b"AUD ": "audience", b"PRM ": "prm",
         b"WAZA": "moves"}
UNPACK = {0x0: (1, 32), 0x1: (1, 16), 0x2: (1, 8), 0x4: (2, 32), 0x5: (2, 16), 0x6: (2, 8), 0x8: (3, 32),
          0x9: (3, 16), 0xA: (3, 8), 0xC: (4, 32), 0xD: (4, 16), 0xE: (4, 8), 0xF: (4, 5)}


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
        if depth > 8:
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
        lba, n = self.files[name.upper()]
        size = n - offset if size is None else size
        if offset < 0 or size < 0 or offset + size > n:
            raise FormatError(f"{name}: read 0x{offset:x}+0x{size:x} outside 0x{n:x} bytes")
        with open(self.path, "rb") as f:
            f.seek(lba * 2048 + offset)
            return f.read(size)


# --- ELF file table ----------------------------------------------------------------------------------------
def _vaddr_offset(elf: bytes, vaddr: int) -> int:
    if elf[:4] != b"\x7fELF":
        raise FormatError("boot file is not an ELF")
    phoff, = struct.unpack_from("<I", elf, 0x1C)
    phent, phnum = struct.unpack_from("<HH", elf, 0x2A)
    for i in range(phnum):
        p_type, p_off, p_vaddr, _p_paddr, p_filesz = struct.unpack_from("<5I", elf, phoff + i * phent)
        if p_type == 1 and p_vaddr <= vaddr < p_vaddr + p_filesz:
            return p_off + vaddr - p_vaddr
    raise FormatError(f"vaddr 0x{vaddr:x} is not in a loaded ELF segment")


def _chain(elf: bytes, off: int) -> list[tuple[int, int]]:
    """{sector, sectors} pairs that start at sector 0 and stay contiguous."""
    ents, pos = [], 0
    while off + 8 <= len(elf):
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
        ents = _chain(elf, _vaddr_offset(elf, vaddr))
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


def identify(iso) -> dict:
    disc = iso if isinstance(iso, Iso) else Iso(iso)
    cnf = disc.read("SYSTEM.CNF").decode("latin-1") if "SYSTEM.CNF" in disc.files else ""
    kv = {k.strip().upper(): v.strip() for k, _, v in (ln.partition("=") for ln in cnf.splitlines()) if v}
    serial = kv.get("BOOT2", "").replace("\\", "/").rsplit("/", 1)[-1].split(";")[0].lstrip(":")
    out = {"serial": serial, "version": kv.get("VER"), "vmode": kv.get("VMODE"), "data_file": DATA_NAME,
           "exact_build": False, "files": 0, "error": None}
    try:
        elf = disc.read(serial)
        out["elf_sha256"] = hashlib.sha256(elf).hexdigest()
        out["data_size"] = disc.size(DATA_NAME)
        table = file_table(elf, out["data_size"])
        pinned = _chain(elf, _vaddr_offset(elf, FILE_TABLE_VADDR))
        out["files"] = len(table)
        out["file_table_vaddr"] = f"0x{FILE_TABLE_VADDR:x}" if pinned == table else None
        out["exact_build"] = (serial == SERIAL and out["version"] == VERSION and pinned == table
                              and len(table) == FILE_TABLE_COUNT)
    except (KeyError, FormatError) as e:
        out["error"] = str(e)
    return out


def entries(disc: Iso) -> list[dict]:
    """Every data.bin entry with its sector span and container kind (from the 4-byte magic)."""
    table = file_table(disc.read(SERIAL), disc.size(DATA_NAME))
    out = []
    for i, (sec, cnt) in enumerate(table):
        head = disc.read(DATA_NAME, sec * 2048, 4)
        out.append({"index": i, "sector": sec, "sectors": cnt, "offset": sec * 2048, "size": cnt * 2048,
                    "magic": head.hex(), "kind": KINDS.get(head, "data")})
    return out


# --- WRS container and model slots ---------------------------------------------------------------------------
def parse_wrs(b: bytes) -> dict:
    if b[:4] != WRS_MAGIC:
        raise FormatError("not a WRS fighter container")
    size = _u32(b, 4)
    if not 0x90 <= size <= len(b):
        raise FormatError(f"WRS size 0x{size:x} outside 0x90..0x{len(b):x}")
    starts = {}
    for i in range(WRS_SLOTS):
        rel = _u32(b, 0x10 + 4 * i)
        if rel == 0xFFFFFFFF:
            continue
        s = 0x10 + 4 * i + rel                                  # self-relative to the slot's table entry
        if not 0x90 <= s < size:
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


def _batch(data: bytes, n: int, acc: dict):
    ns, nw, nst, flags = struct.unpack_from("<4I", data, 0)
    need = 1 + 3 * ns + 4 * nw
    if not flags & 0x8000 or need > n or nst > 4096:
        raise FormatError(f"bad batch header ({ns}, {nw}, {nst}, 0x{flags:x}) for {n} qwords")
    q = np.frombuffer(data, "<f4", count=n * 4).reshape(n, 4)
    qi = np.frombuffer(data, "<u4", count=n * 4).reshape(n, 4)
    offs = {}
    for j in range(ns + nw):
        k = 1 + 3 * j if j < ns else 1 + 3 * ns + 4 * (j - ns)
        offs[k] = len(acc["P"])
        acc["T"].append(q[k, :2]); acc["N"].append(q[k + 1, :3]); acc["P"].append(q[k + 2, :3])
        if j < ns:
            acc["J"].append((0, 0)); acc["W"].append((1.0, 0.0))
        else:
            acc["J"].append((int(qi[k + 3, 0]), int(qi[k + 3, 2]))); acc["W"].append((float(q[k + 3, 1]), float(q[k + 3, 3])))
    words, pos, strips = qi[need:].reshape(-1), 0, []
    for _ in range(nst):
        if pos >= len(words):
            raise FormatError("strip list runs past the batch")
        ln = int(words[pos]); pos += 1
        if ln < 3 or pos + ln > len(words):
            raise FormatError(f"bad strip length {ln}")
        strips.append([int(x) for x in words[pos:pos + ln]]); pos += ln
    addrs = {a for s in strips for a in s}
    base = next((bb for bb in (0, 0x100, 0x200, 0x300) if all(a - bb in offs for a in addrs)), None)
    if base is None:
        raise FormatError("strip addresses do not map onto the batch's vertices")
    for s in strips:
        for i in range(len(s) - 2):
            a, b_, c = (offs[x - base] for x in s[i:i + 3])
            if i & 1:
                a, b_ = b_, a
            if a != b_ and b_ != c and a != c:
                acc["tris"].append((a, b_, c))
    acc["weighted"] += nw


def parse_model(blk: bytes) -> dict:
    if len(blk) < 0x20:
        raise FormatError("model slot shorter than its header")
    geo, gsz, nn = struct.unpack_from("<3I", blk, 0)
    if not 1 <= nn <= 256:
        raise FormatError(f"implausible node count {nn}")
    want = (0x20 + nn * NODE_SIZE + 0x7F) & ~0x7F
    if geo != want or geo + gsz > len(blk):
        raise FormatError(f"geometry 0x{geo:x}+0x{gsz:x} does not follow {nn} node records in 0x{len(blk):x} bytes")
    nodes = [{"inverse_bind": np.array(struct.unpack_from("<16f", blk, 0x20 + k * NODE_SIZE), np.float32).reshape(4, 4),
              "bind": np.array(struct.unpack_from("<16f", blk, 0x60 + k * NODE_SIZE), np.float32).reshape(4, 4)}
             for k in range(nn)]
    acc = {"P": [], "N": [], "T": [], "J": [], "W": [], "tris": [], "weighted": 0}
    o, end, batches = geo, geo + gsz, 0
    while o + 4 <= end:
        w = _u32(blk, o); o += 4
        cmd, num, imm = (w >> 24) & 0x7F, (w >> 16) & 0xFF, w & 0xFFFF
        if cmd & 0x60 == 0x60:
            if cmd & 0xF not in UNPACK:
                raise FormatError(f"unknown UNPACK format 0x{cmd:x} at 0x{o - 4:x}")
            vn, vl = UNPACK[cmd & 0xF]
            n = num or 256
            nbytes = (vl * vn * n + 31) // 32 * 4
            if o + nbytes > end:
                raise FormatError(f"UNPACK at 0x{o - 4:x} runs past the geometry")
            if cmd & 0x6F == 0x6C and imm & 0x8000:
                _batch(blk[o:o + nbytes], n, acc)
                batches += 1
            o += nbytes
        elif cmd in (0x30, 0x31):
            o += 16
        elif cmd == 0x20:
            o += 4
        elif cmd in (0x50, 0x51):
            o += (imm or 0x10000) * 16
        elif cmd == 0x4A:
            o += (num or 256) * 8
    P = np.array(acc["P"], np.float32).reshape(-1, 3)
    tri = np.array(acc["tris"], np.int64).reshape(-1, 3)
    return {"positions": P, "normals": np.array(acc["N"], np.float32).reshape(-1, 3),
            "uvs": np.array(acc["T"], np.float32).reshape(-1, 2), "matrices": acc["J"], "weights": acc["W"],
            "tri_index": tri, "triangles": [tuple((int(v),) * 3 for v in t) for t in tri],
            "node_count": nn, "nodes": nodes, "batches": batches, "weighted": acc["weighted"]}


def winding(mesh: dict) -> float:
    """Share of triangles whose right-hand face normal agrees with the stored vertex normals (0.5 = noise)."""
    t, P, N = mesh["tri_index"], mesh["positions"], mesh["normals"]
    if not len(t):
        return 0.0
    fn = np.cross(P[t[:, 1]] - P[t[:, 0]], P[t[:, 2]] - P[t[:, 0]])
    d = (fn * (N[t[:, 0]] + N[t[:, 1]] + N[t[:, 2]])).sum(1)
    ok = np.abs(d) > 1e-12
    return float((d[ok] > 0).mean()) if ok.any() else 0.0


def place(mesh: dict, m: np.ndarray) -> dict:
    """Copy of a bone-local part moved by a row-vector 4x4 (translation in row 3)."""
    P = np.c_[mesh["positions"], np.ones(len(mesh["positions"]), np.float32)] @ m
    N = mesh["normals"] @ m[:3, :3]
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
    return {**mesh, "positions": P[:, :3].astype(np.float32), "normals": N.astype(np.float32)}


def _bbox(P):
    return [P.min(0).round(3).tolist(), P.max(0).round(3).tolist()] if len(P) else None


def _placement_ok(role: str, P: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> bool:
    c, h = (P.min(0) + P.max(0)) / 2, hi[1] - lo[1]
    if not ((c >= lo - 0.1 * (hi - lo)) & (c <= hi + 0.1 * (hi - lo))).all():
        return False
    if role == "face":
        return bool(c[1] >= lo[1] + 0.75 * h)
    return bool(abs(c[0]) >= 0.6 * max(abs(lo[0]), abs(hi[0])))     # hands sit at the T-pose arm ends


def extract_wrs(b: bytes, out: Path, name: str, extras: dict | None = None) -> dict:
    """One WRS container -> static GLB of BODY/BODY2 (+ attachments that place on the body) and checks."""
    from .defjam_vendetta import write_glb
    w = parse_wrs(b)
    report, meshes = [], {}
    for i, s in sorted(w["slots"].items()):
        if i not in MODEL_SLOTS:
            continue
        blk = b[s["start"]:s["end"]]
        rec = {"slot": i, "role": s["name"], "sha256": hashlib.sha256(blk).hexdigest(), "size": len(blk)}
        try:
            m = parse_model(blk)
        except FormatError as e:
            report.append({**rec, "verified": False, "error": str(e)})
            continue
        wv = winding(m)
        nl = float(np.linalg.norm(m["normals"], axis=1).mean()) if len(m["normals"]) else 0.0
        rec.update(space="model" if i in MODEL_SPACE else "bone_local" if i in ATTACHMENTS else "aux",
                   nodes=m["node_count"], batches=m["batches"], vertices=len(m["positions"]),
                   weighted_vertices=m["weighted"], triangles=len(m["tri_index"]), winding=round(max(wv, 1 - wv), 4),
                   flipped=wv < 0.5, normal_length=round(nl, 3), bbox=_bbox(m["positions"]))
        rec["verified"] = bool(rec["triangles"] and rec["winding"] >= MIN_WINDING and abs(nl - 1) < 0.05)
        report.append(rec)
        meshes[i] = m
    body = next((r for r in report if r["slot"] == 1), None)
    if not body or not body["verified"]:
        raise FormatError(f"{name}: BODY slot did not verify ({body and body.get('error')})")
    lo, hi = np.array(body["bbox"][0]), np.array(body["bbox"][1])
    parts, alt = [], []
    for r in report:
        if not r["verified"] or r["slot"] not in MODEL_SPACE + ATTACHMENTS:
            continue
        m = meshes[r["slot"]]
        if r["slot"] in ATTACHMENTS:
            m = place(m, m["nodes"][0]["bind"])
            r["placed_bbox"] = _bbox(m["positions"])
            r["placed"] = _placement_ok(r["role"], m["positions"], lo, hi)
            if not r["placed"]:
                continue
        part = {"name": f"{name}_{r['role']}", "mesh": m, "flip": r["flipped"], "image": None}
        (alt if r["slot"] == 2 else parts).append(part)
    meta = {"source": f"Def Jam Vendetta PS2 {SERIAL} v{VERSION}", **(extras or {}),
            "units": "game units, y-up, static bind pose (skin weights not exported)"}
    glb = write_glb(out, parts, name, meta)
    glb2 = write_glb(out.with_name(f"{out.stem}_body2.glb"), alt, f"{name}_body2", meta) if alt else None
    model_ok = all(r["verified"] for r in report if r["slot"] in MODEL_SPACE)
    return {"model": name, "glb": str(glb), "glb_body2": str(glb2) if glb2 else None, "verified": model_ok,
            "parts": report, "exported": [p["name"] for p in parts + alt], "height": round(float(hi[1] - lo[1]), 2)}


# --- disc-level extraction -----------------------------------------------------------------------------------
def roster() -> list[dict]:
    """The 58 WRS fighter buffers of SLUS_206.39 v1.00 (data.bin 198..255). Display names are not decoded yet."""
    return [{"key": f"wrs{i:03d}", "slug": f"djv_ps2_wrs{i:03d}", "data_index": i, "kind": "character",
             "name": f"Def Jam Vendetta (PS2) wrestler buffer {i - WRS_FIRST}",
             "aliases": [f"wrs{i:03d}", f"Def Jam Vendetta PS2 wrestler {i - WRS_FIRST}"]}
            for i in range(WRS_FIRST, WRS_FIRST + WRS_COUNT)]


def extract_index(disc: Iso, index: int, out: Path) -> dict:
    ents = entries(disc)
    if not 0 <= index < len(ents) or ents[index]["kind"] != "fighter":
        raise FormatError(f"data.bin entry {index} is not a WRS fighter container")
    e = ents[index]
    b = disc.read(DATA_NAME, e["offset"], e["size"])
    r = extract_wrs(b, out, out.stem, {"data_index": index, "data_sector": e["sector"]})
    r.update(data_index=index, sector=e["sector"], container_sha256=hashlib.sha256(b[:parse_wrs(b)["size"]]).hexdigest())
    return r


def _source_iso(ctx, game: dict) -> Path:
    from . import characters as C
    for attr in ("_ps2_iso", "_iso"):
        fn = getattr(C, attr, None)
        if fn is None:
            continue
        try:
            p = fn(ctx, game)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
            p = None
        if p and Path(p).suffix.lower() == ".iso" and Path(p).exists():
            return Path(p)
    p = Path(str(game.get("path") or ""))
    if p.suffix.lower() == ".iso" and p.exists():
        return p
    gid = game.get("game_id") or game.get("id")
    cache = Path.home() / "gbox-cache" / str(gid) / "source.iso"
    if cache.exists():
        return cache
    raise FormatError(f"no unpacked ISO for {gid}: stage it at {cache}")


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters.DEDICATED hook: one WRS buffer -> verified static GLB (rig roles stay empty)."""
    disc = Iso(_source_iso(ctx, game))
    ident = identify(disc)
    if not ident["exact_build"]:
        raise FormatError(f"{ident['serial']} v{ident['version']}: the reader is verified on {SERIAL} v{VERSION} only")
    r = extract_index(disc, int(e.get("data_index") or e["key"][3:]), Path(work) / f"{e['slug']}.glb")
    if not r["verified"]:
        raise FormatError(f"{e['key']}: model-space parts failed verification")
    tris = sum(p.get("triangles", 0) for p in r["parts"] if p["role"] in ("body", "body2"))
    return {"files": [Path(r["glb"])] + ([Path(r["glb_body2"])] if r.get("glb_body2") else []), "roles": {},
            "tool": "gbox.defjam_vendetta_ps2",
            "source_files": [f"{DATA_NAME}#{r['data_index']}"],
            "notes": (f"Native {SERIAL} v{VERSION} WRS meshes ({', '.join(r['exported'])}; {tris} body triangles), static "
                      "bind pose. Skin matrices/weights are decoded but not exported, so it is not retargetable yet.")}


def extract_all(iso, out_dir: Path) -> dict:
    disc = Iso(iso)
    out_dir = Path(out_dir)
    results = []
    for i in range(WRS_FIRST, WRS_FIRST + WRS_COUNT):
        try:
            results.append(extract_index(disc, i, out_dir / f"djv_ps2_wrs{i:03d}.glb"))
        except FormatError as e:
            results.append({"data_index": i, "verified": False, "error": str(e)})
    kinds: dict[str, int] = {}
    for e in entries(disc):
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    man = {"identity": identify(disc), "kinds": kinds, "verified": sum(bool(r["verified"]) for r in results),
           "total": len(results), "models": results}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    return man


if __name__ == "__main__":
    import sys
    m = extract_all(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps({k: m[k] for k in ("identity", "kinds", "verified", "total")}, indent=1))
