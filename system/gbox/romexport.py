"""Export ROM hack: a bootable modded image of the operator's OWN library file + a shareable patch (no game data).

For personal use on a flash cart, a modded console or an emulator. Everything is written locally under
<data_dir>/exports/<game_id>/<name>/ and is downloadable only through the authenticated gBox API; nothing is uploaded.

What goes in
  * file mods (cache/mods/<game>/<name>, built by file_mod / sm64_swap / char_swap / metal_arms / aki_wrestling /
    gta_stories_models / re4wii / re6 ...): their image (or folder) is the starting point; several image mods of the
    same game are stacked by applying each one's byte difference from the vanilla image (a conflict is an error).
  * saved mods (/api/mods): each step is classified - '@launch mod=X' = that file mod; re_mods code patches
    (infinite_ammo, combo_freeze, merc_timer_freeze, unlimited_health) = baked into main.dol on the disc;
    'cheats' codes = a cheat file next to the image (RetroArch .cht / Dolphin GameSettings .ini / PCSX2 .pnach);
    anything else = live memory work gBox does while the game runs: reported as not bakeable, with the reason.
  * extra file changes (file_mod format: {disc path: {from|bytes|patch}}, "@image" = byte patches on the image).

Per platform
  * N64: big-endian .z64 (v64/n64 byte orders converted), CIC detected from the IPL3 boot code, header CRC recomputed
    (6101/6102/7102/6103/6105/6106).
  * GameCube: plain .iso; a replaced file that no longer fits its slot is moved to free space after the last file
    (FST offset + size updated; the disc stays within 1,459,978,240 bytes).
  * Wii: the mod's extracted disc tree is rebuilt into an .iso (or .rvz) with dolphin-tool (Dolphin's DirectoryBlob
    re-encrypts the partition; the signature is not Nintendo's, so real hardware needs a USB loader / cIOS).
  * PS2 (and other ISO9660 discs): file replaced in place when it fits its sectors, else appended at the end of the
    image (directory record + volume size updated).
  * Folder games (PS3 disc folders, Xbox 360 extracted XEX folders): a hard-link copy of the mod folder, bootable as
    an extracted game (RPCS3 / CFW PS3, Xenia / RGH-JTAG). No ISO is rebuilt (XGD / PS3 discs need console keys).
  * Patches: BPS always (source = the vanilla image as gBox reads it: unzipped .z64, GCZ/CHD unpacked to .iso);
    IPS too when the target is <= 16 MiB; xdelta3 when that program is installed. A patch holds only the bytes that
    differ from the original at the same offset (SourceRead for everything unchanged). Folder/Wii mods get a patch
    kit: one .bps per changed file (vs the vanilla extracted file) in a .zip.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import struct
import subprocess
import time
import zipfile
import zlib
from pathlib import Path

import numpy as np

GC_DISC_SIZE = 1_459_978_240
IPS_MAX = 1 << 24


# ================================================================ N64

N64_ORDER = {b"\x80\x37\x12\x40": "z64", b"\x37\x80\x40\x12": "v64", b"\x40\x12\x37\x80": "n64"}
# CRC32 of the IPL3 boot code (ROM 0x40..0x1000) -> CIC chip
CIC_BY_IPL3 = {0x6170A4A1: "6101", 0x90BB6CB5: "6102", 0x0B050EE0: "6103", 0x98BC2C86: "6105", 0xACC8580A: "6106",
               0x009E9EA3: "7102"}
CIC_SEED = {"6101": 0xF8CA4DDC, "6102": 0xF8CA4DDC, "7102": 0xF8CA4DDC, "6103": 0xA3886759, "6105": 0xDF26F436,
            "6106": 0x1FEA617A}


def n64_to_z64(data: bytes) -> bytes:
    """Any N64 byte order -> big-endian .z64."""
    order = N64_ORDER.get(bytes(data[:4]))
    if order is None:
        raise ValueError("not an N64 ROM (unknown header magic)")
    if order == "v64":
        return np.frombuffer(data, ">u2").astype("<u2").tobytes()
    if order == "n64":
        return np.frombuffer(data, ">u4").astype("<u4").tobytes()
    return bytes(data)


def n64_read(path) -> bytes:
    """.z64/.v64/.n64 or a .zip holding one (any byte order)."""
    p = Path(path)
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            return z.read(next(n for n in z.namelist() if n.lower().endswith((".z64", ".n64", ".v64"))))
    return p.read_bytes()


def n64_cic(rom: bytes) -> str:
    c = zlib.crc32(rom[0x40:0x1000]) & 0xFFFFFFFF
    if c not in CIC_BY_IPL3:
        raise ValueError(f"unknown N64 boot code (IPL3 CRC32 {c:08X}): can't recompute the header CRC")
    return CIC_BY_IPL3[c]


def n64_crc(rom: bytes, cic: str | None = None) -> tuple[int, int]:
    """The two header checksums (0x10, 0x14) the boot code verifies over ROM 0x1000..0x101000."""
    cic = cic or n64_cic(rom)
    if len(rom) < 0x101000:
        rom = bytes(rom) + bytes(0x101000 - len(rom))
    m = 0xFFFFFFFF
    t1 = t2 = t3 = t4 = t5 = t6 = CIC_SEED[cic]
    words = struct.unpack_from(">262144I", rom, 0x1000)
    key = struct.unpack_from(">64I", rom, 0x750) if cic == "6105" else None
    for i, d in enumerate(words):
        t = (t6 + d) & m
        if t < t6:
            t4 = (t4 + 1) & m
        t6 = t
        t3 ^= d
        s = d & 0x1F
        r = ((d << s) | (d >> (32 - s))) & m if s else d
        t5 = (t5 + r) & m
        t2 = t2 ^ r if t2 > d else t2 ^ t6 ^ d
        t1 = (t1 + ((key[i & 0x3F] if key else t5) ^ d)) & m
    if cic == "6103":
        return ((t6 ^ t4) + t3) & m, ((t5 ^ t2) + t1) & m
    if cic == "6106":
        return ((t6 * t4) + t3) & m, ((t5 * t2) + t1) & m
    return t6 ^ t4 ^ t3, t5 ^ t2 ^ t1


def n64_finalize(path: Path) -> dict:
    """In place: byte order -> .z64, header CRC recomputed. Returns what was done."""
    data = Path(path).read_bytes()
    order = N64_ORDER.get(data[:4])
    rom = bytearray(n64_to_z64(data))
    cic = n64_cic(rom)
    old = struct.unpack_from(">II", rom, 0x10)
    new = n64_crc(rom, cic)
    struct.pack_into(">II", rom, 0x10, *new)
    Path(path).write_bytes(bytes(rom))
    return {"byte_order": f"{order} -> z64", "cic": cic, "crc_before": f"{old[0]:08X} {old[1]:08X}",
            "crc": f"{new[0]:08X} {new[1]:08X}", "crc_fixed": old != new}


# ================================================================ GameCube disc (FST)

def gc_disc_id(path: Path) -> str:
    with open(path, "rb") as f:
        h = f.read(0x20)
    if struct.unpack_from(">I", h, 0x1C)[0] != 0xC2339F3D:
        raise ValueError(f"{Path(path).name} is not a GameCube disc image")
    return h[:6].decode("ascii", "replace")


def gc_used_end(f, disc) -> int:
    """First byte after everything the disc uses (files, FST, DOL), aligned to 32 KiB."""
    f.seek(0x420)
    dol, fst, fst_size = struct.unpack(">III", f.read(12))
    f.seek(dol)
    h = f.read(0x100)
    offs, sizes = struct.unpack_from(">18I", h, 0), struct.unpack_from(">18I", h, 0x90)
    end = max([fst + fst_size, dol + max(o + s for o, s in zip(offs, sizes))] + [o + s for o, s in disc.files.values()])
    return (end + 0x7FFF) & ~0x7FFF


def gc_used_regions(f, disc) -> list[tuple[int, int]]:
    """(start, end) of everything the disc uses: boot header + apploader, the DOL, the FST and every file."""
    f.seek(0x2454)
    app_size, app_trailer = struct.unpack(">II", f.read(8))
    f.seek(0x420)
    dol, fst, fst_size = struct.unpack(">III", f.read(12))
    f.seek(dol)
    h = f.read(0x100)
    offs, sizes = struct.unpack_from(">18I", h, 0), struct.unpack_from(">18I", h, 0x90)
    regions = [(0, 0x2460 + app_size + app_trailer), (dol, dol + max(o + s for o, s in zip(offs, sizes))),
               (fst, fst + fst_size)]
    regions += [(o, o + s) for o, s in disc.files.values() if s]
    return sorted(regions)


def gc_find_gap(f, disc, size: int, align: int = 0x8000) -> int | None:
    """The first 32 KiB-aligned unused stretch of at least `size` bytes between used regions (Nintendo masters fill
    unused disc space with junk data, so a full image still has room between files), or None."""
    end = 0
    for a, b in gc_used_regions(f, disc):
        start = (end + align - 1) & ~(align - 1)
        if a - start >= size:
            return start
        end = max(end, b)
    start = (end + align - 1) & ~(align - 1)
    return start if start + size <= GC_DISC_SIZE else None


def gc_put_file(f, disc, key: str, data: bytes) -> dict:
    """Replace a file on an open (r+b) GameCube image: in its slot when it fits, else moved to free space after the
    last used byte (FST entry offset + size rewritten). Updates disc.files."""
    off, size = disc.files[key]
    ent = disc.entries[key]
    if len(data) <= size:
        f.seek(off)
        f.write(data + b"\0" * (size - len(data)))
        f.seek(ent + 8)
        f.write(struct.pack(">I", len(data)))
        disc.files[key] = (off, len(data))
        return {"file": key, "mode": "in place", "size": len(data)}
    new = gc_used_end(f, disc)
    if new + len(data) > GC_DISC_SIZE:                     # a full disc (PSO Ep I&II ends on the last byte):
        new = gc_find_gap(f, disc, len(data))              # an unused stretch between files (mastering filler)
        if new is None:
            raise ValueError(f"{key}: {len(data)} bytes don't fit on the disc (no free space after the last file "
                             f"and no gap between files that large)")
    f.seek(new)
    f.write(data)
    f.seek(ent + 4)
    f.write(struct.pack(">II", new, len(data)))
    disc.files[key] = (new, len(data))
    return {"file": key, "mode": f"moved to 0x{new:X} (was 0x{off:X}, {size} bytes)", "size": len(data)}


def dol_file_offset(dol_hdr: bytes, addr: int) -> int | None:
    """RAM address -> offset inside a DOL (text/data sections)."""
    offs, addrs, sizes = (struct.unpack_from(">18I", dol_hdr, o) for o in (0x00, 0x48, 0x90))
    for o, a, s in zip(offs, addrs, sizes):
        if s and a <= addr < a + s:
            return o + addr - a
    return None


def patch_dol(f, dol_base: int, patches: list[dict]) -> list[dict]:
    """Code patches [{addr, orig, new, name}] into a DOL that starts at dol_base in the open file. The original word
    is checked first (already-patched counts as done)."""
    f.seek(dol_base)
    hdr = f.read(0x100)
    out = []
    for p in patches:
        o = dol_file_offset(hdr, p["addr"])
        if o is None:
            raise ValueError(f"{p['name']}: 0x{p['addr']:08X} is not in main.dol")
        f.seek(dol_base + o)
        cur = f.read(len(p["new"]) // 2).hex()
        if cur not in (p["orig"], p["new"]):
            raise ValueError(f"{p['name']}: main.dol has {cur} at 0x{p['addr']:08X}, expected {p['orig']} (other version?)")
        f.seek(dol_base + o)
        f.write(bytes.fromhex(p["new"]))
        out.append({"patch": p["name"], "address": f"0x{p['addr']:08X}", "dol_offset": f"0x{o:X}", "was": cur, "now": p["new"]})
    return out


# ================================================================ ISO9660 (PS2, PS1 data tracks, ...)

def _iso_walk(f, lba: int, size: int, prefix: str, out: dict):
    from .formats import iso9660                          # the shared ISO9660 walk (gbox.formats)
    for parts, rec, dlba in iso9660.walk(iso9660.file_reader(f), lba, size):
        if not rec.is_dir:
            path = prefix + "".join(p.rstrip(".") + "/" for p in parts) + rec.name.rstrip(".")
            out[path.upper()] = (dlba * 2048 + rec.offset, rec.lba, rec.size)


def iso_files(f) -> dict:
    """{UPPER/CASE/PATH: (record offset, extent lba, size)} of an ISO9660 image."""
    f.seek(16 * 2048)
    pvd = f.read(2048)
    if pvd[1:6] != b"CD001":
        raise ValueError("not an ISO9660 image (no CD001 volume descriptor at sector 16)")
    root = pvd[156:190]
    out: dict = {}
    _iso_walk(f, struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "", out)
    return out


def iso_put_file(f, files: dict, key: str, data: bytes) -> dict:
    """Replace a file on an open (r+b) ISO9660 image: in place when it fits its sectors, else appended at the end
    (extent + size rewritten both-endian, volume space size grown)."""
    k = key.upper().lstrip("/")
    if k not in files:
        raise ValueError(f"{key} is not on this disc")
    rec, lba, size = files[k]
    room = (size + 2047) // 2048 * 2048
    mode = "in place"
    if len(data) > room:
        f.seek(0, 2)
        end = f.tell()
        lba = (end + 2047) // 2048
        mode = f"appended at sector {lba} (was {files[k][1]})"
        f.seek(lba * 2048)
        f.write(data + b"\0" * (-len(data) % 2048))
        sectors = lba + (len(data) + 2047) // 2048
        f.seek(16 * 2048 + 80)
        f.write(struct.pack("<I", sectors) + struct.pack(">I", sectors))
    else:
        f.seek(lba * 2048)
        f.write(data + b"\0" * (room - len(data)))
    f.seek(rec + 2)
    f.write(struct.pack("<I", lba) + struct.pack(">I", lba) + struct.pack("<I", len(data)) + struct.pack(">I", len(data)))
    files[k] = (rec, lba, len(data))
    return {"file": key, "mode": mode, "size": len(data)}


# ================================================================ byte diff + patch formats

def diff_regions(a: Path, b: Path, chunk: int = 1 << 24):
    """(offset, bytes of b) for every run where b differs from a at the same offset (b's tail past a's end included)."""
    na, nb = Path(a).stat().st_size, Path(b).stat().st_size
    pend_off, pend = None, bytearray()
    with open(a, "rb") as fa, open(b, "rb") as fb:
        pos = 0
        while pos < nb:
            cb = fb.read(chunk)
            ca = fa.read(len(cb)) if pos < na else b""
            xb = np.frombuffer(cb, np.uint8)
            xa = np.frombuffer(ca, np.uint8)
            ne = np.ones(len(xb), bool)
            ne[:len(xa)] = xa != xb[:len(xa)]
            idx = np.flatnonzero(ne)
            if len(idx):
                cuts = np.flatnonzero(np.diff(idx) > 1) + 1
                starts = np.concatenate(([idx[0]], idx[cuts]))
                ends = np.concatenate((idx[cuts - 1], [idx[-1]])) + 1
                for s, e in zip(starts.tolist(), ends.tolist()):
                    if pend_off is not None and pend_off + len(pend) == pos + s:
                        pend += cb[s:e]
                        continue
                    if pend_off is not None:
                        yield pend_off, bytes(pend)
                    pend_off, pend = pos + s, bytearray(cb[s:e])
            pos += len(cb)
    if pend_off is not None:
        yield pend_off, bytes(pend)


def _crc_file(p: Path) -> int:
    c = 0
    with open(p, "rb") as f:
        while blk := f.read(1 << 24):
            c = zlib.crc32(blk, c)
    return c & 0xFFFFFFFF


def _vli(n: int) -> bytes:
    out = bytearray()
    while True:
        x, n = n & 0x7F, n >> 7
        if n == 0:
            out.append(0x80 | x)
            return bytes(out)
        out.append(x)
        n -= 1


def make_bps(src: Path, dst: Path, out: Path, meta: str = "", regions=None) -> dict:
    """BPS patch src -> dst: SourceRead for unchanged spans, TargetRead (new bytes) for the differences."""
    ns, nt = Path(src).stat().st_size, Path(dst).stat().st_size
    m = meta.encode()
    body = bytearray(b"BPS1" + _vli(ns) + _vli(nt) + _vli(len(m)) + m)
    pos, changed = 0, 0
    for off, data in (regions if regions is not None else diff_regions(src, dst)):
        if off > pos:
            body += _vli(((off - pos) - 1) << 2 | 0)
        body += _vli((len(data) - 1) << 2 | 1) + data
        pos, changed = off + len(data), changed + len(data)
    if pos < nt:
        body += _vli(((nt - pos) - 1) << 2 | 0)
    cs = _crc_file(src)
    body += struct.pack("<II", cs, _crc_file(dst))
    body += struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)
    Path(out).write_bytes(bytes(body))
    return {"format": "bps", "file": Path(out).name, "size": len(body), "changed_bytes": changed, "source_crc32": f"{cs:08x}"}


def apply_bps(src: bytes, patch: bytes) -> bytes:
    """Reference applier (self-test / verification)."""
    assert patch[:4] == b"BPS1"
    p = 4

    def vli():
        nonlocal p
        n, s = 0, 1
        while True:
            x = patch[p]
            p += 1
            n += (x & 0x7F) * s
            if x & 0x80:
                return n
            s <<= 7
            n += s
    ns, nt, ml = vli(), vli(), vli()
    p += ml
    out = bytearray()
    sr = tr = 0
    while p < len(patch) - 12:
        d = vli()
        cmd, n = d & 3, (d >> 2) + 1
        if cmd == 0:
            out += src[len(out):len(out) + n]
        elif cmd == 1:
            out += patch[p:p + n]
            p += n
        elif cmd == 2:
            d = vli()
            sr += (-1 if d & 1 else 1) * (d >> 1)
            out += src[sr:sr + n]
            sr += n
        else:
            d = vli()
            tr += (-1 if d & 1 else 1) * (d >> 1)
            for _ in range(n):
                out.append(out[tr])
                tr += 1
    assert len(out) == nt and len(src) == ns
    assert struct.unpack_from("<I", patch, len(patch) - 8)[0] == zlib.crc32(out) & 0xFFFFFFFF, "target CRC"
    return bytes(out)


def make_ips(src: Path, dst: Path, out: Path, regions=None) -> dict:
    """IPS (offsets < 16 MiB). Truncation uses the common 3-byte EOF extension."""
    ns, nt = Path(src).stat().st_size, Path(dst).stat().st_size
    if nt > IPS_MAX:
        raise ValueError("IPS can't address past 16 MiB")
    body = bytearray(b"PATCH")
    tgt = Path(dst).read_bytes()
    for off, data in (regions if regions is not None else diff_regions(src, dst)):
        if off == 0x454F46:                                # 'EOF' as an offset would end the patch: start 1 byte early
            off, data = off - 1, tgt[off - 1:off] + data
        for i in range(0, len(data), 0xFFFF):
            part = data[i:i + 0xFFFF]
            o = off + i
            if o == 0x454F46:
                o, part = o - 1, tgt[o - 1:o] + part[:0xFFFE]
            body += o.to_bytes(3, "big") + len(part).to_bytes(2, "big") + part
    body += b"EOF"
    if nt < ns:
        body += nt.to_bytes(3, "big")
    Path(out).write_bytes(bytes(body))
    return {"format": "ips", "file": Path(out).name, "size": len(body)}


def make_xdelta(src: Path, dst: Path, out: Path) -> dict | None:
    exe = shutil.which("xdelta3")
    if not exe:
        return None
    r = subprocess.run([exe, "-e", "-f", "-9", "-s", str(src), str(dst), str(out)], capture_output=True, text=True,
                       timeout=7200)
    if r.returncode:
        return {"format": "xdelta", "error": (r.stderr or r.stdout)[-300:]}
    return {"format": "xdelta", "file": Path(out).name, "size": Path(out).stat().st_size}


# ================================================================ inputs: library image, mods, saved-mod steps

def safe(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w .()'&+,-]+", "", s)).strip() or "export"


def vanilla_image(cfg, game: dict, rom: Path, progress=None) -> Path:
    """The unmodified image as a plain file gBox can diff against (never the library file itself when it is packed)."""
    from . import filemods
    plat, rom = game.get("platform", ""), Path(rom)
    base = filemods.base_dir(cfg, game["game_id"])
    if plat in ("n64", "n64dd"):
        out = Path(cfg.cache) / "romexport_base" / game["game_id"] / (rom.stem + ".z64")
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(n64_to_z64(n64_read(rom)))
        return out
    have = sorted(base.glob("*.iso")) if base.is_dir() else []
    if have:
        return have[0]
    ext = rom.suffix.lower()
    if ext in (".iso", ".gcm", ".bin") and rom.is_file():
        return rom
    base.mkdir(parents=True, exist_ok=True)
    out = base / (rom.stem + ".iso")
    if ext == ".gcz":
        filemods.gcz_to_iso(rom, out.with_suffix(".part"), progress)
        out.with_suffix(".part").replace(out)
        return out
    if ext == ".chd":
        from .gta_stories_models import lcs_iso_from_rom
        return lcs_iso_from_rom(rom, out, progress)
    if ext in (".rvz", ".wia", ".ciso", ".wbfs") and plat == "gamecube":
        _dolphin_tool(cfg, ["convert", "-i", str(rom), "-o", str(out), "-f", "iso"], [rom.parent, base])
        return out
    raise ValueError(f"can't read {rom.name} as a plain image ({ext})")


def _dolphin_tool(cfg, args: list[str], dirs: list[Path]) -> None:
    if os.name == "nt":
        exe = Path(cfg.runtime) / "dolphin" / "Dolphin-x64" / "DolphinTool.exe"
        if not exe.is_file():
            raise FileNotFoundError("DolphinTool.exe isn't in runtime/dolphin/Dolphin-x64 on this PC")
        argv = [str(exe), *args]
    else:
        if not shutil.which("flatpak"):
            raise FileNotFoundError("dolphin-tool (Dolphin flatpak) isn't installed on this node")
        argv = ["flatpak", "run", *[f"--filesystem={d}" for d in dict.fromkeys(str(Path(x).resolve()) for x in dirs)],
                "--command=dolphin-tool", "org.DolphinEmu.dolphin-emu", *args]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=7200)
    if r.returncode:
        raise RuntimeError(f"dolphin-tool {args[0]} failed: {(r.stderr or r.stdout)[-400:]}")


def file_mod_info(cfg, game_id: str, name: str, server=None, headers=None, progress=None) -> dict:
    from . import filemods
    d = filemods.mod_dir(cfg, game_id, name)
    if not (d / ".gbox-mod.json").exists() and server:
        if progress:
            progress(8, f"Fetching mod {name} from the collection")
        filemods.fetch(cfg, server, headers or {}, game_id, name, progress)
    if not (d / ".gbox-mod.json").exists():
        raise ValueError(f"file mod {name!r} isn't built for game {game_id} (not here and not in the collection)")
    meta = json.loads((d / ".gbox-mod.json").read_text())
    img = d / meta["image"] if meta.get("image") else None
    folder = img is None or img.suffix.lower() in (".xex", ".dol", ".bin", ".self", ".elf") or img.name.upper() == "EBOOT.BIN"
    return {"name": name, "dir": d, "meta": meta, "image": None if folder else img, "folder": folder}


RE_PATCH_ALIASES = {"ammo": "infinite_ammo", "god": "unlimited_health", "god_mode": "unlimited_health",
                    "invincible": "unlimited_health", "infinite_combo": "combo_freeze", "combo": "combo_freeze",
                    "freeze_timer": "merc_timer_freeze", "timer_freeze": "merc_timer_freeze"}


def classify(mod: dict, cfg=None) -> list[dict]:
    """A saved mod's steps -> components: {kind: file_mod|code_patch|cheat|none, ...}."""
    out = []
    for c in mod.get("calls") or []:
        tool, inp = c.get("tool"), c.get("input") or {}
        label = f"{mod.get('title', '')}: {tool} {inp.get('op', '')}".strip()
        if tool == "@launch" and inp.get("mod"):
            out.append({"kind": "file_mod", "game_id": inp.get("game_id") or mod.get("game_id"), "name": inp["mod"],
                        "label": label})
        elif tool == "@launch":
            out.append({"kind": "none", "label": label, "why": "launches the plain game: nothing to bake"})
        elif tool == "pso_mods" and inp.get("op") == "crit_always" and inp.get("on", True):
            out.append({"kind": "pso_code_patch", "patch": "crit_always", "label": label,
                        "game_id": inp.get("game_id") or mod.get("game_id")})
        elif tool == "re_mods":
            op = str(inp.get("op", "")).strip().lower().replace(" ", "_").replace("-", "_")
            op = RE_PATCH_ALIASES.get(op, op)
            from . import re_games as R
            if op in R.PATCHES and inp.get("on", True):
                out.append({"kind": "code_patch", "tool": "re_mods", "patch": op, "label": label})
            else:
                out.append({"kind": "none", "label": label,
                            "why": "changes game memory while the game runs (gBox's dispatcher / live "
                                   "writes); there is no static code patch for it yet, so it can't be baked into the disc"})
        elif tool == "cheats" and inp.get("codes"):
            out.append({"kind": "cheat", "desc": inp.get("desc") or mod.get("title") or "gBox code",
                        "codes": list(inp["codes"]), "label": label})
        elif tool == "characters" and inp.get("character") and cfg is not None:
            hit = _character_mod(cfg, inp.get("game_id") or mod.get("game_id"), inp["character"])
            out.append({"kind": "file_mod", "game_id": inp.get("game_id") or mod.get("game_id"), "name": hit, "label": label}
                       if hit else {"kind": "none", "label": label,
                                    "why": f"character swap {inp['character']!r}: its file mod isn't built on this node; "
                                           "build it (Use in this game) and export by mod name"})
        else:
            out.append({"kind": "none", "label": label,
                        "why": "a live change gBox makes in game memory while the game runs "
                               "(not a file or code change), so there is nothing to bake into the image; it stays a "
                               "gBox mod (Activate)"})
    return out


def _character_mod(cfg, game_id: str, character: str) -> str | None:
    d = Path(cfg.cache) / "mods" / str(game_id)
    if not d.is_dir():
        return None
    slug = re.sub(r"\W+", "_", character.lower()).strip("_")
    for m in sorted(d.glob("*/.gbox-mod.json")):
        meta = json.loads(m.read_text())
        if meta.get("character") == character or m.parent.name.endswith("_" + slug):
            return m.parent.name
    return None


def code_patches_for(disc_id: str, names: list[str]) -> list[dict]:
    from . import re_games as R
    v = R.VERSIONS.get(disc_id.encode())
    if v is None:
        raise ValueError(f"the re_mods code patches are known for {', '.join(k.decode() for k in R.VERSIONS)}, "
                         f"not disc {disc_id}")
    table = v.PATCHES
    out = []
    for n in names:
        if n not in table:
            raise ValueError(f"{n} isn't located in {v.name} yet")
        a, orig, new, what = table[n]
        out.append({"name": n, "addr": a, "orig": orig, "new": new, "what": what})
    return out


# ================================================================ cheat files

def write_cheats(plat: str, disc_id: str, stem: str, cheats: list[dict], code_patches: list[dict], d: Path) -> list[str]:
    """Codes as cheat files the target emulator loads (codes kept exactly as entered; code patches as Gecko 04 writes)."""
    files = []
    if plat in ("n64", "n64dd", "psx", "snes", "nes", "gb", "gbc", "gba", "genesis", "megadrive", "dreamcast") and cheats:
        lines = [f"cheats = {len(cheats)}", ""]
        for i, c in enumerate(cheats):
            lines += [f'cheat{i}_desc = "{c["desc"]}"', f'cheat{i}_code = "{"+".join(c["codes"])}"', f"cheat{i}_enable = true", ""]
        (d / f"{stem}.cht").write_text("\n".join(lines))
        files.append(f"{stem}.cht")
        txt = "\n\n".join(f"{c['desc']}\n" + "\n".join(c["codes"]) for c in cheats)
        (d / f"{stem} - codes.txt").write_text(txt + "\n")
        files.append(f"{stem} - codes.txt")
    if plat in ("gamecube", "wii") and (cheats or code_patches):
        ini = ["[Gecko]"]
        for p in code_patches:
            ini += [f"$gBox: {p['name']} ({p['what']})", f"{0x04000000 | (p['addr'] & 0x01FFFFFF):08X} {p['new'].upper()}"]
        for c in cheats:
            ini += [f"$gBox: {c['desc']}", *c["codes"]]
        ini += ["", "[Gecko_Enabled]", *[f"$gBox: {p['name']} ({p['what']})" for p in code_patches],
                *[f"$gBox: {c['desc']}" for c in cheats], ""]
        (d / f"{disc_id}.ini").write_text("\n".join(ini))
        files.append(f"{disc_id}.ini")
    if plat == "ps2" and cheats:
        body = []
        for c in cheats:
            body.append(f"// {c['desc']}")
            for ln in c["codes"]:
                parts = ln.replace(",", " ").split()
                body.append(ln if ln.startswith("patch=") else
                            f"patch=1,EE,{parts[0]},extended,{parts[1]}" if len(parts) == 2 else f"// {ln}")
        (d / f"{stem}.pnach").write_text("\n".join(body) + "\n")
        files.append(f"{stem}.pnach")
    return files


# ================================================================ export

def exports_root(cfg) -> Path:
    return Path(cfg.data_dir) / "exports"


def _link_or_copy(src: Path, dst: Path, write: bool):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    if not write:
        try:
            os.link(src, dst)
            return
        except OSError:
            pass
    shutil.copy2(src, dst)


def _mirror(src: Path, dst: Path, progress=None):
    """Hard-link copy of a folder (real copy where links aren't possible)."""
    files = [p for p in src.rglob("*") if p.is_file() and p.name not in (".gbox-mod.json",) and not p.name.endswith(".part")]
    for i, p in enumerate(files):
        _link_or_copy(p, dst / p.relative_to(src), False)
        if progress and i % 500 == 0:
            progress(20 + 30 * i / max(1, len(files)), f"Linking the mod folder ({i}/{len(files)} files)")


def _break_link(p: Path):
    """Make p a private copy before writing to it (it may be a hard link into the mod / base copy)."""
    if p.stat().st_nlink > 1:
        tmp = p.with_name(p.name + ".tmp")
        shutil.copy2(p, tmp)
        os.replace(tmp, p)


def _patch_kit(base: Path, tree: Path, out_zip: Path, only: list[str] | None = None) -> dict:
    """One .bps per file that differs from the vanilla extracted file (new files listed, not included).
    only: compare just these relative paths (a partial vanilla copy)."""
    changed, new = [], []
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in ([tree / o for o in only] if only else sorted(tree.rglob("*"))):
            if not p.is_file():
                continue
            rel = p.relative_to(tree)
            b = base / rel
            if not b.exists():
                new.append(rel.as_posix())
                continue
            sb, sp = b.stat(), p.stat()
            if (sb.st_ino == sp.st_ino and sb.st_dev == sp.st_dev) or (sb.st_size == sp.st_size and _same(b, p)):
                continue
            buf = out_zip.with_name(".kit.bps")
            make_bps(b, p, buf)
            z.write(buf, rel.as_posix() + ".bps")
            buf.unlink()
            changed.append(rel.as_posix())
        z.writestr("README.txt", "gBox patch kit: apply each .bps (Flips / beat) to the same file of your own extracted "
                                 "disc.\n" + ("New files (not included, they come from the mod): " + ", ".join(new) if new else ""))
    return {"format": "bps kit", "file": out_zip.name, "size": out_zip.stat().st_size, "changed_files": changed, "new_files": new}


def _same(a: Path, b: Path) -> bool:
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(1 << 22), fb.read(1 << 22)
            if x != y:
                return False
            if not x:
                return True


def _apply_changes(img: Path, plat: str, changes: dict) -> list[dict]:
    done = []
    with open(img, "r+b") as f:
        disc = isofs = None
        for key, ch in changes.items():
            if key == "@image":
                for p in ch.get("patch", []):
                    f.seek(int(str(p["offset"]), 0))
                    f.write(bytes.fromhex(p["hex"]))
                done.append({"file": "@image", "mode": "byte patches", "count": len(ch.get("patch", []))})
                continue
            if plat in ("n64", "n64dd", "snes", "nes", "gb", "gbc", "gba", "genesis"):
                raise ValueError(f"{key}: cartridge ROMs have no file system; use '@image' byte patches")
            if plat == "gamecube":
                if disc is None:
                    from .gcdisc import GCDisc
                    disc = GCDisc(img)
                put = lambda k, data: gc_put_file(f, disc, k, data)
                cur = lambda k: (f.flush(), disc.read(k))[1]
                if key not in disc.files:
                    raise ValueError(f"{key} is not on this disc")
            else:
                if isofs is None:
                    isofs = iso_files(f)
                put = lambda k, data: iso_put_file(f, isofs, k, data)

                def cur(k):
                    f.flush()
                    _r, lba, size = isofs[k.upper().lstrip("/")]
                    f.seek(lba * 2048)
                    return f.read(size)
            if "patch" in ch:
                data = bytearray(cur(key))
                for p in ch["patch"]:
                    o, b = int(str(p["offset"]), 0), bytes.fromhex(p["hex"])
                    data[o:o + len(b)] = b
                data = bytes(data)
            else:
                data = Path(ch["from"]).read_bytes() if "from" in ch else ch["bytes"]
            done.append(put(key, data))
        if disc is not None:
            disc.f.close()
    return done


def export(cfg, game: dict, rom: Path, mods: list[dict] | None = None, file_mods: list[str] | None = None,
           changes: dict | None = None, name: str = "", formats: tuple = ("bps", "ips", "xdelta"),
           wii_format: str = "iso", server=None, headers=None, progress=None) -> dict:
    """Build the export. mods = saved mod docs; file_mods = file-mod names of this game; changes = extra file changes."""
    prog = progress or (lambda p, m: None)
    plat, gid = game.get("platform", ""), game["game_id"]
    comps = [c for m in (mods or []) for c in classify(m, cfg)]
    comps += [{"kind": "file_mod", "game_id": gid, "name": n, "label": f"file mod {n}"} for n in (file_mods or [])]
    if any(c["kind"] == "pso_code_patch" for c in comps):
        if plat != "dreamcast" or changes or any(c["kind"] != "pso_code_patch" or
                (c.get("game_id") and c["game_id"] != gid) for c in comps):
            raise ValueError("Export the PSO US v2 critical-hit modification alone; mixed changes need a verified combined writer")
        from . import pso_rom_export
        return pso_rom_export.export(cfg, game, rom, name, progress)
    fms = []
    for c in comps:
        if c["kind"] == "file_mod":
            if c["game_id"] and c["game_id"] != gid:
                c.update(kind="none", why=f"built for another catalog entry ({c['game_id']}): export that game instead")
                continue
            if any(f["name"] == c["name"] for f in fms):
                continue
            try:
                fms.append(file_mod_info(cfg, gid, c["name"], server, headers, prog))
            except ValueError as e:
                c.update(kind="none", why=str(e))
    cheats = [c for c in comps if c["kind"] == "cheat"]
    patch_names = list(dict.fromkeys(c["patch"] for c in comps if c["kind"] == "code_patch"))
    if not fms and not changes and not patch_names and not cheats:
        why = "; ".join(f"{c['label']}: {c.get('why', '')}" for c in comps) or "no mods given"
        raise ValueError(f"nothing in this selection can be baked into a {plat} image: {why}")
    title = name or " + ".join([m["title"] for m in mods or []] + [n for n in file_mods or []])[:120] or "gBox mod"
    slug = re.sub(r"[^\w.-]+", "_", title.lower()).strip("_")[:60] or "export"
    out = exports_root(cfg) / gid / slug
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    stem = f"{safe(re.sub(r'[(].*', '', game.get('title', gid)).strip())} - {safe(title)}"
    res = {"name": slug, "title": title, "game_id": gid, "game": game.get("title"), "platform": plat,
           "dir": str(out), "rel_dir": f"exports/{gid}/{slug}", "built": time.time(), "image": None, "patches": [],
           "cheat_files": [], "steps": [], "components": comps,
           "note": "Personal-use export of your own game file; kept on this gBox, never uploaded. The patch holds only the bytes "
                   "that differ from the original at the same offset (no unchanged game data)."}
    folder = [f for f in fms if f["folder"]]
    images = [f for f in fms if not f["folder"]]
    if folder and (images or len(folder) > 1):
        raise ValueError("folder mods can't be stacked with other mods yet: export them one at a time")

    if folder:                                             # ---- extracted-folder games (Wii, PS3, Xbox 360)
        fm = folder[0]
        tree = out / "game"
        prog(15, f"Linking {fm['name']} (hard links: no extra space)")
        _mirror(fm["dir"], tree, prog)
        res["steps"].append({"step": "folder", "from": fm["name"], "files": sum(1 for p in tree.rglob('*') if p.is_file())})
        dol = tree / "disc" / "DATA" / "sys" / "main.dol"
        if patch_names:
            if not dol.is_file():
                raise ValueError("code patches need main.dol (a GameCube/Wii disc)")
            disc_id = (tree / "disc" / "DATA" / "sys" / "boot.bin").read_bytes()[:6].decode()
            _break_link(dol)
            with open(dol, "r+b") as f:
                res["steps"] += patch_dol(f, 0, code_patches_for(disc_id, patch_names))
        base, only = _folder_base(cfg, gid, fm, rom, prog)
        if plat == "wii" and dol.is_file():
            prog(55, f"Rebuilding the Wii disc ({wii_format}) with dolphin-tool")
            ext = ".rvz" if wii_format == "rvz" else ".iso"
            img = out / (stem + ext)
            args = ["convert", "-i", str(dol), "-o", str(img), "-f", "rvz" if ext == ".rvz" else "iso"]
            if ext == ".rvz":
                args += ["-b", "131072", "-c", "zstd", "-l", "5"]
            _dolphin_tool(cfg, args, [tree, out])
            res["image"] = img.name
            res["steps"].append({"step": "wii rebuild", "tool": "dolphin-tool convert (DirectoryBlob)", "format": ext[1:],
                                 "boots": "Dolphin; real Wii via a USB loader with cIOS (fake-signed partition)"})
            if base:
                prog(85, "Patch kit (one .bps per changed file)")
                res["patches"].append(_patch_kit(base, tree, out / (stem + " - patch kit.zip"), only))
            disc_id = (tree / "disc" / "DATA" / "sys" / "boot.bin").read_bytes()[:6].decode()
            shutil.rmtree(tree)
        else:
            res["image"] = "game/"
            res["steps"].append({"step": "folder export", "boots": {"ps3": "RPCS3 / CFW PS3 (disc folder)",
                                                                    "xbox360": "Xenia / RGH-JTAG (extracted XEX folder)"}
                                 .get(plat, "as an extracted game"),
                                 "why_no_iso": "an Xbox 360 / PS3 disc can't be re-authored without console keys"})
            if base:
                prog(85, "Patch kit (one .bps per changed file)")
                res["patches"].append(_patch_kit(base, tree, out / (stem + " - patch kit.zip"), only))
            else:
                res["patches"].append({"format": "bps kit", "error": "no vanilla extracted copy on this node to diff against"})
            disc_id = ""
        res["cheat_files"] = write_cheats(plat, disc_id, stem, cheats, code_patches_for(disc_id, patch_names) if patch_names else [], out)
        return _finish(res, out)

    if not fms and not changes and not patch_names:      # ---- codes only: no image change, just the cheat file(s)
        disc_id = ""
        if plat == "gamecube":
            try:
                disc_id = gc_disc_id(vanilla_image(cfg, game, rom, prog))
            except Exception:                              # noqa: BLE001
                disc_id = "GAMEID"
        res["cheat_files"] = write_cheats(plat, disc_id, stem, cheats, [], out)
        if not res["cheat_files"]:
            raise ValueError(f"gBox has no cheat-file format for {plat}: codes {', '.join(c['desc'] for c in cheats)}")
        res["steps"].append({"step": "cheat file only", "why": "the codes are RAM writes the emulator / cheat device applies "
                             "every frame; a cartridge or disc can't hold them without a code hook, so the image stays vanilla"})
        return _finish(res, out)

    # ---- single-image games
    prog(10, "Reading the vanilla image")
    base = vanilla_image(cfg, game, rom, prog)
    ext = ".z64" if plat in ("n64", "n64dd") else base.suffix if base.suffix.lower() != ".gcz" else ".iso"
    img = out / (stem + ext)
    needs_write = bool(patch_names or changes or len(images) > 1 or plat in ("n64", "n64dd") or not images)
    prog(25, "Copying the image" if needs_write else "Linking the mod image")
    _link_or_copy(images[0]["image"] if images else base, img, needs_write)
    res["steps"].append({"step": "start", "from": images[0]["name"] if images else "vanilla image"})
    for fm in images[1:]:                                  # stack: apply each further mod's difference from vanilla
        prog(35, f"Stacking {fm['name']}")
        n = 0
        with open(img, "r+b") as f, open(base, "rb") as fb:
            for off, data in diff_regions(base, fm["image"]):
                f.seek(off)
                cur = f.read(len(data))
                fb.seek(off)
                van = fb.read(len(data))
                if cur != van and cur != data:
                    raise ValueError(f"{fm['name']} and an earlier mod both change bytes at 0x{off:X}: they can't be stacked")
                f.seek(off)
                f.write(data)
                n += len(data)
        res["steps"].append({"step": "stack", "mod": fm["name"], "bytes": n})
    if changes:
        prog(45, "Applying file changes")
        res["steps"] += _apply_changes(img, plat, changes)
    disc_id = ""
    if plat == "gamecube":
        disc_id = gc_disc_id(img)
        if patch_names:
            prog(50, "Baking code patches into main.dol")
            with open(img, "r+b") as f:
                f.seek(0x420)
                res["steps"] += patch_dol(f, struct.unpack(">I", f.read(4))[0], code_patches_for(disc_id, patch_names))
    elif patch_names:
        raise ValueError(f"re_mods code patches are GameCube/Wii main.dol patches; this is a {plat} game")
    if plat in ("n64", "n64dd"):
        prog(55, "Byte order + header CRC")
        res["steps"].append({"step": "n64 header", **n64_finalize(img)})
    res["image"] = img.name
    res["image_size"] = img.stat().st_size
    if base.stat().st_size and abs(img.stat().st_size - base.stat().st_size) > base.stat().st_size // 2:
        res["warning"] = "the image size differs a lot from the vanilla one: check the source image"
    res["source"] = {"file": Path(rom).name, "vanilla_image": base.name, "size": base.stat().st_size}
    prog(60, "Writing the patch (BPS)")
    regions = list(diff_regions(base, img))
    changed = sum(len(d) for _, d in regions)
    res["changed_bytes"] = changed
    if changed > base.stat().st_size // 2:
        res["warning"] = (f"{changed} bytes differ from the vanilla image (more than half): the mod may have been built "
                          "from a different dump; the patch is valid but large")
    if "bps" in formats:
        res["patches"].append(make_bps(base, img, out / (stem + ".bps"), meta=f"gBox export: {title}", regions=regions))
        res["source"]["crc32"] = res["patches"][-1]["source_crc32"]
    if "ips" in formats and img.stat().st_size <= IPS_MAX and base.stat().st_size <= IPS_MAX:
        res["patches"].append(make_ips(base, img, out / (stem + ".ips"), regions=regions))
    if "xdelta" in formats:
        prog(80, "xdelta3 patch")
        x = make_xdelta(base, img, out / (stem + ".xdelta"))
        if x:
            res["patches"].append(x)
    if os.environ.get("GBOX_VERIFY_BPS", "1") != "0" and img.stat().st_size <= 64 << 20 and "bps" in formats:
        p = (out / (stem + ".bps")).read_bytes()
        res["patch_verified"] = apply_bps(base.read_bytes(), p) == img.read_bytes()
    res["cheat_files"] = write_cheats(plat, disc_id, stem, cheats,
                                      code_patches_for(disc_id, patch_names) if patch_names else [], out)
    return _finish(res, out)


def _folder_base(cfg, gid: str, fm: dict, rom: Path | None = None, progress=None) -> tuple[Path | None, list | None]:
    """The vanilla extracted copy a folder mod was linked from (Wii/PS3: cache/modbase/<game>, RE6: runtime/re6/base),
    else (Xbox 360) just the mod's changed files pulled out of the library ISO. Returns (dir, only-these-files)."""
    from . import filemods
    b = filemods.base_dir(cfg, gid)
    if (fm["dir"] / "disc").is_dir() and (b / "disc").is_dir():
        return b, None                                     # the mod tree mirrors modbase/<game> (disc/ inside both)
    if b.is_dir() and (b / ".gbox-base-complete").exists():
        return b, None
    r = Path(cfg.runtime) / "re6" / "base"
    if (fm["dir"] / "default.xex").exists() and (r / ".gbox-base-complete").exists():
        return r, None
    files = [f for f in fm["meta"].get("files") or [] if not f.startswith("@")]
    if (fm["dir"] / "default.xex").exists() and files and rom and Path(rom).suffix.lower() == ".iso" and Path(rom).is_file():
        from .re6 import extract                           # XDVDFS reader: only the files the mod replaced
        dst = Path(cfg.cache) / "romexport_base" / gid
        if progress:
            progress(60, f"Reading the {len(files)} original files from {Path(rom).name}")
        extract(rom, dst, only=files)
        return dst, files
    return None, None


README = """{title}
{game} ({platform}) - exported by gBox {when}

{image_line}
Patches (the shareable form: only the bytes that differ from your original at the same offset, no unchanged game data;
if the mod repacks archives, the changed bytes can include repacked original assets):
{patches}
{cheats}
What was baked in:
{steps}
{skipped}
This export is for your own use with your own copy of the game. It stays on your gBox; nothing was uploaded.
"""


def _finish(res: dict, out: Path) -> dict:
    files = []
    for p in sorted(out.rglob("*")):
        if p.is_file():
            files.append({"path": p.relative_to(out).as_posix(), "size": p.stat().st_size})
    res["files"] = [f for f in files if not f["path"].startswith("game/")][:200]
    res["folder_files"] = sum(1 for f in files if f["path"].startswith("game/"))
    skipped = [c for c in res["components"] if c["kind"] == "none"]
    img = res.get("image")
    (out / "README.txt").write_text(README.format(
        title=res["title"], game=res.get("game"), platform=res["platform"], when=time.strftime("%Y-%m-%d %H:%M"),
        image_line=(f"Original library file: {img} (unchanged; archives may require extraction)" if res.get("mode") == "original" else
                    f"Bootable image: {img}" if img and img != "game/" else
                    f"Bootable folder: game/ ({res['folder_files']} files)" if img else "No image"),
        patches="\n".join(f"  {p.get('file', '?')} ({p['format']})" + (f" - apply to: {res['source']['vanilla_image']} "
                          f"(crc32 {res['source'].get('crc32', '?')})" if res.get("source") else "")
                          for p in res["patches"] if p.get("file")) or "  none",
        cheats=("Cheat files: " + ", ".join(res["cheat_files"]) + "\n") if res["cheat_files"] else "",
        steps="\n".join("  " + json.dumps(s) for s in res["steps"]),
        skipped=("Not baked (stays a live gBox mod):\n" + "\n".join(f"  {c['label']}: {c['why']}" for c in skipped))
        if skipped else ""))
    res["files"].append({"path": "README.txt", "size": (out / "README.txt").stat().st_size})
    (out / "export.json").write_text(json.dumps(res, default=str, indent=1))
    return res


def list_exports(cfg, game_id: str = "") -> list[dict]:
    root = exports_root(cfg)
    if not root.is_dir():
        return []
    pat = f"{game_id}/*/export.json" if game_id else "*/*/export.json"
    out = []
    for m in root.glob(pat):
        try:
            out.append(json.loads(m.read_text()))
        except Exception:                                  # noqa: BLE001 - half-written export
            pass
    return sorted(out, key=lambda e: -e.get("built", 0))


def remove(cfg, game_id: str, name: str) -> bool:
    d = exports_root(cfg) / game_id / name
    if d.is_dir() and d.resolve().is_relative_to(exports_root(cfg).resolve()):
        shutil.rmtree(d)
        return True
    return False


# ================================================================ self-test

def _selftest():
    import tempfile
    import types
    td = Path(tempfile.mkdtemp())
    # BPS / IPS round trip (growth, change at 0, change at the end)
    a = bytes(range(256)) * 64
    b = bytearray(a)
    b[0] = 0xEE
    b[1000:1010] = b"0123456789"
    b += b"tail!"
    (td / "a").write_bytes(a)
    (td / "b").write_bytes(bytes(b))
    make_bps(td / "a", td / "b", td / "p.bps")
    assert apply_bps(a, (td / "p.bps").read_bytes()) == bytes(b)
    make_ips(td / "a", td / "b", td / "p.ips")
    ips = (td / "p.ips").read_bytes()
    assert ips[:5] == b"PATCH" and ips.endswith(b"EOF")
    # region splitter across chunk boundaries
    r = list(diff_regions(td / "a", td / "b", chunk=1004))
    assert r[0] == (0, b"\xee") and r[1] == (1000, b"0123456789") and r[-1][1].endswith(b"tail!"), r
    # N64 CRC: a fake 6102 ROM checks against sm64_writer's reference implementation
    from .sm64_writer import crc6102
    rom = bytearray(os.urandom(0x101000))
    rom[:4] = b"\x80\x37\x12\x40"
    assert n64_crc(rom, "6102") == crc6102(rom)
    from .oot_writer import crc6105
    assert n64_crc(rom, "6105") == crc6105(rom)
    v64 = np.frombuffer(bytes(rom), ">u2").astype("<u2").tobytes()
    assert n64_to_z64(v64) == bytes(rom)
    # ISO9660: a minimal image with one file, replaced in place and appended
    iso = bytearray(2048 * 24)
    pvd = bytearray(2048)
    pvd[0:6] = b"\x01CD001"
    root = bytearray(34)
    root[0] = 34
    struct.pack_into("<I", root, 2, 20)
    struct.pack_into("<I", root, 10, 2048)
    root[25], root[32] = 2, 1
    pvd[156:190] = root
    iso[16 * 2048:17 * 2048] = pvd
    rec = bytearray(33 + 10)
    rec[0] = len(rec)
    struct.pack_into("<I", rec, 2, 22)
    struct.pack_into("<I", rec, 10, 5)
    rec[32] = 10
    rec[33:43] = b"HELLO.TXT;"
    d = bytearray(2048)
    d[0:34] = root                                         # "."
    d[34:68] = root                                        # ".."
    d[34 + 33] = 1
    d[68:68 + len(rec)] = rec
    iso[20 * 2048:21 * 2048] = d
    iso[22 * 2048:22 * 2048 + 5] = b"hello"
    (td / "t.iso").write_bytes(bytes(iso))
    with open(td / "t.iso", "r+b") as f:
        fs = iso_files(f)
        assert "HELLO.TXT" in fs, fs
        assert iso_put_file(f, fs, "hello.txt", b"HI")["mode"] == "in place"
        assert iso_put_file(f, fs, "HELLO.TXT", b"x" * 3000)["mode"].startswith("appended")
    with open(td / "t.iso", "rb") as f:
        fs = iso_files(f)
        _r, lba, size = fs["HELLO.TXT"]
        f.seek(lba * 2048)
        assert size == 3000 and f.read(size) == b"x" * 3000
    # DOL patch
    dol = bytearray(0x200)
    struct.pack_into(">I", dol, 0x00, 0x100)               # text0 at file 0x100
    struct.pack_into(">I", dol, 0x48, 0x80003100)
    struct.pack_into(">I", dol, 0x90, 0x100)
    dol[0x110:0x114] = bytes.fromhex("a07f0000")
    bio = io.BytesIO(bytes(dol))
    r = patch_dol(bio, 0, [{"name": "t", "addr": 0x80003110, "orig": "a07f0000", "new": "4bfffff8"}])
    assert bio.getvalue()[0x110:0x114] == bytes.fromhex("4bfffff8") and r[0]["dol_offset"] == "0x110"
    # classify
    comps = classify({"title": "t", "calls": [{"tool": "@launch", "input": {"mod": "m1", "game_id": "g"}},
                                              {"tool": "re_mods", "input": {"op": "ammo", "on": True}},
                                              {"tool": "cheats", "input": {"codes": ["80000000 0001"], "desc": "x"}},
                                              {"tool": "pso_mods", "input": {"op": "meseta"}}]})
    assert [c["kind"] for c in comps] == ["file_mod", "code_patch", "cheat", "none"], comps
    # end to end: a cartridge image mod -> export with CRC fix + patches
    cfg = types.SimpleNamespace(cache=td / "cache", data_dir=td / "data", runtime=td / "rt")
    lib = td / "lib"
    lib.mkdir()
    rom0 = bytearray(0x101000 + 0x1000)
    rom0[:4] = b"\x80\x37\x12\x40"
    rom0[0x40:0x1000] = b"\0" * (0x1000 - 0x40)
    with zipfile.ZipFile(lib / "game.zip", "w") as z:
        z.writestr("game.z64", bytes(rom0))
    global CIC_BY_IPL3
    saved = dict(CIC_BY_IPL3)
    CIC_BY_IPL3[zlib.crc32(bytes(rom0[0x40:0x1000])) & 0xFFFFFFFF] = "6102"
    try:
        from . import filemods
        game = {"game_id": "g", "platform": "n64", "title": "Test Game (USA)"}
        md = filemods.mod_dir(cfg, "g", "m1")
        md.mkdir(parents=True)
        mrom = bytearray(rom0)
        mrom[0x2000:0x2004] = b"MOD!"
        (md / "mod.z64").write_bytes(bytes(mrom))
        (md / ".gbox-mod.json").write_text(json.dumps({"name": "m1", "game_id": "g", "image": "mod.z64"}))
        res = export(cfg, game, lib / "game.zip", mods=[{"title": "Mod One", "calls": [
            {"tool": "@launch", "input": {"mod": "m1", "game_id": "g"}},
            {"tool": "cheats", "input": {"codes": ["8033B21E 0008"], "desc": "lives"}},
            {"tool": "zelda", "input": {"op": "noclip"}}]}])
        outimg = Path(res["dir"]) / res["image"]
        data = outimg.read_bytes()
        assert data[0x2000:0x2004] == b"MOD!" and struct.unpack_from(">II", data, 0x10) == n64_crc(data, "6102")
        assert res["patch_verified"] and any(p["format"] == "ips" for p in res["patches"]), res
        assert res["cheat_files"] and (Path(res["dir"]) / "README.txt").exists()
        assert [c["kind"] for c in res["components"]] == ["file_mod", "cheat", "none"]
        assert list_exports(cfg, "g")[0]["name"] == res["name"] and remove(cfg, "g", res["name"])
    finally:
        CIC_BY_IPL3.clear()
        CIC_BY_IPL3.update(saved)
    shutil.rmtree(td, ignore_errors=True)
    print("romexport selftest ok")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "cic":
        for p in sys.argv[2:]:
            r = n64_to_z64(n64_read(p))
            print(p, n64_cic(r), "header", r[0x10:0x18].hex(), "computed", "%08x%08x" % n64_crc(r))
    else:
        _selftest()
