"""Nintendo DS (Nitro) low-level formats shared by every DS title reader.

  NitroFS       cartridge header, FNT (directory table + sub-tables, ids from each directory's first_id) and FAT
  NARC          'NARC' archives: BTAF (FAT), BTNF (FNT, same layout as the cartridge's), GMIF (file image)
  LZ77          Nintendo LZ10 (type 0x10) and LZ11 (type 0x11) streams, optionally behind an "LZ77" magic
                (Super Mario 64 DS stores most files as b"LZ77" + an LZ10 stream)
  texels        the seven 3D texture formats of the DS GPU (TEXIMAGE_PARAM bits 26..28) with their palettes:
                1 A3I5, 2 4-colour, 3 16-colour, 4 256-colour, 5 4x4 compressed (+ palette-index data),
                6 A5I3, 7 direct colour; colour 0 transparent (bit 29) for formats 2..4
  GX            the geometry engine's packed command lists (display lists): four command bytes per word followed by
                their parameters. decode_display_list() runs the vertex/matrix subset a model uses and returns
                triangles with the matrix-stack slot each vertex was emitted under, so a reader binds every vertex to
                its bone. NSBMD (MDL0) and Super Mario 64 DS's BMD both draw through these lists.

Everything is little-endian. References: GBATEK (DS 3D video, cartridge file system), and the owned ROMs themselves.
"""
from __future__ import annotations

import struct

import numpy as np

from .lz import LZ10Error, lz10_decompress


# ------------------------------------------------------------------ LZ77 (LZ10 / LZ11)

def lz11_decompress(data: bytes) -> bytes:
    """Nintendo LZ11 (type 0x11): copy lengths up to 0x10110 via the 1/2/3-byte length forms."""
    if not data or data[0] != 0x11:
        raise LZ10Error("not an LZ11 stream (missing 0x11 type byte)")
    size = data[1] | data[2] << 8 | data[3] << 16
    pos = 4
    if size == 0:
        size = struct.unpack_from("<I", data, 4)[0]
        pos = 8
    out = bytearray()
    while len(out) < size:
        if pos >= len(data):
            raise LZ10Error("truncated LZ11 stream")
        flags = data[pos]
        pos += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if not flags & (0x80 >> bit):
                out.append(data[pos])
                pos += 1
                continue
            b0 = data[pos]
            ind = b0 >> 4
            if ind == 0:
                length = (((b0 & 0xF) << 4) | (data[pos + 1] >> 4)) + 0x11
                disp = ((data[pos + 1] & 0xF) << 8 | data[pos + 2]) + 1
                pos += 3
            elif ind == 1:
                length = (((b0 & 0xF) << 12) | (data[pos + 1] << 4) | (data[pos + 2] >> 4)) + 0x111
                disp = ((data[pos + 2] & 0xF) << 8 | data[pos + 3]) + 1
                pos += 4
            else:
                length = ind + 1
                disp = ((b0 & 0xF) << 8 | data[pos + 1]) + 1
                pos += 2
            if disp > len(out):
                raise LZ10Error("LZ11 copy before the start of the output")
            for _ in range(length):
                out.append(out[-disp])
    return bytes(out[:size])


def decompress(data: bytes) -> bytes:
    """A DS file's payload: "LZ77"-tagged LZ10/LZ11 streams are decompressed, anything else (including bare
    0x10 streams, which a one-byte check can't tell from data) is returned as it is."""
    if data[:4] == b"LZ77" and len(data) > 8 and data[4] in (0x10, 0x11):
        data = data[4:]
        return lz10_decompress(data) if data[0] == 0x10 else lz11_decompress(data)
    return data


def is_compressed(data: bytes) -> bool:
    return data[:4] == b"LZ77" and len(data) > 8 and data[4] in (0x10, 0x11)


# ------------------------------------------------------------------ file name tables (cartridge and NARC share it)

def parse_fnt(fnt: bytes, n_files: int) -> dict[int, str]:
    """FNT -> {file id: 'dir/sub/name'}. The main table has one 8-byte row per directory (u32 sub-table offset,
    u16 first file id, u16 parent id / directory count for the root); a sub-table entry is a length byte (bit 7 =
    sub-directory, then a u16 directory id 0xF000 + n), the name, and files take consecutive ids from first_id."""
    if len(fnt) < 8:
        return {}
    n_dirs = struct.unpack_from("<H", fnt, 6)[0]
    if not 0 < n_dirs <= 4096 or n_dirs * 8 > len(fnt):
        raise ValueError(f"FNT: bad directory count {n_dirs}")
    names: dict[int, str] = {}
    seen = set()

    def walk(d: int, prefix: str):
        if d in seen or d >= n_dirs:
            raise ValueError(f"FNT: directory {d:#x} loops or is out of range")
        seen.add(d)
        off, fid = struct.unpack_from("<IH", fnt, d * 8)
        pos = off
        while True:
            if pos >= len(fnt):
                raise ValueError(f"FNT overrun at {pos:#x} under {prefix!r}")
            c = fnt[pos]
            pos += 1
            if c == 0:
                return
            if c == 0x80:
                raise ValueError("FNT: reserved length byte 0x80")
            name = fnt[pos:pos + (c & 0x7F)].decode("latin-1")
            pos += c & 0x7F
            if c & 0x80:
                sub = struct.unpack_from("<H", fnt, pos)[0]
                pos += 2
                walk(sub & 0x0FFF, prefix + name + "/")
            else:
                if fid >= n_files:
                    raise ValueError(f"FNT: file id {fid} beyond the FAT ({n_files})")
                names[fid] = prefix + name
                fid += 1

    walk(0, "")
    return names


class NitroROM:
    """A Nintendo DS cartridge image: header fields, the NitroFS file system and the ARM9 overlay table."""

    def __init__(self, data: bytes):
        if len(data) < 0x200:
            raise ValueError("not an NDS image (smaller than its header)")
        self.data = data
        self.title = data[0:12].split(b"\0")[0].decode("latin-1")
        self.gamecode = data[12:16].decode("latin-1")
        self.arm9_off, self.arm9_entry, self.arm9_ram, self.arm9_size = struct.unpack_from("<4I", data, 0x20)
        self.fnt_off, self.fnt_size, self.fat_off, self.fat_size = struct.unpack_from("<4I", data, 0x40)
        self.ovt9_off, self.ovt9_size = struct.unpack_from("<2I", data, 0x50)
        if self.fat_off + self.fat_size > len(data) or self.fnt_off + self.fnt_size > len(data):
            raise ValueError("NDS header points past the end of the image")
        self.fat = [struct.unpack_from("<II", data, self.fat_off + 8 * i) for i in range(self.fat_size // 8)]
        for start, end in self.fat:
            if end < start or end > len(data):
                raise ValueError(f"FAT entry {start:#x}..{end:#x} outside the image")
        self.names = parse_fnt(data[self.fnt_off:self.fnt_off + self.fnt_size], len(self.fat))
        self.ids = {name.lower(): fid for fid, name in self.names.items()}

    def paths(self) -> list[str]:
        return sorted(self.names.values())

    def file(self, fid: int) -> bytes:
        start, end = self.fat[fid]
        return self.data[start:end]

    def raw(self, path: str) -> bytes:
        try:
            return self.file(self.ids[path.lower().lstrip("/")])
        except KeyError:
            raise KeyError(path) from None

    def read(self, path: str) -> bytes:
        return decompress(self.raw(path))

    def overlays9(self) -> list[dict]:
        """ARM9 overlay table rows (id, RAM address, sizes, file id)."""
        out = []
        for o in range(self.ovt9_off, self.ovt9_off + self.ovt9_size, 32):
            oid, ram, size, bss, s0, s1, fid, _r = struct.unpack_from("<8I", self.data, o)
            out.append({"id": oid, "ram": ram, "size": size, "bss": bss, "file_id": fid})
        return out


def narc(blob: bytes) -> list[tuple[str, bytes]]:
    """A NARC archive -> [(name or '#index', payload)] in file-id order (payloads are not decompressed)."""
    if blob[:4] != b"NARC":
        raise ValueError("not a NARC archive")
    pos = struct.unpack_from("<H", blob, 12)[0]
    sections = {}
    while pos + 8 <= len(blob):
        tag, size = blob[pos:pos + 4], struct.unpack_from("<I", blob, pos + 4)[0]
        if size < 8:
            raise ValueError(f"NARC section {tag!r} has size {size}")
        sections[tag] = (pos, size)
        pos += size
    if not {b"BTAF", b"BTNF", b"GMIF"} <= sections.keys():
        raise ValueError(f"NARC lacks a section: {sorted(sections)}")
    fo, _ = sections[b"BTAF"]
    count = struct.unpack_from("<H", blob, fo + 8)[0]
    fat = [struct.unpack_from("<II", blob, fo + 12 + 8 * i) for i in range(count)]
    no, nsize = sections[b"BTNF"]
    go, gsize = sections[b"GMIF"]
    names = parse_fnt(blob[no + 8:no + nsize], count)
    out = []
    for i, (s, e) in enumerate(fat):
        if e < s or go + 8 + e > go + gsize:
            raise ValueError(f"NARC file {i} outside GMIF")
        out.append((names.get(i, f"#{i}"), blob[go + 8 + s:go + 8 + e]))
    return out


# ------------------------------------------------------------------ textures

FORMATS = {0: "none", 1: "a3i5", 2: "pal4", 3: "pal16", 4: "pal256", 5: "4x4", 6: "a5i3", 7: "direct"}
BPP = {1: 8, 2: 2, 3: 4, 4: 8, 5: 2, 6: 8, 7: 16}


def rgb555(words: np.ndarray) -> np.ndarray:
    """BGR555 words -> (n, 3) uint8 (5-bit channels widened by bit replication)."""
    w = np.asarray(words, dtype=np.uint16)
    c = np.stack([w & 31, (w >> 5) & 31, (w >> 10) & 31], axis=-1).astype(np.uint16)
    return ((c << 3) | (c >> 2)).astype(np.uint8)


def teximage(param: int) -> dict:
    """TEXIMAGE_PARAM -> {format, width, height, repeat_s/t, flip_s/t, color0_transparent, address}."""
    return {"format": (param >> 26) & 7, "width": 8 << ((param >> 20) & 7), "height": 8 << ((param >> 23) & 7),
            "repeat_s": bool(param & 1 << 16), "repeat_t": bool(param & 1 << 17),
            "flip_s": bool(param & 1 << 18), "flip_t": bool(param & 1 << 19),
            "color0_transparent": bool(param & 1 << 29), "address": (param & 0xFFFF) << 3}


def texel_bytes(fmt: int, w: int, h: int) -> int:
    """Bytes of texel data (4x4: the 2-bit block data only; its palette-index data is half that again)."""
    return w * h * BPP[fmt] // 8


def decode_texture(fmt: int, w: int, h: int, texels: bytes, palette: bytes = b"", *, color0_transparent=False,
                   palette_index: bytes = b"") -> np.ndarray:
    """One DS texture -> (h, w, 4) RGBA uint8. palette: BGR555 words; palette_index: 4x4 format's u16 per block."""
    n = w * h
    pal = rgb555(np.frombuffer(palette[:len(palette) // 2 * 2], dtype="<u2")) if palette else np.zeros((0, 3), np.uint8)

    def lookup(idx: np.ndarray) -> np.ndarray:
        if len(pal) == 0:
            raise ValueError(f"texture format {FORMATS.get(fmt)} needs a palette")
        idx = np.minimum(idx, len(pal) - 1)
        return pal[idx]

    need = texel_bytes(fmt, w, h)
    if len(texels) < need:
        raise ValueError(f"{FORMATS.get(fmt)} {w}x{h} needs {need} texel bytes, got {len(texels)}")
    t = np.frombuffer(texels[:need], dtype=np.uint8)
    rgba = np.zeros((n, 4), np.uint8)
    if fmt in (2, 3, 4):
        bits = BPP[fmt]
        per = 8 // bits
        idx = ((t[:, None] >> (np.arange(per) * bits)) & ((1 << bits) - 1)).reshape(-1).astype(np.int64)
        rgba[:, :3] = lookup(idx)
        rgba[:, 3] = 255
        if color0_transparent:
            rgba[idx == 0, 3] = 0
    elif fmt == 1:                                            # A3I5
        idx, a = (t & 31).astype(np.int64), t >> 5
        rgba[:, :3] = lookup(idx)
        rgba[:, 3] = ((a.astype(np.uint16) * 4 + a // 2) * 255 // 31).astype(np.uint8)
    elif fmt == 6:                                            # A5I3
        idx, a = (t & 7).astype(np.int64), t >> 3
        rgba[:, :3] = lookup(idx)
        rgba[:, 3] = (a.astype(np.uint16) * 255 // 31).astype(np.uint8)
    elif fmt == 7:                                            # direct colour
        words = np.frombuffer(texels[:need], dtype="<u2")
        rgba[:, :3] = rgb555(words)
        rgba[:, 3] = np.where(words & 0x8000, 255, 0)
    elif fmt == 5:
        return _decode_4x4(w, h, texels, palette_index, palette)
    else:
        raise ValueError(f"texture format {fmt} has no texels")
    return rgba.reshape(h, w, 4)


def _decode_4x4(w: int, h: int, texels: bytes, pidx: bytes, palette: bytes) -> np.ndarray:
    """4x4 compressed: per 4x4 block a u32 of 2-bit indices (row per byte) and a u16 [mode:2 | offset:14]; colours
    are read at palette + offset*4. Modes: 0 c0 c1 c2 transparent; 1 c0 c1 (c0+c1)/2 transparent; 2 c0..c3;
    3 c0 c1 (5c0+3c1)/8 (3c0+5c1)/8."""
    bw, bh = w // 4, h // 4
    blocks = bw * bh
    if len(texels) < blocks * 4 or len(pidx) < blocks * 2:
        raise ValueError("4x4 texture: truncated block or palette-index data")
    words = np.frombuffer(palette[:len(palette) // 2 * 2], dtype="<u2")
    cols = rgb555(words).astype(np.int32)
    out = np.zeros((h, w, 4), np.uint8)
    data = np.frombuffer(texels[:blocks * 4], dtype="<u4")
    infos = np.frombuffer(pidx[:blocks * 2], dtype="<u2")
    for b in range(blocks):
        info = int(infos[b])
        mode, base = info >> 14, (info & 0x3FFF) * 2
        c = [cols[min(base + k, len(cols) - 1)] if len(cols) else np.zeros(3, np.int32) for k in range(4)]
        a = [255, 255, 255, 255]
        if mode == 0:
            a[3] = 0
        elif mode == 1:
            c[2] = (c[0] + c[1]) // 2
            a[3] = 0
        elif mode == 3:
            c[2] = (c[0] * 5 + c[1] * 3) // 8
            c[3] = (c[0] * 3 + c[1] * 5) // 8
        bits = int(data[b])
        by, bx = divmod(b, bw)
        for py in range(4):
            for px in range(4):
                k = (bits >> (2 * (py * 4 + px))) & 3
                out[by * 4 + py, bx * 4 + px, :3] = c[k]
                out[by * 4 + py, bx * 4 + px, 3] = a[k]
    return out


# ------------------------------------------------------------------ GX display lists

# parameter words per command (GBATEK "DS 3D Geometry Commands"); unknown ids are rejected
GX_PARAMS = {0x00: 0, 0x10: 1, 0x11: 0, 0x12: 1, 0x13: 1, 0x14: 1, 0x15: 0, 0x16: 16, 0x17: 12, 0x18: 16, 0x19: 12,
             0x1A: 9, 0x1B: 3, 0x1C: 3, 0x20: 1, 0x21: 1, 0x22: 1, 0x23: 2, 0x24: 1, 0x25: 1, 0x26: 1, 0x27: 1,
             0x28: 1, 0x29: 1, 0x2A: 1, 0x2B: 1, 0x30: 1, 0x31: 1, 0x32: 1, 0x33: 1, 0x34: 32, 0x40: 1, 0x41: 0,
             0x50: 1, 0x60: 1, 0x70: 3, 0x71: 2, 0x72: 1}
GX_NAMES = {0x14: "MTX_RESTORE", 0x20: "COLOR", 0x21: "NORMAL", 0x22: "TEXCOORD", 0x23: "VTX_16", 0x24: "VTX_10",
            0x25: "VTX_XY", 0x26: "VTX_XZ", 0x27: "VTX_YZ", 0x28: "VTX_DIFF", 0x40: "BEGIN_VTXS", 0x41: "END_VTXS"}


def _s(v: int, bits: int) -> int:
    v &= (1 << bits) - 1
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def gx_commands(dl: bytes) -> list[tuple[int, tuple[int, ...]]]:
    """Packed GX list -> [(command id, params)]. Trailing NOP padding is dropped."""
    out, pos = [], 0
    n = len(dl) // 4
    words = struct.unpack_from(f"<{n}I", dl, 0)
    while pos < n:
        packed = words[pos]
        pos += 1
        for k in range(4):
            cmd = (packed >> (8 * k)) & 0xFF
            if cmd not in GX_PARAMS:
                raise ValueError(f"GX: unknown command {cmd:#04x} at word {pos - 1}")
            np_ = GX_PARAMS[cmd]
            if pos + np_ > n:
                raise ValueError(f"GX: command {cmd:#04x} runs past the list")
            params = words[pos:pos + np_]
            pos += np_
            if cmd:
                out.append((cmd, params))
    return out


def decode_display_list(dl: bytes) -> dict:
    """Run a GX list's vertex subset. Returns {'tris': [(v0, v1, v2)], 'pos': [(x, y, z) 4.12 floats], 'slot': [matrix
    slot per vertex], 'uv': [(s, t) texels], 'normal': [...], 'color': [(r, g, b)]} plus 'commands' counts.
    Quads and strips are triangulated with DS winding (strips alternate); positions are in the model space of the
    matrix-stack slot that MTX_RESTORE last selected."""
    pos, slot, uv, nrm, col, tris = [], [], [], [], [], []
    cur = [0, 0, 0]
    cur_uv, cur_n, cur_c, cur_slot = (0.0, 0.0), (0.0, 0.0, 1.0), (255, 255, 255), 0
    prim, strip = None, []
    counts: dict[str, int] = {}

    def emit(v: int):
        if prim is None:
            return
        strip.append(v)
        k = len(strip)
        if prim == 0 and k % 3 == 0:
            tris.append((strip[-3], strip[-2], strip[-1]))
        elif prim == 1 and k % 4 == 0:
            a, b, c, d = strip[-4:]
            tris.extend([(a, b, c), (a, c, d)])
        elif prim == 2 and k >= 3:
            a, b, c = strip[-3:]
            tris.append((a, b, c) if k % 2 else (b, a, c))
        elif prim == 3 and k >= 4 and k % 2 == 0:
            a, b, c, d = strip[-4:]                           # quad strip: (a b d c) per pair
            tris.extend([(a, b, d), (a, d, c)])

    def vertex():
        pos.append(tuple(v / 4096.0 for v in cur))
        slot.append(cur_slot)
        uv.append(cur_uv)
        nrm.append(cur_n)
        col.append(cur_c)
        emit(len(pos) - 1)

    for cmd, p in gx_commands(dl):
        name = GX_NAMES.get(cmd, f"{cmd:#04x}")
        counts[name] = counts.get(name, 0) + 1
        if cmd == 0x14:
            cur_slot = p[0] & 31
        elif cmd == 0x20:
            c = rgb555(np.array([p[0] & 0x7FFF]))[0]
            cur_c = (int(c[0]), int(c[1]), int(c[2]))
        elif cmd == 0x21:
            cur_n = (_s(p[0], 10) / 512.0, _s(p[0] >> 10, 10) / 512.0, _s(p[0] >> 20, 10) / 512.0)
        elif cmd == 0x22:
            cur_uv = (_s(p[0], 16) / 16.0, _s(p[0] >> 16, 16) / 16.0)
        elif cmd == 0x23:
            cur = [_s(p[0], 16), _s(p[0] >> 16, 16), _s(p[1], 16)]
            vertex()
        elif cmd == 0x24:
            cur = [_s(p[0], 10) << 6, _s(p[0] >> 10, 10) << 6, _s(p[0] >> 20, 10) << 6]
            vertex()
        elif cmd == 0x25:
            cur = [_s(p[0], 16), _s(p[0] >> 16, 16), cur[2]]
            vertex()
        elif cmd == 0x26:
            cur = [_s(p[0], 16), cur[1], _s(p[0] >> 16, 16)]
            vertex()
        elif cmd == 0x27:
            cur = [cur[0], _s(p[0], 16), _s(p[0] >> 16, 16)]
            vertex()
        elif cmd == 0x28:
            cur = [cur[0] + _s(p[0], 10), cur[1] + _s(p[0] >> 10, 10), cur[2] + _s(p[0] >> 20, 10)]
            vertex()
        elif cmd == 0x40:
            prim, strip = p[0] & 3, []
        elif cmd == 0x41:
            prim, strip = None, []
    return {"pos": pos, "slot": slot, "uv": uv, "normal": nrm, "color": col, "tris": tris, "commands": counts}


# ------------------------------------------------------------------ encoders (tests build synthetic data with these)

def lz10_literal(data: bytes, magic: bool = True) -> bytes:
    """An all-literal LZ10 stream (valid input for every decoder; used by tests and synthetic fixtures)."""
    out = bytearray([0x10, len(data) & 0xFF, (len(data) >> 8) & 0xFF, (len(data) >> 16) & 0xFF])
    for i in range(0, len(data), 8):
        out.append(0)
        out.extend(data[i:i + 8])
    return (b"LZ77" if magic else b"") + bytes(out)


def build_fnt(paths: list[str], first_id: int = 0) -> tuple[bytes, list[str]]:
    """paths -> (FNT bytes, paths in file-id order). Directories are numbered breadth-first like Nintendo's tools."""
    tree: dict = {}
    for p in paths:
        node = tree
        parts = p.split("/")
        for d in parts[:-1]:
            node = node.setdefault(d + "/", {})
        node[parts[-1]] = None
    dirs = [("", tree)]
    i = 0
    while i < len(dirs):
        prefix, node = dirs[i]
        for k in sorted(node):
            if k.endswith("/"):
                dirs.append((prefix + k, node[k]))
        i += 1
    dir_id = {prefix: n for n, (prefix, _node) in enumerate(dirs)}
    order, subs, fid = [], [], first_id
    first_ids = []
    for prefix, node in dirs:
        first_ids.append(fid)
        sub = bytearray()
        for k in sorted(node, key=lambda s: (s.endswith("/"), s)):
            if k.endswith("/"):
                nm = k[:-1].encode()
                sub += bytes([0x80 | len(nm)]) + nm + struct.pack("<H", 0xF000 | dir_id[prefix + k])
            else:
                nm = k.encode()
                sub += bytes([len(nm)]) + nm
                order.append(prefix + k)
                fid += 1
        subs.append(bytes(sub) + b"\0")
    main = bytearray()
    off = 8 * len(dirs)
    for n, (prefix, _node) in enumerate(dirs):
        up = prefix.rstrip("/").rpartition("/")[0]
        parent = len(dirs) if n == 0 else 0xF000 | dir_id[up + "/" if up else ""]
        main += struct.pack("<IHH", off, first_ids[n], parent)
        off += len(subs[n])
    return bytes(main) + b"".join(subs), order


def build_narc(files: dict[str, bytes]) -> bytes:
    """{path: payload} -> NARC bytes (tests)."""
    fnt, order = build_fnt(list(files))
    image, fat = bytearray(), bytearray()
    for p in order:
        while len(image) % 4:
            image.append(0xFF)
        fat += struct.pack("<II", len(image), len(image) + len(files[p]))
        image += files[p]
    btaf = b"BTAF" + struct.pack("<IHH", 12 + len(fat), len(order), 0) + bytes(fat)
    fnt += b"\xff" * (-len(fnt) % 4)
    btnf = b"BTNF" + struct.pack("<I", 8 + len(fnt)) + fnt
    image += b"\xff" * (-len(image) % 4)
    gmif = b"GMIF" + struct.pack("<I", 8 + len(image)) + bytes(image)
    body = btaf + btnf + gmif
    return b"NARC" + struct.pack("<HHIHH", 0xFFFE, 0x0100, 16 + len(body), 16, 3) + body


def gx_pack(cmds: list[tuple[int, list[int]]]) -> bytes:
    """[(command, params)] -> packed GX list (tests)."""
    out = bytearray()
    for i in range(0, len(cmds), 4):
        group = cmds[i:i + 4]
        packed = 0
        for k, (c, _p) in enumerate(group):
            packed |= c << (8 * k)
        out += struct.pack("<I", packed)
        for c, p in group:
            if len(p) != GX_PARAMS[c]:
                raise ValueError(f"GX {c:#x} takes {GX_PARAMS[c]} params")
            out += struct.pack(f"<{len(p)}I", *[x & 0xFFFFFFFF for x in p])
    return bytes(out)
