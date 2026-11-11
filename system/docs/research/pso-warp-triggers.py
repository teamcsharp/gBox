"""Locate the area warp from the collision data: cluster the TRIGGER_FLAG triangles.

map_forest01c.rel carries 164 triangles flagged TRIGGER_FLAG (psomap.TRIGGER_FLAG). Those flags mark the zones the level uses for events
and warps, so their positions are a candidate list for the teleporter - available without exploring the room, which is what the operator
asked for ("you should be able to have access to it by looking at the byte RAM information").

Each triangle's centroid is clustered by proximity and the clusters are printed with their world bounds and a size, largest first.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import psomap                                            # noqa: E402

REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
CLUSTER_RADIUS = 30.0


def main():
    tris = psomap.collision(REL.read_bytes())
    triggers = []
    for (a, b, c, flags, normal) in tris:
        if not (flags & psomap.TRIGGER_FLAG):
            continue
        cx = (a[0] + b[0] + c[0]) / 3.0
        cy = (a[1] + b[1] + c[1]) / 3.0
        cz = (a[2] + b[2] + c[2]) / 3.0
        triggers.append((cx, cy, cz))
    print(f"trigger triangles: {len(triggers)}")
    clusters = []
    for point in triggers:
        for cluster in clusters:
            if math.dist(point, cluster["centre"]) <= CLUSTER_RADIUS:
                cluster["points"].append(point)
                n = len(cluster["points"])
                cluster["centre"] = tuple(sum(p[i] for p in cluster["points"]) / n for i in range(3))
                break
        else:
            clusters.append({"centre": point, "points": [point]})
    clusters.sort(key=len, reverse=True)
    print(f"clusters: {len(clusters)}")
    for index, cluster in enumerate(clusters):
        xs = [p[0] for p in cluster["points"]]
        ys = [p[1] for p in cluster["points"]]
        zs = [p[2] for p in cluster["points"]]
        print(f"  cluster {index}: {len(cluster['points']):4d} triangles, centre "
              f"({cluster['centre'][0]:8.1f},{cluster['centre'][1]:7.1f},{cluster['centre'][2]:8.1f})  "
              f"x {min(xs):7.0f}..{max(xs):7.0f}  y {min(ys):5.0f}..{max(ys):5.0f}  z {min(zs):7.0f}..{max(zs):7.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
