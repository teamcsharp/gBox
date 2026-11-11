"""CP4 helper: is the Forest 1 mission's plan geometrically valid on the rel it names?

The mission `pso-gc-forest1-first-wave` declares `rel_artifact: 0e7bc121...` with `be: true`. That digest is exactly
`Scene/map_forest01c.rel` on this disc (verified by sha256), so the artifact is reproducible offline. This script parses that rel with
CP8's room reader and checks every mission waypoint against the rooms' opening footprints.
"""
import hashlib
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp\cp8wt\system")

from gbox import gcdisc, pso_rooms as R                                    # noqa: E402

DISC = r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved\Phantasy Star Online Episode I & II Plus (USA).iso"
REL = "Scene/map_forest01c.rel"
WANT = "0e7bc121a41e483e2c4d03bb031226461fecafb6c14ebfbeaab8ffe76ecfd2f5"
STEPS = [("interact", -95, 214), ("navigate", -140, 330), ("interact", 7, 362), ("navigate", 90, 300)]


def main():
    data = gcdisc.GCDisc(DISC).read(REL)
    digest = hashlib.sha256(data).hexdigest()
    print(f"{REL}: {len(data)} bytes, sha256 {digest[:16]} {'== the mission artifact' if digest == WANT else '!= the artifact'}")
    quads = R.rooms(data)
    print(f"rooms: {len(quads)}")
    for kind, x, z in STEPS:
        inside = [i for i, q in enumerate(quads) if R.contains(q, float(x), float(z))]
        print(f"  {kind:9s} ({x:5d}, {z:4d}) -> room(s) {inside if inside else 'NONE'}")
        if inside:
            q = quads[inside[0]]
            print(f"      room {inside[0]} footprint {q['size']} at {q['origin']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
