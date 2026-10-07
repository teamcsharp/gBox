"""Extract a Final Fantasy VII (PS1) battle model straight from the disc image to a rigged glTF (gbox.ff7_models).

  python scripts/ff7_extract.py "Final Fantasy VII (USA) (Disc 1).chd" cloud.gltf                  # Cloud, idle anim
  python scripts/ff7_extract.py disc.chd cloud.gltf --model ENEMY6/HICLOUD.LZS --anim 16 --weapon 0 --static
  python scripts/ff7_extract.py disc.chd --list                                                    # party models

--anim picks the animation that is both the bind pose (--frame) and the exported glTF animation (--static: none).
--weapon N attaches weapon model N (Cloud: 0 = Buster Sword) to --weapon-bone (13 = Cloud's right hand).
The disc can be a CHD v4 (HyperSpin set) or an already decompressed LZS file.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import ff7_models as F  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("disc")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--model", default="ENEMY6/CLOUD.LZS")
    ap.add_argument("--anim", type=int, default=16)
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--weapon", type=int, default=None)
    ap.add_argument("--weapon-bone", type=int, default=13)
    ap.add_argument("--static", action="store_true", help="no glTF animation (bind pose only, e.g. for retargeting)")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        from gbox.psxdisc import PSXDisc
        d = PSXDisc(a.disc)
        for k, (_lba, size) in sorted(d.files.items()):
            if k.startswith("ENEMY6/") and k.endswith(".LZS") and not k[7:12] == "ENEMY":
                print(f"{k:24s} {size:8d}")
        return
    if a.disc.lower().endswith(".lzs"):
        model = F.read_battle_model(Path(a.disc).read_bytes())
    else:
        model = F.from_disc(a.disc, a.model)
    names = F.CLOUD_BONES if "CLOUD" in a.model.upper() else None
    info = F.to_gltf(model, Path(a.out), anim=a.anim, rest_frame=a.frame, weapon=a.weapon, weapon_bone=a.weapon_bone,
                     animate=not a.static, names={i: f"j{i:02d}" for i in range(len(model["bones"]))})
    info["animations"] = len(model["anims"])
    info["weapons"] = len(model["weapons"])
    if names:
        info["joint_names"] = {f"j{i:02d}": n for i, n in names.items()}
    print(info)


if __name__ == "__main__":
    main()
