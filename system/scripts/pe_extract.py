"""Parasite Eve (PS1 USA) asset extractor CLI (gbox.parasite_eve).

  python scripts/pe_extract.py SRC list                       # room packages: models / anim counts
  python scripts/pe_extract.py SRC aya OUT [--outfit N|all]  # Aya Brea -> OUT/aya_<outfit>.glb (rigged, textured, anims)
  python scripts/pe_extract.py SRC rooms OUT [--room I]      # every unique enemy/NPC model -> OUT/pe_rIII_mMM.glb + index.json
  python scripts/pe_extract.py SRC all OUT                   # aya (all outfits) + rooms
SRC = the disc 1 CHD/BIN (read directly, no chdman) or a directory holding PE.IMG + SLUS_006.62.
Add --upload to store each .glb as a gBox artifact (needs gbox-data/api_token; prints the sha256 refs).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gbox import parasite_eve as P  # noqa: E402


def upload(path: Path, meta: dict):
    import httpx
    root = Path(__file__).resolve().parents[1]
    tok = (root / "gbox-data" / "api_token").read_text().strip()
    url = "http://10.89.1.246:8765/api/artifacts"
    r = httpx.post(url, params={"name": path.name, "media_type": "model/gltf-binary",
                                "provenance": json.dumps({"game": "parasite eve (usa)", "tool": "pe_extract", **meta})},
                   content=path.read_bytes(), headers={"authorization": f"Bearer {tok}"}, timeout=120)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("cmd", choices=["list", "aya", "rooms", "all"])
    ap.add_argument("out", nargs="?", default="pe_out")
    ap.add_argument("--outfit", default="all")
    ap.add_argument("--room", type=int)
    ap.add_argument("--scale", type=float, default=1 / 290)
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    pe = P.PEData(a.src)
    if a.cmd == "list":
        for x in P.list_packages(pe):
            print(json.dumps(x))
        return
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    if a.cmd in ("aya", "all"):
        outfits = range(P.AYA_OUTFITS) if a.outfit == "all" else [int(a.outfit)]
        for o in outfits:
            r = P.export_aya(pe, out / f"aya_{P.AYA_OUTFITS_NAMES[o]}.glb", outfit=o, scale=a.scale)
            r["outfit"] = P.AYA_OUTFITS_NAMES[o]
            results.append(r)
            print(json.dumps(r))
    if a.cmd in ("rooms", "all"):
        seen = {}
        rooms = [a.room] if a.room is not None else [x["index"] for x in P.list_packages(pe)]
        for i in rooms:
            for r in P.export_room_models(pe, i, out, scale=a.scale, seen=seen):
                print(json.dumps({k: r[k] for k in ("path", "bones", "verts", "animations")}))
        (out / "index.json").write_text(json.dumps(list(seen.values()), indent=1))
        results += list(seen.values())
    if a.upload:
        for r in results:
            ref = upload(Path(r["path"]), {k: r.get(k) for k in ("outfit", "room", "model_id", "bones", "animations")})
            print("artifact", Path(r["path"]).name, ref.get("sha256"))


if __name__ == "__main__":
    main()
