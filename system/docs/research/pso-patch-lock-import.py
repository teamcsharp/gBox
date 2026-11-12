"""Add the missing `import os` inside claim_lock, so the supervisor lock actually works.

`supervisor.py` never imports `os` at module level, and `claim_lock` calls `os.getpid()`. That raised NameError, and the function's own `except Exception:
return True` swallowed it - so every instance believed it had the lock, wrote nothing, and started. That is why the lock file was empty and why four
supervisors were alive at once.

The import goes inside the function (deliberately narrow, no effect on anything else in the file).
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\supervisor.py")
text = path.read_text(encoding="utf-8")

anchor = "def claim_lock():"
if "import os" in text.split(anchor, 1)[-1][:200] if anchor in text else False:
    print("import already inside claim_lock")
else:
    index = text.find(anchor)
    if index < 0:
        raise SystemExit("claim_lock not found")
    after = text.find("\n", index) + 1
    text = text[:after] + "    import os\n" + text[after:]
    path.write_text(text, encoding="utf-8")
    print("import os added at the top of claim_lock")

print(pathlib.Path(r"C:\_tools\gBox\.tmp\supervisor.py").read_text(encoding="utf-8")[
      pathlib.Path(r"C:\_tools\gBox\.tmp\supervisor.py").read_text(encoding="utf-8").find("def claim_lock"):
      pathlib.Path(r"C:\_tools\gBox\.tmp\supervisor.py").read_text(encoding="utf-8").find("def claim_lock") + 240])
