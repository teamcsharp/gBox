"""Convert Sonic's .glb against the pack with the largest weight table, so its 62 joints carry individually.

`pl04.udas` slot 0 has 112 bones and **256 weight records** (measured by best_template_pack), against the 4 that the Ganado's slot
offers - which is why the donor was bucketed into four groups. With this container the donor keeps every joint, and the band transfer
can match head to head, hand to hand.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import glb_donor as G
from gbox import re4hd_models as R

ROMFS = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), "010099A00BC1E000", "bio4", "em")
GLB = os.path.expanduser("~/agent-work/re4chars/sonic_src.glb")


def main() -> int:
    template = os.path.join(ROMFS, "pl04.udas")
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sonic_full.bin"
    blob = G.donor_bin(GLB, template)
    open(out, "wb").write(blob)
    mesh = R.bin_read(blob)
    print(f"{GLB} -> {out}: {len(blob)} bytes, {len(mesh.pos)} verts, {len(mesh.tris)} tris, "
          f"bones {len(mesh.bones)}, weight records {len(mesh.weights or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
