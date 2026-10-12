"""Inventory probe for Metal Arms - Glitch in the System (USA) GC (GM5E7D), game 7e103ec3aab47fa2.
Resolves the owned disc, hashes the source executable and master-file assets, and emits a
machine-readable manifest. Stdlib-only apart from gbox.gcdisc (read-only)."""
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/home/ehm_eckx/gBox/system")
from gbox.gcdisc import GCDisc  # noqa: E402

ISO = Path("/home/ehm_eckx/gbox-cache/modbase/7e103ec3aab47fa2/Metal Arms - Glitch in the System (USA).iso")
GCZ = Path("/home/ehm_eckx/gbox-cache/7e103ec3aab47fa2/Metal Arms - Glitch in the System (USA).gcz")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
MST = "mettlearms_gc.mst"
ROSTER = {  # ape file -> (slug, display name)
    "grdggltch00.ape": ("glitch", "Glitch (player)"),
    "grmggrunt00.ape": ("ma_grunt", "Mil Grunt"),
    "grdmminer00.ape": ("ma_miner", "Droid Miner"),
    "grdkkrunk00.ape": ("ma_krunk", "Krunk"),
    "grdzzobby00.ape": ("ma_zobby", "Zobby"),
    "grdxexavo00.ape": ("ma_exavolt", "Exavolt"),
    "grmttitan00.ape": ("ma_titan", "Titan"),
    "grmggrunt01.ape": ("ma_grunt2", "Mil Grunt (variant)"),
}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    d = GCDisc(ISO)
    hdr = d._r(0, 0x60)
    magic = struct.unpack(">I", d._r(0x1C, 4))[0]
    dol = d.dol()
    dol_sha = hashlib.sha256(dol).hexdigest()
    (OUT / "start.dol").write_bytes(dol)  # preserve the original executable

    base, mst_size = d.files[MST]
    h = d._r(base, 0x10)
    assert h[:4] == b"GNAF", h[:4]
    n = struct.unpack_from(">I", h, 0xC)[0]
    raw = d._r(base + 0x6C, 36 * n)
    entries = []
    ext_counter = Counter()
    for i in range(n):
        name = raw[36 * i:36 * i + 20].split(b"\0")[0].decode("latin-1")
        off, size, mtime, crc = struct.unpack_from(">4I", raw, 36 * i + 20)
        entries.append({"name": name, "offset": off, "size": size, "mtime": mtime, "crc": f"{crc:08x}"})
        ext_counter[name.rsplit(".", 1)[-1].lower() if "." in name else "(none)"] += 1
    by_name = {e["name"].lower(): e for e in entries}

    # per-character texture resolution: the .ape material layers name their .tga textures
    try:
        from gbox.metal_arms import Ape  # type: ignore

        def ape_textures(ape_name: str) -> list[str]:
            e = by_name[ape_name]
            data = d._r(base + e["offset"], e["size"])
            a = Ape(data)
            out = []
            for m in a.mats:
                out.extend(t for t in m["textures"] if t not in out)
            return out
    except Exception as ex:  # pragma: no cover
        print(f"WARN: Ape import failed ({ex}); texture resolution skipped", file=sys.stderr)
        ape_textures = lambda n: []

    ANIM_TOKENS = {"glitch": ["gltch"], "ma_grunt": ["grunt"], "ma_miner": ["miner"], "ma_krunk": ["krunk"],
                   "ma_zobby": ["zobby"], "ma_exavolt": ["exavo"], "ma_titan": ["titan", "grunt"],
                   "ma_grunt2": ["grunt"]}
    mtx_names = [e["name"] for e in entries if e["name"].lower().endswith(".mtx")]

    chars = []
    for ape, (slug, label) in ROSTER.items():
        stem = ape[:-4]
        rec: dict = {"slug": slug, "name": label}
        e = by_name.get(ape)
        rec["mesh_entry"] = {k: e[k] for k in ("name", "size", "crc")} if e else None
        rec["mesh_ok"] = bool(e)
        if e:
            rec["textures"] = ape_textures(ape)
            toks = ANIM_TOKENS[slug]
            rec["anim_banks"] = [n for n in mtx_names if any(t in n.lower() for t in toks)][:8]
        chars.append(rec)

    manifest = {
        "game_id": "7e103ec3aab47fa2",
        "title": "Metal Arms - Glitch in the System (USA)",
        "platform": "gamecube",
        "core": "dolphin",
        "game_code": d.game_id,
        "disc_magic_ok": magic == 0xC2339F3D,
        "iso": {"path": str(ISO), "size": ISO.stat().st_size, "sha256": sha256_file(ISO)},
        "gcz": {"path": str(GCZ), "size": GCZ.stat().st_size, "sha256": sha256_file(GCZ)},
        "executable": {
            "name": "start.dol (disc header 0x420 -> offset)",
            "size": len(dol),
            "sha256": dol_sha,
            "saved": str(OUT / "start.dol"),
        },
        "fst_files": len(d.files),
        "master_file": {
            "name": MST, "size": mst_size, "entry_count": n,
            "by_extension": dict(sorted(ext_counter.items())),
            "total_payload": sum(e["size"] for e in entries),
        },
        "roster": chars,
    }
    (OUT / "metal_arms_inventory.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
