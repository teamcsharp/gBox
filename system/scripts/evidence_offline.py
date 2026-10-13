#!/usr/bin/env python3
"""Offline PR evidence: before/after model renders and fit-event snapshots, without starting a game session.

Use it when an in-game frame can't be taken (no idle node, no gameplay moment yet) or as a companion to one. Every
picture it writes is an "offline render" (headless gbox.characters.render_preview, no GPU, no emulator) and is listed
in <out>/manifest.json ({file, caption, kind}) for scripts/pr_evidence.py --manifest.

  # any stock model next to any fitted model (glTF / GLB / KMD), or two existing pictures
  python scripts/evidence_offline.py pair --before stock.glb --after fitted.gltf --caption "..." --out DIR [--name x]

  # MGS VR Missions (PR #296): fit donors onto Snake / the Genome soldiers / the ninja from the owned disc, render
  # the disc's stock model next to the fitted KMD (textured through MetalMintSolid when it is installed), plus the
  # writer's fit-event snapshots
  python scripts/evidence_offline.py mgs-vr --disc ".../Metal Gear Solid - VR Missions (USA).bin" \
      --collection <characters dir> --pair player=sonic --pair enemy:soldier=sa2_knuckles \
      --pair enemy:ninja=sa2_shadow --out DIR

Nothing here writes game data anywhere but the scratch work folder (deleted at the end); only the PNGs and the
manifest stay in --out. Run it at low priority on a shared PC (`start /low` on Windows, `nice` on Linux).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import evidence_render as ER  # noqa: E402

MODEL_EXT = {".glb", ".gltf"}


def _low_priority():
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
        else:
            os.nice(10)
    except Exception:                                    # noqa: BLE001 - best effort
        pass


class Manifest:
    def __init__(self, out: Path):
        self.out, self.items = out, []
        out.mkdir(parents=True, exist_ok=True)
        f = out / "manifest.json"
        if f.is_file():
            self.items = [i for i in json.loads(f.read_text()).get("images", []) if (out / i["file"]).is_file()]

    def add(self, name: str, data: bytes, caption: str, kind: str = "offline render"):
        (self.out / name).write_bytes(data)
        self.items = [i for i in self.items if i["file"] != name] + [{"file": name, "caption": caption, "kind": kind}]
        (self.out / "manifest.json").write_text(json.dumps({"images": self.items}, indent=1))
        print(f"wrote {self.out / name}")


def _picture(src: Path, work: Path, size: int = 512) -> bytes:
    """A model (glTF/GLB/KMD) rendered, or an existing picture as it is."""
    src = Path(src)
    if src.suffix.lower() in MODEL_EXT:
        png = work / (src.stem + ".png")
        ER.render_model(src, png, size=size)
        return png.read_bytes()
    if src.suffix.lower() == ".kmd":
        glb = ER.prims_glb(ER.kmd_prims(src.read_bytes()), work / (src.stem + ".glb"))
        return _picture(glb, work, size)
    return src.read_bytes()


def cmd_pair(a):
    man = Manifest(Path(a.out))
    with tempfile.TemporaryDirectory() as t:
        data = ER.before_after(_picture(Path(a.before), Path(t)), _picture(Path(a.after), Path(t)), a.caption,
                               before_title=a.before_title, after_title=a.after_title)
    man.add(f"{a.name}.png", data, a.caption)


# ------------------------------------------------------------------------------------------------ MGS VR Missions

def _mint() -> Path | None:
    for c in (os.environ.get("GBOX_METAL_MINT"), "D:/gBox/runtime/tools/metal_mint/MetalMintSolid.exe",
              shutil.which("MetalMintSolid")):
        if c and Path(c).is_file():
            return Path(c)
    return None


def _textured_glb(mint: Path | None, kmd: bytes, archive: dict, work: Path, name: str) -> Path | None:
    """KMD + its PSX textures -> a textured GLB through MetalMintSolid (None when it isn't installed / fails)."""
    if mint is None:
        return None
    d = work / name
    (d / "pcc").mkdir(parents=True, exist_ok=True)
    (d / "png").mkdir(exist_ok=True)
    for h, body in archive.items():
        (d / "pcc" / f"{h}.pcc").write_bytes(body)
    (d / "model.kmd").write_bytes(kmd)
    try:
        for args in (["pcx", "batchdecode", d / "pcc", d / "png"],
                     ["kmd", "decode", d / "model.kmd", d / "model.glb", "--textures", d / "png"]):
            r = subprocess.run([str(mint), *map(str, args)], capture_output=True, text=True, timeout=300)
            if r.returncode:
                print(f"MetalMintSolid {args[0]} {args[1]}: {(r.stderr or r.stdout)[-300:]}", file=sys.stderr)
                return None
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"MetalMintSolid: {e}", file=sys.stderr)
        return None
    glb = d / "model.glb"
    return glb if glb.is_file() and glb.read_bytes()[:4] == b"glTF" else None


def _render_kmd(mint, kmd: bytes, archive: dict, work: Path, name: str, size: int = 512) -> tuple[bytes, bool]:
    glb = _textured_glb(mint, kmd, archive, work, name)
    textured = glb is not None
    if glb is None:
        glb = ER.prims_glb(ER.kmd_prims(kmd), work / f"{name}.glb")
    png = work / f"{name}.png"
    ER.render_model(glb, png, size=size)
    return png.read_bytes(), textured


def cmd_mgs_vr(a):
    from gbox import fit_events as FE, mgs_vr_swap as V, oot_swap, retarget_profile as RP, sm64_swap as S
    man, coll, mint = Manifest(Path(a.out)), Path(a.collection), (None if a.no_mint else _mint())
    data = V.read_stage_dir(Path(a.disc))
    print(f"STAGE.DIR {len(data):,} bytes; MetalMintSolid: {mint or 'not found (untextured renders)'}")
    with tempfile.TemporaryDirectory(prefix="gbox-evidence-") as t:
        work = Path(t)
        for pair in a.pair:
            slot_name, slug = pair.split("=", 1)
            slot = V.slot_of(slot_name) or slot_name
            spec = V.SLOTS[slot]
            sites = V.model_sites(data, spec["models"])
            if not sites:
                print(f"{slot}: none of {spec['models']} on this disc", file=sys.stderr)
                continue
            where = a.stage.get(slot) if a.stage else None
            first = next((s for s in sites if s["stage"] == where), sites[0])
            stage_sites = [s for s in sites if s["stage"] == first["stage"]]
            originals = {}
            for s in stage_sites:
                originals.setdefault(s["model"], data[s["offset"]:s["offset"] + s["size"]])
            archive, bins = {}, {}
            for k, d in enumerate(V.stage_textures(data, first["stage_offset"])):
                for h, (o, n) in d["entries"].items():
                    archive.setdefault(h, data[o:o + n])
                    bins.setdefault(h, k)
            meta = json.loads((coll / slug / "meta.json").read_text())
            meta = RP.apply_to_meta(meta, "afd2fc507bb69843", slot)
            glb = coll / slug / meta["model"]
            roles = oot_swap.roles_of(meta, glb)
            rig = S.load_rig(glb, roles, [p["node"] for p in meta.get("props") or []])
            label = f"{meta.get('name', slug)} as {spec['name']}"
            events, snaps = [], work / f"snap-{slug}"
            snaps.mkdir()

            def sink(_pct, msg, events=events):
                _text, ev = FE.split(msg)
                if ev:
                    events.append(ev)
            print(f"fitting {label} ({first['stage']}, models {sorted(originals)})")
            with FE.job(sink, snaps):
                FE.plan([(slot, slug, label)])
                FE.model(slot, label, slug)
                res = V.fit_slot(originals, rig, (meta.get("rig") or {}).get("scale"),
                                 [{"key": first["stage"], "archive": archive, "bins": bins}])
            arc = res["archives"][first["stage"]]
            model = spec["model"] if spec["model"] in arc["kmd"] else next(iter(arc["kmd"]))
            painted = {**archive, **arc["painted"]}
            before, tex_b = _render_kmd(mint, originals[model], archive, work, f"stock-{slug}-{model}")
            after, tex_a = _render_kmd(mint, arc["kmd"][model], painted, work, f"fit-{slug}-{model}")
            rep = res["models"][model]["report"]
            mrep = arc["report"]["models"][model]
            caption = (f"MGS VR Missions: {label}. Model {model} from {first['stage']} on the owned US disc "
                       f"({len(sites)} place{'' if len(sites) == 1 else 's'} on the disc). Fitted KMD {mrep['kmd_bytes']:,} of {len(originals[model]):,}"
                       f" bytes, {mrep['triangles']} triangles, {mrep['welds']} seam welds"
                       f"{', textures painted' if arc['painted'] else ', untextured'}"
                       f"{'' if tex_a else ' (render without textures: MetalMintSolid unavailable)'}; "
                       f"scale {rep.get('scale')}. Not yet seen in a live mission.")
            tag, short = slot.replace(":", "-"), spec["name"].split(" (")[0]
            man.add(f"mgsvr-{tag}-{slug}.png",
                    ER.before_after(before, after, caption, before_title=f"Stock {short} (disc KMD {model})",
                                    after_title=f"Fitted {meta.get('name', slug)}"),
                    f"MGS VR Missions: {meta.get('name', slug)} as {short}: the disc's stock model {model} vs the fitted "
                    f"KMD ({mrep['kmd_bytes']:,} of {len(originals[model]):,} bytes, {mrep['triangles']} triangles"
                    f"{', textured' if tex_a else ''})")
            glbs = sorted(snaps.glob("*.glb"), key=lambda p: p.stat().st_mtime)
            if glbs:
                items = [(g, g.stem.split("-")[-2] if g.stem.count("-") >= 2 else g.stem) for g in glbs[:4]]
                lines = ER.fit_report_lines(events, 6)
                cap = (f"Fit-event snapshots of {label} (gbox.fit_events, the geometry after each writer stage). "
                       + " | ".join(lines))
                man.add(f"mgsvr-{tag}-{slug}-fit-snapshots.png", ER.snapshot_strip(items, cap, work=work),
                        f"Fit-event snapshots: {meta.get('name', slug)} as {short} after each writer stage "
                        f"({', '.join(t for _g, t in items)})")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("pair", help="before/after of two models or pictures")
    s.add_argument("--before", required=True)
    s.add_argument("--after", required=True)
    s.add_argument("--caption", default="")
    s.add_argument("--before-title", default="Before (stock)")
    s.add_argument("--after-title", default="After (mod)")
    s.add_argument("--name", default="pair")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_pair)
    s = sub.add_parser("mgs-vr", help="MGS VR Missions slot fits from the owned disc")
    s.add_argument("--disc", required=True, help="the unpacked US VR Missions .bin")
    s.add_argument("--collection", required=True, help="the character collection folder (slug/meta.json)")
    s.add_argument("--pair", action="append", required=True, help="slot=slug, e.g. player=sonic")
    s.add_argument("--stage", type=lambda v: dict(x.split("=", 1) for x in v.split(",")), default=None,
                   help="slot=stage,... which stage's copy to render (default: the first on the disc)")
    s.add_argument("--no-mint", action="store_true", help="untextured renders even when MetalMintSolid exists")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_mgs_vr)
    a = p.parse_args(argv)
    _low_priority()
    a.fn(a)


if __name__ == "__main__":
    main()
