"""Fix the undefined name and clean the dead variables the linter found, then prove it with pyflakes."""
import pathlib
import subprocess
import sys

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")

fixes = [
    # the actual crash: `me` is called `player` inside play()
    ('GOOD_POSITION.update(x=x, y=float(me.get("y") or 0), z=z)',
     'GOOD_POSITION.update(x=x, y=float(player.get("y") or 0), z=z)'),
    # dead code the linter flagged
    ("                after_state = state(pad).get(\"player\") or {}\n                now_target = [e for e in (after_state.get(\"entities\") or [])] if False else None\n",
     ""),
    ("        heading = float(player.get(\"heading_deg\") or 0)\n\n", ""),
]

for old, new in fixes:
    count = text.count(old)
    print(f"anchor count {count}: {old.strip()[:60]}")
    if count == 1:
        text = text.replace(old, new, 1)

ENDLESS.write_text(text, encoding="utf-8")
print("written")

result = subprocess.run([sys.executable, "-m", "pyflakes", str(ENDLESS)], capture_output=True, text=True)
lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
print("pyflakes:")
for line in lines:
    print("  ", line)
undefined = [line for line in lines if "undefined name" in line]
print("UNDEFINED NAMES:", len(undefined))
sys.exit(1 if undefined else 0)
