"""Offline engine-emulation render of a SoulCalibur DC costume entry: engine_skin positions (rest pose), engine_light
intensities, strips with the game's winding, textures sampled from the costume's own pages by material & 3.
Back-facing triangles (per the game's winding) are drawn magenta when --show-back, else culled."""
import sys, os
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gbox import soulcalibur_dc as D

def costume_view(entry: bytes, yaw_deg: float, size=(240, 360), cull=True, light=True, mark_back=False):
    cp = D.costume_parts(entry)
    m = D.parse_model(cp["model"])
    pages = [D.page_rgb(p) for p in cp["pages"]]
    world = D.bone_world(m["bones"])
    P = D.engine_skin(m, world, dtype=np.float64)["positions"]
    Lw = np.array([[0.3, -0.5, -0.8]]); Lw /= np.linalg.norm(Lw)            # light travels down/back (game frame)
    I = D.engine_light(m, world, Lw)[:, 0]
    P = P @ D.FRAME.T                                                       # library frame (right-handed)
    c, s = np.cos(np.radians(yaw_deg)), np.sin(np.radians(yaw_deg))
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    Q = P @ R.T
    ok = np.isfinite(Q).all(1)
    lo = np.array([-1.3, -1.25]); hi = np.array([1.3, 1.45])               # fixed world box: same scale for all
    W, H = size
    sc = min(W / (hi[0] - lo[0]), H / (hi[1] - lo[1]))
    sx = (Q[:, 0] - lo[0]) * sc + (W - (hi[0] - lo[0]) * sc) / 2
    sy = H - ((Q[:, 1] - lo[1]) * sc)
    zb = np.full((H, W), -1e9); img = np.zeros((H, W, 3), np.uint8); img[:] = (38, 40, 48)
    stats = {"tris": 0, "back": 0, "nan": 0, "dark": 0}
    for sec in m["sections"]:
        for st in sec:
            page = pages[(st["material"] & 3) % len(pages)] if pages else None
            for a, b, cc in D.strip_triangles(len(st["pos"])):
                ids = [st["pos"][a], st["pos"][b], st["pos"][cc]]
                if len(set(ids)) < 3: continue
                stats["tris"] += 1
                if not ok[ids].all(): stats["nan"] += 1; continue
                nidx = [st["nrm"][a], st["nrm"][b], st["nrm"][cc]]
                uv = st["uv"][[a, b, cc]]
                x = sx[ids]; y = sy[ids]; z = Q[ids, 2]
                area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
                # game winding faces out in the game's (left-handed) space; mirrored to library + screen y down:
                front = area > 0
                if not front:
                    stats["back"] += 1
                    if cull and not mark_back: continue
                xi0, xi1 = int(max(0, np.floor(x.min()))), int(min(W - 1, np.ceil(x.max())))
                yi0, yi1 = int(max(0, np.floor(y.min()))), int(min(H - 1, np.ceil(y.max())))
                if xi1 < xi0 or yi1 < yi0 or abs(area) < 1e-9: continue
                gx, gy = np.meshgrid(np.arange(xi0, xi1 + 1) + .5, np.arange(yi0, yi1 + 1) + .5)
                w0 = ((x[1] - gx) * (y[2] - gy) - (x[2] - gx) * (y[1] - gy)) / area
                w1 = ((x[2] - gx) * (y[0] - gy) - (x[0] - gx) * (y[2] - gy)) / area
                w2 = 1 - w0 - w1
                inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
                if not inside.any(): continue
                zz = w0 * z[0] + w1 * z[1] + w2 * z[2]
                sub = zb[yi0:yi1 + 1, xi0:xi1 + 1]
                win = inside & (zz > sub)
                if not win.any(): continue
                if not front and mark_back:
                    col = np.array([255, 0, 255], float)[None, :]
                    cols = np.repeat(col, win.sum(), 0)
                else:
                    u = w0 * uv[0, 0] + w1 * uv[1, 0] + w2 * uv[2, 0]
                    v = w0 * uv[0, 1] + w1 * uv[1, 1] + w2 * uv[2, 1]
                    tx = (np.floor(u[win] * 256).astype(int)) % 256; ty = (np.floor(v[win] * 256).astype(int)) % 256
                    cols = page[ty, tx].astype(float) if page is not None else np.full((win.sum(), 3), 200.)
                    if light:
                        li = np.nan_to_num(I[nidx], nan=0.0)
                        lv = (w0 * li[0] + w1 * li[1] + w2 * li[2])[win]
                        cols = cols * np.clip(0.35 + 0.8 * lv, 0, 1.3)[:, None]
                sub[win] = zz[win]
                blk = img[yi0:yi1 + 1, xi0:xi1 + 1]
                blk[win] = np.clip(cols, 0, 255).astype(np.uint8)
    return Image.fromarray(img), stats

def sheet(entries, labels, out, mark_back=False):
    tiles = []
    for e, lab in zip(entries, labels):
        row = []
        for yaw in (0, 180):
            im, stt = costume_view(e, yaw, mark_back=mark_back)
            d = ImageDraw.Draw(im); d.text((4, 4), f"{lab} {'front' if yaw == 0 else 'back'}", fill=(240, 240, 240))
            d.text((4, 16), f"tris {stt['tris']} back {stt['back']} nan {stt['nan']}", fill=(200, 200, 200))
            row.append(im)
        tiles.append(row)
    W, H = tiles[0][0].size
    S = Image.new("RGB", (W * 2 * len(tiles), H))
    for i, row in enumerate(tiles):
        for j, im in enumerate(row):
            S.paste(im, ((i * 2 + j) * W, 0))
    S.save(out, optimize=True)
    return out

if __name__ == "__main__":
    from gbox.gdrom import GDRom
    stock = D.olnk(GDRom("D:/gBox/cache/dc/c747331797369f74/disc.gdi").read(D.HUMAN))
    built = D.olnk(GDRom(sys.argv[1]).read(D.HUMAN))
    outdir = sys.argv[2]; os.makedirs(outdir, exist_ok=True)
    only = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[3] else None
    mark = os.environ.get("MARK_BACK") == "1"
    for g, k, name, _a in D.FIGHTERS:
        for c in D.costumes_of(stock, g):
            if only and f"{k}{c}" not in only and k not in only: continue
            e = g * D.GROUP + c
            sheet([stock[e], built[e]], [f"{k}{c} stock", f"{k}{c} built"], os.path.join(outdir, f"{k.lower()}{c}.png"), mark)
            print(k, c, flush=True)
