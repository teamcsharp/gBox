"""Locate the technique-level table inside the player actor, read-only.

The plane cannot grant techniques: `psoitems.catalog` explicitly skips technique disks (class 2) so `give`, `enemy_drops` and `randomized`
all refuse them, and no live op writes the technique table. The only path is a memory write - which needs the job channel, dead for this
session (it was launched by an earlier worker).

So this does the part that is possible now: find the table. A HUmar knows a handful of techniques, so the technique levels form a run of
small values (0-30) with several non-zero entries inside the 0x340-byte player actor. The scan reports every candidate run with its offset,
length and values, and dumps the whole actor so the layout can be compared against a known-tech character later.
"""
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

PLAYER_POINTER = 0x8050EA10
ACTOR_SIZE = 0x340
MIN_RUN = 14                                                       # PSO has about 19-20 techniques
MAX_LEVEL = 31
OUT = r"D:\gBox\pso-ds\tech-scan.txt"


def main():
    pointer = int.from_bytes(S.read_memory(PLAYER_POINTER, 4), "big")
    print(f"player actor: {hex(pointer)}")
    blob = S.read_memory(pointer, ACTOR_SIZE)
    if len(blob) != ACTOR_SIZE:
        print(f"short read: {len(blob)} bytes")
        return 2
    hp = struct.unpack(">H", blob[0x32C:0x32E])[0]
    tp = struct.unpack(">H", blob[0x32E:0x330])[0]
    print(f"hp {hp}, tp {tp} (sanity: these fields are at 0x32C/0x32E as established)")
    lines = [f"player actor {hex(pointer)}, {ACTOR_SIZE} bytes",
             f"hp {hp} tp {tp}", "offsets are relative to the actor start", ""]
    candidates = []
    index = 0
    while index < ACTOR_SIZE:
        run = []
        while index + len(run) < ACTOR_SIZE and blob[index + len(run)] <= MAX_LEVEL:
            run.append(blob[index + len(run)])
            if len(run) > 40:
                break
        if len(run) >= MIN_RUN:
            non_zero = [value for value in run if value]
            score = len(run) + 3 * len(non_zero)
            candidates.append((score, index, list(run)))
        index += max(1, len(run))
    candidates.sort(reverse=True)
    print(f"\ntechnique-table candidates (runs of values <= {MAX_LEVEL}, length >= {MIN_RUN}):")
    for score, offset, run in candidates[:8]:
        text = " ".join(f"{value:02d}" for value in run)
        print(f"  +0x{offset:03X}  len {len(run):2d}  non-zero {sum(1 for v in run if v):2d}  score {score:3d}  [{text}]")
        lines.append(f"+0x{offset:03X} len {len(run)} non-zero {sum(1 for v in run if v)} :: {text}")
    if candidates:
        best_score, best_offset, best_run = candidates[0]
        print(f"\nbest candidate: +0x{best_offset:03X}, values {best_run}")
    print("\nfull actor hexdump follows in", OUT)
    lines.append("")
    for offset in range(0, ACTOR_SIZE, 16):
        row = blob[offset:offset + 16]
        lines.append(f"+0x{offset:03X}  {row.hex(' ')}  " + "".join(chr(b) if 32 <= b < 127 else "." for b in row))
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
