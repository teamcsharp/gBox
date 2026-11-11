"""Point the live helper scripts at the working desktop API and the current session id."""
import pathlib
import re

FILES = ("map_viewer.py", "map_bot.py", "demo_recorder.py", "pso_operator.py")
NEW_API = 'API = "http://127.0.0.1:18765"'
NEW_SID = 'SID = "78a8746f5b514450-e9867839b8b74d3d"'

for name in FILES:
    path = pathlib.Path(name)
    text = path.read_text(encoding="utf-8")
    before = text
    text = re.sub(r'API = "http://127\.0\.0\.1:\d+"', NEW_API, text)
    text = re.sub(r'SID = "[0-9a-f\-]+"', NEW_SID, text)
    if text != before:
        path.write_text(text, encoding="utf-8")
    api = re.search(r'API = "([^"]+)"', text)
    sid = re.search(r'SID = "([^"]+)"', text)
    print(f"{name}: api={api.group(1) if api else '-'} sid={(sid.group(1)[:22] + '...') if sid else '-'}")
