"""MUGEN 1.0-era character reader: select.def roster, character .def -> sprite/anim files, and SFF v1 sprite tables.

Owned build: "DC vs Capcom vs Marvel" (windows_native, MUGEN, mugen.exe 2007). Little-endian, offsets absolute from the
start of the .sff. SFF v1 layout (Elecbyte spec): 512-byte header = "ElecbyteSpr\\0"(12) + version(4) + groups(u32) +
images(u32) + first_subfile_offset(u32) + subheader_size(u32) + palette_type(u8) + 3 pad + comments(476); each subfile =
32-byte header [next(u32) length(u32) axis_x(i16) axis_y(i16) group(u16) image(u16) linked(u16) same_palette(u8)
comments(14)] followed by `length-32`... in practice `next - offset - 32` PCX bytes (length 0 = linked sprite).
This is a read-only inventory/sprite-table reader, not a writer; every traversal is bounded by file size.
"""
from __future__ import annotations

import hashlib
import os
import re
import struct

SIG = b"ElecbyteSpr\x00"
HEADER = 512
SUB = 32
MAX_SPRITES = 200000


class MugenError(ValueError):
    pass


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def parse_sff1(data: bytes):
    """Return {version, groups, images, sprites:[...]} for an SFF v1 blob; raise MugenError on malformed input."""
    n = len(data)
    if n < HEADER or data[:12] != SIG:
        raise MugenError("not an SFF (bad signature or short header)")
    ver = tuple(data[12:16])
    if ver[3] != 0 and ver[0] == 0 and ver[1] == 0 and ver[2] == 0 and ver[3] >= 2:
        raise MugenError("SFF v2 not supported by this reader")
    groups, images, first, subsize = struct.unpack_from("<IIII", data, 16)
    if images > MAX_SPRITES:
        raise MugenError("image count out of range")
    sprites, off, seen = [], first, set()
    for i in range(images):
        if off < HEADER or off + SUB > n or off in seen:
            raise MugenError("subfile %d offset %d out of range or cycle" % (i, off))
        seen.add(off)
        nxt, length, ax, ay, grp, img, link, same = struct.unpack_from("<IIhhHHHB", data, off)
        body = off + SUB
        end = nxt if (nxt and i != images - 1) else min(n, body + length)
        if length == 0:
            if link >= i:
                raise MugenError("subfile %d links forward to %d" % (i, link))
            kind, size = "linked", 0
        else:
            if length > n or end > n or end < body:
                raise MugenError("subfile %d length out of range" % i)
            size = end - body
            kind = "pcx" if data[body:body + 1] == b"\x0a" else "unknown"
        s = {"index": i, "group": grp, "image": img, "axis": (ax, ay), "linked": link if length == 0 else None,
             "same_palette": bool(same), "offset": body, "size": size, "kind": kind}
        if kind == "pcx" and size >= 128:
            xmin, ymin, xmax, ymax = struct.unpack_from("<HHHH", data, body + 4)
            s["width"], s["height"] = xmax - xmin + 1, ymax - ymin + 1
            s["bpp"], s["planes"] = data[body + 3], data[body + 65]
            if data[body + 3] == 8 and size >= 769 and data[end - 769] == 0x0C:
                s["palette_offset"] = end - 768
        sprites.append(s)
        if nxt == 0:
            break
        if nxt <= off:
            raise MugenError("subfile %d next pointer does not advance" % i)
        off = nxt
    return {"version": ver, "groups": groups, "images": images, "palette_type": data[48],
            "sprites": sprites}


def read_sff1(path):
    with open(path, "rb") as f:
        return parse_sff1(f.read())


def parse_select_def(text: str):
    """Roster entries of the [Characters] section (name, stage/options); keywords randomselect/blank kept as such."""
    out, sec = [], None
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            sec = m.group(1).strip().lower()
            continue
        if sec == "characters":
            parts = [p.strip() for p in line.split(",")]
            out.append({"name": parts[0], "options": parts[1:], "random": parts[0].lower() == "randomselect"})
    return out


def parse_char_def(text: str):
    """Pull the [Files] sprite/palette entries and [Info] name from a character .def."""
    sec, info, files = None, {}, {}
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            sec = m.group(1).strip().lower()
            continue
        if "=" in line and sec in ("info", "files"):
            k, v = [x.strip().strip('"') for x in line.split("=", 1)]
            (info if sec == "info" else files)[k.lower()] = v
    return {"name": info.get("displayname") or info.get("name"), "files": files}


def _ci(base, rel):
    """Case-insensitive path resolve (MUGEN content is Windows-cased)."""
    cur = base
    for part in rel.replace("\\", "/").split("/"):
        if not part:
            continue
        try:
            names = os.listdir(cur)
        except OSError:
            return None
        hit = next((x for x in names if x.lower() == part.lower()), None)
        if hit is None:
            return None
        cur = os.path.join(cur, hit)
    return cur


def inventory(root, hash_exe=True):
    """Manifest of an owned MUGEN install: engine exe hash, roster, per-character .def/.sff with sprite counts."""
    exe = _ci(root, "mugen.exe") or _ci(root, os.path.basename(root) + ".exe")
    sel = _ci(root, "data/select.def")
    if not sel:
        raise MugenError("no data/select.def under %s" % root)
    with open(sel, "r", errors="replace") as f:
        roster = parse_select_def(f.read())
    chars = []
    for e in roster:
        if e["random"]:
            continue
        cdir = _ci(root, "chars/" + e["name"])
        rec = {"slot": e["name"], "dir": cdir, "def": None, "sff": None, "sprites": None, "error": None}
        chars.append(rec)
        if not cdir or not os.path.isdir(cdir):
            rec["error"] = "character folder missing"
            continue
        defp = None
        if cdir:
            if e["name"].lower().endswith(".def"):
                defp = _ci(root, "chars/" + e["name"])
            else:
                defp = _ci(cdir, e["name"] + ".def") or next(
                    (os.path.join(cdir, x) for x in sorted(os.listdir(cdir)) if x.lower().endswith(".def")
                     and not x.lower().startswith(("intro", "ending"))), None)
        if not defp:
            rec["error"] = "no .def"
            continue
        rec["def"] = defp
        with open(defp, "r", errors="replace") as f:
            cd = parse_char_def(f.read())
        rec["display_name"] = cd["name"]
        sffp = _ci(os.path.dirname(defp), cd["files"].get("sprite", ""))
        if not sffp or not os.path.isfile(sffp):
            rec["error"] = "sprite file missing"
            continue
        rec["sff"] = sffp
        try:
            with open(sffp, "rb") as f:
                head = f.read(HEADER)
            rec["sff_size"] = os.path.getsize(sffp)
            rec["sff_version"] = list(head[12:16])
            rec["sff_groups"], rec["sff_images"] = struct.unpack_from("<II", head, 16)
        except Exception as ex:  # noqa: BLE001
            rec["error"] = str(ex)
    return {"engine_exe": exe, "engine_sha256": sha256_file(exe) if (exe and hash_exe) else None,
            "roster_count": len(chars), "characters": chars}


# ---------------------------------------------------------------- PCX decode / export (read-only)

def decode_pcx(pcx: bytes):
    """Decode an 8bpp single-plane RLE PCX -> (width, height, indices bytes, palette 768B|None). Bounded and strict."""
    if len(pcx) < 128 or pcx[0] != 0x0A or pcx[2] != 1 or pcx[3] != 8 or pcx[65] != 1:
        raise MugenError("unsupported PCX (need 8bpp, 1 plane, RLE)")
    xmin, ymin, xmax, ymax = struct.unpack_from("<HHHH", pcx, 4)
    w, h = xmax - xmin + 1, ymax - ymin + 1
    stride = struct.unpack_from("<H", pcx, 66)[0]
    if not (0 < w <= 4096 and 0 < h <= 4096) or stride < w:
        raise MugenError("PCX dimensions out of range")
    pal = pcx[-768:] if len(pcx) >= 897 and pcx[-769] == 0x0C else None
    end = len(pcx) - (769 if pal else 0)
    out, i, need = bytearray(), 128, stride * h
    while len(out) < need:
        if i >= end:
            raise MugenError("PCX RLE data truncated")
        b = pcx[i]
        i += 1
        if b >= 0xC0:
            if i >= end:
                raise MugenError("PCX RLE data truncated")
            out += bytes([pcx[i]]) * (b & 0x3F)
            i += 1
        else:
            out.append(b)
    if len(out) != need:
        raise MugenError("PCX RLE run overflows image")
    rows = b"".join(bytes(out[y * stride:y * stride + w]) for y in range(h))
    return w, h, rows, pal


def sprite_pixels(data: bytes, parsed: dict, index: int, _depth=0):
    """Resolve linked sprites and same_palette; return (w, h, indices, palette768, axis)."""
    sp = parsed["sprites"]
    s = sp[index]
    if s["kind"] == "linked":
        if _depth > 8:
            raise MugenError("link chain too deep")
        w, h, px, pal, _ = sprite_pixels(data, parsed, s["linked"], _depth + 1)
        return w, h, px, pal, s["axis"]
    if s["kind"] != "pcx":
        raise MugenError("sprite %d is not a PCX" % index)
    w, h, px, pal = decode_pcx(data[s["offset"]:s["offset"] + s["size"]])
    if pal is None:
        j = index - 1
        while j >= 0 and pal is None:  # same_palette: inherit from the nearest earlier sprite with one
            if sp[j]["kind"] == "pcx" and "palette_offset" in sp[j]:
                pal = data[sp[j]["palette_offset"]:sp[j]["palette_offset"] + 768]
            j -= 1
    return w, h, px, pal, s["axis"]


def indexed_to_png(w, h, px: bytes, pal: bytes) -> bytes:
    """Minimal PNG writer (palette type 3; index 0 transparent, as MUGEN treats it)."""
    import zlib

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + px[y * w:(y + 1) * w] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
            + chunk(b"PLTE", pal[:768].ljust(768, b"\0")) + chunk(b"tRNS", b"\x00")
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def export_sprite_png(data: bytes, parsed: dict, index: int) -> bytes:
    w, h, px, pal, _ = sprite_pixels(data, parsed, index)
    if pal is None:
        raise MugenError("sprite %d has no palette" % index)
    return indexed_to_png(w, h, px, pal)
