"""Offline renders of a built Soul Calibur II cast (gbox.soulcalibur2_swap): every rebuilt costume read back from the
BUILT image (soulcalibur2.read_costume -> export, the fighter's default weapon on the hands), front and back, one sheet
per fighter with the stock costume 1 for scale. Back faces are culled with GX's clockwise fronts (characters.render_preview cull="cw"), so a
single-sided donor part seen from behind shows as the hole a culling GPU would leave. Each PNG stays under 1 MB.

    python scripts/sc2_cast_evidence.py BUILT.iso STOCK.iso OUT_DIR [--only mitsurugi,ivy] [--no-cull]

Writes OUT_DIR/sc2_<fighter>.png and OUT_DIR/evidence.json (kind "offline render").
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import characters as C, evidence_render as E, soulcalibur2 as S  # noqa: E402

MAX_BYTES = 1_000_000


def png_under(img, limit: int = MAX_BYTES) -> bytes:
    from PIL import Image
    for colours in (None, 256, 128):
        im = img if colours is None else img.convert("P", palette=Image.ADAPTIVE, colors=colours)
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        if buf.tell() <= limit:
            return buf.getvalue()
    scale = (limit / buf.tell()) ** 0.5
    return png_under(img.resize((int(img.width * scale), int(img.height * scale))), limit)


def views(costume, work: Path, stem: str, cull: bool, size: int = 300) -> tuple[Path, Path, dict]:
    glb = work / f"{stem}.glb"
    info = S.export(costume, glb, stem)
    front, back = work / f"{stem}_front.png", work / f"{stem}_back.png"
    # soulcalibur2.export keeps the game's winding: GX lists front faces clockwise in model space (stock and rebuilt
    # costumes alike: toes / chin at +Z, CW-outward), so the culled views keep the clockwise fronts
    C.render_preview(glb, front, size=size, yaw=-30.0, cull="cw" if cull else False)
    C.render_preview(glb, back, size=size, yaw=150.0, cull="cw" if cull else False)
    return front, back, {"triangles": info["triangles"], "textures": info["textures"], "roles": len(info["roles"]),
                         "front_check": C.check_preview(front), "back_check": C.check_preview(back)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("built")
    ap.add_argument("stock")
    ap.add_argument("out")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-cull", action="store_true")
    a = ap.parse_args(argv)
    from PIL import Image
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    marker = json.loads((Path(a.built).parent / ".gbox-mod.json").read_text(encoding="utf-8"))
    slots = marker["report"]["slots"]
    by_fighter: dict[str, list[tuple[int, dict]]] = {}
    for sk, row in slots.items():
        key, c = sk.rsplit(":", 1)
        by_fighter.setdefault(key, []).append((int(c) - 1, row))
    only = {s.strip().lower() for s in a.only.split(",") if s.strip()}
    cull = not a.no_cull
    index = {"kind": "offline render", "build": marker["name"], "image": str(a.built), "cull_back_faces": cull,
             "renderer": "gbox.characters.render_preview (headless, no emulator)", "fighters": []}
    with S.Disc(Path(a.built)) as built, S.Disc(Path(a.stock)) as stock, tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for key, rows in sorted(by_fighter.items()):
            if only and key not in only:
                continue
            name = marker.get("cast_names", {}).get(key, key)
            sf, sb, _ = views(S.read_costume(stock, key, 0), work, f"{key}_stock", cull)
            panels = [(sf, f"{name} stock 1"), (sb, "stock 1 back")]
            rec = {"fighter": key, "costumes": []}
            for c, row in sorted(rows, key=lambda t: t[0]):
                if row.get("status") != "built":
                    rec["costumes"].append({"costume": c + 1, "status": row.get("status"), "reason": row.get("reason")})
                    continue
                f, b, info = views(S.read_costume(built, key, c), work, f"{key}_{c + 1}", cull)
                panels += [(f, f"{c + 1}: {row['donor']}"), (b, f"{c + 1} back")]
                rec["costumes"].append({"costume": c + 1, "donor": row["donor"], "status": "built"} | info)
            cap = (f"Soul Calibur II {name}: stock costume 1, then every rebuilt costume read back from the built disc "
                   f"({marker['name']}), 3/4 front and back, default weapon on the hands"
                   + (", back faces culled." if cull else ", both sides drawn."))
            sheet = Image.open(io.BytesIO(E.compose(panels, cap, height=300)))
            data = png_under(sheet)
            (out / f"sc2_{key}.png").write_bytes(data)
            rec |= {"file": f"sc2_{key}.png", "bytes": len(data)}
            index["fighters"].append(rec)
            print(key, len(data), flush=True)
    (out / "evidence.json").write_text(json.dumps(index, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
