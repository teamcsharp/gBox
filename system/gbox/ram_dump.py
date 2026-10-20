"""ram_dump: a live session's main RAM as one gzip artifact with a small JSON header, read without holding the game.

Autoplay coaching notes attach one per note (gbox.coaching); Ghidra / REA load it as a raw binary at its base address.

Format (ram.gz, gzip). Unpacked, the first header_size bytes (4096, or the next multiple of 4096 when the JSON is
longer) are one line of JSON padded with spaces and ended by a newline; each region's bytes follow at its "offset":
  {"format": "gbox-ram-dump/1", "header_size": 4096, "platform": "gamecube", "big_endian": true,
   "base": 2147483648, "base_hex": "0x80000000", "length": 25165824, "sha256": "<sha256 of every region's bytes>",
   "regions": [{"name": "MEM1", "base": ..., "base_hex": "0x80000000", "length": ..., "offset": 4096,
                "sha256": ..., "complete": true}],
   "partial": false, "missing": [], "source": "...", "read_s": 0.04, "disc_id": "G4BE08", ...}
Ghidra: gunzip, import as Raw Binary with the region's base_hex as base address and its offset as file offset.

Which RAM: the adapter's own regions() when it has one (Xenia), else gbox.tools.MAIN_RAM, the main RAM as the
emulators' debuggers address it: GameCube MEM1 24 MiB at 0x80000000 (Wii also MEM2 64 MiB at 0x90000000), Dreamcast /
NAOMI 16 MiB at 0x8C000000, N64 RDRAM 8 MiB at 0x80000000 (ParaLLEl's word-swapped RDRAM put back in order), PS1 2 MiB
at 0x80000000, PS2 EE 32 MiB, GBA EWRAM + IWRAM, NDS 4 MiB. At most MAX_BYTES. Any other platform: Unsupported.
How, quickest first, so the game is never held for long:
  * Dolphin on Linux (the Spark's flatpak): the shared-memory RAM views of this session's own Dolphin process, read
    through /proc/<pid>/mem in one go: no halt, a few milliseconds (the RE4 Mercenaries bot reads RAM the same way).
  * anything else (Windows Dolphin's process memory, RetroArch's network commands at ~1 MiB/s, Xenia): the adapter's
    read_memory in 1 MiB pieces; through a GDB stub (which halts the CPU while it answers) in 128 KiB pieces with a
    short pause between, so the game keeps running.
  * budget_s bounds the whole read: whatever is left is listed in "missing" and the dump is marked partial.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import zlib
from pathlib import Path

from pydantic import BaseModel, Field

from .registry import HOST_OS, Unsupported, tool

FORMAT = "gbox-ram-dump/1"
HEADER = 4096
MAX_BYTES = 96 << 20                          # Wii MEM1 + MEM2 fit; artifacts travel inline (base64) with the result
CHUNK, GDB_CHUNK, GDB_GAP_S = 1 << 20, 1 << 17, 0.03   # a GDB stub halts the CPU per read: short halts, play between
LEVEL = 3                                     # gzip level: GameCube MEM1 in well under a second
NAMES = {"gamecube": ["MEM1"], "wii": ["MEM1", "MEM2"], "dreamcast": ["main RAM"], "naomi": ["main RAM"],
         "n64": ["RDRAM"], "n64dd": ["RDRAM"], "psx": ["main RAM"], "ps2": ["EE RAM"], "gba": ["EWRAM", "IWRAM"],
         "nds": ["main RAM"]}
SHM_SIZES = {0x80000000: 0x2000000, 0x90000000: 0x4000000}   # Dolphin's MEM1 / MEM2 views (whole 32 / 64 MiB)


class RamDumpIn(BaseModel):
    session_id: str
    budget_s: float = Field(default=10.0, ge=0.5, le=60.0)    # stop reading after this long (a partial dump)


class RamDumpOut(BaseModel):
    result: dict


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --- the format -------------------------------------------------------------------------------------------------------
def header_block(meta: dict, lengths: list[int]) -> tuple[bytes, dict]:
    """The padded header for meta (its regions get their offsets) -> (bytes, meta as written)."""
    size = HEADER
    while True:
        meta = dict(meta, header_size=size)
        offset, regions = size, []
        for r, n in zip(meta.get("regions") or [], lengths):
            regions.append(dict(r, offset=offset))
            offset += n
        meta["regions"] = regions
        text = json.dumps(meta, separators=(",", ":")).encode()
        if len(text) < size:
            return text + b" " * (size - 1 - len(text)) + b"\n", meta
        size += HEADER


def read_header(blob: bytes) -> dict:
    """The JSON header of a ram.gz, unpacking only as much as it takes."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    head, rest = b"", blob
    for _ in range(256):                                   # at most 1 MiB of header
        more = d.decompress(rest, HEADER)
        rest = d.unconsumed_tail
        head += more
        if b"\n" in head or not (more or rest):
            break
    if b"\n" not in head or not head.startswith(b"{"):
        raise ValueError("not a gBox RAM dump (no JSON header line)")
    meta = json.loads(head.split(b"\n", 1)[0])
    if meta.get("format") != FORMAT:
        raise ValueError(f"unknown RAM dump format {meta.get('format')!r}")
    return meta


def load(blob: bytes) -> tuple[dict, list[tuple[dict, bytes]]]:
    """(header, [(region, bytes)]) of a ram.gz."""
    import gzip
    raw = gzip.decompress(blob)
    meta = json.loads(raw[:raw.index(b"\n")])
    if meta.get("format") != FORMAT:
        raise ValueError(f"unknown RAM dump format {meta.get('format')!r}")
    return meta, [(r, raw[r["offset"]:r["offset"] + r["length"]]) for r in meta.get("regions") or []]


def _validate(out: RamDumpOut, arts) -> list[str]:
    blob = arts.get("ram.gz")
    if not blob:
        return ["ram.gz missing"]
    try:
        meta = read_header(blob)
    except (ValueError, zlib.error) as e:
        return [f"ram.gz header unreadable: {e}"]
    res = out.result
    if (meta.get("sha256"), meta.get("length")) != (res.get("sha256"), res.get("length")) or res.get("artifact") != _sha(blob):
        return ["ram.gz header does not match the reported RAM"]
    return []


# --- what to read -----------------------------------------------------------------------------------------------------
def regions_for(ad, platform: str) -> tuple[list[tuple[str, int, int]], list[list[int]]]:
    """([(name, base, size)] of the session's main RAM, at most MAX_BYTES in all; [[base, size]] left out by that cap)."""
    rs: list[tuple[str, int, int]] = []
    own = getattr(ad, "regions", None)
    if callable(own):
        try:
            rs = [(f"region {i}", int(a), int(n)) for i, (a, n) in enumerate(own())]
        except Exception:                            # noqa: BLE001 - an adapter that can't list them: the table
            rs = []
    if not rs:
        from .tools import MAIN_RAM
        names = NAMES.get(platform) or []
        rs = [(names[i] if i < len(names) else f"region {i}", int(a), int(n))
              for i, (a, n) in enumerate(MAIN_RAM.get(platform) or [])]
    if not rs:
        raise Unsupported(f"no main-RAM layout for platform {platform or '?'}")
    out, capped, total = [], [], 0
    for name, base, size in rs:
        keep = max(0, min(size, MAX_BYTES - total))
        if keep:
            out.append((name, base, keep))
            total += keep
        if keep < size:
            capped.append([base + keep, size - keep])
    return out, capped


# --- Dolphin's shared RAM on Linux --------------------------------------------------------------------------------------
def _children() -> dict[int, list[int]]:
    kids: dict[int, list[int]] = {}
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            stat = Path(f"/proc/{p}/stat").read_text()
            ppid = int(stat.rsplit(")", 1)[1].split()[1])      # pid (comm) state ppid ...
        except (OSError, IndexError, ValueError):
            continue
        kids.setdefault(ppid, []).append(int(p))
    return kids


def _descendants(pid: int) -> list[int]:
    kids, out, todo = _children(), [], [pid]
    while todo:
        for c in kids.get(todo.pop(), []):
            if c not in out:
                out.append(c)
                todo.append(c)
    return out


def _views(pid: int) -> list[tuple[int, int, int]]:
    """(host address, size, file offset) of every dolphin-emu shared-memory mapping in a process."""
    try:
        maps = Path(f"/proc/{pid}/maps").read_text()
    except OSError:
        return []
    out = []
    for line in maps.splitlines():
        if "dolphin-emu" not in line or ("/dev/shm/" not in line and "memfd:" not in line):
            continue
        parts = line.split()
        try:
            a, b = (int(x, 16) for x in parts[0].split("-"))
            out.append((a, b - a, int(parts[2], 16)))
        except (IndexError, ValueError):
            continue
    return out


class ShmRam:
    """This Dolphin's MEM1 (and Wii MEM2) views, read through /proc/<pid>/mem: no halt, the whole region at once."""

    def __init__(self, pid: int, hosts: dict[int, int]):
        self.pid, self.hosts = pid, hosts                       # region base -> host address of its view
        self.fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)

    @classmethod
    def find(cls, ad) -> "ShmRam | None":
        if HOST_OS != "linux" or getattr(ad, "name", "") != "dolphin":
            return None
        pid = getattr(getattr(ad, "proc", None), "pid", None)
        return cls.find_pid(int(pid)) if pid else None

    @classmethod
    def find_pid(cls, pid: int) -> "ShmRam | None":
        """The RAM views of the Dolphin that is pid or runs under it (the RAM inspector also starts from a pid)."""
        if HOST_OS != "linux":
            return None
        for p in [pid, *_descendants(pid)]:                     # flatpak run -> bwrap -> dolphin-emu: this session's
            views = _views(p)
            hosts = {}
            for base, size in SHM_SIZES.items():
                view = next((a for a, n, off in views if n == size and (off == 0 or base != 0x80000000)), None)
                if view is not None:
                    hosts[base] = view
            if 0x80000000 not in hosts:
                continue
            try:
                ram = cls(p, hosts)
            except OSError:                                     # not ours to read (another user, ptrace scope)
                continue
            try:
                gid = ram.read(0x80000000, 6)
            except OSError:
                gid = b""
            if gid[:4].isalnum() and gid[:1].isalpha():         # MEM1 starts with the game id (DolphinProcMem._find)
                return ram
            ram.close()
        return None

    def read(self, address: int, n: int) -> bytes:
        base = next((b for b in self.hosts if b <= address and address + n <= b + SHM_SIZES[b]), None)
        if base is None:
            raise ValueError(f"{address:#x}+{n:#x} is outside this Dolphin's RAM views")
        host, out = self.hosts[base] + (address - base), bytearray()
        while len(out) < n:
            got = os.pread(self.fd, n - len(out), host + len(out))
            if not got:
                break
            out += got
        return bytes(out)

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


# --- reading -----------------------------------------------------------------------------------------------------------
def _halting(ad) -> bool:
    """Memory reads go through a GDB stub that stops the emulated CPU while it answers."""
    return type(getattr(ad, "dbg", None)).__name__ == "GdbDebugger"


def read_regions(read, regions, *, chunk: int, gap_s: float, budget_s: float, clock=time.monotonic,
                 sleep=time.sleep) -> list[dict]:
    """Each region read in chunks until it is complete, a read fails or the budget is spent."""
    t0, out = clock(), []
    for name, base, size in regions:
        buf, error = bytearray(), None
        while len(buf) < size:
            if clock() - t0 > budget_s:
                error = f"stopped after {budget_s:g} s (budget)"
                break
            n = min(chunk, size - len(buf))
            try:
                got = bytes(read(base + len(buf), n))
            except Exception as e:                       # noqa: BLE001 - unmapped / emulator busy: what was read stays
                error = f"{type(e).__name__}: {e}"[:300]
                break
            buf += got[:n]
            if len(got) < n:
                error = f"short read at {base + len(buf):#x}"
                break
            if gap_s and len(buf) < size:
                sleep(gap_s)                             # the halted CPU runs again between pieces
        out.append({"name": name, "base": base, "size": size, "data": bytes(buf), "error": error})
    return out


def dump(ad, g: dict, sid: str = "", *, budget_s: float = 10.0, clock=time.monotonic, sleep=time.sleep) -> tuple[bytes, dict]:
    """(ram.gz bytes, header) of the session's main RAM right now."""
    platform = str(g.get("platform") or getattr(ad, "platform", "") or "")
    regions, capped = regions_for(ad, platform)
    t0 = clock()
    shm = ShmRam.find(ad)
    try:
        if shm is not None:
            source = f"Dolphin shared memory (/proc/{shm.pid}/mem, no halt)"
            got = read_regions(shm.read, regions, chunk=max(s for _, _, s in regions), gap_s=0,
                               budget_s=budget_s, clock=clock, sleep=sleep)
            if any(r["error"] for r in got):             # a view we could not read: the adapter's way instead
                shm.close()
                shm = None
        if shm is None:
            halting = _halting(ad)
            source = "adapter read_memory" + (" through the GDB stub (128 KiB per halt)" if halting else "")
            got = read_regions(ad.read_memory, regions, chunk=GDB_CHUNK if halting else CHUNK,
                               gap_s=GDB_GAP_S if halting else 0, budget_s=budget_s, clock=clock, sleep=sleep)
    finally:
        if shm is not None:
            shm.close()
    read_s = round(clock() - t0, 3)
    if not any(r["data"] for r in got):
        raise RuntimeError("no RAM could be read: " + "; ".join(f"{r['name']}: {r['error']}" for r in got))
    notes = []
    if platform in ("n64", "n64dd") and len(got[0]["data"]) >= 0x400:
        try:
            from .pick_ram import fix_n64                # ParaLLEl's RDRAM reads as little-endian words
            got[0]["data"], swapped = fix_n64(got[0]["data"])
            if swapped:
                notes.append("RDRAM was word-swapped (ParaLLEl N64): put back in big-endian order")
        except ImportError:
            notes.append("RDRAM word order not checked (numpy missing)")
    got = [r for r in got if r["data"]]
    data = b"".join(r["data"] for r in got)
    mem = got[0]["data"] if got[0]["base"] == 0x80000000 else b""
    disc = mem[:6].decode("ascii") if platform in ("gamecube", "wii") and mem[:6].isalnum() else None
    from .tools import BIG_ENDIAN
    missing = [[r["base"] + len(r["data"]), r["size"] - len(r["data"])] for r in got if len(r["data"]) < r["size"]]
    missing += [[base, size] for _, base, size in regions if base not in {r["base"] for r in got}]
    missing += capped                                    # past MAX_BYTES (Xenia's guest regions)
    if capped:
        notes.append(f"only the first {MAX_BYTES >> 20} MiB of the regions were dumped")
    meta = {"format": FORMAT, "platform": platform, "big_endian": platform in BIG_ENDIAN,
            "base": got[0]["base"], "base_hex": f"{got[0]['base']:#010x}", "length": len(data), "sha256": _sha(data),
            "regions": [{"name": r["name"], "base": r["base"], "base_hex": f"{r['base']:#010x}", "length": len(r["data"]),
                         "sha256": _sha(r["data"]), "complete": len(r["data"]) == r["size"],
                         **({"error": r["error"]} if r["error"] else {})} for r in got],
            "partial": bool(missing), "missing": [[a, n] for a, n in missing],
            "source": source, "read_s": read_s, "session_id": sid, "game_id": g.get("game_id"),
            "title": g.get("title"), "disc_id": disc, "notes": notes, "captured_at": round(time.time(), 3)}
    head, meta = header_block(meta, [len(r["data"]) for r in got])
    z = zlib.compressobj(LEVEL, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    blob = z.compress(head) + b"".join(z.compress(r["data"]) for r in got) + z.flush()
    return blob, meta


@tool("ram_dump", "1.0", RamDumpIn, RamDumpOut, capabilities=["runtime", "memory"], artifacts=["ram.gz"],
      validate=_validate, validation="gzip JSON header matches the reported RAM length/sha256", timeout_s=120)
def ram_dump(inp: RamDumpIn, ctx):
    """A live session's main RAM (MAIN_RAM layout) as one gzip artifact with a JSON header (platform, base address,
    length, sha256, regions): Dolphin on Linux through its shared-memory view (no halt), else the adapter's reads in
    pieces; budget_s bounds it (a partial dump says what is missing)."""
    from .tools import SESSIONS
    session = SESSIONS.get(inp.session_id)
    if session is None:
        raise Unsupported("This session ended. Open the running game to dump its RAM.")
    ad, g = session
    blob, meta = dump(ad, g, inp.session_id, budget_s=inp.budget_s)
    ctx.artifact("ram.gz", blob, "application/gzip", session=inp.session_id, game=g.get("game_id"),
                 platform=meta["platform"], base=meta["base_hex"], length=meta["length"], ram_sha256=meta["sha256"],
                 partial=meta["partial"], format=FORMAT)
    keep = ("format", "platform", "big_endian", "base", "base_hex", "length", "sha256", "regions", "partial", "missing",
            "source", "read_s", "disc_id", "notes", "header_size")
    return {"result": {"artifact": _sha(blob), "bytes": len(blob), "name": "ram.gz", **{k: meta[k] for k in keep}}}
