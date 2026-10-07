"""Embed glyphs/*.svg into ../padglyph.js (between the GLYPHS-BEGIN / GLYPHS-END markers).

The web shell only serves /padglyph.js, so the SVGs travel inside it. Each file's <style id="standalone"> (there only so
the .svg previews on its own) and <title> are dropped; padglyph.js styles the parts with its own CSS.
"""
import json, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
JS = HERE.parent / "padglyph.js"
svgs = {}
for f in sorted(HERE.glob("*.svg")):
    s = f.read_text(encoding="utf-8")
    s = re.sub(r'<style id="standalone">.*?</style>|<title>.*?</title>|<\?xml[^>]*>', "", s, flags=re.S)
    svgs[f.stem] = re.sub(r">\s+<", "><", s.strip())
block = "const SVG = {\n" + "".join(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)},\n" for k, v in svgs.items()) + "};\n"
js = JS.read_text(encoding="utf-8")
new, n = re.subn(r"(/\* GLYPHS-BEGIN[^\n]*\n).*?(/\* GLYPHS-END \*/)", lambda m: m[1] + block + m[2], js, flags=re.S)
if n != 1:
    raise SystemExit("padglyph.js: GLYPHS-BEGIN/END markers not found")
JS.write_text(new, encoding="utf-8", newline="\n")
print(f"embedded {len(svgs)} glyphs ({sum(map(len, svgs.values())) // 1024} KB) into {JS.name}")
