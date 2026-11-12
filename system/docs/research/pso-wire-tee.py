"""Wire teeChild to the worker child: one line after the workerChannel call."""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\main.js")
text = path.read_text(encoding="utf-8")

if "teeChild(child" in text:
    print("already wired")
else:
    anchor = "const channel=clientHandoff.workerChannel(child,controlSecret,"
    count = text.count(anchor)
    print("anchor count:", count)
    if count == 1:
        text = text.replace(anchor, 'teeChild(child, "worker");\n' + anchor, 1)
        path.write_text(text, encoding="utf-8")
        print("teeChild wired before the workerChannel call")
    else:
        # fall back: find the line containing workerChannel
        for index, line in enumerate(text.splitlines()):
            if "workerChannel(child" in line:
                print(f"line {index + 1}: {line.strip()[:130]}")

print("--- verify ---")
for index, line in enumerate(pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\main.js").read_text(encoding="utf-8").splitlines()):
    if "teeChild(child" in line or "workerChannel(child" in line:
        print(f"{index + 1}: {line.strip()[:140]}")
