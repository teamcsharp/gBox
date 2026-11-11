"""Add click-to-order to the minimap: click a point and the bot walks there.

The operator asked for this directly - "click on the map in order to tell the bot where it needs to go". The minimap already knows the world-to-screen
transform, so a click can be inverted into a world coordinate and written to an order file that the bot reads before choosing its own destination.

Endpoints:
  POST /api/order?x=<world x>&z=<world z>   record an order
  GET  /api/order                           read the pending order (the bot uses this)

The page gains a click handler that inverts the transform and posts the order, so one picture serves as both the level view and the control surface.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\minimap_live.py")
text = path.read_text(encoding="utf-8")

# record the last transform so a click can be inverted
old_render_sig = "def render(floor_data, state):"
new_render_sig = '''_transform = {"min_x": 0.0, "min_z": 0.0, "scale": 1.0, "width": 900, "height": 640}


def render(floor_data, state):'''
text = text.replace(old_render_sig, new_render_sig, 1)

old_scale = '''    def screen(x, z):
        return ((x - min_x) * scale + 20, (z - min_z) * scale + 20)'''
new_scale = '''    _transform.update(min_x=min_x, min_z=min_z, scale=scale, width=width, height=height)

    def screen(x, z):
        return ((x - min_x) * scale + 20, (z - min_z) * scale + 20)'''
if text.count(old_scale) != 1:
    raise SystemExit(f"screen() pattern count {text.count(old_scale)}")
text = text.replace(old_scale, new_scale)

old_handler = '''        if self.path.startswith("/minimap.svg"):'''
new_handler = '''        if self.path.startswith("/api/order"):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            order_path = Path(r"D:\\gBox\\pso-ds\\goto-order.json")
            if query:
                order = {"x": float(query["x"][0]), "z": float(query["z"][0]), "t": round(time.time(), 2)}
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
        if self.path.startswith("/api/transform"):
            body = json.dumps(_transform).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/minimap.svg"):'''
if text.count(old_handler) != 1:
    raise SystemExit(f"handler anchor count {text.count(old_handler)}")
text = text.replace(old_handler, new_handler)

old_page = '''        page = ("<!doctype html><meta charset='utf-8'><title>PSO minimap</title>"
                "<body style='margin:0;background:#0d1117;color:#c9d1d9;font-family:monospace'>"
                "<div style='padding:6px 12px'>PSO live minimap - refreshing</div>"
                "<img id='m' src='/minimap.svg' style='display:block'>"
                "<script>setInterval(()=>{document.getElementById('m').src='/minimap.svg?'+Date.now()},1000)</script>")'''
new_page = '''        page = ("<!doctype html><meta charset='utf-8'><title>PSO minimap</title>"
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
                "  const res=await (await fetch(`/api/order?x=${wx.toFixed(1)}&z=${wz.toFixed(1)}`,{method:'POST'})).json();"
                "  document.getElementById('o').textContent='order: '+wx.toFixed(0)+','+wz.toFixed(0);"
                "};"
                "setInterval(()=>{img.src='/minimap.svg?'+Date.now()},1000);"
                "</script>")'''
if text.count(old_page) != 1:
    raise SystemExit(f"page pattern count {text.count(old_page)}")
text = text.replace(old_page, new_page)
path.write_text(text, encoding="utf-8")
print("minimap now accepts click orders")
