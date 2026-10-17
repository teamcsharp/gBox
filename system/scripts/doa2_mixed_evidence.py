"""PR evidence for a DOA2 mixed random-select build (gbox.doa2_mixed): one PNG per fighter and one for the select
patch (docs/pr-evidence.md: offline renders, each under 1 MB).

Per fighter, two rows:
  top     the stock DOA2 costume, then each pool donor as the character collection holds it
  middle  the same stock costume, then each pool costume read back from the BUILT image and assembled through the
          game's own costume path (doa2_seams.assemble_core: CHR models on the costume's rig, SUP seams baked)
  bottom  the same built costumes from behind (both sides drawn: the writer's meshes use the native cull-small
          mode 1, which keeps both sides of a face)
The select-patch picture shows the patched call path, the hook's disassembly, the pool table and the costumes an
interpreted run of hook + the game's rand() picked over many confirmations.

    python scripts/doa2_mixed_evidence.py STOCK.gdi MOD_DIR LIBRARY OUT_DIR [--only KAS,AYA]
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import characters as C, doa2_random_select as R, evidence_render as E  # noqa: E402
from gbox.gdrom import GDRom  # noqa: E402

SA2_COLOUR, DS_COLOUR = (79, 140, 255), (255, 120, 90)
MAX_BYTES = 1_000_000


def assemble_render(disc, stock, archive: str, out: Path, size: int = 300, report: dict | None = None) -> Path:
    """Render one costume from `disc` through the native assembly on the stock costume's rig. A built costume uses
    the model -> bone map its writer recorded (rigid parts; the SUP binds the seam models it moved to spare slots)."""
    from gbox import doa2_rig, doa2_seams as S
    profile = doa2_rig.for_archive(stock, f"DOA2/{archive}.CHR")
    parts = profile["component_models"]
    if report is not None:
        seams = set(report.get("seam_model_ids") or [])
        parts = {int(m): int(b) for m, b in (report.get("model_draw_bones") or {}).items() if int(m) not in seams}
    core = S.assemble_core(disc.read(f"DOA2/{archive}.CHR"), disc.read(f"DOA2/{archive}.SUP"),
                           disc.read(f"DOA2/{archive}.BIN"), np.asarray(profile["world"]),
                           parts, S.native_coefficients(stock.read("1ST_READ.BIN")))
    gltf = S.write_core(out.with_suffix(".gltf"), core, profile, archive)
    C.render_preview(gltf, out.with_name(out.stem + "_back.png"), size=size, yaw=150.0)
    return C.render_preview(gltf, out, size=size)


def _png(img, limit=MAX_BYTES) -> bytes:
    from PIL import Image
    for colours in (None, 256, 128):
        im = img if colours is None else img.convert("P", palette=Image.ADAPTIVE, colors=colours)
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        if buf.tell() <= limit:
            return buf.getvalue()
    scale = (limit / buf.tell()) ** 0.5
    img = img.resize((int(img.width * scale), int(img.height * scale)))
    return _png(img, limit)


def fighter_sheet(entry: dict, stock, mod, library: Path, work: Path, out: Path, reports: dict) -> dict:
    from PIL import Image
    fam = entry["fighter"]
    first = entry["pool"][0]["costume"]
    stock_png = assemble_render(stock, stock, f"{fam}{first}", work / f"{fam}{first}_stock.png")
    top, bottom = [(stock_png, f"{entry['name']} stock {first}")], [(stock_png, f"{entry['name']} stock {first}")]
    back = [(stock_png.with_name(stock_png.stem + "_back.png"), "stock, back")]
    rows = []
    for item in entry["pool"]:
        c, slug = item["costume"], item["character"]
        meta = C.get(library, slug)
        prev = library / slug / (meta.get("preview") or "preview.png")
        built = assemble_render(mod, stock, f"{fam}{c}", work / f"{fam}{c}_built.png", report=reports[(fam, c)])
        tag = ("HD" if slug.endswith("_hd") else "SM64DS" if slug.startswith("sm64ds_") else "SM64")             if item["franchise"] == "SM64DS" else "SA2"
        top.append((prev, f"{tag}: {meta.get('name', slug)}"))
        bottom.append((built, f"{fam}{c} (#{item['render_costume']}) built"))
        back.append((built.with_name(built.stem + "_back.png"), f"{fam}{c} back"))
        rows.append({"costume": c, "donor": slug, "franchise": item["franchise"], "render": built.name})
    names = ", ".join(f"{i['costume']}={i['character']}" for i in entry["pool"])
    cap_top = (f"{entry['name']} ({fam}, render slot {entry['render_slot']}): its costume pool. Top: the donors as "
               f"collected (SA2 = Sonic Adventure 2, SM64DS = Super Mario 64 DS, HD = Render96 HD model).")
    cap_bot = (f"Bottom: each costume read back from the built disc and assembled through DOA2's own costume path "
               f"(CHR on the costume rig, SUP seams baked). A selection draws one at random: {names}.")
    a = Image.open(io.BytesIO(E.compose(top, cap_top, height=230)))
    b = Image.open(io.BytesIO(E.compose(bottom, cap_bot, height=230)))
    c = Image.open(io.BytesIO(E.compose(back, "The same built costumes from behind.", height=230)))
    sheet = Image.new("RGB", (max(a.width, b.width, c.width), a.height + b.height + c.height), E.BAR)
    sheet.paste(a, (0, 0))
    sheet.paste(b, (0, a.height))
    sheet.paste(c, (0, a.height + b.height))
    data = _png(sheet)
    out.write_bytes(data)
    return {"fighter": fam, "file": out.name, "bytes": len(data), "costumes": rows}


def select_patch_picture(mod, marker: dict, out: Path, picks: int = 240) -> dict:
    """The patched call path, the hook's disassembly, the pool table and simulated picks per fighter."""
    from PIL import Image, ImageDraw
    exe = mod.read("1ST_READ.BIN")
    rb = R.read_back(exe)
    f_h, f_t, f_m = E._font(22), E._font(15), E._font(13)
    W, H = 1700, 1110
    im = Image.new("RGB", (W, H), E.BAR)
    dr = ImageDraw.Draw(im)
    dr.text((20, 14), "DOA2 LE select screen: random costume on every confirmation (gbox.doa2_random_select)",
            fill=E.INK, font=f_h)
    dr.text((20, 44), f"installed={rb['installed']}  pool word {R.POOL_WORD:#010x} = {rb['pool_word']}  "
                      f"hook {R.HOOK:#010x}  table {R.TABLE:#010x}  routine sha256 {rb['routine_sha256'][:16]}",
            fill=E.MUTED, font=f_t)
    # call path
    boxes = [("confirm handler 0x8c0262e0", "r14 = cursor (+1 slot, +2 costume); plays SE 36"),
             ("jsr @r2  (0x8c02631c)", f"r2 = [{R.POOL_WORD:#x}]: was 0x8c02a1ca, now {R.HOOK:#x}"),
             ("HOOK 0x8c010100 (boot-header gap)", "slot = cursor[1]; if TABLE[slot].count:"),
             ("rand() 0x8c120cf0  ^  TMU0 TCNT", "r = low 15 bits; i = (r * count) >> 15"),
             ("cursor[2] = TABLE[slot].costume[i]", "registers, pr, macl restored"),
             ("jmp commit 0x8c02a1ca", "tables 0x8c239d50 / 0x8c239d64 -> loader, render script, actor")]
    y = 90
    for i, (a, b) in enumerate(boxes):
        dr.rectangle((20, y, 560, y + 62), outline=(110, 160, 255), width=2)
        dr.text((32, y + 8), a, fill=E.INK, font=f_t)
        dr.text((32, y + 34), b, fill=E.MUTED, font=f_m)
        if i < len(boxes) - 1:
            dr.line((290, y + 62, 290, y + 82), fill=(110, 160, 255), width=3)
            dr.polygon([(282, y + 74), (298, y + 74), (290, y + 84)], fill=(110, 160, 255))
        y += 84
    # disassembly
    try:
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_SH, capstone.CS_MODE_SH4 | capstone.CS_MODE_LITTLE_ENDIAN)
        code = exe[R.HOOK - R.BASE:R.HOOK - R.BASE + 0x70]
        lines = [f"{i.address:08x}  {i.mnemonic} {i.op_str}" for i in md.disasm(code, R.HOOK)]
    except ImportError:
        code = exe[R.HOOK - R.BASE:R.HOOK - R.BASE + 0x70]
        lines = [f"{R.HOOK + 2 * k:08x}  .word {w:04x}" for k, w in enumerate(np.frombuffer(code, '<u2'))]
    dr.text((590, 90), "hook (disassembled from the built 1ST_READ.BIN)", fill=E.INK, font=f_t)
    for k, ln in enumerate(lines):
        dr.text((590 + 250 * (k // 28), 116 + 15 * (k % 28)), ln, fill=E.INK, font=f_m)
    # pools + simulated picks
    x0, y0 = 590, 600
    dr.text((x0, y0 - 26), f"pool table and {picks} interpreted confirmations per fighter (hook + the game's rand())",
            fill=E.INK, font=f_t)
    dr.rectangle((x0, y0 - 4, x0 + 12, y0 + 8), fill=SA2_COLOUR)
    dr.text((x0 + 18, y0 - 6), "Sonic Adventure 2", fill=E.MUTED, font=f_m)
    dr.rectangle((x0 + 160, y0 - 4, x0 + 172, y0 + 8), fill=DS_COLOUR)
    dr.text((x0 + 178, y0 - 6), "Super Mario 64 DS", fill=E.MUTED, font=f_m)
    sim = {}
    seed = 0x5EED1652
    for row, entry in enumerate(marker["roster"]):
        y = y0 + 18 + row * 33
        slot = entry["render_slot"]
        by_idx = {p["render_costume"]: p for p in entry["pool"]}
        cnt = collections.Counter()
        for k in range(picks):
            r = R.simulate(exe, slot=slot, costume=0, player=k % 2, seed=seed, tcnt=(k * 2654435761) & 0xFFFFFFFF)
            seed = r["seed"]
            cnt[r["costume"]] += 1
        sim[entry["fighter"]] = dict(cnt)
        dr.text((x0, y + 4), f"{entry['name'][:12]:12s} slot {slot:2d}", fill=E.INK, font=f_m)
        bx = x0 + 150
        top_n = max(cnt.values()) if cnt else 1
        for idx in sorted(by_idx):
            p = by_idx[idx]
            n = cnt.get(idx, 0)
            col = DS_COLOUR if p["franchise"] == "SM64DS" else SA2_COLOUR
            w = 98
            dr.rectangle((bx, y, bx + w, y + 29), outline=col, width=1)
            dr.rectangle((bx + 1, y + 29 - int(27 * n / top_n), bx + 7, y + 28), fill=col)
            label = p["character"].replace("sm64ds_", "").replace("sa2_", "")[:10]
            dr.text((bx + 11, y + 1), f"#{idx} {label}", fill=E.INK, font=f_m)
            dr.text((bx + 11, y + 15), f"{n} picks", fill=E.MUTED, font=f_m)
            bx += w + 4
    for k, (a, b) in enumerate([("Only the gap 0x8c010100..0x8c010390 and one literal word change in 1ST_READ.BIN.", ""),
                                ("CPU picks keep the game's own random costume routine (0x8c02ac04).", ""),
                                ("Picks are interpreted from the built executable's bytes, not re-implemented.", "")]):
        dr.text((20, 610 + 22 * k), a, fill=E.MUTED, font=f_m)
    tag = "[offline render]"
    dr.rectangle((20, H - 34, 30 + E._text_w(dr, tag, f_m), H - 12), fill=E.KIND_COLOURS["offline render"])
    dr.text((24, H - 32), tag, fill=E.BAR, font=f_m)
    data = _png(im)
    out.write_bytes(data)
    return {"file": out.name, "bytes": len(data), "installed": rb["installed"], "simulated_picks": sim}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stock_gdi")
    ap.add_argument("mod_dir")
    ap.add_argument("library")
    ap.add_argument("out")
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    mod_dir, out, library = Path(a.mod_dir), Path(a.out), Path(a.library)
    out.mkdir(parents=True, exist_ok=True)
    marker = json.loads((mod_dir / ".gbox-mod.json").read_text(encoding="utf-8"))
    stock, mod = GDRom(a.stock_gdi), GDRom(mod_dir / marker["image"])
    reports = {(r["fighter"], r["costume"]): r for r in
               json.loads((mod_dir / "build-report.json").read_text(encoding="utf-8"))["costumes"]}
    only = {s.strip().upper() for s in a.only.split(",") if s.strip()}
    index = {"select_patch": select_patch_picture(mod, marker, out / "select_patch_logic.png"), "fighters": []}
    with tempfile.TemporaryDirectory() as tmp:
        for entry in marker["roster"]:
            if only and entry["fighter"] not in only:
                continue
            index["fighters"].append(fighter_sheet(entry, stock, mod, library, Path(tmp),
                                                   out / f"{entry['fighter']}_{entry['name'].replace(' ', '_')}.png",
                                                   reports))
            print(index["fighters"][-1]["file"], index["fighters"][-1]["bytes"], flush=True)
    (out / "evidence.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(json.dumps({"select_patch": index["select_patch"]["file"], "fighters": len(index["fighters"])}))


if __name__ == "__main__":
    main()
