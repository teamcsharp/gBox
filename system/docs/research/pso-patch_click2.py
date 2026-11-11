"""Make click-to-order work on both view types and over POST.

Two gaps found by testing: the radar (used on floors without a room graph) never recorded its transform, so a click could not be inverted, and the
server only implemented do_GET so a POST to /api/order returned 501. Both are fixed: the radar records its transform, and do_POST delegates to the
same handler.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\minimap_live.py")
text = path.read_text(encoding="utf-8")

# radar: record its transform
old_radar = '''    def screen(x, z):
        return (centre_x + (x - px) * scale, centre_y + (z - pz) * scale)'''
new_radar = '''    _transform.update(min_x=px - centre_x / scale, min_z=pz - centre_y / scale,
                      scale=scale, width=width, height=height)

    def screen(x, z):
        return (centre_x + (x - px) * scale, centre_y + (z - pz) * scale)'''
if text.count(old_radar) != 1:
    raise SystemExit(f"radar screen pattern count {text.count(old_radar)}")
text = text.replace(old_radar, new_radar)

# POST support
old_log = '''    def log_message(self, *args):
        return'''
new_log = '''    def do_POST(self):                                            # noqa: N802
        self.do_GET()

    def log_message(self, *args):
        return'''
if text.count(old_log) != 1:
    raise SystemExit(f"log_message pattern count {text.count(old_log)}")
text = text.replace(old_log, new_log)
path.write_text(text, encoding="utf-8")
print("radar records its transform and POST is accepted")
