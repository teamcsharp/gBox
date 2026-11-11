"""Live PSO map viewer: a top-down view of the level, the bot and the enemies, with click-to-command.

Serves a small page on http://127.0.0.1:8801/ :
  * rooms from the collision graph (forest1-rooms.json) drawn as the level floor,
  * doors coloured by their RAM state (green = unlocked/cleared, red = locked, blue = key door),
  * enemies as red triangles, the player as a yellow arrow,
  * the live minimap crop as an inset (refreshed from the newest capture),
  * click anywhere to give the bot a waypoint, click an enemy to make it the target.

Commands go to D:\\gBox\\pso-ds\\goto.json, which map_bot.py follows. Everything is read-only on the game except the bot's own input,
which is gated by pso_operator so it never fights the operator.
"""
import json
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:18765"
SID = "78a8746f5b514450-e9867839b8b74d3d"
PORT = 8801
ROOMS = Path(r"D:\gBox\pso-ds\routes\forest1-rooms.json")
ROUTES = Path(r"D:\gBox\pso-ds\routes")
OBJECTS = Path(r"D:\gBox\pso-ds\routes\set-objects-floors.json")
GOTO = Path(r"D:\gBox\pso-ds\goto.json")
DEMO = Path(r"D:\gBox\pso-ds\demo")
TABLE, MAX_ENTRIES, HP = 0x8050D460, 256, 0x32C
FLOOR = 0x805D5FC0

_cache = {"rooms": None, "rooms_mtime": 0.0}


def _read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    for _ in range(1):
        try:
            req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                                  "content-type": "application/json"})
            return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=2.5).read() or b'""'))
        except Exception:                                        # noqa: BLE001
            time.sleep(0.05)
    return b""


def _cstring(address, limit=40):
    raw = _read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def rooms(floor=1):
    """Rooms for a floor: the mesh segmentation when it exists, else the original Forest 1 graph."""
    sources = [ROUTES / f"forest{floor}-rooms-mesh.json", ROUTES / f"forest{floor}-rooms.json"]
    if floor == 1:
        sources.append(ROOMS)
    for path in sources:
        try:
            mtime = path.stat().st_mtime
            cache_key = f"rooms{floor}"
            if _cache.get(cache_key) is None or _cache.get(cache_key + "_mtime") != mtime:
                _cache[cache_key] = json.loads(path.read_text(encoding="utf-8"))
                _cache[cache_key + "_mtime"] = mtime
            return _cache[cache_key]
        except Exception:                                        # noqa: BLE001
            continue
    return {"rooms": [], "doors": []}


def _u32(address):
    blob = _read(address, 4)
    return int.from_bytes(blob, "big") if len(blob) == 4 else 0


def _u16(address):
    blob = _read(address, 2)
    return int.from_bytes(blob, "big") if len(blob) == 2 else None


def _vec3(address):
    blob = _read(address, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def state():
    payload = {"t": time.time(), "floor": _u32(FLOOR), "player": None, "hp": None, "doors": [], "enemies": []}
    if payload["floor"] is None:
        # no live session: answer immediately so the page still shows the cached map instead of hanging
        payload["live"] = False
        payload["why"] = "no running PSO session"
        return payload
    payload["live"] = True
    actor = _u32(0x8050EA10)
    if actor:
        point = _vec3(actor + 0x38)
        if point:
            x, y, z = point
            payload["player"] = {"x": round(x, 1), "y": round(y, 1), "z": round(z, 1)}
        payload["hp"] = _u16(actor + HP)
    raw = _read(TABLE, MAX_ENTRIES * 4)
    if len(raw) < MAX_ENTRIES * 4:
        return payload
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(_read(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = _cstring(name_pointer)
        if name.startswith("TObjDoor"):
            blob = _read(pointer, 0x190)
            if len(blob) >= 0x190:
                x, _y, z = struct.unpack(">fff", blob[0x38:0x44])
                payload["doors"].append({"i": index, "class": name, "x": round(x, 1), "z": round(z, 1),
                                         "state": struct.unpack(">i", blob[0x18C:0x190])[0]})
        elif name.startswith("TObjEne"):
            point = _vec3(pointer + 0x38)
            if point:
                x, y, z = point
                hp = _u16(pointer + HP)
                payload["enemies"].append({"class": name, "x": round(x, 1), "z": round(z, 1), "hp": hp})
    return payload


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>PSO live map</title>
<style>
body{margin:0;background:#0d1117;color:#c9d1d9;font:13px/1.4 Consolas,monospace}
#wrap{display:flex;gap:10px;padding:8px}
canvas{background:#161b22;border:1px solid #30363d;border-radius:6px}
#side{width:300px}
#side img{width:100%;border:1px solid #30363d;border-radius:6px}
h3{margin:6px 0;color:#58a6ff;font-size:13px}
.k{color:#8b949e}
</style></head><body>
<div id="wrap">
 <div><canvas id="map" width="880" height="700"></canvas></div>
 <div id="side">
  <h3>PSO live map</h3>
  <div><span class="k">floor</span> <b id="floor">-</b> &nbsp; <span class="k">view</span>
    <select id="viewfloor" style="background:#0d1117;color:#c9d1d9;border:1px solid #30363d">
      <option value="1">Forest 1</option><option value="2">Forest 2</option>
    </select> &nbsp; <span class="k">hp</span> <b id="hp">-</b></div>
  <div><span class="k">pos</span> <b id="pos">-</b></div>
  <div><span class="k">target</span> <b id="target">none</b></div>
  <div id="roominfo" style="margin-top:6px;color:#8b949e">-</div>
  <div style="margin-top:8px"><label class="k"><input type="checkbox" id="placemode"> place</label>
    <span class="k">record</span> <input id="placerecord" value="3" size="4"
      style="background:#0d1117;color:#c9d1d9;border:1px solid #30363d;width:48px">
    <span class="k" id="placeresult"></span></div>
  <div><span class="k">doors</span> <b id="doors">-</b> <span class="k">enemies</span> <b id="enemies">-</b></div>
  <h3>live minimap</h3>
  <img id="mini" src="/api/minimap.png" alt="minimap">
  <p class="k">Click the map to send the bot there. Shift+click an enemy to target it.</p>
 </div>
</div>
<script>
let rooms=null, st=null, scale=0.55, ox=0, oz=0;
let objects=null, roomObjects={};
function fit(){
  if(!rooms || !rooms.rooms.length) return;
  const cells=[]; rooms.rooms.forEach(r=>r.cell_list.forEach(c=>cells.push(c)));
  const xs=cells.map(c=>c[0]), zs=cells.map(c=>c[1]);
  const minx=Math.min(...xs), maxx=Math.max(...xs), minz=Math.min(...zs), maxz=Math.max(...zs);
  const cw=document.getElementById('map').width, ch=document.getElementById('map').height, pad=20;
  scale=Math.min((cw-2*pad)/(maxx-minx||1),(ch-2*pad)/(maxz-minz||1));
  ox=pad-minx*scale; oz=pad-minz*scale;
  document.getElementById('map').dataset.minx=minx;
}
function X(x){return ox+x*scale;} function Y(z){return oz+z*scale;}
function draw(){
  const cv=document.getElementById('map'), ctx=cv.getContext('2d');
  ctx.clearRect(0,0,cv.width,cv.height);
  if(rooms){
    const shades=['#1f6feb','#2ea043','#8957e5','#d29922','#db6d28','#39c5cf','#f85149','#a5d6ff'];
    rooms.rooms.forEach((r,i)=>{
      ctx.fillStyle=shades[i%shades.length]; ctx.globalAlpha=0.18;
      r.cell_list.forEach(c=>ctx.fillRect(X(c[0])-scale*5,Y(c[1])-scale*5,scale*10,scale*10));
    });
    ctx.globalAlpha=1;
    rooms.doors.forEach(d=>{
      const unlocked=(d.state===2||d.state===240);
      ctx.fillStyle = d.class.indexOf('Key')>=0 ? '#79c0ff' : (unlocked ? '#3fb950' : '#f85149');
      ctx.beginPath(); ctx.arc(X(d.x),Y(d.z),6,0,7); ctx.fill();
    });
    if(objects && objects.objects){
      objects.objects.forEach(o=>{
        ctx.fillStyle = o.class.indexOf('Sensor')>=0 ? '#8b949e'
                      : (o.class.indexOf('Rock')>=0 ? '#6e7681'
                      : (o.class.indexOf('Symbolchat')>=0 ? '#d2a8ff' : '#58a6ff'));
        ctx.fillRect(X(o.x)-2, Y(o.z)-2, 4, 4);
      });
    }
  }
  if(st){
    st.doors.forEach(d=>{
      const unlocked=(d.state===2||d.state===240);
      ctx.strokeStyle = d.class.indexOf('Key')>=0 ? '#79c0ff' : (unlocked ? '#3fb950' : '#f85149');
      ctx.lineWidth=2; ctx.beginPath(); ctx.arc(X(d.x),Y(d.z),9,0,7); ctx.stroke();
    });
    st.enemies.forEach(e=>{
      ctx.fillStyle='#ff7b72'; ctx.beginPath();
      ctx.moveTo(X(e.x),Y(e.z)-7); ctx.lineTo(X(e.x)-6,Y(e.z)+5); ctx.lineTo(X(e.x)+6,Y(e.z)+5); ctx.closePath(); ctx.fill();
      ctx.fillStyle='#8b949e'; ctx.fillText(e.hp, X(e.x)-4, Y(e.z)-10);
    });
    if(st.player){
      ctx.fillStyle='#f2cc60'; ctx.beginPath();
      ctx.arc(X(st.player.x),Y(st.player.z),7,0,7); ctx.fill();
      ctx.strokeStyle='#f2cc60'; ctx.beginPath(); ctx.arc(X(st.player.x),Y(st.player.z),12,0,7); ctx.stroke();
    }
  }
  requestAnimationFrame(()=>{});
}
let viewFloor = 1;
document.getElementById('viewfloor').addEventListener('change', ev=>{ viewFloor = +ev.target.value; rooms = null; });
async function loadObjects(){
  try{
    objects = await (await fetch('/api/objects?floor='+viewFloor)).json();
    roomObjects = {};
    (objects.objects||[]).forEach(o=>{
      let best={d:1e9, r:null};
      rooms.rooms.forEach(r=>r.cell_list.forEach(c=>{
        const d=Math.hypot(o.x-c[0], o.z-c[1]);
        if(d<best.d) best={d:d, r:r.room};
      }));
      if(best.r!==null){ (roomObjects[best.r]=roomObjects[best.r]||[]).push(o.class); }
    });
  }catch(e){ objects=null; roomObjects={}; }
}
async function tick(){
  try{
    if(!rooms){ rooms = await (await fetch('/api/rooms?floor='+viewFloor)).json(); fit(); await loadObjects(); }
    st = await (await fetch('/api/state')).json();
    if(st.player){ document.getElementById('pos').textContent = st.player.x+', '+st.player.y+', '+st.player.z; }
    document.getElementById('floor').textContent = st.floor;
    document.getElementById('hp').textContent = st.hp;
    document.getElementById('doors').textContent = st.doors.length;
    document.getElementById('enemies').textContent = st.enemies.length;
    draw();
  }catch(e){}
  setTimeout(tick, 700);
}
document.getElementById('map').addEventListener('click', async ev=>{
  const rect=ev.target.getBoundingClientRect();
  const px=ev.clientX-rect.left, py=ev.clientY-rect.top;
  const wx=(px-ox)/scale, wz=(py-oz)/scale;
  if(document.getElementById('placemode') && document.getElementById('placemode').checked){
    const record=parseInt(document.getElementById('placerecord').value||'0',10);
    const result=await (await fetch('/api/place',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({floor:viewFloor, record:record, x:Math.round(wx), y:0, z:Math.round(wz)})})).json();
    document.getElementById('placeresult').textContent = result.ok
      ? 'placed in room '+result.room+' ('+result.distance+' units)'
      : 'refused: '+(result.why||'unknown');
    return;
  }
  let target={x:Math.round(wx), z:Math.round(wz)};
  if(rooms){
    let bestRoom={d:1e9, r:null};
    rooms.rooms.forEach(r=>r.cell_list.forEach(c=>{
      const d=Math.hypot(wx-c[0], wz-c[1]);
      if(d<bestRoom.d) bestRoom={d:d, r:r};
    }));
    const info=document.getElementById('roominfo');
    if(info){
      if(bestRoom.r && bestRoom.d<25){
        const counts={};
        (roomObjects[bestRoom.r.room]||[]).forEach(n=>counts[n]=(counts[n]||0)+1);
        const text=Object.entries(counts).map(([n,c])=>n+' x'+c).join(', ') || 'no placed objects';
        info.textContent = 'room '+bestRoom.r.room+' ('+bestRoom.r.cells+' cells, centre '
          +bestRoom.r.centre[0]+','+bestRoom.r.centre[1]+'): '+text;
      } else { info.textContent = '-'; }
    }
  }
  if(ev.shiftKey && st){
    let best=null;
    st.enemies.forEach(e=>{ const d=Math.hypot(X(e.x)-px,Y(e.z)-py); if(!best||d<best.d) best={d,e}; });
    if(best && best.d<25){ target={enemy:best.e.class, x:best.e.x, z:best.e.z}; }
  }
  await fetch('/api/goto',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(target)});
  document.getElementById('target').textContent = JSON.stringify(target);
});
tick();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _place(self, payload):
        """Validate a placement against the room graph, then append the record to an edited copy of the set file."""
        import math
        floor = int(payload.get("floor") or 1)
        record = int(payload.get("record") or 0)
        x, y, z = float(payload["x"]), float(payload.get("y") or 0.0), float(payload["z"])
        graph = rooms(floor)
        best = {"d": 1e9, "room": None}
        for room in graph.get("rooms") or []:
            for cell in room["cell_list"]:
                distance = math.hypot(x - cell[0], z - cell[1])
                if distance < best["d"]:
                    best = {"d": distance, "room": room["room"]}
        inside = best["d"] <= 7.5
        if not inside:
            return {"ok": False, "why": f"outside the walkable rooms (nearest room {best['room']} at "
                                        f"{best['d']:.1f} units)", "room": best["room"], "distance": round(best["d"], 1)}
        set_name = f"map_forest0{floor}d.dat"
        script = str(Path(r"C:\_tools\gBox\.tmp\set_edit.py"))
        try:
            finished = subprocess.run([sys.executable, script, "add", set_name, str(record),
                                       str(x), str(y), str(z)],
                                      capture_output=True, text=True, timeout=60)
        except Exception as exc:                                 # noqa: BLE001
            return {"ok": False, "why": f"set_edit failed: {type(exc).__name__}: {str(exc)[:120]}"}
        # never report success without proving the edited file is structurally sound and keeps every original record
        edited_path = Path(r"D:\gBox\pso-ds\rel\edited") / set_name
        check_script = str(Path(r"C:\_tools\gBox\.tmp\set_check.py"))
        try:
            check = subprocess.run([sys.executable, check_script, str(edited_path),
                                    str(Path(r"D:\gBox\pso-ds\rel") / set_name)],
                                   capture_output=True, text=True, timeout=60)
            verdict = (check.stdout or "").strip().splitlines()
        except Exception as exc:                                 # noqa: BLE001
            check, verdict = None, [f"set_check failed: {type(exc).__name__}"]
        structure_ok = check is not None and check.returncode == 0
        return {"ok": finished.returncode == 0 and structure_ok, "room": best["room"],
                "distance": round(best["d"], 1), "set": set_name, "record": record,
                "structure_ok": structure_ok, "structure": verdict[-2:] if verdict else [],
                "output": (finished.stdout or "").strip()[-300:]}

    def _send(self, code, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if self.path == "/api/objects" or self.path.startswith("/api/objects?"):
            floor = "1"
            if "?" in self.path:
                for part in self.path.split("?", 1)[1].split("&"):
                    if part.startswith("floor="):
                        floor = part.split("=", 1)[1]
            try:
                data = json.loads(OBJECTS.read_text(encoding="utf-8"))
            except Exception:                                    # noqa: BLE001
                data = {}
            block = data.get(floor) or {}
            return self._send(200, json.dumps({"floor": floor, "set": block.get("set"),
                                               "objects": block.get("objects") or []}))
        if self.path == "/api/rooms" or self.path.startswith("/api/rooms?"):
            floor = 1
            if "?" in self.path:
                for part in self.path.split("?", 1)[1].split("&"):
                    if part.startswith("floor="):
                        try:
                            floor = int(part.split("=", 1)[1])
                        except ValueError:
                            floor = 1
            return self._send(200, json.dumps(rooms(floor)))
        if self.path == "/api/state":
            try:
                return self._send(200, json.dumps(state()))
            except Exception as exc:                             # noqa: BLE001
                return self._send(200, json.dumps({"error": str(exc)[:120]}))
        if self.path == "/api/minimap.png":
            try:
                import io

                from PIL import Image
                newest = sorted(DEMO.glob("*gbox-docked.png"), key=lambda p: p.stat().st_mtime)[-1]
                image = Image.open(newest).convert("RGB").crop((660, 80, 900, 275))
                buffer = io.BytesIO()
                image.resize((480, 390), Image.NEAREST).save(buffer, "PNG")
                return self._send(200, buffer.getvalue(), "image/png")
            except Exception:                                    # noqa: BLE001
                return self._send(404, b"", "image/png")
        return self._send(404, "{}")

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        if self.path == "/api/goto":
            try:
                payload = json.loads(body)
            except Exception:                                    # noqa: BLE001
                payload = {}
            payload["t"] = time.time()
            GOTO.write_text(json.dumps(payload), encoding="utf-8")
            return self._send(200, json.dumps({"ok": True}))
        if self.path == "/api/place":
            try:
                payload = json.loads(body)
            except Exception:                                    # noqa: BLE001
                payload = {}
            return self._send(200, json.dumps(self._place(payload)))
        return self._send(404, "{}")


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"map viewer on http://127.0.0.1:{PORT}/", flush=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
