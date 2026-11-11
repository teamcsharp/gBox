"""Click an enemy on the minimap to make it the bot's locked target.

The other half of the operator's request: "click on enemies telling it what it needs to target". The minimap already draws enemies, so the click just
has to identify one of them.

  * `/api/state` now returns the enemies (with their actor pointers), the bosses, and the transform, so the page can hit-test a click in screen
    space;
  * `/api/target?pointer=<p>` records a target order in `target-order.json`;
  * the page tries an enemy hit first (within 14 px) and falls back to a positional order when the click is on empty ground.

The bot side reads that order and locks the named actor, which is already the unit of identity the fight loop uses.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\minimap_live.py")
text = path.read_text(encoding="utf-8")

# expose live state for hit-testing
old = '''        if self.path.startswith("/api/transform"):'''
new = '''        if self.path.startswith("/api/state"):
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
            order_path = Path(r"D:\\gBox\\pso-ds\\target-order.json")
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
        if self.path.startswith("/api/transform"):'''
if text.count(old) != 1:
    raise SystemExit(f"transform anchor count {text.count(old)}")
text = text.replace(old, new)

# record enemy pointers in read_state so a click can name one
old_enemy = '''            if entity_hp > 0:
                enemies.append({"x": x, "z": z, "hp": entity_hp, "class": name})'''
new_enemy = '''            if entity_hp > 0:
                enemies.append({"x": x, "z": z, "hp": entity_hp, "class": name, "pointer": p})'''
if text.count(old_enemy) != 1:
    raise SystemExit(f"enemy append count {text.count(old_enemy)}")
text = text.replace(old_enemy, new_enemy)

old_boss = '''            bosses.append({"x": x, "z": z, "hp": entity_hp, "class": name})'''
new_boss = '''            bosses.append({"x": x, "z": z, "hp": entity_hp, "class": name, "pointer": p})'''
if text.count(old_boss) == 1:
    text = text.replace(old_boss, new_boss)

# the click handler: enemy first, ground second
old_click = '''                "  const res=await (await fetch(`/api/order?x=${wx.toFixed(1)}&z=${wz.toFixed(1)}`,{method:'POST'})).json();"
                "  document.getElementById('o').textContent='order: '+wx.toFixed(0)+','+wz.toFixed(0);"'''
new_click = '''                "  const st=await (await fetch('/api/state')).json();"
                "  let best=null,bd=1e9;"
                "  for (const e of (st.enemies||[]).concat(st.bosses||[])) {"
                "    const sx=20+(e.x-t.min_x)*t.scale, sz=20+(e.z-t.min_z)*t.scale;"
                "    const d=Math.hypot(sx-px,sz-pz); if(d<bd){bd=d;best=e;} }"
                "  if(best && bd<14){"
                "    await fetch(`/api/target?pointer=${best.pointer}&class=${encodeURIComponent(best.class)}`,{method:'POST'});"
                "    document.getElementById('o').textContent='target: '+best.class+' hp '+best.hp;"
                "  } else {"
                "    await fetch(`/api/order?x=${wx.toFixed(1)}&z=${wz.toFixed(1)}`,{method:'POST'});"
                "    document.getElementById('o').textContent='move to: '+wx.toFixed(0)+','+wz.toFixed(0);"
                "  }"'''
if text.count(old_click) != 1:
    raise SystemExit(f"click handler count {text.count(old_click)}")
text = text.replace(old_click, new_click)
path.write_text(text, encoding="utf-8")
print("minimap can now target an enemy by click")
