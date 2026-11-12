"""Add `api` to the stream picker's options - the picker's own object has none.

Confirmed at index.html 4809-4819: `read, current, title, select, launch, broadcast, valid` - no `api`. The panel needs two reads (sessions, catalog), so it must
be given one.

The wrapper unwraps `gbox.api`'s `{ok, data, error}` into the value the panel expects, and throws on failure so its try/catch reports something rather than
drawing an empty list.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

anchor = "    select:(sid, valid) => pipSelection.select(sid, valid),\n    // Start a recently played game into the PiP"
if "api: async (path, body) => {\n      const answer = await gbox.api(path, body);" in text:
    print("already added")
else:
    count = text.count(anchor)
    print("anchor count:", count)
    if count != 1:
        raise SystemExit("select anchor not unique")
    addition = """    select:(sid, valid) => pipSelection.select(sid, valid),
    // The add-game panel reads sessions and catalog; gbox.api answers {ok,data,error}.
    api: async (path, body) => {
      const answer = await gbox.api(path, body);
      if (answer && answer.ok === false) throw new Error(answer.error || 'request failed');
      return answer && typeof answer === 'object' && 'data' in answer ? answer.data : answer;
    },
    // Start a recently played game into the PiP"""
    text = text.replace(anchor, addition, 1)
    path.write_text(text, encoding="utf-8")
    print("io.api added")

lines = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html").read_text(encoding="utf-8").splitlines()
for index, line in enumerate(lines):
    if "GBoxPipStreamPicker.mount" in line:
        for offset in range(0, 12):
            if index + offset < len(lines):
                print(f"{index + offset + 1}: {lines[index + offset].strip()[:130]}")
        break
