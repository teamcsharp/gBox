"""Owned-build inventory for TimeSplitters: Future Perfect (GameCube): streaming hashes, FST census, magic census.
Read-only on the source image. Usage: python scripts/tspfp_inventory.py <image.gcz|iso> <outdir>"""
import hashlib, json, re, struct, sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gbox.gcdisc import GCDisc, dol_to_elf


def stream_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def parse_c2n(text):
    """Free Radical .c2n sidecar: one '0x<crc32>  <asset path>' line per member of the matching .pak, in pak order."""
    rows = []
    for ln in text.splitlines():
        if not ln.strip():
            continue
        m = re.fullmatch(r"0x([0-9a-f]{8})  (\S.*)", ln)
        if not m:
            raise ValueError("bad c2n line: %r" % ln[:80])
        rows.append((int(m.group(1), 16), m.group(2)))
    return rows


def c2n_census(rows):
    kinds = collections.Counter(p.rsplit(".", 1)[-1] for _, p in rows)
    chrs = [p for _, p in rows if "/models/chrs/" in p and p.endswith(".gcr")]
    guns = [p for _, p in rows if "/models/guns/" in p and p.endswith(".gcr")]
    return {"members": len(rows), "kinds": dict(kinds), "character_models": len(chrs), "gun_models": len(guns),
            "first_character_models": [c.split("/")[-1] for c in chrs[:10]]}


def inventory(src, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    d = GCDisc(src)
    dol = d.dol()
    elf = dol_to_elf(dol)
    (out / "main.dol").write_bytes(dol)
    ext = collections.Counter(); magics = collections.Counter(); topdirs = collections.Counter()
    total = 0; samples = {}
    for name, (off, size) in d.files.items():
        total += size
        ext[Path(name).suffix.lower() or "(none)"] += 1
        topdirs[name.split("/")[0] if "/" in name else "(root)"] += 1
        if size >= 4:
            m = d._r(off, 4)
            magics[m.hex() + ":" + "".join(chr(c) if 32 <= c < 127 else "." for c in m)] += 1
            samples.setdefault(m.hex(), name)
    big = sorted(d.files.items(), key=lambda kv: -kv[1][1])[:25]
    man = {
        "source_path": str(src), "source_bytes": Path(src).stat().st_size,
        "source_sha256": stream_sha256(src),
        "disc_game_id": d.game_id, "disc_title": d.title, "platform": "gamecube", "byte_order": "big",
        "offset_base": "disc offset (FST), DOL file offsets for main.dol",
        "main_dol_sha256": hashlib.sha256(dol).hexdigest(), "main_dol_bytes": len(dol),
        "main_elf_sha256": hashlib.sha256(elf).hexdigest(),
        "file_count": len(d.files), "total_file_bytes": total,
        "extensions": ext.most_common(), "topdirs": topdirs.most_common(),
        "magics_top": magics.most_common(25),
        "magic_samples": {k: v for k, v in list(samples.items())[:25]},
        "largest": [(n, o, s) for n, (o, s) in big],
        "files": {n: list(v) for n, v in d.files.items()},
    }
    if "pak/chr.c2n" in d.files:
        raw = d.read("pak/chr.c2n")
        man["chr_c2n_sha256"] = hashlib.sha256(raw).hexdigest()
        man["chr_pak_sha256"] = hashlib.sha256(d.read("pak/chr.pak")).hexdigest()
        man["chr_c2n"] = c2n_census(parse_c2n(raw.decode("latin-1")))
    (out / "manifest.json").write_text(json.dumps(man, indent=1))
    return man


if __name__ == "__main__":
    m = inventory(sys.argv[1], sys.argv[2])
    print({k: v for k, v in m.items() if k not in ("files", "magic_samples")})
