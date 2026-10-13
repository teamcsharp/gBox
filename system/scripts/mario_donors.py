"""Mario-series donors for the character library: Super Mario 64 (the operator's ROM) and the Render96 HD models,
converted by gbox.sm64_decomp and imported through the Blender round trip (`characters op=add`).

  build   ROM (+ Render96 actors folder) -> donor GLBs in OUT (never inside the repo; the HD files are third-party)
  local   import the GLBs into a library folder (the Windows mirror D:/gBox/cache/characters_mirror) with
          gbox.blender_roundtrip.import_model, the same code `characters op=add` runs; --replace re-imports a slug
  push    import them into the Spark library through the API: POST /api/characters/blender/import (b64 GLB, name =
          the slug, rig_roles), then poll /api/jobs/{id}; slugs already in the library are skipped

  python scripts/mario_donors.py build --rom "Super Mario 64 (USA).zip" --render96 <ModelPack>/Render96/actors --out D:/gBox/research/mario_donors/glb
  python scripts/mario_donors.py local --glb D:/gBox/research/mario_donors/glb --library D:/gBox/cache/characters_mirror --replace
  python scripts/mario_donors.py push --glb D:/gBox/research/mario_donors/glb --server http://10.89.1.246:8765

Render96 ModelPack: https://github.com/Render96/ModelPack (branch models_vanilla). The repository has no licence file;
the models are a free fan release for SM64 PC ports. Every entry records that, with the attribution, in its meta
(licence / attribution, from the GLB's gbox_source extras); the files stay local and are never committed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROM_SLUGS = {w: f"sm64_{w}" for w in ("mario", "peach", "toad", "yoshi", "bowser")}
HD_SLUGS = {w: f"{w}_hd" for w in ("mario", "luigi", "wario", "peach", "toad", "yoshi", "bowser")}


def build(a) -> list[dict]:
    from gbox import n64_rom, sm64_decomp as D
    rom = n64_rom.read(a.rom)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    only = set(a.only.split(",")) if a.only else None
    for who, slug in ROM_SLUGS.items():
        if only and slug not in only:
            continue
        r = D.build_rom_donor(rom, who, out / f"{slug}.glb")
        rows.append({"slug": slug, "glb": str(r["path"]), **r["stats"], "roles": r["roles"]})
        print(json.dumps({k: v for k, v in rows[-1].items() if k != "roles"}), flush=True)
    if a.render96:
        for who, slug in HD_SLUGS.items():
            if only and slug not in only:
                continue
            r = D.build_pack_donor(Path(a.render96) / who, who, out / f"{slug}.glb", rom=rom)
            rows.append({"slug": slug, "glb": str(r["path"]), **r["stats"], "roles": r["roles"]})
            print(json.dumps({k: v for k, v in rows[-1].items() if k != "roles"}), flush=True)
    (out / "donors.json").write_text(json.dumps(rows, indent=1))
    return rows


def _rows(glb_dir: Path) -> list[dict]:
    p = Path(glb_dir) / "donors.json"
    if not p.is_file():
        raise SystemExit(f"{p} missing: run `build` first")
    return json.loads(p.read_text())


def local(a) -> list[dict]:
    """The Blender round-trip import into a library folder, as `characters op=add` does on the control plane."""
    os.environ["GBOX_CHARACTERS"] = str(Path(a.library))
    from gbox import blender_roundtrip, characters as C, replacement_readiness as RR
    work = Path(a.work or Path(a.glb) / "_work")
    work.mkdir(parents=True, exist_ok=True)
    ctx = SimpleNamespace(config=SimpleNamespace(cache=str(work)), progress=lambda *x, **k: None)
    out = []
    for row in _rows(Path(a.glb)):
        slug = row["slug"]
        dst = Path(a.library) / slug
        if dst.exists():
            if not a.replace:
                print(json.dumps({"slug": slug, "status": "exists (use --replace)"}), flush=True)
                continue
            shutil.rmtree(dst)
        inp = SimpleNamespace(rig_roles=row["roles"], from_clipboard=False, artifact="", path=row["glb"], kind="character",
                              props=[], auto_rig=False, base="", replace="", derived_ok=True, scale={})
        res = blender_roundtrip.import_model(ctx, inp, Path(row["glb"]).read_bytes(), slug)
        meta = res["entry"]
        if meta["slug"] != slug:
            raise SystemExit(f"{slug}: stored as {meta['slug']}")
        meta = RR.ensure(Path(a.library), C.get(Path(a.library), slug), force=True)
        rd = meta.get("readiness") or {}
        out.append({"slug": slug, "name": meta.get("name"), "mode": res["mode"], "roles": len((meta.get("rig") or {}).get("roles") or {}),
                    "readiness": rd.get("status"), "missing": rd.get("missing"), "warnings": rd.get("warnings"),
                    "licence": meta.get("licence")[:60]})
        print(json.dumps(out[-1]), flush=True)
    return out


def push(a) -> list[dict]:
    """POST every GLB to the Spark's /api/characters/blender/import and wait for the jobs."""
    import httpx
    tok = a.token or os.environ.get("GBOX_TOKEN") or Path(a.token_file).read_text().strip()
    api = httpx.Client(base_url=a.server, headers={"authorization": f"Bearer {tok}"}, timeout=300)
    out = []
    for row in _rows(Path(a.glb)):
        slug = row["slug"]
        if api.get(f"/api/characters/{slug}").status_code == 200:
            print(json.dumps({"slug": slug, "status": "already in the library (skipped)"}), flush=True)
            continue
        body = {"name": slug, "b64": base64.b64encode(Path(row["glb"]).read_bytes()).decode(), "rig_roles": row["roles"],
                "auto_rig": False, "derived_ok": True}
        j = api.post("/api/characters/blender/import", json=body).raise_for_status().json()
        jid = j.get("id") or j.get("job_id")
        for _ in range(int(a.wait / 5)):
            st = api.get(f"/api/jobs/{jid}").json()
            if st.get("state") in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(5)
        res = ((st.get("output") or {}).get("result") or {})
        out.append({"slug": slug, "job": jid, "state": st.get("state"), "stored_as": (res.get("entry") or {}).get("slug"),
                    "error": st.get("error")})
        print(json.dumps(out[-1]), flush=True)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--rom", required=True, help="Super Mario 64 ROM (.z64 / .zip): the SM64 donors and every pose")
    b.add_argument("--render96", default="", help="the Render96 ModelPack actors folder (Render96/actors)")
    b.add_argument("--out", required=True)
    b.add_argument("--only", default="", help="comma list of slugs")
    lo = sub.add_parser("local")
    lo.add_argument("--glb", required=True)
    lo.add_argument("--library", required=True)
    lo.add_argument("--work", default="")
    lo.add_argument("--replace", action="store_true")
    p = sub.add_parser("push")
    p.add_argument("--glb", required=True)
    p.add_argument("--server", default="http://10.89.1.246:8765")
    p.add_argument("--token", default="")
    p.add_argument("--token-file", default=str(Path(__file__).resolve().parent.parent / "gbox-data" / "api_token"))
    p.add_argument("--wait", type=float, default=1800)
    a = ap.parse_args(argv)
    {"build": build, "local": local, "push": push}[a.cmd](a)


if __name__ == "__main__":
    main()
