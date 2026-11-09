"""Build a uEm10 archive whose high `em1000` model carries Sonic geometry in every LOD0 part.

The high `em1000` entry is written through its own part table (formats/strides/counts preserved), then the archive is
ready to be placed under the uEm11 class with the IPS class rebind (`gbox.re5_ips`). zlib level 6 is required; level 9
streams are rejected by the title's low loader.

Run on the Spark:
    python3 re5_em10_high_sonic.py
Writes /tmp/em10_high_sonic.arc and /tmp/em10_high_sonic.bin.
"""
import sys, zlib, struct
sys.path.insert(0, '/home/ehm_eckx/gBox/system')
import numpy as np
from pathlib import Path
from gbox import mt_arc, mt_model, characters, mtf_fit

ROOT = Path('/home/ehm_eckx/gBox_alt/switch/romfs/010018100CD46000/nativeNXx64/ImgNX/Archive')
SONIC = Path('/home/ehm_eckx/gBox_alt/gbox-cache/characters/sonic/sa2_sonic_0.glb')
FORMATS = {0x2000D414: 28, 0x1580B60C: 20, 0x18B0FAA8: 20, 0x1C201FC3: 24}


def sonic_mesh():
    gl, acc, img, world = characters._load(SONIC)
    skin = max(gl.get('skins') or [], key=lambda s: len(s['joints']))
    joints = list(skin['joints']); ordinal = {n: i for i, n in enumerate(joints)}
    P = []; N = []; UV = []; J = []; W = []; T = []
    for node in gl.get('nodes') or []:
        if 'mesh' not in node:
            continue
        if 'skin' in node and gl['skins'][node['skin']] is not skin:
            continue
        for prim in gl['meshes'][node['mesh']]['primitives']:
            a = prim['attributes']
            if 'POSITION' not in a:
                continue
            p = acc(a['POSITION']).astype(float)
            n = acc(a['NORMAL']).astype(float) if 'NORMAL' in a else np.tile([0., 1, 0], (len(p), 1))
            uv = acc(a['TEXCOORD_0']).astype(float) if 'TEXCOORD_0' in a else np.zeros((len(p), 2))
            if 'JOINTS_0' in a and 'WEIGHTS_0' in a:
                j = acc(a['JOINTS_0']).astype(int); w = acc(a['WEIGHTS_0']).astype(float)
                mapped = np.array([[ordinal.get(int(joints[k]), 0) for k in row] for row in j], int)
            else:
                mapped = np.zeros((len(p), 4), int); w = np.zeros((len(p), 4), float); w[:, 0] = 1
            base = sum(len(x) for x in P); P.append(p); N.append(n); UV.append(uv); J.append(mapped); W.append(w)
            idx = acc(prim['indices']).astype(int).reshape(-1, 3) if 'indices' in prim else np.arange(len(p), dtype=int).reshape(-1, 3)
            T.append(idx + base)
    return np.concatenate(P), np.concatenate(N), np.concatenate(UV), np.concatenate(J), np.concatenate(W), np.concatenate(T), gl, joints


def map_bones(gl, joints, m):
    src = mtf_fit.glb_roles(gl); roles = m.bone_roles(); tp = m.bone_world()
    mapping = mtf_fit.match(src, roles, tp)
    scale = roles['height'] / max(src['height'], 1e-9)
    ground = min(p[1] for p in tp)
    low = src['positions'][src['lowest']][1]
    inv = {}
    for i, node in enumerate(joints):
        if node in mapping:
            inv[i] = mapping[node]
        else:
            pos = np.array(src['positions'].get(node, [0, 0, 0])) * scale + np.array([0, ground - low * scale, 0])
            inv[i] = min(tp, key=lambda p: (p[1] - pos[0]) ** 2 + (p[2] - pos[1]) ** 2 + (p[3] - pos[2]) ** 2)[0]
    return inv, scale, ground, low, roles


def build(arc_name='uEm10.arc', model_name='em1000'):
    arc = mt_arc.parse((ROOT / arc_name).read_bytes()); idx = e0 = raw = m = None
    for i, e in enumerate(arc.entries):
        try:
            r = zlib.decompress(e.data)
        except Exception:
            continue
        if r[:4] == mt_model.MOD_MAGIC and model_name in e.name:
            idx, e0, raw, m = i, e, r, mt_model.parse_mod(r)
            break
    if m is None:
        raise SystemExit('model not found')
    P, N, UV, J, W, T, gl, joints = sonic_mesh(); inv, scale, ground, low, roles = map_bones(gl, joints, m)
    ymin = P[:, 1].min(); ymax = P[:, 1].max(); s = roles['height'] / max(ymax - ymin, 1e-9)
    b = m.bounds()
    cx = 0.5 * (b['min']['x'] + b['max']['x']); cz = 0.5 * (b['min']['z'] + b['max']['z'])
    pos = (P - np.array([0, ymin, 0])) * s + np.array([cx, ground, cz])
    dom = np.array([inv[int(J[k, np.argmax(W[k])])] for k in range(len(P))])
    recs = m.meshes(); h = m.header()
    order = sorted([i for i in range(len(recs)) if recs[i]['level_of_detail'] == 0],
                   key=lambda i: (0 if recs[i]['vertex_format'] == 0x2000D414 else
                                  1 if recs[i]['vertex_format'] == 0x1580B60C else
                                  2 if recs[i]['vertex_format'] == 0x18B0FAA8 else 9,
                                  -recs[i]['vertex_count']))
    parts = []; cap = 0
    for i in order:
        if recs[i]['vertex_format'] not in FORMATS or recs[i]['vertex_count'] < 3:
            continue
        parts.append(i); cap += recs[i]['vertex_count']
    print('parts', len(parts), 'cap', cap, 'sonic verts', len(P), 'tris', len(T))
    local = {i: [] for i in parts}; lut = {i: {} for i in parts}; tri_parts = {i: [] for i in parts}; cursor = 0
    for tri in T:
        placed = False
        for k in range(len(parts)):
            pi = parts[(cursor + k) % len(parts)]
            new = sum(1 for v in tri if int(v) not in lut[pi])
            if len(local[pi]) + new <= recs[pi]['vertex_count'] - 3:
                cursor = (cursor + k + 1) % len(parts); placed = True
                for v in tri:
                    v = int(v)
                    if v not in lut[pi]:
                        lut[pi][v] = len(local[pi]); local[pi].append(v)
                tri_parts[pi].append(tuple(lut[pi][int(v)] for v in tri))
                break
        if not placed:
            print('ran out of slots at tri', len(T)); break
    out = bytearray(raw); face_at = 0
    for pi in parts:
        rec = recs[pi]; n = rec['vertex_count']; stride = rec['vertex_stride']; fmt = rec['vertex_format']
        base_off = h['offsets']['vertex_buffer'] + rec['vertex_offset'] + rec['vertex_index'] * stride
        base = raw[base_off:base_off + n * stride]
        verts = []
        for k in range(n):
            sv = local[pi][k] if k < len(local[pi]) else (local[pi][-1] if local[pi] else None)
            if sv is None:
                verts.append({'position': (cx, ground, cz), 'normal': (0, 1, 0), 'uv': (0, 0), 'bones': [0], 'bounds': b})
            else:
                nv = N[sv] / max(np.linalg.norm(N[sv]), 1e-9)
                verts.append({'position': tuple(pos[sv]), 'normal': tuple(nv), 'uv': tuple(UV[sv]), 'bounds': b})
        out[base_off:base_off + n * stride] = mt_model.pack_vertices(verts, fmt, stride, base=base)
        fi = rec['face_index']; vb = rec['vertex_index']; ib = bytearray()
        for (a, c, d) in tri_parts[pi]:
            ib += struct.pack('<4H', a + vb, c + vb, d + vb, 0xFFFF)
        rec_off = h['offsets']['meshes'] + pi * 56
        struct.pack_into('<I', out, rec_off + 0x1c, max(0, len(ib) // 2 - 1))
        ib_off = h['offsets']['index_buffer'] + 2 * fi
        out[ib_off:ib_off + len(ib)] = ib
        face_at += len(ib) // 2
    print('total face_at', face_at, 'header face_count', h['face_count'])
    new = bytes(out)
    new_arc = mt_arc.replace_at((ROOT / arc_name).read_bytes(), idx, zlib.compress(new, 6)[2:-4])
    Path('/tmp/em10_high_sonic.arc').write_bytes(new_arc)
    Path('/tmp/em10_high_sonic.bin').write_bytes(new)
    print('wrote', len(new_arc), len(new))


if __name__ == '__main__':
    build()
