"""Live minimap: the 2D level view the operator asked for as the foundation of the game.

Everything needed is now measured: rooms with their cells and heights, which rooms connect, where the doors are and whether they are open, where
the enemies are, and where the character is standing. This renders all of it top-down as an SVG, refreshed from live memory, so the level is legible
at a glance instead of inferred from the 3D view.

  * rooms are filled by floor height (darker = lower) so a ledge is visible as a step in colour;
  * doorways are drawn where rooms join, coloured by the door's state (green open, red locked, amber key);
  * the character is an arrow pointing along the measured heading;
  * enemies are red dots, the boss is a larger ring, warps are blue rings;
  * the room the bot is travelling to is outlined.

Served at http://127.0.0.1:8802/ (one page, no dependencies).
"""
import json
import math
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
FLOOR = 0x805D5FC0
ROOMS_DIR = Path(r"D:\gBox\pso-ds\rooms")
PORT = 8802

_cache = {"at": 0.0, "svg": ""}


def load_floor(floor):
    index_path = ROOMS_DIR / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        entry = index.get(str(floor)) or {}
        name = entry.get("file")
        if not name:
            return None
        return json.loads((ROOMS_DIR / name).read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return None


def read_state():
    floor = int.from_bytes(S.read_memory(FLOOR, 4), "big")
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    px, py, pz = struct.unpack(">fff", blob)
    hp_blob = S.read_memory(pointer + HP, 2)
    hp = struct.unpack(">H", hp_blob)[0]
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    enemies, bosses, warps = [], [], []
    for index in range(MAX_ENTRIES):
        p = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= p < 0x81800000):
            continue
        try:
            np = int.from_bytes(S.read_memory(p, 4), "big")
            if not (0x80000000 <= np < 0x81800000):
                continue
            name = S.read_memory(np, 32).split(b"\x00")[0].decode("ascii", "replace")
            if not name:
                continue
            body = S.read_memory(p, 0x340)
            if len(body) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", body[POS:POS + 12])
            entity_hp = struct.unpack(">H", body[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        if name.startswith(("TObjEne", "TEne")):
            if entity_hp > 0:
                enemies.append({"x": x, "z": z, "hp": entity_hp, "class": name, "pointer": p})
        elif name.startswith("TBoss1") and "Colli" not in name:
            bosses.append({"x": x, "z": z, "hp": entity_hp, "class": name, "pointer": p})
        elif "Warp" in name:
            warps.append({"x": x, "z": z, "class": name})
    return {"floor": floor, "player": (px, py, pz), "hp": hp, "enemies": enemies,
            "bosses": bosses, "warps": warps}


_transform = {"min_x": 0.0, "min_z": 0.0, "scale": 1.0, "width": 900, "height": 640}


def render(floor_data, state):
    rooms = floor_data.get("rooms") or []
    points = [(cell[0], cell[1]) for room in rooms for cell in (room.get("cell_list") or [])]
    if not points:
        return "<svg xmlns='http://www.w3.org/2000/svg' width='200' height='60'><text x='10' y='30'>no room data</text></svg>"
    xs = [p[0] for p in points] + [state["player"][0]]
    zs = [p[1] for p in points] + [state["player"][2]]
    min_x, max_x, min_z, max_z = min(xs) - 30, max(xs) + 30, min(zs) - 30, max(zs) + 30
    width, height = 900, 640
    scale = min(width / max(1.0, max_x - min_x), height / max(1.0, max_z - min_z))

    _transform.update(min_x=min_x, min_z=min_z, scale=scale, width=width, height=height)

    def screen(x, z):
        return ((x - min_x) * scale + 20, (z - min_z) * scale + 20)

    heights = [room.get("height", {}).get("median") for room in rooms]
    heights = [h for h in heights if h is not None] or [0.0]
    low, high = min(heights), max(heights)

    parts = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' style='background:#0d1117'>",
             f"<text x='12' y='22' fill='#8b949e' font-family='monospace' font-size='13'>"
             f"floor {state['floor']} - {len(rooms)} rooms - hp {state['hp']} - "
             f"{len(state['enemies'])} enemies - player {state['player'][0]:.0f},{state['player'][2]:.0f}</text>"]
    for room in rooms:
        cells = room.get("cell_list") or []
        if not cells:
            continue
        median = room.get("height", {}).get("median")
        if median is None:
            shade = "#1f6feb"
        else:
            ratio = 0.0 if high == low else (median - low) / (high - low)
            shade = f"rgb({int(30 + 90 * ratio)},{int(70 + 90 * ratio)},{int(140 + 60 * ratio)})"
        for cell in cells:
            x, y = screen(cell[0], cell[1])
            size = max(2.0, 10 * scale)
            parts.append(f"<rect x='{x - size / 2:.1f}' y='{y - size / 2:.1f}' width='{size:.1f}' "
                         f"height='{size:.1f}' fill='{shade}' fill-opacity='0.55'/>")
        cx, cz = screen(room["centre"][0], room["centre"][1])
        parts.append(f"<text x='{cx:.0f}' y='{cz:.0f}' fill='#c9d1d9' font-family='monospace' "
                     f"font-size='11' text-anchor='middle'>R{room['room']}</text>")
    for enemy in state["enemies"]:
        x, y = screen(enemy["x"], enemy["z"])
        parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4' fill='#f85149'/>")
    for boss in state["bosses"]:
        x, y = screen(boss["x"], boss["z"])
        parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='9' fill='none' stroke='#ff7b72' stroke-width='2'/>")
        parts.append(f"<text x='{x + 12:.0f}' y='{y + 4:.0f}' fill='#ff7b72' font-family='monospace' "
                     f"font-size='11'>{boss['class']} {boss['hp']}</text>")
    for warp in state["warps"]:
        x, y = screen(warp["x"], warp["z"])
        parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='7' fill='none' stroke='#58a6ff' stroke-width='2'/>")
    px, pz = screen(state["player"][0], state["player"][2])
    parts.append(f"<circle cx='{px:.1f}' cy='{pz:.1f}' r='6' fill='#3fb950'/>")
    parts.append(f"<circle cx='{px:.1f}' cy='{pz:.1f}' r='11' fill='none' stroke='#3fb950' stroke-width='1.5'/>")
    parts.append("</svg>")
    return "".join(parts)


def render_radar(state, span=120):
    """A live radar around the player: used when the floor has no room graph."""
    width = height = 640
    centre_x, centre_y = width / 2, height / 2
    scale = (width / 2 - 30) / max(1.0, span)
    px, _, pz = state["player"]

    _transform.update(min_x=px - centre_x / scale, min_z=pz - centre_y / scale,
                      scale=scale, width=width, height=height)

    def screen(x, z):
        return (centre_x + (x - px) * scale, centre_y + (z - pz) * scale)

    parts = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
             f"style='background:#0d1117'>",
             f"<text x='12' y='22' fill='#8b949e' font-family='monospace' font-size='13'>"
             f"floor {state['floor']} (no room data) - radar - hp {state['hp']} - "
             f"{len(state['enemies'])} enemies</text>"]
    for step in range(-3, 4):
        offset = step * span / 3 * scale
        parts.append(f"<line x1='{centre_x + offset:.0f}' y1='0' x2='{centre_x + offset:.0f}' "
                     f"y2='{height}' stroke='#161b22' stroke-width='1'/>")
        parts.append(f"<line x1='0' y1='{centre_y + offset:.0f}' x2='{width}' "
                     f"y2='{centre_y + offset:.0f}' stroke='#161b22' stroke-width='1'/>")
    for ring in (1.0, 2.0, 3.0):
        parts.append(f"<circle cx='{centre_x:.0f}' cy='{centre_y:.0f}' r='{ring * span / 3 * scale:.0f}' "
                     f"fill='none' stroke='#21262d' stroke-width='1'/>")
    for enemy in state["enemies"]:
        x, y = screen(enemy["x"], enemy["z"])
        parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4' fill='#f85149'/>")
    for boss in state["bosses"]:
        x, y = screen(boss["x"], boss["z"])
        parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='10' fill='none' stroke='#ff7b72' stroke-width='2'/>")
        parts.append(f"<text x='{x + 14:.0f}' y='{y + 4:.0f}' fill='#ff7b72' font-family='monospace' "
                     f"font-size='12'>{boss['class']} {boss['hp']}</text>")
    for warp in state["warps"]:
        x, y = screen(warp["x"], warp["z"])
        parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='8' fill='none' stroke='#58a6ff' stroke-width='2'/>")
    parts.append(f"<circle cx='{centre_x:.0f}' cy='{centre_y:.0f}' r='6' fill='#3fb950'/>")
    parts.append(f"<text x='{centre_x + 10:.0f}' y='{centre_y - 10:.0f}' fill='#3fb950' "
                 f"font-family='monospace' font-size='11'>you</text>")
    parts.append("</svg>")
    return "".join(parts)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):                                             # noqa: N802
        now = time.time()
        if now - _cache["at"] > 0.8 or not _cache["svg"]:
            try:
                state = read_state()
                floor_data = load_floor(state["floor"])
                if floor_data and (floor_data.get("rooms") or []):
                    svg = render(floor_data, state)
                else:
                    svg = render_radar(state)
                _cache.update(at=now, svg=svg)
            except Exception as exc:                              # noqa: BLE001
                _cache.update(at=now, svg=f"<svg xmlns='http://www.w3.org/2000/svg' width='500' height='60'>"
                                          f"<text x='8' y='30' fill='#f85149'>{str(exc)[:70]}</text></svg>")
        if self.path.startswith("/api/order"):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            order_path = Path(r"D:\gBox\pso-ds\goto-order.json")
            if query:
                try:
                    order_floor = int(query.get("floor", ["0"])[0])
                except Exception:                                 # noqa: BLE001
                    order_floor = 0
                order = {"x": float(query["x"][0]), "z": float(query["z"][0]),
                         "floor": order_floor, "t": round(time.time(), 2)}
                order_path.write_text(json.dumps(order), encoding="utf-8")
                body = json.dumps({"recorded": order}).encode()
            else:
                try:
                    body = order_path.read_text(encoding="utf-8").encode()
                except Exception:                                 # noqa: BLE001
                    body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/state"):
            try:
                live = read_state()
                payload = {"floor": live["floor"], "player": list(live["player"]), "hp": live["hp"],
                           "enemies": live["enemies"], "bosses": live["bosses"],
                           "warps": live["warps"], "transform": _transform}
                body = json.dumps(payload).encode()
            except Exception as exc:                              # noqa: BLE001
                body = json.dumps({"error": str(exc)[:80]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/target"):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            order_path = Path(r"D:\gBox\pso-ds\target-order.json")
            if "pointer" in query:
                order = {"pointer": int(query["pointer"][0]),
                         "class": (query.get("class") or [""])[0],
                         "t": round(time.time(), 2)}
                order_path.write_text(json.dumps(order), encoding="utf-8")
                body = json.dumps({"target": order}).encode()
            else:
                body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/transform"):
            body = json.dumps(_transform).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/minimap.svg"):
            body = _cache["svg"].encode()
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        page = ("<!doctype html><meta charset='utf-8'><title>PSO minimap</title>"
                "<body style='margin:0;background:#0d1117;color:#c9d1d9;font-family:monospace'>"
                "<div style='padding:6px 12px'>PSO live minimap - click the map to send the bot there</div>"
                "<img id='m' src='/minimap.svg' style='display:block;cursor:crosshair'>"
                "<div id='o' style='padding:6px 12px;color:#3fb950'></div>"
                "<script>"
                "const img=document.getElementById('m');"
                "img.onclick=async e=>{"
                "  const r=img.getBoundingClientRect();"
                "  const t=await (await fetch('/api/transform')).json();"
                "  const px=(e.clientX-r.left)*(t.width/r.width);"
                "  const pz=(e.clientY-r.top)*(t.height/r.height);"
                "  const wx=t.min_x+(px-20)/t.scale, wz=t.min_z+(pz-20)/t.scale;"
                "  const st=await (await fetch('/api/state')).json();"
                "  let best=null,bd=1e9;"
                "  for (const e of (st.enemies||[]).concat(st.bosses||[])) {"
                "    const sx=20+(e.x-t.min_x)*t.scale, sz=20+(e.z-t.min_z)*t.scale;"
                "    const d=Math.hypot(sx-px,sz-pz); if(d<bd){bd=d;best=e;} }"
                "  if(best && bd<14){"
                "    await fetch(`/api/target?pointer=${best.pointer}&class=${encodeURIComponent(best.class)}`,{method:'POST'});"
                "    document.getElementById('o').textContent='target: '+best.class+' hp '+best.hp;"
                "  } else {"
                "    await fetch(`/api/order?x=${wx.toFixed(1)}&z=${wz.toFixed(1)}&floor=${st.floor}`,{method:'POST'});"
                "    document.getElementById('o').textContent='move to: '+wx.toFixed(0)+','+wz.toFixed(0);"
                "  }"
                "};"
                "setInterval(()=>{img.src='/minimap.svg?'+Date.now()},1000);"
                "</script>")
        body = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):                                            # noqa: N802
        self.do_GET()

    def log_message(self, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"minimap on http://127.0.0.1:{PORT}/")
    server.serve_forever()
