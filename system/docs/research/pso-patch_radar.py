"""Minimap: fall back to a live radar when a floor has no room database.

Floors 1 and 2 have room graphs; the boss arena (floor 11) does not, so the SVG renderer returned an empty view there. A radar is still useful in that
case and needs nothing but what is already read from memory: the character, the enemies, the boss and any warps, drawn relative to the player with a
grid and a range ring.

So `render` now always produces something: rooms when it has them, a radar when it does not.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\minimap_live.py")
text = path.read_text(encoding="utf-8")

anchor = "class Handler(BaseHTTPRequestHandler):"
radar = '''def render_radar(state, span=120):
    """A live radar around the player: used when the floor has no room graph."""
    width = height = 640
    centre_x, centre_y = width / 2, height / 2
    scale = (width / 2 - 30) / max(1.0, span)
    px, _, pz = state["player"]

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


class Handler(BaseHTTPRequestHandler):'''
if anchor not in text:
    raise SystemExit("handler anchor not found")
text = text.replace(anchor, radar, 1)

old = '''                svg = render(floor_data or {"rooms": []}, state) if floor_data else \\
                    f"<svg xmlns='http://www.w3.org/2000/svg' width='400' height='60'>" \\
                    f"<text x='8' y='30' fill='#c9d1d9' font-family='monospace'>" \\
                    f"no room database for floor {state['floor']}</text></svg>"'''
new = '''                if floor_data and (floor_data.get("rooms") or []):
                    svg = render(floor_data, state)
                else:
                    svg = render_radar(state)'''
if text.count(old) != 1:
    raise SystemExit(f"svg fallback pattern count {text.count(old)}")
text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("minimap falls back to a live radar when the floor has no room graph")
