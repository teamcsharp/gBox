"""`re_executable`: put a title's main executable where Ghidra can import it, with the right load address and processor.

The typed Ghidra tools (analyze_binary, ghidra_script) import a file with Ghidra's default loaders and can't pass
-loader BinaryLoader / -loader-baseAddr, so every raw image is wrapped as an ELF with its real load address here:

  gamecube   disc (.iso/.gcm, .gcz unpacked once to the shared mod base)  main.dol -> gcdisc.dol_to_elf
  dreamcast  GD-ROM (.gdi, or .chd unpacked once with chdman)              1ST_READ.BIN at 0x8C010000 (SH-4 LE)
  psx        disc (.chd v4 / .bin)                                          SYSTEM.CNF BOOT -> PS-X EXE body at t_addr
  ps2        disc (.iso, .chd unpacked once with chdman)                    SYSTEM.CNF BOOT2 -> the ELF itself
  n64        ROM (.z64/.v64/.n64, in a .zip)                                boot code ROM 0x1000 (1 MiB) at the header entry
  gba        ROM                                                            the ROM at 0x08000000 (ARM LE)
  xbox360    disc (.iso, XDVD)                                              default.xex -> PE image (gbox.re6.xex_image)
  any        source=ram + session_id: the session's main RAM read through the control plane -> ELF at the RAM base

Output goes to <data_dir>/analysis/re/<game_id>/ on this node (the Spark: the same folder Windows sees as
\\\\10.89.1.246\\ehm_eckx\\gBox\\system\\gbox-data\\analysis). The source library file is only read.
The exe_info.json artifact records hashes of the source executable and of the ELF (provenance for every later finding).
"""
import hashlib
import json
import re
import shutil
import struct
import subprocess
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel

from .gcdisc import dol_to_elf, ram_to_elf
from .registry import tool

# platform -> (cpu, Ghidra processor or None = let the ELF loader pick, ELF machine, big endian)
PLATFORM_CPU = {
    "gamecube": ("ppc", "PowerPC:BE:32:default", 20, True),
    "wii": ("ppc", "PowerPC:BE:32:default", 20, True),
    "dreamcast": ("sh4", "SuperH4:LE:32:default", 42, False),
    "psx": ("mips_le", "MIPS:LE:32:default", 8, False),
    "ps2": ("r5900", "MIPS:LE:64:64-32addr", 8, False),
    "n64": ("mips_be", "MIPS:BE:32:default", 8, True),
    "gba": ("arm", "ARM:LE:32:v4t", 40, False),
    "xbox360": ("ppc64", None, 20, True),      # Xenon: ELF loader's PowerPC:BE:32 default; VMX128 opcodes won't decode
    "xbox": ("x86", None, 3, False),         # Original Xbox: 32-bit little-endian x86
}
DC_BASE = 0x8C010000
GBA_BASE = 0x08000000


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def system_cnf_boot(text: str) -> str:
    """'BOOT = cdrom:\\SLUS_006.62;1' / 'BOOT2 = cdrom0:\\SLUS_214.23;1' -> 'SLUS_006.62' (upper case, no version)."""
    m = re.search(r"BOOT2?\s*=\s*cdrom0?:\\?\\?([^;\s]+)", text, re.I)
    if not m:
        raise ValueError("SYSTEM.CNF has no BOOT/BOOT2 line")
    return m.group(1).replace("\\", "/").lstrip("/").upper()


def psx_exe_to_elf(exe: bytes) -> tuple[bytes, dict]:
    """PS-X EXE: header 0x800 bytes (pc0 +0x10, gp0 +0x14, t_addr +0x18, t_size +0x1C), body loaded at t_addr."""
    if exe[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    pc0, gp0, t_addr, t_size = struct.unpack_from("<4I", exe, 0x10)
    body = exe[0x800:0x800 + t_size]
    info = {"base": t_addr, "entry": pc0, "size": len(body), "format": "PS-X EXE"}
    if gp0:
        info["registers"] = {"gp": f"0x{gp0:08X}"}
    return ram_to_elf(body, t_addr, pc0, 8, False), info


def n64_to_z64(rom: bytes) -> bytes:
    """Any N64 byte order -> big-endian .z64."""
    m = rom[:4]
    if m == b"\x80\x37\x12\x40":
        return rom
    if m == b"\x37\x80\x40\x12":                         # .v64: byte-swapped 16-bit
        return bytes(b for i in range(0, len(rom) - 1, 2) for b in (rom[i + 1], rom[i]))
    if m == b"\x40\x12\x37\x80":                         # .n64: little-endian 32-bit
        return b"".join(rom[i:i + 4][::-1] for i in range(0, len(rom) - 3, 4))
    raise ValueError("not an N64 ROM (bad header magic)")


def n64_boot_to_elf(z64: bytes) -> tuple[bytes, dict]:
    """libultra boot: 1 MiB from ROM 0x1000 is copied to the header's entry point (u32 BE at 0x08). Code that the game
    loads later from ROM (overlays, compressed segments) is NOT in it: use source=ram for those."""
    entry = struct.unpack_from(">I", z64, 8)[0]
    code = z64[0x1000:0x1000 + 0x100000]
    return ram_to_elf(code, entry, entry, 8, True), {"base": entry, "entry": entry, "size": len(code),
                                                      "format": "N64 boot segment"}


N64_RESET_WORD = 0x3C1A8000                              # 'lui k0, 0x8000': the exception vectors at 0x80000000


def fix_n64_ram(ram: bytes) -> tuple[bytes, bool]:
    """ParaLLEl N64 exposes RDRAM as little-endian 32-bit words: swap every word when the vectors read swapped."""
    be = struct.pack(">I", N64_RESET_WORD)
    head = ram[:0x200]
    if be in head:
        return ram, False
    if be[::-1] in head:
        n = len(ram) // 4 * 4
        return b"".join(ram[i:i + 4][::-1] for i in range(0, n, 4)) + ram[n:], True
    return ram, False


def ram_layout(platform: str) -> tuple[int, int]:
    """(base, size) of the platform's main RAM as the emulators' debuggers address it (tools.MAIN_RAM)."""
    from .tools import MAIN_RAM
    r = MAIN_RAM.get(platform)
    if not r:
        raise ValueError(f"no main-RAM layout for platform {platform!r}: pass ram_base and ram_size")
    return r[0][0], r[0][1]


def ram_to_image(platform: str, ram: bytes, base: int) -> tuple[bytes, dict]:
    cpu, proc, machine, be = PLATFORM_CPU.get(platform, (None, None, None, None))
    if machine is None:
        raise ValueError(f"no CPU mapping for platform {platform!r}")
    notes = []
    if platform == "n64":
        ram, swapped = fix_n64_ram(ram)
        if swapped:
            notes.append("RDRAM was word-swapped (ParaLLEl N64); fixed")
    entry = base + (0x400 if platform == "n64" else 0)
    return ram_to_elf(ram, base, entry, machine, be), {"base": base, "entry": entry, "size": len(ram),
                                                       "format": f"{platform} RAM image", "notes": notes}


# --- disc readers (read-only; unpacked images are cached where gBox's mod builders keep them) ---

def _gc_iso(cfg, game: dict, rom: Path, progress) -> Path:
    from . import filemods
    if rom.suffix.lower() in (".iso", ".gcm"):
        return rom
    if rom.suffix.lower() != ".gcz":
        raise ValueError(f"{rom.name}: GameCube images are read as ISO/GCM/GCZ (convert RVZ/WIA with Dolphin first)")
    base = filemods.base_dir(cfg, game["game_id"]) / (rom.stem + ".iso")   # shared with characters/_gc_iso
    if not base.exists():
        base.parent.mkdir(parents=True, exist_ok=True)
        progress(5, f"Unpacking {rom.name} (once per game)")
        filemods.gcz_to_iso(rom, base.with_suffix(".part"), lambda p, m: progress(5 + p * 0.3, m))
        base.with_suffix(".part").replace(base)
    return base


def _dc_gdi(cfg, game: dict, rom: Path, progress) -> Path:
    if rom.suffix.lower() == ".gdi":
        return rom
    d = Path(cfg.cache) / "dc" / game["game_id"]                         # shared with characters._dc_gdi
    if (d / "disc.gdi").exists():
        return d / "disc.gdi"
    if rom.suffix.lower() != ".chd" or not shutil.which("chdman"):
        raise ValueError(f"{rom.name}: reading a Dreamcast disc needs a GDI, or a CHD plus chdman on this node")
    tmp = d.with_name(d.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    progress(5, f"Unpacking the GD-ROM {rom.name} (chdman, once per game)")
    subprocess.run(["chdman", "extractcd", "-f", "-i", str(rom), "-o", str(tmp / "disc.gdi")], check=True,
                   capture_output=True, timeout=1800)
    shutil.rmtree(d, ignore_errors=True)
    tmp.rename(d)
    return d / "disc.gdi"


def _ps2_iso(cfg, game: dict, rom: Path, progress) -> Path:
    from . import filemods
    if rom.suffix.lower() == ".iso":
        return rom
    if rom.suffix.lower() == ".cso":                                      # CISO: decompressed once, cached
        from .cso import cached_iso
        return cached_iso(rom, filemods.base_dir(cfg, game["game_id"]) / (rom.stem + ".iso"),
                          lambda p, m: progress(5 + int(p * 40), m))
    if rom.suffix.lower() != ".chd":
        raise ValueError(f"{rom.name}: PS2 discs are read as .iso, .cso or .chd")
    from .gta_stories_models import lcs_iso_from_rom                      # chdman -> plain .iso, cached
    return lcs_iso_from_rom(rom, filemods.base_dir(cfg, game["game_id"]) / (rom.stem + ".iso"),
                            lambda p, m: progress(p, m))


def _iso_read(f, files: dict, name: str) -> bytes:
    _rec, lba, size = files[name.upper()]
    f.seek(lba * 2048)
    return f.read(size)


def _rom_bytes(rom: Path, exts: tuple[str, ...]) -> bytes:
    from . import rom_archives
    if rom_archives.is_archive(rom):
        entries = rom_archives.members(rom)
        choices = [e for e in entries if e['name'].lower().endswith(exts)]
        if not choices:
            raise ValueError(f'{rom.name}: no matching ROM member ({exts})')
        entry = max(choices, key=lambda e: e['size'])
        data = rom_archives.prefix(rom, entry['name'], entry['size'])
        if len(data) != entry['size']:
            raise ValueError(f"Incomplete archive member: {entry['name']}")
        return data
    return rom.read_bytes()


def extract_from_disc(cfg, game: dict, rom: Path, progress=lambda p, m: None) -> tuple[bytes, bytes, dict]:
    """-> (ELF bytes, the executable as stored on the disc/ROM, info)."""
    plat = game.get("platform") or ""
    if plat in ("gamecube",):
        from .gcdisc import GCDisc
        d = GCDisc(_gc_iso(cfg, game, rom, progress))
        dol = d.dol()
        entry = struct.unpack_from(">I", dol, 0xE0)[0]
        return dol_to_elf(dol), dol, {"source_file": "main.dol", "format": "GameCube DOL", "disc_id": d.game_id,
                                       "entry": entry, "base": min(a for a, s in zip(struct.unpack_from(">18I", dol, 0x48),
                                                                                    struct.unpack_from(">18I", dol, 0x90)) if s)}
    if plat == "dreamcast":
        from .gdrom import GDRom
        exe = GDRom(_dc_gdi(cfg, game, rom, progress)).read("1ST_READ.BIN")
        return ram_to_elf(exe, DC_BASE, DC_BASE, 42, False), exe, {"source_file": "1ST_READ.BIN", "format": "Dreamcast binary",
                                                                  "base": DC_BASE, "entry": DC_BASE}
    if plat == "psx":
        from .psxdisc import PSXDisc, RawBin
        disc = RawBin(rom, writable=False) if rom.suffix.lower() == ".bin" else PSXDisc(str(rom))
        name = system_cnf_boot(disc.read("SYSTEM.CNF").decode("latin-1"))
        exe = disc.read(name)
        elf, info = psx_exe_to_elf(exe)
        return elf, exe, info | {"source_file": name}
    if plat == "ps2":
        from .romexport import iso_files
        with open(_ps2_iso(cfg, game, rom, progress), "rb") as f:
            files = iso_files(f)
            name = system_cnf_boot(_iso_read(f, files, "SYSTEM.CNF").decode("latin-1"))
            exe = _iso_read(f, files, name)
        if exe[:4] != b"\x7fELF":
            raise ValueError(f"{name} is not an ELF")
        entry = struct.unpack_from("<I", exe, 0x18)[0]
        return exe, exe, {"source_file": name, "format": "PS2 ELF", "entry": entry}
    if plat == "n64":
        z64 = n64_to_z64(_rom_bytes(rom, (".z64", ".n64", ".v64")))
        elf, info = n64_boot_to_elf(z64)
        return elf, z64, info | {"source_file": rom.name, "disc_id": z64[0x3B:0x3F].decode("latin-1", "replace")}
    if plat == "gba":
        data = _rom_bytes(rom, (".gba",))
        return ram_to_elf(data, GBA_BASE, GBA_BASE, 40, False), data, {"source_file": rom.name, "format": "GBA ROM",
                                                                      "base": GBA_BASE, "entry": GBA_BASE}
    if plat == "xbox360":
        from .re6 import XDVD, xex_image
        x = XDVD(rom)
        try:
            xex = x.read("default.xex")
        finally:
            x.close()
        im = xex_image(xex)
        return ram_to_elf(im["image"], im["base"], im["entry"] or im["base"], 20, True), xex, {
            "source_file": "default.xex", "format": "XEX2 -> PE image", "base": im["base"], "entry": im["entry"],
            "notes": ["Xenon VMX128 opcodes don't decode in Ghidra's PowerPC; function starts come from auto-analysis "
                      "only (Xbox360Pdata.java needs a raw import, not available through ghidra_script)"]}
    raise ValueError(f"no executable reader for platform {plat!r}: use source=ram with a running session "
                     "(or path=<an extracted executable the worker can read>)")


# --- the tool ---

class ExeIn(BaseModel):
    game_id: str
    source: str = "auto"                   # auto | disc | ram | path
    session_id: str = ""                   # source=ram: the running session to snapshot
    path: str = ""                         # source=path: an executable file this worker can read
    ram_base: int | None = None            # source=ram: override the platform's main RAM range
    ram_size: int | None = None


class ExeOut(BaseModel):
    game_id: str
    title: str
    platform: str
    source: str
    source_file: str
    format: str
    cpu: str | None
    processor: str | None
    elf_path: str                          # absolute path on THIS worker
    rel: str                               # path relative to <data_dir>/analysis (same on every node that shares it)
    base: str | None
    entry: str | None
    size: int
    sha256: str                            # of the ELF Ghidra imports
    source_sha256: str                     # of the executable as stored on the disc / in RAM
    disc_id: str = ""
    registers: dict = {}
    notes: list[str] = []
    session_id: str = ""
    mod: str = ""
    worker_id: str = ""                    # owner of the live game, not the analysis worker
    snapshot_started_at: float | None = None
    snapshot_finished_at: float | None = None
    revision: dict = {}                     # RAM snapshot fingerprint, never a catalog/disc executable hash


def _api(ctx, method, path, **kw):
    import httpx
    if not ctx.server:
        raise RuntimeError("no control plane connection on this worker")
    r = httpx.request(method, ctx.server + path, headers=ctx.headers, timeout=kw.pop("timeout", 30), **kw)
    r.raise_for_status()
    return r.json()


def _ram_snapshot(ctx, sid: str, base: int, size: int) -> bytes:
    out = bytearray()
    step = 0x100000
    for o in range(0, size, step):
        n = min(step, size - o)
        h = _api(ctx, "POST", f"/api/sessions/{quote(sid, safe='')}/rpc", json={"op": "read_memory", "args": {"address": base + o,
                                                                                                "length": n}}, timeout=60)
        text = h if isinstance(h, str) else h.get("hex") if isinstance(h, dict) else None
        if not isinstance(text, str):
            raise ValueError("The selected session did not return a RAM byte payload")
        chunk = bytes.fromhex(text)
        if len(chunk) != n:
            raise ValueError(f"Incomplete RAM snapshot: requested {n} bytes at {base + o:#x}, received {len(chunk)}")
        out += chunk
        ctx.progress(10 + 70 * (o + n) / size, f"read {(o + n) >> 20} of {size >> 20} MiB of RAM")
    return bytes(out)


def _live_ram_target(ctx, game: dict, sid: str) -> dict:
    """Authenticate the exact ledger row and the worker's current session info."""
    from .live_request import bind_target
    sessions = _api(ctx, "GET", "/api/sessions")
    if not isinstance(sessions, list):
        raise ValueError("The control plane did not return a session inventory")
    target = bind_target({"session_id": sid, "game_id": game["game_id"]}, sessions)
    row = next(item for item in sessions if isinstance(item, dict) and item.get("session_id") == sid)
    if row.get("stopping"):
        raise ValueError("The selected session is stopping; no RAM was read")
    info = _api(ctx, "POST", f"/api/sessions/{quote(sid, safe='')}/rpc", json={"op": "info"})
    if not isinstance(info, dict) or info.get("game_id") != game["game_id"]:
        raise ValueError("The live worker's session belongs to a different game; no RAM was accepted")
    platform = info.get("platform")
    if platform != game.get("platform") or (row.get("platform") and row["platform"] != platform):
        raise ValueError("The live session platform does not match the requested game's RAM layout")
    if platform not in PLATFORM_CPU:
        raise ValueError(f"No verified CPU mapping for live platform {platform!r}")
    runtime = info.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("running") is not True:
        raise ValueError("The selected session's emulator is no longer running")
    capabilities = info.get("capabilities")
    if not isinstance(capabilities, dict) or capabilities.get("read_memory") != "supported":
        raise ValueError("The selected live session does not support RAM reads")
    if row.get("adapter") and info.get("emulator") != row["adapter"]:
        raise ValueError("The live session emulator changed; no RAM was accepted")
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    collection_mod = row.get("collection_mod") or target["mod"]
    actual_mod = row.get("launch_mod") or row.get("staged_mod") or detail.get("mod") or target["mod"]
    if not isinstance(collection_mod, str) or not isinstance(actual_mod, str):
        raise ValueError("The selected session has an invalid build identity")
    if "mod" in info and info["mod"] != actual_mod:
        raise ValueError("The live session build changed; no RAM was accepted")
    return target | {"platform": platform, "core": info.get("core"), "emulator": info.get("emulator"),
                     "rom": info.get("rom"), "actual_mod": actual_mod, "collection_mod": collection_mod,
                     "started": row.get("started"), "pid": runtime.get("pid") or detail.get("pid"),
                     "runtime_content": runtime.get("content")}


def _live_ram_range(inp: ExeIn, platform: str) -> tuple[int, int]:
    from .tools import MAIN_RAM
    ranges = MAIN_RAM.get(platform)
    if not ranges:
        raise ValueError(f"No verified main-RAM layout for live platform {platform!r}")
    if (inp.ram_base is None) != (inp.ram_size is None):
        raise ValueError("ram_base and ram_size must be supplied together")
    base, size = (inp.ram_base, inp.ram_size) if inp.ram_base is not None else ranges[0]
    if size <= 0 or not any(lo <= base and base + size <= lo + length for lo, length in ranges):
        raise ValueError("Requested RAM range is outside the verified live platform layout")
    return base, size


def analysis_root(cfg) -> Path:
    return (Path(cfg.data_dir) / "analysis").resolve()


def _validate(out: ExeOut, arts) -> list[str]:
    d = arts.get("exe_info.json")
    if not d:
        return ["exe_info.json missing"]
    info = json.loads(d)
    fields = ("game_id", "source", "sha256", "rel")
    if out.source == "ram":
        fields += ("source_sha256", "session_id", "mod", "worker_id", "platform", "revision",
                   "snapshot_started_at", "snapshot_finished_at")
    return [] if all(info.get(key) == getattr(out, key) for key in fields) else ["exe_info.json does not match the output"]


@tool("re_executable", "1.1", ExeIn, ExeOut, capabilities=["analysis"], timeout_s=3600, artifacts=["exe_info.json"],
      side_effects=["writes <data_dir>/analysis/re/<game_id>/*.elf", "may unpack a disc image once into the cache"],
      validate=_validate, validation="exe_info.json matches the ELF hash, path and live-session provenance")
def re_executable(inp: ExeIn, ctx):
    """Extract a title's main executable (or a live RAM image) as an ELF that Ghidra imports at the right address."""
    from .models import CatalogEntry
    from .tools import rom_path
    game = _api(ctx, "GET", f"/api/catalog/{inp.game_id}")
    if game.get("game_id") != inp.game_id:
        raise ValueError("The catalog response does not match the requested game")
    plat = game.get("platform") or ""
    cpu, proc, _m, _be = PLATFORM_CPU.get(plat, (None, None, None, None))
    src = inp.source if inp.source in ("disc", "ram", "path") else ("path" if inp.path else "disc")
    notes: list[str] = []
    live, revision = {}, {}
    snapshot_started_at = snapshot_finished_at = None
    ctx.progress(2, f"{game['title']}: reading the executable ({src})")
    if src == "disc":
        try:
            rom = rom_path(CatalogEntry.model_validate(game), ctx.config)
            if not rom.exists():
                raise FileNotFoundError(f"{game['title']}: {rom} isn't readable on this node")
            elf, raw, info = extract_from_disc(ctx.config, game, rom, ctx.progress)
            notes += info.pop("notes", [])
        except Exception as e:                       # noqa: BLE001
            if inp.source != "auto" or not inp.session_id:
                raise
            notes.append(f"disc route failed ({type(e).__name__}: {e}); used the live RAM instead")
            src = "ram"
    if src == "path":
        p = Path(inp.path)
        raw = p.read_bytes()
        if raw[:4] == b"\x7fELF":
            elf, info = raw, {"format": "ELF", "entry": struct.unpack_from(">I" if raw[5] == 2 else "<I", raw, 0x18)[0]}
        elif raw[:8] == b"PS-X EXE":
            elf, info = psx_exe_to_elf(raw)
        elif plat == "gamecube" or plat == "wii":
            elf, info = dol_to_elf(raw), {"format": "DOL", "entry": struct.unpack_from(">I", raw, 0xE0)[0]}
        else:
            raise ValueError(f"{p.name}: give an ELF, a PS-X EXE or a DOL (raw images: use source=ram or a disc)")
        info["source_file"] = p.name
    elif src == "ram":
        if not inp.session_id:
            raise ValueError("source=ram needs session_id (a running session of this game)")
        live = _live_ram_target(ctx, game, inp.session_id)
        plat = live["platform"]
        cpu, proc, _m, _be = PLATFORM_CPU[plat]
        base, size = _live_ram_range(inp, plat)
        snapshot_started_at = time.time()
        raw = _ram_snapshot(ctx, inp.session_id, base, size)
        snapshot_finished_at = time.time()
        if _live_ram_target(ctx, game, inp.session_id) != live:
            raise ValueError("The selected session/build changed while reading RAM; the snapshot was discarded")
        elf, info = ram_to_image(plat, raw, base)
        info["source_file"] = f"RAM {base:#x}+{size:#x} of session {inp.session_id}"
        notes += info.pop("notes", [])
        notes.append("RAM image includes heap and stack. Reads are non-atomic: in-game state can change between chunks. "
                     "The RAM hash identifies this snapshot, not an immutable executable or the catalog's base disc.")
        revision = live | {"kind": "ram_snapshot", "sha256": sha(raw), "base": base, "size": size,
                           "atomic": False, "snapshot_started_at": snapshot_started_at,
                           "snapshot_finished_at": snapshot_finished_at}
    d = analysis_root(ctx.config) / "re" / inp.game_id
    d.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(info.get("source_file") or "exe").name)[:40] if src != "ram" else \
        f"ram_{sha(elf)}"
    out = d / f"{stem}.elf"
    out.write_bytes(elf)
    regs = dict(info.get("registers") or {})
    res = {"game_id": inp.game_id, "title": game["title"], "platform": plat, "source": src,
           "source_file": info.get("source_file", ""), "format": info.get("format", ""), "cpu": cpu, "processor": proc,
           "elf_path": str(out), "rel": out.relative_to(analysis_root(ctx.config)).as_posix(),
           "base": f"0x{info['base']:08X}" if info.get("base") is not None else None,
           "entry": f"0x{info['entry']:08X}" if info.get("entry") is not None else None,
           "size": int(info.get("size") or len(raw)), "sha256": sha(elf), "source_sha256": sha(raw),
           "disc_id": info.get("disc_id", ""), "registers": regs, "notes": notes,
           "session_id": live.get("session_id", ""), "mod": live.get("mod", ""),
           "worker_id": live.get("worker_id", ""), "revision": revision,
           "snapshot_started_at": snapshot_started_at, "snapshot_finished_at": snapshot_finished_at}
    ctx.artifact("exe_info.json", json.dumps(res, indent=1).encode(), "application/json", game_id=inp.game_id,
                 session_id=res["session_id"], mod=res["mod"], worker_id=res["worker_id"],
                 source_sha256=res["source_sha256"], revision=revision)
    ctx.progress(100, f"{res['source_file']} -> {res['rel']}")
    return res
