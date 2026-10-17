"""The game's own routine as the oracle: run a decoder/expander/skeleton routine from the title's executable on an
interpreter, and judge gBox's Python reader/writer against what the game itself produces.

This is how Dead or Alive++ was cracked (gbox.zn_tps_boot runs the TPS BIOS decode; doapp_models.unpack_model runs the
fight loader's expander 0x8006c718; doapp_swap proves pack_mesh is its exact inverse, 327/327 sections) and how DOA2's
cloth initialisers were checked (Ghidra's emulator). The harness makes that a three-call recipe for the next title:

    o = RoutineOracle("mips_le", ram=program_ram)          # the decoded executable / RAM image
    got = o.run(0x8006c718, inputs={0x80300000: packed}, args=(0, 0x80300000, 0x801fe800),
                read=(0x801fe800, length))                   # bytes the game's routine wrote
    report = check_inverse(my_pack, lambda x: o.run(...), samples)   # my encoder is the routine's exact inverse

CPUs: "mips_le" (R3000A: PS1, ZN arcade; gbox.zn_tps_boot.R3000, optional GTE via gbox.psx_gte). SH-4 (Dreamcast) and
PowerPC (GameCube/Wii) have no in-repo interpreter yet: oracle_route() names the Ghidra-emulator route (ghidra_bridge
op=run_script with ghidra.app.emulator.EmulatorHelper) that DOA2 used, so the recipe stays the same.
"""
from __future__ import annotations

from typing import Callable, Iterable

INTERPRETERS = {"mips_le": "gbox.zn_tps_boot.R3000 (+ gbox.psx_gte.GTE)"}
GHIDRA_ROUTE = {
    "sh4": "ghidra_bridge op=run_script: EmulatorHelper on the SH-4 program (SuperH4:LE:32:default), as DOA2's cloth "
           "initialisers were verified",
    "ppc": "ghidra_bridge op=run_script: EmulatorHelper on the PowerPC program (PowerPC:BE:32:default)",
    "mips_be": "ghidra_bridge op=run_script: EmulatorHelper on the MIPS:BE:32 image (N64)",
    "r5900": "ghidra_bridge op=run_script: EmulatorHelper on MIPS:LE:64:64-32addr (PS2; no COP2/VU)",
}


def oracle_route(cpu: str) -> str:
    """How to run a routine of this CPU as an oracle in gBox today."""
    if cpu in INTERPRETERS:
        return f"in-process interpreter {INTERPRETERS[cpu]}: gbox.formats.oracle.RoutineOracle({cpu!r}, ram=...)"
    return GHIDRA_ROUTE.get(cpu, "no interpreter: record the routine's input/output pairs from a live session "
                                 "(debugger breakpoints) and compare against those")


class RoutineOracle:
    """A RAM image + an interpreter; run(fn) calls a routine like the game does and returns what it wrote."""

    def __init__(self, cpu: str = "mips_le", ram: bytes = b"", *, ram_size: int = 0x400000, gte: bool = False,
                 stack: int | None = None):
        if cpu not in INTERPRETERS:
            raise NotImplementedError(f"no in-process {cpu} interpreter; route: {oracle_route(cpu)}")
        from .. import zn_tps_boot as Z
        self.cpu_name = cpu
        self.mem = Z.ZNMemory(b"\0" * 16, b"", b"\0" * 8, b"\0" * 8, ram_size=ram_size)
        self.mem.ram[:len(ram)] = ram[:ram_size]
        g = None
        if gte:
            from .. import psx_gte
            g = psx_gte.GTE()
        self.cpu = Z.R3000(self.mem, g)
        self.stack = stack if stack is not None else 0x80000000 | (ram_size - 0x100)
        self.calls = 0

    def _o(self, addr: int) -> int:
        return addr & self.mem.ram_mask

    def put(self, addr: int, data: bytes) -> None:
        o = self._o(addr)
        self.mem.ram[o:o + len(data)] = data

    def get(self, addr: int, n: int) -> bytes:
        o = self._o(addr)
        return bytes(self.mem.ram[o:o + n])

    def call(self, fn: int, *args: int, limit: int = 20_000_000) -> int:
        """Call fn(args...) (a0..a3) with ra = a stop address; returns v0."""
        self.calls += 1
        return self.cpu.call(fn, args, sp=self.stack, limit=limit)

    def run(self, fn: int, *, inputs: dict[int, bytes] | None = None, args: Iterable[int] = (),
            read: tuple[int, int] | None = None, limit: int = 20_000_000):
        """Place inputs, call fn, return (v0, bytes read back from `read` = (address, length) or None)."""
        for a, d in (inputs or {}).items():
            self.put(a, d)
        v0 = self.call(fn, *args, limit=limit)
        return v0, (self.get(*read) if read else None)


def first_difference(a: bytes, b: bytes) -> int | None:
    """Offset of the first differing byte (or the shorter length), None when equal."""
    if a == b:
        return None
    n = min(len(a), len(b))
    return next((i for i in range(n) if a[i] != b[i]), n)


def check_inverse(encode: Callable[[bytes], bytes], oracle_decode: Callable[[bytes], bytes],
                  samples: Iterable[bytes]) -> dict:
    """Is `encode` the exact inverse of the game's decoder? oracle_decode runs the game's routine (RoutineOracle or a
    live/Ghidra-emulator capture). Returns {checked, matched, mismatches: [{index, size, first_diff}]}."""
    out = {"checked": 0, "matched": 0, "mismatches": []}
    for i, s in enumerate(samples):
        out["checked"] += 1
        got = oracle_decode(encode(s))
        d = first_difference(got, s)
        if d is None:
            out["matched"] += 1
        else:
            out["mismatches"].append({"index": i, "size": len(s), "first_diff": d})
    return out


def check_reader(reader: Callable[[bytes], bytes], oracle: Callable[[bytes], bytes], files: Iterable[bytes]) -> dict:
    """Does gBox's Python reader produce what the game's own routine produces, file by file?"""
    out = {"checked": 0, "matched": 0, "mismatches": []}
    for i, f in enumerate(files):
        out["checked"] += 1
        a, b = reader(f), oracle(f)
        d = first_difference(a, b)
        if d is None:
            out["matched"] += 1
        else:
            out["mismatches"].append({"index": i, "first_diff": d, "python": len(a), "game": len(b)})
    return out
