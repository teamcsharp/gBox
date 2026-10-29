"""Bounded live acceptance test for re5_switch_native_nav on the running RE5 Switch session.

Read-only: opens the citron process's memory, locates main via the signature,
then attempts sAI discovery and navmesh decode.  Reports findings and exits.
"""
import os
import sys
import struct

# Add the workspace system dir so we import the new module
sys.path.insert(0, "/home/ehm_eckx/gBox_alt/gbox-hermes-tasks/0bf5827a4e884af9/system")

from gbox.mercs.titles import re5_switch_native_nav as NAV
from gbox.mercs.titles import re5_nav

PID = 930373
SIG_OFF = 0x1191000
SIGNATURE = bytes.fromhex(
    "03040000000000003052000000000000e821ce01000000000304000000000000"
    "1053000000000000f021ce010000000003040000000000005054000000000000"
)


class ProcMem:
    """Minimal /proc/<pid>/mem reader matching the gbox memory interface."""

    def __init__(self, pid: int):
        self.pid = pid
        self.fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
        # cached module base
        self._base = None

    @property
    def base(self):
        if self._base is None:
            self._base = self._find_base()
        return self._base

    def _find_base(self) -> int:
        """Scan mapped regions for the NSO signature."""
        with open(f"/proc/{self.pid}/maps") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 6:
                    continue
                addr_range = parts[0]
                perms = parts[1]
                if "r" not in perms:
                    continue
                start_s, end_s = addr_range.split("-")
                start, end = int(start_s, 16), int(end_s, 16)
                size = end - start
                if size < SIG_OFF + len(SIGNATURE):
                    continue
                try:
                    os.lseek(self.fd, start + SIG_OFF, os.SEEK_SET)
                    data = os.read(self.fd, len(SIGNATURE))
                    if data == SIGNATURE:
                        return start
                except OSError:
                    continue
        # Fallback: scan all readable regions for the signature itself
        with open(f"/proc/{self.pid}/maps") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 6:
                    continue
                perms = parts[1]
                if "r" not in perms:
                    continue
                start_s, end_s = parts[0].split("-")
                start, end = int(start_s, 16), int(end_s, 16)
                size = end - start
                if size < len(SIGNATURE) or size > 0x10000000:
                    continue
                off = 0
                while off < size - len(SIGNATURE):
                    try:
                        os.lseek(self.fd, start + off, os.SEEK_SET)
                        data = os.read(self.fd, min(4096, size - off))
                        idx = data.find(SIGNATURE)
                        if idx >= 0:
                            sig_addr = start + off + idx
                            return sig_addr - SIG_OFF
                    except OSError:
                        break
                    off += 4096
        raise RuntimeError("module base not found (signature scan failed)")

    def rd(self, addr: int, n: int) -> bytes:
        os.lseek(self.fd, addr, os.SEEK_SET)
        return os.read(self.fd, n)

    def close(self):
        os.close(self.fd)


def main():
    print(f"[live-accept] opening /proc/{PID}/mem ...")
    m = ProcMem(PID)
    base = m.base
    print(f"[live-accept] module base = {base:#x}")

    # --- 1. sAI discovery -------------------------------------------------
    print("[live-accept] scanning for sAI singleton ...")
    sai = NAV.find_sai(m, base)
    if sai is None:
        print("[live-accept] RESULT: sAI NOT found in this boot's statics window")
        print("[live-accept] The navmesh reader is ready but sAI is not yet mapped.")
        print("[live-accept] This is expected until the sAI offset is documented.")
        m.close()
        return 2

    print(f"[live-accept] sAI found at {sai:#x}")

    # --- 2. navmesh decode ------------------------------------------------
    mesh = NAV.read(m, s_ai=sai, ptr_base=base)
    if mesh is None:
        print("[live-accept] RESULT: sAI found but navmesh decode failed")
        m.close()
        return 3

    print(f"[live-accept] navmesh decoded: {len(mesh.points)} points, {len(mesh.tris)} triangles")

    # --- 3. sanity: route across the mesh --------------------------------
    if len(mesh.tris) >= 2:
        # pick two triangles that share a link
        t0 = mesh.tris[0]
        c0 = (
            sum(mesh.points[i][0] for i in t0) / 3,
            sum(mesh.points[i][1] for i in t0) / 3,
            sum(mesh.points[i][2] for i in t0) / 3,
        )
        # find a linked triangle
        route = None
        for nb, edge, cost in mesh.links[0]:
            if nb < len(mesh.tris):
                t1 = mesh.tris[nb]
                c1 = (
                    sum(mesh.points[i][0] for i in t1) / 3,
                    sum(mesh.points[i][1] for i in t1) / 3,
                    sum(mesh.points[i][2] for i in t1) / 3,
                )
                route = mesh.route(c0, c1)
                if route:
                    print(f"[live-accept] route tri0->tri{nb}: {len(route)} waypoints")
                    break
        if route is None:
            print("[live-accept] WARNING: no route found between linked triangles")

    print("[live-accept] RESULT: PASS - native navmesh discovered and decoded on live RE5 Switch")
    m.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
