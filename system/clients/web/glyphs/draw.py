"""gBox controller glyphs: draws clients/web/glyphs/<key>.svg, one per console (original line art, viewBox 260x170).

    python draw.py && python embed.py      # redraw every SVG, then embed them into ../padglyph.js


Each interactive part is <g data-btn="<console button>" [data-c="#rrggbb"]> with a .pg-s shape (fills when lit),
.pg-t label / .pg-y symbol / .pg-a arrow. Sticks: <g data-btn="lstick|rstick" data-stick="l|r" data-travel="n">
holding .pg-gate and <g class="pg-knob">. D-pad arms carry class pg-arm.
"""
import math, sys
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)
G = ""  # current glyph key


def f(v):
    return f"{round(v, 2):g}"


def mirror_half(start, segs, cx=130):
    """Right half (top-centre -> bottom-centre) as cubic segs [(c1x,c1y,c2x,c2y,x,y)], mirrored into a closed path."""
    d = f"M{f(start[0])} {f(start[1])}"
    pts = [start]
    for s in segs:
        d += f"C{f(s[0])} {f(s[1])} {f(s[2])} {f(s[3])} {f(s[4])} {f(s[5])}"
        pts.append((s[4], s[5]))
    for i in range(len(segs) - 1, -1, -1):           # walk back up the left side
        c1x, c1y, c2x, c2y, x, y = segs[i]
        px, py = pts[i]
        d += f"C{f(2*cx-c2x)} {f(c2y)} {f(2*cx-c1x)} {f(c1y)} {f(2*cx-px)} {f(py)}"
    return d + "Z"


def body(d):
    return f'<path class="pg-body" d="{d}"/>'


def deco(s):
    return f'<g class="pg-d">{s}</g>'


def text(x, y, s, fs, cls="pg-t", extra=""):
    return f'<text class="{cls}" x="{f(x)}" y="{f(y)}" font-size="{f(fs)}"{extra}>{s}</text>'


def cap(x, y, s, fs=5, red=False):
    return text(x, y, s, fs, "pg-c pg-cr" if red else "pg-c")


def grp(btn, inner, c=None, cls=""):
    a = f' data-c="{c}"' if c else ""
    k = f' class="{cls}"' if cls else ""
    return f'<g id="{G}-{btn}" data-btn="{btn}"{a}{k}>{inner}</g>'


def button(btn, x, y, r, label="", c=None, fs=None):
    lab = text(x, y + .3, label, fs or r * 1.05) if label else ""
    return grp(btn, f'<circle class="pg-s" cx="{f(x)}" cy="{f(y)}" r="{f(r)}"/>' + lab, c)


def rbtn(btn, x, y, w, h, label="", c=None, rot=0, rx=None, fs=None):
    rx = min(w, h) / 2 if rx is None else rx
    t = f' transform="rotate({f(rot)} {f(x)} {f(y)})"' if rot else ""
    lab = text(x, y + .3, label, fs or min(h * .78, 7.5), extra=t) if label else ""
    return grp(btn, f'<rect class="pg-s" x="{f(x-w/2)}" y="{f(y-h/2)}" width="{f(w)}" height="{f(h)}" rx="{f(rx)}"{t}/>' + lab, c)


def pbtn(btn, d, label="", lx=0, ly=0, fs=6, c=None):
    return grp(btn, f'<path class="pg-s" d="{d}"/>' + (text(lx, ly, label, fs) if label else ""), c)


def arcband(cx, cy, r0, r1, a0, a1):
    """Closed band between radii r0<r1 from angle a0 to a1 (degrees, 0 = right, clockwise as SVG y-down)."""
    p = lambda r, a: (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
    x0, y0 = p(r1, a0); x1, y1 = p(r1, a1); x2, y2 = p(r0, a1); x3, y3 = p(r0, a0)
    lg = 1 if abs(a1 - a0) > 180 else 0
    return (f"M{f(x0)} {f(y0)}A{f(r1)} {f(r1)} 0 {lg} 1 {f(x1)} {f(y1)}L{f(x2)} {f(y2)}"
            f"A{f(r0)} {f(r0)} 0 {lg} 0 {f(x3)} {f(y3)}Z")


def arrow(x, y, d, ang):
    return (f'<path class="pg-a" transform="rotate({ang} {f(x)} {f(y)})" '
            f'd="M{f(x)} {f(y-d)}L{f(x+d*.9)} {f(y+d*.6)}L{f(x-d*.9)} {f(y+d*.6)}Z"/>')


def dpad(x, y, s, arrows=True, ring=0, square=0):
    """Cross D-pad: arm width s, half-length 1.5 s. ring = recess circle radius, square = recess square half-size."""
    h, L = s / 2, 1.5 * s
    out = ""
    if ring:
        out += deco(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(ring)}"/>')
    if square:
        out += deco(f'<rect x="{f(x-square)}" y="{f(y-square)}" width="{f(2*square)}" height="{f(2*square)}" rx="{f(square*.25)}"/>')
    arms = [("up", x - h, y - L, 0, 0, -1), ("down", x - h, y + h, 180, 0, 1), ("left", x - L, y - h, 270, -1, 0), ("right", x + h, y - h, 90, 1, 0)]
    for k, ax, ay, ang, dx, dy in arms:
        cxa, cya = ax + h + dx * s * .12, ay + h + dy * s * .12
        out += grp(k, f'<rect class="pg-s" x="{f(ax)}" y="{f(ay)}" width="{f(s)}" height="{f(s)}"/>' +
                   (arrow(cxa, cya, s * .22, ang) if arrows else ""), cls="pg-arm")
    out += (f'<path class="pg-dpo" d="M{f(x-h)} {f(y-L)}H{f(x+h)}V{f(y-h)}H{f(x+L)}V{f(y+h)}H{f(x+h)}V{f(y+L)}'
            f'H{f(x-h)}V{f(y+h)}H{f(x-L)}V{f(y-h)}H{f(x-h)}Z"/>')
    out += f'<circle class="pg-dpc" cx="{f(x)}" cy="{f(y)}" r="{f(s*.22)}"/>'
    return out


def dpad4(x, y, off, w, ln):
    """PlayStation-style D-pad: four separate pointed keys around a centre."""
    out = ""
    for k, ang in (("up", 0), ("right", 90), ("down", 180), ("left", 270)):
        # key pointing to the centre: tip at distance off-ln*.35 ... drawn for "up" then rotated
        t, b = y - off + ln * .5, y - off - ln * .5
        d = (f"M{f(x)} {f(t+ln*.28)}L{f(x+w/2)} {f(t)}V{f(b+1.5)}Q{f(x+w/2)} {f(b)} {f(x+w/2-1.5)} {f(b)}"
             f"H{f(x-w/2+1.5)}Q{f(x-w/2)} {f(b)} {f(x-w/2)} {f(b+1.5)}V{f(t)}Z")
        out += grp(k, f'<path class="pg-s" transform="rotate({ang} {f(x)} {f(y)})" d="{d}"/>' +
                   arrow(*rot_pt(x, y, x, y - off - ln * .05, ang), w * .2, ang), cls="pg-dk")
    return out


def rot_pt(cx, cy, px, py, ang):
    a = math.radians(ang)
    dx, dy = px - cx, py - cy
    return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)


def octagon(x, y, r):
    pts = [(x + r * math.cos(math.radians(22.5 + 45 * i)), y + r * math.sin(math.radians(22.5 + 45 * i))) for i in range(8)]
    return "M" + "L".join(f"{f(a)} {f(b)}" for a, b in pts) + "Z"


def stick(sid, x, y, gate, knob, label="", c=None, octa=False, dirs=False, ball=False):
    btn = sid + "stick" if sid in ("l", "r") else sid
    gate_el = (f'<path class="pg-gate" d="{octagon(x, y, gate)}"/>' if octa else
               f'<circle class="pg-gate" cx="{f(x)}" cy="{f(y)}" r="{f(gate)}"/>')
    knob_el = (f'<circle class="pg-s" cx="{f(x)}" cy="{f(y)}" r="{f(knob)}"/>'
               f'<circle class="pg-kd" cx="{f(x)}" cy="{f(y)}" r="{f(knob*.55)}"/>' +
               (text(x, y + .3, label, knob * .9) if label else ""))
    a = f' data-c="{c}"' if c else ""
    dd = ' data-dirs="1"' if dirs else ""
    return (f'<g id="{G}-{btn}" data-btn="{btn}" data-stick="{sid[0]}" data-travel="{f(gate-knob)}"{a}'
            f'{dd}>{gate_el}<g class="pg-knob">{knob_el}</g></g>')


def sym(btn, x, y, r, shape, c=None):
    d = r * .45
    g = {
        "cross": f'<path class="pg-y" d="M{f(x-d)} {f(y-d)}L{f(x+d)} {f(y+d)}M{f(x+d)} {f(y-d)}L{f(x-d)} {f(y+d)}"/>',
        "circle": f'<circle class="pg-y" cx="{f(x)}" cy="{f(y)}" r="{f(d)}"/>',
        "square": f'<rect class="pg-y" x="{f(x-d*.85)}" y="{f(y-d*.85)}" width="{f(d*1.7)}" height="{f(d*1.7)}"/>',
        "triangle": f'<path class="pg-y" d="M{f(x)} {f(y-d*1.05)}L{f(x+d)} {f(y+d*.7)}L{f(x-d)} {f(y+d*.7)}Z"/>',
    }[shape]
    return grp(btn, f'<circle class="pg-s" cx="{f(x)}" cy="{f(y)}" r="{f(r)}"/>' + g, c)


def cbtn(btn, x, y, r, dirn, c):
    ang = {"u": 0, "r": 90, "d": 180, "l": 270}[dirn]
    return grp(btn, f'<circle class="pg-s" cx="{f(x)}" cy="{f(y)}" r="{f(r)}"/>' + arrow(x, y, r * .5, ang), c)


STANDALONE = """<style id="standalone">
svg{color:#e8e8ee;background:#16161a;font-family:system-ui,sans-serif}
.pg-body{fill:#ffffff0d;stroke:#ffffff6b;stroke-width:1.3;stroke-linejoin:round}
.pg-d *{fill:none;stroke:#ffffff33}
.pg-s{fill:#ffffff0a;stroke:#ffffff94;stroke-width:1.2}
.pg-t,.pg-c{fill:#ffffffb8;font-weight:600;text-anchor:middle;dominant-baseline:central}
.pg-cr{fill:#e0453a}
.pg-y{fill:none;stroke:#ffffffb8;stroke-width:1.3}.pg-a{fill:#ffffff99}
.pg-arm .pg-s{fill:none;stroke:none}.pg-dpo{fill:none;stroke:#ffffff94}.pg-dpc,.pg-kd{fill:none;stroke:#ffffff44}
.pg-gate{fill:none;stroke:#ffffff55;stroke-dasharray:2 2}
</style>"""

GLYPHS = {}


def glyph(key, name):
    def deco_(fn):
        GLYPHS[key] = (name, fn)
        return fn
    return deco_


C = dict(red="#e0453a", blue="#3b6fd6", yellow="#e7c33a", green="#3aa55a",
         n64A="#3d6fe0", n64B="#2e9e57", n64C="#f2c230", n64S="#d8453a",
         sfcA="#d8333a", sfcB="#e8c228", sfcX="#3b5fd6", sfcY="#2fa34a", nes="#d8333a",
         psT="#3ab795", psO="#e2554a", psX="#7d9cf0", psS="#e07fbf",
         gcA="#2fae6c", gcB="#e0453a", gcZ="#8a6cf0", gcC="#f2c230",
         xA="#3fae49", xB="#e04b3a", xX="#3a78d6", xY="#e8b93a", gb="#c23a7e", gba="#a9a4d6", white="#eeeeee")


# ---------------------------------------------------------------- Sega
@glyph("dc", "Dreamcast")
def dc():
    b = mirror_half((130, 6), [
        (160, 6, 182, 10, 194, 20),
        (208, 21, 228, 25, 238, 40),
        (246, 56, 245, 96, 239, 124),
        (234, 150, 228, 166, 214, 166),
        (204, 166, 198, 156, 194, 140),
        (186, 118, 166, 113, 130, 113)])
    s = (rbtn("l", 48, 17, 34, 8, "L", rot=-16) + rbtn("r", 212, 17, 34, 8, "R", rot=16) + body(b) +
         deco('<path d="M76 34A58 58 0 0 0 184 34"/><rect x="104" y="12" width="52" height="58" rx="7"/>'
              '<rect x="115" y="30" width="30" height="24" rx="2"/>') +
         text(130, 21, "VMU", 5, "pg-c") +
         stick("l", 64, 42, 15, 10) +
         dpad(72, 88, 10) +
         grp("start", '<path class="pg-s" stroke-linejoin="round" d="M130 92L137.5 104.5H122.5Z"/>') + cap(130, 110, "START", 4.6) +
         button("y", 196, 50, 7.5, "Y", C["green"]) + button("b", 212, 65, 7.5, "B", C["blue"]) +
         button("a", 196, 80, 7.5, "A", C["red"]) + button("x", 180, 65, 7.5, "X", C["yellow"]))
    return s


@glyph("saturn", "Sega Saturn")
def saturn():
    b = mirror_half((130, 30), [
        (166, 27, 206, 20, 232, 36),
        (252, 50, 254, 108, 238, 134),
        (224, 154, 192, 152, 172, 140),
        (160, 133, 147, 129, 130, 129)])
    return (rbtn("l", 58, 27, 44, 8, "L", rot=-16) + rbtn("r", 202, 27, 44, 8, "R", rot=16) + body(b) +
            text(130, 48, "SEGA SATURN", 5.2, "pg-c") +
            dpad(68, 80, 12, ring=26) +
            rbtn("start", 127, 104, 18, 8, "") + cap(127, 95, "START", 4.6) +
            button("x", 162, 86, 7.5, "X") + button("y", 184, 77, 7.5, "Y") + button("z", 206, 72, 7.5, "Z") +
            button("a", 166, 111, 9.5, "A") + button("b", 191, 101, 9.5, "B") + button("c", 216, 96, 9.5, "C"))


@glyph("md3", "Mega Drive / Genesis (3-button)")
def md3():
    b = mirror_half((130, 30), [
        (180, 27, 230, 28, 244, 60),
        (256, 92, 246, 136, 216, 148),
        (190, 156, 172, 122, 130, 120)])
    return (body(b) +
            dpad(70, 76, 13, ring=30) +
            text(132, 52, "SEGA", 6.5, "pg-c") +
            rbtn("start", 186, 52, 24, 9, "") + cap(186, 43, "START", 4.6) +
            deco('<path d="M150 96C160 80 220 66 236 80C246 92 230 110 214 112C196 116 168 120 156 114C148 110 147 102 150 96Z"/>') +
            button("a", 166, 101, 10.5, "A") + button("b", 192, 94, 10.5, "B") + button("c", 218, 87, 10.5, "C"))


@glyph("md6", "Mega Drive / Genesis (6-button)")
def md6():
    b = mirror_half((130, 34), [
        (172, 30, 224, 22, 242, 56),
        (256, 86, 248, 136, 214, 146),
        (190, 152, 176, 126, 130, 124)])
    return (rbtn("mode", 214, 31, 20, 6, "", rot=24) + cap(222, 22, "MODE", 4.4) + body(b) +
            text(130, 50, "SEGA", 6.5, "pg-c") +
            dpad(68, 82, 12, ring=28) +
            rbtn("start", 130, 84, 16, 7, "") + cap(130, 94, "START", 4.6) +
            button("x", 160, 80, 7.5, "X") + button("y", 182, 72, 7.5, "Y") + button("z", 204, 66, 7.5, "Z") +
            button("a", 166, 106, 9.5, "A") + button("b", 190, 98, 9.5, "B") + button("c", 214, 91, 9.5, "C"))


@glyph("sms", "Master System")
def sms():
    return (body("M22 48H238Q244 48 244 54V126Q244 132 238 132H22Q16 132 16 126V54Q16 48 22 48Z") +
            deco('<rect x="24" y="56" width="80" height="68" rx="3"/><path d="M110 48V62H244"/>'
                 '<path d="M110 84H138M110 90H138M110 96H138M110 102H138M110 108H138"/>'
                 '<rect x="144" y="82" width="44" height="42" rx="2"/><rect x="194" y="82" width="44" height="42" rx="2"/>') +
            cap(64, 63, "CONTROL PAD", 4.6) +
            dpad(64, 94, 13, square=24) +
            cap(166, 75, "1 START", 5, red=True) + cap(216, 75, "2", 5, red=True) +
            button("b1", 166, 103, 13, "1", fs=7) + button("b2", 216, 103, 13, "2", fs=7))


# ---------------------------------------------------------------- Nintendo
@glyph("nes", "NES")
def nes():
    return (body("M24 40H236Q242 40 242 46V130Q242 136 236 136H24Q18 136 18 130V46Q18 40 24 40Z") +
            deco('<rect x="26" y="50" width="208" height="78" rx="3"/>'
                 '<rect x="98" y="58" width="64" height="8" rx="2"/><rect x="98" y="70" width="64" height="8" rx="2"/>'
                 '<rect x="98" y="82" width="64" height="8" rx="2"/><rect x="98" y="96" width="64" height="26" rx="3"/>'
                 '<rect x="170" y="94" width="28" height="28" rx="2"/><rect x="204" y="94" width="28" height="28" rx="2"/>') +
            text(214, 61, "Nintendo", 6.5, "pg-c pg-cr") +
            dpad(60, 94, 14) +
            cap(116, 92, "SELECT", 4.6, red=True) + cap(144, 92, "START", 4.6, red=True) +
            rbtn("select", 116, 108, 18, 7) + rbtn("start", 144, 108, 18, 7) +
            button("b", 184, 108, 10.5, "B", C["nes"], fs=0.01) + button("a", 218, 108, 10.5, "A", C["nes"], fs=0.01) +
            cap(196, 89, "B", 5.5, red=True) + cap(230, 89, "A", 5.5, red=True))


@glyph("snes", "Super Nintendo")
def snes():
    b = ("M66 34C90 34 104 42 130 42C156 42 170 34 194 34C228 34 252 58 252 90C252 122 228 146 194 146"
         "C170 146 156 138 130 138C104 138 90 146 66 146C32 146 8 122 8 90C8 58 32 34 66 34Z")
    return (pbtn("l", arcband(66, 90, 56, 61, 214, 252), "") + text(42, 32, "L", 5.5, "pg-c") +
            pbtn("r", arcband(194, 90, 56, 61, 288, 326), "") + text(218, 32, "R", 5.5, "pg-c") +
            body(b) +
            deco('<circle cx="66" cy="90" r="34"/><ellipse cx="198" cy="90" rx="44" ry="30" transform="rotate(-34 198 90)"/>') +
            dpad(66, 90, 14) +
            rbtn("select", 114, 98, 18, 7, rot=-40) + rbtn("start", 140, 98, 18, 7, rot=-40) +
            cap(112, 112, "SELECT", 4.4) + cap(142, 112, "START", 4.4) +
            button("x", 198, 66, 11, "X", C["sfcX"]) + button("a", 222, 90, 11, "A", C["sfcA"]) +
            button("b", 198, 114, 11, "B", C["sfcB"]) + button("y", 174, 90, 11, "Y", C["sfcY"]))


@glyph("n64", "Nintendo 64")
def n64():
    b = mirror_half((130, 6), [
        (150, 6, 166, 8, 176, 16),
        (190, 22, 230, 22, 244, 42),
        (256, 60, 252, 92, 244, 120),
        (238, 146, 236, 166, 220, 166),
        (206, 166, 200, 150, 198, 132),
        (196, 112, 186, 98, 172, 98),
        (160, 98, 156, 112, 152, 130),
        (148, 152, 146, 168, 130, 168)])
    return (rbtn("l", 50, 24, 36, 7, "L", rot=-16) + rbtn("r", 210, 24, 36, 7, "R", rot=16) + body(b) +
            text(130, 18, "Nintendo", 6, "pg-c") +
            dpad(60, 54, 11, ring=23) +
            button("start", 130, 52, 6.5, "", C["n64S"]) + cap(130, 41, "START", 4.6) +
            stick("l", 130, 88, 15, 9, octa=True) +
            rbtn("z", 130, 146, 16, 10, "Z", rx=3) + cap(130, 158, "(back)", 4) +
            button("b", 172, 58, 9, "B", C["n64B"]) + button("a", 182, 80, 9, "A", C["n64A"]) +
            cbtn("cup", 213, 49, 6.2, "u", C["n64C"]) + cbtn("cright", 225, 61, 6.2, "r", C["n64C"]) +
            cbtn("cdown", 213, 73, 6.2, "d", C["n64C"]) + cbtn("cleft", 201, 61, 6.2, "l", C["n64C"]))


@glyph("gc", "GameCube")
def gc():
    b = mirror_half((130, 6), [
        (168, 5, 196, 8, 214, 15),
        (238, 24, 248, 46, 242, 72),
        (238, 92, 246, 122, 238, 148),
        (234, 162, 218, 167, 210, 157),
        (202, 147, 204, 130, 196, 120),
        (188, 130, 156, 132, 147, 110),
        (142, 98, 142, 76, 130, 76)])
    ax, ay = 192, 52
    yk, xk = arcband(ax, ay, 15.5, 23, 222, 282), arcband(ax, ay, 15.5, 23, -40, 14)
    lab = lambda a: (ax + 19.3 * math.cos(math.radians(a)), ay + 19.3 * math.sin(math.radians(a)))
    return (rbtn("l", 58, 8, 38, 8, "L", rot=-8) + rbtn("r", 202, 8, 38, 8, "R", rot=8) + body(b) +
            rbtn("z", 212, 16, 24, 6, "Z", C["gcZ"], rot=10, fs=5) +
            deco('<circle cx="64" cy="50" r="27"/><circle cx="194" cy="50" r="31"/>') +
            stick("l", 64, 50, 18, 11, octa=True) +
            dpad(94, 94, 9) +
            button("start", 129, 52, 4.5) + cap(129, 43, "START/PAUSE", 4.2) +
            stick("r", 164, 96, 13, 8, "C", C["gcC"], octa=True) +
            button("a", ax, ay, 12, "A", C["gcA"]) + button("b", 169, 66, 7, "B", C["gcB"]) +
            pbtn("y", yk, "Y", *lab(252), 5.5) + pbtn("x", xk, "X", *lab(-13), 5.5))


@glyph("wii", "Wii Classic Controller")
def wii():
    b = mirror_half((130, 28), [
        (166, 27, 196, 25, 216, 26),
        (246, 28, 254, 56, 252, 86),
        (250, 122, 236, 146, 210, 146),
        (190, 146, 178, 138, 162, 138),
        (150, 138, 142, 138, 130, 138)])
    return (rbtn("l", 40, 25, 34, 7, "L", rot=-10) + rbtn("r", 220, 25, 34, 7, "R", rot=10) +
            rbtn("zl", 98, 24, 20, 6, "ZL", fs=4.4) + rbtn("zr", 162, 24, 20, 6, "ZR", fs=4.4) + body(b) +
            text(130, 50, "Wii", 8, "pg-c") +
            dpad(54, 64, 11) +
            button("minus", 112, 69, 5, "−", fs=7) + button("home", 130, 69, 5, "⌂", fs=6) + button("plus", 148, 69, 5, "+", fs=7) +
            cap(112, 79, "SELECT", 4) + cap(130, 79, "HOME", 4) + cap(148, 79, "START", 4) +
            stick("l", 98, 108, 17, 10, octa=True) + stick("r", 162, 108, 17, 10, octa=True) +
            button("x", 210, 50, 8, "x") + button("y", 190, 68, 8, "y") +
            button("a", 230, 68, 8, "a") + button("b", 210, 86, 8, "b"))


@glyph("gb", "Game Boy")
def gb():
    return (body("M90 4H170Q178 4 178 12V138Q178 166 150 166H90Q82 166 82 158V12Q82 4 90 4Z") +
            deco('<path d="M92 12H168V68Q168 80 156 80H92Z"/><rect x="106" y="20" width="48" height="44"/>'
                 '<path d="M152 154L166 140M157 158L171 144M162 162L174 150"/>') +
            text(130, 88, "Nintendo GAME BOY", 4.6, "pg-c") +
            dpad(103, 112, 9) +
            button("b", 146, 120, 8, "", C["gb"]) + button("a", 164, 108, 8, "", C["gb"]) +
            cap(146, 132, "B", 5) + cap(164, 120, "A", 5) +
            rbtn("select", 120, 142, 13, 4.5, rot=-28) + rbtn("start", 138, 142, 13, 4.5, rot=-28) +
            cap(118, 151, "SELECT", 3.8) + cap(138, 151, "START", 3.8))


@glyph("gbc", "Game Boy Color")
def gbc():
    return (body("M96 4H164Q172 4 172 12V124Q172 160 130 166Q88 160 88 124V12Q88 4 96 4Z") +
            deco('<rect x="94" y="12" width="72" height="66" rx="4"/><rect x="106" y="20" width="48" height="44"/>'
                 '<path d="M150 150L162 138M154 155L166 143"/>') +
            text(130, 86, "GAME BOY COLOR", 4.6, "pg-c") +
            dpad(106, 108, 8.5) +
            button("b", 144, 114, 7.5, "", C["gb"]) + button("a", 161, 103, 7.5, "", C["gb"]) +
            cap(144, 125, "B", 5) + cap(161, 114, "A", 5) +
            rbtn("select", 121, 136, 11, 5) + rbtn("start", 139, 136, 11, 5) +
            cap(121, 144, "SELECT", 3.8) + cap(139, 144, "START", 3.8))


@glyph("gba", "Game Boy Advance")
def gba():
    b = ("M58 30H202C232 30 248 54 248 88C248 122 232 146 202 146H58C28 146 12 122 12 88C12 54 28 30 58 30Z")
    return (pbtn("l", arcband(58, 88, 58, 62, 222, 258), "") + text(30, 30, "L", 5.2, "pg-c") +
            pbtn("r", arcband(202, 88, 58, 62, 282, 318), "") + text(230, 30, "R", 5.2, "pg-c") +
            body(b) +
            deco('<rect x="72" y="38" width="116" height="96" rx="8"/><rect x="86" y="48" width="88" height="62"/>') +
            text(130, 122, "GAME BOY ADVANCE", 4.6, "pg-c") +
            dpad(44, 76, 10) +
            button("start", 44, 112, 4, "") + button("select", 44, 128, 4, "") +
            cap(58, 112, "START", 4) + cap(59, 128, "SELECT", 4) +
            button("a", 222, 74, 9, "A", C["gba"]) + button("b", 202, 88, 9, "B", C["gba"]))


# ---------------------------------------------------------------- Sony
def ps_body(sticks):
    tail = ([(190, 124, 186, 124, 180, 127), (172, 136, 150, 136, 145, 125), (141, 118, 137, 117, 130, 117)]
            if sticks else [(190, 120, 180, 114, 166, 114), (150, 114, 140, 114, 130, 114)])
    return mirror_half((130, 38), [
        (150, 38, 166, 36, 180, 34),
        (198, 30, 224, 30, 236, 50),
        (246, 70, 248, 110, 250, 140),
        (252, 158, 240, 166, 228, 164),
        (214, 162, 206, 146, 198, 130)] + tail)


def ps_common(face_y=72):
    return (rbtn("l2", 64, 18, 36, 8, "L2") + rbtn("r2", 196, 18, 36, 8, "R2") +
            rbtn("l1", 64, 28, 42, 8, "L1") + rbtn("r1", 196, 28, 42, 8, "R1"))


def ps_face(x, y, d, r, col=True):
    return (sym("triangle", x, y - d, r, "triangle", C["psT"] if col else None) +
            sym("circle", x + d, y, r, "circle", C["psO"] if col else None) +
            sym("cross", x, y + d, r, "cross", C["psX"] if col else None) +
            sym("square", x - d, y, r, "square", C["psS"] if col else None))


def ps_mid(start_tri=True, y=70):
    return (rbtn("select", 113, y, 13, 6, rx=1.5) + cap(113, y + 9, "SELECT", 4.2) +
            grp("start", f'<path class="pg-s" stroke-linejoin="round" d="M141 {y-3.5}H149L154 {y}L149 {y+3.5}H141Z"/>') +
            cap(147, y + 9, "START", 4.2))


@glyph("ps1", "PlayStation (digital)")
def ps1():
    return (ps_common() + body(ps_body(False)) + text(130, 50, "SONY", 5.5, "pg-c") +
            dpad4(64, 72, 15, 11.5, 15) + ps_mid() + ps_face(196, 72, 16, 8))


@glyph("ds1", "PlayStation DualShock")
def ds1():
    return (ps_common() + body(ps_body(True)) + text(130, 48, "SONY", 5.5, "pg-c") +
            dpad4(64, 70, 15, 11.5, 15) + ps_mid(y=64) + ps_face(196, 70, 16, 8) +
            rbtn("analog", 130, 86, 9, 5, rx=1) + cap(130, 79, "ANALOG", 4) +
            deco('<circle cx="130" cy="94" r="1.6"/>') +
            stick("l", 98, 106, 15, 10) + stick("r", 162, 106, 15, 10))


@glyph("ps2", "PlayStation 2 DualShock 2")
def ps2():
    return (ps_common() + body(ps_body(True)) + text(130, 48, "DUALSHOCK 2", 4.6, "pg-c") +
            dpad4(64, 70, 15, 11.5, 15) + ps_mid(y=64) + ps_face(196, 70, 16, 8) +
            rbtn("analog", 130, 86, 9, 5, rx=1) + cap(130, 79, "ANALOG", 4) +
            deco('<circle cx="130" cy="94" r="1.6"/>') +
            stick("l", 98, 106, 15, 10) + stick("r", 162, 106, 15, 10))


@glyph("ps3", "PlayStation 3 DualShock 3")
def ps3():
    return (ps_common() + body(ps_body(True)) +
            deco('<circle cx="118" cy="38" r="1.3"/><circle cx="126" cy="38" r="1.3"/><circle cx="134" cy="38" r="1.3"/><circle cx="142" cy="38" r="1.3"/>') +
            text(130, 48, "DUALSHOCK 3", 4.6, "pg-c") +
            dpad4(64, 70, 15, 11.5, 15) + ps_mid(y=64) + ps_face(196, 70, 16, 8) +
            button("ps", 130, 88, 6, "PS", fs=4.4) +
            stick("l", 98, 106, 15, 10) + stick("r", 162, 106, 15, 10))


@glyph("psp", "PSP")
def psp():
    b = "M58 34H202C232 34 254 58 254 88C254 118 232 142 202 142H58C28 142 6 118 6 88C6 58 28 34 58 34Z"
    return (pbtn("l", arcband(58, 88, 54, 58, 222, 258), "") + text(30, 32, "L", 5.2, "pg-c") +
            pbtn("r", arcband(202, 88, 54, 58, 282, 318), "") + text(230, 32, "R", 5.2, "pg-c") +
            body(b) + deco('<rect x="62" y="44" width="136" height="78" rx="2"/>') +
            text(130, 83, "PSP", 9, "pg-c") +
            dpad4(34, 70, 10, 8, 10) +
            stick("l", 34, 108, 9, 6.5) +
            ps_face(228, 82, 12, 6, col=False) +
            rbtn("home", 74, 132, 16, 6, "HOME", fs=3.6) +
            rbtn("select", 178, 132, 16, 6, "SELECT", fs=3.4) + rbtn("start", 198, 132, 16, 6, "START", fs=3.6))


# ---------------------------------------------------------------- Microsoft
@glyph("xbox", "Xbox (Controller S)")
def xbox():
    b = mirror_half((130, 22), [
        (162, 20, 198, 14, 226, 20),
        (246, 26, 252, 56, 250, 84),
        (248, 116, 254, 150, 238, 164),
        (222, 174, 206, 160, 196, 140),
        (186, 124, 172, 122, 154, 124),
        (144, 125, 138, 126, 130, 126)])
    return (rbtn("lt", 52, 14, 34, 8, "L", rot=-12) + rbtn("rt", 208, 14, 34, 8, "R", rot=12) + body(b) +
            deco('<circle cx="130" cy="46" r="15"/><path d="M122 38L138 54M138 38L122 54"/>') +
            stick("l", 60, 56, 17, 11) + dpad(100, 96, 9, ring=19) + stick("r", 164, 96, 17, 11) +
            button("back", 34, 92, 5) + button("start", 46, 102, 5) + cap(30, 101, "BACK", 3.8) + cap(46, 111, "START", 3.8) +
            button("y", 198, 30, 7, "Y", C["xY"]) + button("b", 213, 42, 7, "B", C["xB"]) +
            button("x", 183, 42, 7, "X", C["xX"]) + button("a", 198, 54, 7, "A", C["xA"]) +
            button("black", 226, 62, 6.5, "BK", fs=4.2) + button("white", 214, 76, 6.5, "WH", C["white"], fs=4.2))


def x_body():
    return mirror_half((130, 30), [
        (160, 28, 190, 25, 214, 28),
        (238, 32, 247, 52, 250, 80),
        (255, 118, 257, 154, 236, 162),
        (218, 168, 207, 148, 196, 132),
        (186, 118, 170, 116, 130, 117)])


def x_face(x=196, y=62, d=14, r=7):
    return (button("y", x, y - d, r, "Y", C["xY"]) + button("b", x + d, y, r, "B", C["xB"]) +
            button("a", x, y + d, r, "A", C["xA"]) + button("x", x - d, y, r, "X", C["xX"]))


@glyph("x360", "Xbox 360")
def x360():
    return (rbtn("lt", 60, 12, 30, 9, "LT", rx=4) + rbtn("rt", 200, 12, 30, 9, "RT", rx=4) +
            pbtn("lb", "M38 30C44 22 70 20 84 24L86 30C70 28 50 30 40 36Z", "LB", 62, 27.5, 4.6) +
            pbtn("rb", "M222 30C216 22 190 20 176 24L174 30C190 28 210 30 220 36Z", "RB", 198, 27.5, 4.6) +
            body(x_body()) +
            stick("l", 62, 62, 15, 10) + dpad(98, 100, 9, ring=17) + stick("r", 162, 100, 15, 10) +
            button("back", 110, 62, 4.5) + button("guide", 130, 62, 9, "X", fs=7) + button("start", 150, 62, 4.5) +
            cap(110, 71, "BACK", 3.8) + cap(150, 71, "START", 3.8) + x_face())


@glyph("xinput", "Xbox controller")
def xinput():
    return (rbtn("lt", 60, 12, 30, 9, "LT", rx=4) + rbtn("rt", 200, 12, 30, 9, "RT", rx=4) +
            pbtn("lb", "M38 30C44 22 70 20 84 24L86 30C70 28 50 30 40 36Z", "LB", 62, 27.5, 4.6) +
            pbtn("rb", "M222 30C216 22 190 20 176 24L174 30C190 28 210 30 220 36Z", "RB", 198, 27.5, 4.6) +
            body(x_body()) +
            stick("l", 62, 62, 15, 10) + dpad(98, 100, 9, ring=17) + stick("r", 162, 100, 15, 10) +
            button("guide", 130, 44, 7.5, "X", fs=6) +
            button("view", 112, 64, 4.5) + button("menu", 148, 64, 4.5) + rbtn("share", 130, 76, 8, 4.5) +
            cap(112, 73, "VIEW", 3.8) + cap(148, 73, "MENU", 3.8) + x_face())


# ---------------------------------------------------------------- arcade
@glyph("arcade", "Arcade stick")
def arcade():
    return (body("M18 34H242Q252 34 252 44V146Q252 156 242 156H18Q8 156 8 146V44Q8 34 18 34Z") +
            deco('<rect x="16" y="42" width="228" height="106" rx="5"/>') +
            stick("stick", 60, 98, 28, 12, c=C["red"], dirs=True) +
            rbtn("coin", 196, 48, 16, 7, "") + rbtn("start", 224, 48, 16, 7, "") +
            cap(196, 57, "COIN", 4.2) + cap(224, 57, "START", 4.2) +
            button("b1", 124, 86, 11.5, "1") + button("b2", 152, 78, 11.5, "2") + button("b3", 181, 78, 11.5, "3") +
            button("b4", 120, 114, 11.5, "4") + button("b5", 148, 106, 11.5, "5") + button("b6", 177, 106, 11.5, "6") +
            button("b7", 210, 82, 11.5, "") + button("b8", 206, 110, 11.5, ""))


for key, (name, fn) in GLYPHS.items():
    G = key
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 170" data-glyph="{key}" data-name="{name}">'
           f'<title>{name} controller</title>\n{STANDALONE}\n{fn()}\n</svg>\n')
    (OUT / f"{key}.svg").write_text(svg, encoding="utf-8")
print(len(GLYPHS), "glyphs ->", OUT)
