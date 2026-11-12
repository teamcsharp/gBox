"""Add the previous-game row to the real menu, distinguishing it from the loading placeholder."""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = path.read_text(encoding="utf-8")

if "const previousRow = previous" in text:
    print("already added")
else:
    # the real menu block is followed by the games map; the placeholder by "Loading"
    old = """      addMenu.innerHTML = '<div style="padding:6px 8px;font-size:11px;color:#9aa3b4">Recently played</div>' +
        (games.length ? games.map((game, index) =>"""
    new = """      const previousRow = previous
        ? '<button type="button" role="menuitem" data-add-previous="" style="display:block;width:100%;text-align:left;padding:7px 8px;' +
          'background:#22304a;border:1px solid #33456b;border-radius:5px;color:#e6edf3;font:inherit;cursor:pointer;margin-bottom:4px">' +
          'Launch the previous game<span style="display:block;font-size:11px;color:#9aa3b4">' +
          esc(previous.title || previous.game_id) + '</span></button>'
        : '';
      addMenu.innerHTML = '<div style="padding:6px 8px;font-size:11px;color:#9aa3b4">Your recent launches</div>' + previousRow +
        (games.length ? games.map((game, index) =>"""
    count = text.count(old)
    print("specific anchor count:", count)
    if count == 1:
        text = text.replace(old, new, 1)
        path.write_text(text, encoding="utf-8")
        print("previous-game row added to the real menu")
    else:
        for index, line in enumerate(text.splitlines()):
            if "Recently played" in line:
                print(f"  line {index + 1}: {line.strip()[:130]}")

import subprocess
result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=120)
print("node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:200])

source = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js").read_text(encoding="utf-8")
print("previous row built:", "const previousRow = previous" in source)
print("header:", "Your recent launches" in source)
