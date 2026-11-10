"""CP6.2: find the vertex array with a vectorised scan for plausible float triples."""
import struct
import sys

import numpy as np

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
from gbox.gcdisc import GCDisc  # noqa: E402

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"


def main():
    data = GCDisc(DISC).read("Scene/map_aancient01_00n.rel")
    words = np.frombuffer(data, dtype=">f4")                  # every 4-byte word as a float
    plausible = np.isfinite(words) & (np.abs(words) <= 10000.0)
    # a vertex is three consecutive plausible floats at a 12-byte-aligned position
    n = len(words)
    tri = np.zeros(n, dtype=bool)
    tri[: n - 2] = plausible[: n - 2] & plausible[1: n - 1] & plausible[2:]
    runs, start = [], None
    for i in range(0, n - 2):
        if tri[i] and (i % 3 == 0 or start is None):
            if start is None:
                start = i
        elif start is not None:
            if i - start >= 64:
                runs.append((start, i - start))
            start = None
    if start is not None and n - 2 - start >= 64:
        runs.append((start, n - 2 - start))
    runs.sort(key=lambda r: -r[1])
    print(f"float-triple runs >= 64: {len(runs)}")
    for s, c in runs[:10]:
        print(f"  {s*4:#08x}: {c} triples = {c*12} bytes")
    if runs:
        s, c = runs[0]
        tri_arr = words[s * 3: (s + c) * 3].reshape(-1, 3)
        print(f"longest: {c} vertices at {s*4:#x}; bounds "
              f"x [{tri_arr[:,0].min():.1f},{tri_arr[:,0].max():.1f}] "
              f"y [{tri_arr[:,1].min():.1f},{tri_arr[:,1].max():.1f}] "
              f"z [{tri_arr[:,2].min():.1f},{tri_arr[:,2].max():.1f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
