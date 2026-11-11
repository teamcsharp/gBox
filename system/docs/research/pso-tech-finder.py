"""Find the technique-level table by following the player actor's pointers.

The plane's own code shows the actor holds pointers to sub-structures (`p+0x2B0` is the base-stats block, `p+0xD00` the inventory), so the
technique levels most likely live in one of those pointed-to blocks rather than in the actor itself. Techniques are levels 0-30 stored as
one byte each (about twenty of them, mostly zero for a character that knows a few).

This reads the actor, follows every plausible pointer in it, and reports any block holding a run of at least fifteen bytes each <= 30 with
at least two non-zero - the signature of a technique table. It also reports the same test inside the actor itself, where an earlier scan
found a 24-byte zero run with a single `01` at +0x2E7.

Read-only: it prints candidates and never writes.
"""
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S

PLAYER_POINTER = 0x8050EA10
ACTOR_SIZE = 0x340
READ_BLOCK = 0x200
MIN_RUN = 15
MAX_LEVEL = 30
LOG = r"D:\gBox\pso-ds\tech-finder.txt"


def technique_runs(blob, label):
    """Runs of small values long enough to be a technique table."""
    runs = []
    index = 0
    while index < len(blob):
        run = []
        while index + len(run) < len(blob) and blob[index + len(run)] <= MAX_LEVEL:
            run.append(blob[index + len(run)])
            if len(run) > 32:
                break
        if len(run) >= MIN_RUN and sum(1 for value in run if value) >= 2:
            runs.append({"at": index, "values": list(run), "non_zero": sum(1 for v in run if v)})
        index += max(1, len(run))
    return runs


def main():
    pointer = int.from_bytes(S.read_memory(PLAYER_POINTER, 4), "big")
    if not (0x80000000 <= pointer < 0x81800000):
        print(f"no player actor loaded (table holds {hex(pointer)})")
        return 2
    actor = S.read_memory(pointer, ACTOR_SIZE)
    print(f"actor {hex(pointer)} ({len(actor)} bytes read)")
    lines = [f"actor {hex(pointer)}"]
    found = 0
    print("\n-- inside the actor --")
    for run in technique_runs(actor, "actor"):
        text = " ".join(f"{v:02d}" for v in run["values"])
        line = f"  +0x{run['at']:03X} len {len(run['values'])} non-zero {run['non_zero']} :: {text}"
        print(line)
        lines.append(line)
        found += 1
    print("\n-- following pointers --")
    seen = set()
    for offset in range(0, ACTOR_SIZE - 3, 4):
        target = int.from_bytes(actor[offset:offset + 4], "big")
        if not (0x80000000 <= target < 0x81800000) or target in seen:
            continue
        seen.add(target)
        try:
            block = S.read_memory(target, READ_BLOCK)
        except Exception:                                        # noqa: BLE001
            continue
        if len(block) < MIN_RUN:
            continue
        for run in technique_runs(block, "pointer"):
            text = " ".join(f"{v:02d}" for v in run["values"])
            line = (f"  pointer +0x{offset:03X} -> {hex(target)} block +0x{run['at']:03X} "
                    f"len {len(run['values'])} non-zero {run['non_zero']} :: {text}")
            print(line)
            lines.append(line)
            found += 1
    print(f"\ncandidates: {found}")
    with open(LOG, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print("wrote", LOG)
    return 0 if found else 3


if __name__ == "__main__":
    raise SystemExit(main())
