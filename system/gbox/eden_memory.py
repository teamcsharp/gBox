"""Eden's guest memory seen from the host (Linux): where a Switch game's RAM lives inside the emulator process.

Eden (yuzu's continuation) backs guest RAM with one memfd named "HostMemory" and reserves one arena of host address
space for the guest's 39-bit view (src/common/host_memory.cpp, read 2026-10-26): on arm64 ChooseVirtualBase() places
the arena at a random 2 MiB-aligned address between 2^36 and 2^39 (PROT_READ|PROT_WRITE, MAP_NORESERVE; 1<<38 bytes
with NCE built in, src/core/device_memory.cpp), and every guest page the emulated kernel maps is an mmap of that memfd
MAP_FIXED inside the arena. So /proc/<pid>/maps shows the arena as anonymous rows with "/memfd:HostMemory (deleted)"
rows carved into them, and only once a game boots (DeviceMemory is created at boot): the arena doubles as the
readiness signal, the way gbox.adapters.rpcs3_guest_base's reservation does for RPCS3.

Two address modes:
  direct  NCE (native code execution: the game's ARM64 code runs on the ARM64 host). Eden calls
          EnableDirectMappedAddress(), which sets virtual_base to null and clamps mappings to the arena, and the
          fault handler (src/core/arm/nce/arm_nce.cpp) uses the host fault address as the guest address: a guest
          address IS the host address, so the game lives at addresses inside the arena.
  offset  Dynarmic (JIT): host = arena start aligned up to 2 MiB + guest address (HostMemory::virtual_base).
The mode follows the cpu_backend gBox wrote for the launch. A read or write is refused unless its host range lies in a
HostMemory row, so a wrong mode never hands back another mapping's bytes. The first live run on the Spark still has
to confirm this against the GDB stub (docs/research/switch-emulator-spark.md).

Direct mode accepts any HostMemory row, not only the rows of the walk around the first one: every such row maps the
guest's memfd, so it is guest memory wherever it sits. The walk (guest_arena's lo/hi) can stop short of the heap. Live
2026-10-27, Citron NEO's RE5 session (2,325 HostMemory rows, heap rows 0x5d2b800000-0x5df5000000): the turn's first
round made 3 mod writes where earlier turns made about 150 a round, and logged "Switch address 0x5d47d71aa8 is outside
the guest arena (direct mode)" for fire_rate's time scale on the player, while the reads, which go to /proc/<pid>/mem
directly, saw the player. A map read after the turn walked the whole 256 GiB reservation, so the break comes and goes.
Likely causes: Eden's Protect() mprotects whole ranges, so an anonymous placeholder row in one gets perms outside
ARENA_PERMS; and a 3,000-row maps file is read in pieces while rows split and merge. Offset mode keeps the arena
check, because there the arena's start is the address base.
"""
from __future__ import annotations

import bisect
import os
import platform

HOSTMEM = "/memfd:HostMemory"
HUGE_PAGE = 0x200000                           # HostMemory aligns virtual_base up to this (L2 block)
ARENA_PERMS = {"rw-p", "---p"}                 # the reservation: PROT_READ|PROT_WRITE on Linux, PROT_NONE on older builds


def parse_maps(lines) -> list[dict]:
    """/proc/<pid>/maps rows -> [{start, end, perms, path}] (path "" for anonymous memory)."""
    out = []
    for ln in lines:
        parts = ln.split(None, 5)
        if len(parts) < 5:
            continue
        try:
            a, b = (int(x, 16) for x in parts[0].split("-"))
        except ValueError:
            continue
        out.append({"start": a, "end": b, "perms": parts[1], "path": parts[5].strip() if len(parts) > 5 else ""})
    return out


def _arena_row(row: dict) -> bool:
    return row["path"].startswith(HOSTMEM) or (row["path"] == "" and row["perms"] in ARENA_PERMS)


def guest_arena(lines) -> dict | None:
    """The HostMemory arena: {lo, hi, base, mapped: [(start, end, perms)], rows: [(start, end, perms)]} from the rows
    around the first memfd row (adjacent anonymous reservation rows and memfd rows, nothing with another path), or None
    before a game boots. `mapped` holds the memfd rows of that walk (regions(), offset mode), `rows` every memfd row of
    the process, sorted (direct mode)."""
    rows = parse_maps(lines)
    first = next((i for i, r in enumerate(rows) if r["path"].startswith(HOSTMEM)), None)
    if first is None:
        return None
    lo_i = hi_i = first
    while lo_i > 0 and rows[lo_i - 1]["end"] == rows[lo_i]["start"] and _arena_row(rows[lo_i - 1]):
        lo_i -= 1
    while hi_i + 1 < len(rows) and rows[hi_i + 1]["start"] == rows[hi_i]["end"] and _arena_row(rows[hi_i + 1]):
        hi_i += 1
    lo, hi = rows[lo_i]["start"], rows[hi_i]["end"]
    mapped = [(r["start"], r["end"], r["perms"]) for r in rows[lo_i:hi_i + 1] if r["path"].startswith(HOSTMEM)]
    every = sorted((r["start"], r["end"], r["perms"]) for r in rows if r["path"].startswith(HOSTMEM))
    return {"lo": lo, "hi": hi, "base": -(-lo // HUGE_PAGE) * HUGE_PAGE, "mapped": mapped, "rows": every}


def mode_for(nce: bool) -> str:
    return "direct" if nce else "offset"


def nce_capable(machine: str | None = None, pagesize: int | None = None) -> bool:
    """Eden compiles NCE for Linux arm64 and enables it only with 4 KiB pages (Settings::IsFastmemEnabled)."""
    machine = (machine or platform.machine()).lower()
    if pagesize is None:
        try:
            pagesize = os.sysconf("SC_PAGESIZE")
        except (AttributeError, ValueError, OSError):
            pagesize = 4096
    return machine in ("aarch64", "arm64") and pagesize == 4096


def _row(arena: dict, host: int) -> tuple[int, int, str] | None:
    """The HostMemory row (start, end, perms) that holds `host`, any of the process's (rows are sorted, one bisect)."""
    rows = arena.get("rows", arena["mapped"])
    i = bisect.bisect_right(rows, (host, float("inf"))) - 1
    return rows[i] if i >= 0 and rows[i][0] <= host < rows[i][1] else None


def host_address(arena: dict, address: int, mode: str) -> int:
    """The host address of a guest address in this arena, or ValueError when it cannot be in the guest at all. Direct
    mode also takes an address in any HostMemory row outside the walk's lo/hi (module docstring)."""
    if mode == "direct":
        host = address
        if not arena["lo"] <= host < arena["hi"] and _row(arena, host) is None:
            raise ValueError(f"Switch address {address:#x} is outside the guest arena ({mode} mode)")
        return host
    if mode == "offset":
        host = arena["base"] + address
    else:
        raise ValueError(f"unknown address mode {mode!r}")
    if not arena["lo"] <= host < arena["hi"]:
        raise ValueError(f"Switch address {address:#x} is outside the guest arena ({mode} mode)")
    return host


def mapped(arena: dict, host: int, length: int, perm: str | None = "r") -> bool:
    """Whether [host, host+length) lies in one HostMemory row (with `perm` in its flags when given). Any row of the
    process: in offset mode host_address has already kept `host` inside lo/hi, and every memfd row there is the walk's."""
    row = _row(arena, host)
    return row is not None and host + length <= row[1] and (perm is None or perm in row[2])


def guest_address(arena: dict, host: int, mode: str) -> int:
    return host if mode == "direct" else host - arena["base"]


def regions(arena: dict, mode: str) -> list[tuple[int, int]]:
    """Readable guest ranges [(address, size)], adjacent rows merged (the RAM inspector's search, ram_dump)."""
    out: list[tuple[int, int]] = []
    for s, e, p in sorted(arena["mapped"]):
        if "r" not in p:
            continue
        a = guest_address(arena, s, mode)
        if out and out[-1][0] + out[-1][1] == a:
            out[-1] = (out[-1][0], out[-1][1] + e - s)
        else:
            out.append((a, e - s))
    return out
