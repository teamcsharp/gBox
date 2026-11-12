"""Which modules does the repo have that the live install does not?

`pad_route.py` was in `main-repo/system/gbox/` but absent from `C:\\_tools\\gBox\\system\\gbox\\`, and its absence silently disabled the virtual pad - the
difference between focus-free input and twenty-five seconds of blindness per press. One missing file caused the bot to stand still for days of work.

So: compare the module names the two trees ship, and report the gaps. Any other missing module is a latent version of the same bug.
"""
import pathlib

LIVE = pathlib.Path(r"C:\_tools\gBox\system\gbox")
REPO = pathlib.Path(r"C:\_tools\gBox\.tmp\main-repo\system\gbox")


def modules(path):
    return {item.stem for item in path.glob("*.py")} if path.is_dir() else set()


if __name__ == "__main__":
    live, repo = modules(LIVE), modules(REPO)
    print(f"live modules: {len(live)}   repo modules: {len(repo)}")

    missing = sorted(repo - live)
    extra = sorted(live - repo)

    print(f"\n=== in the repo but MISSING from the live install ({len(missing)}) ===")
    for name in missing:
        size = (REPO / f"{name}.py").stat().st_size
        print(f"  {name}.py  ({size} bytes)")

    print(f"\n=== live-only modules ({len(extra)}) ===")
    for name in extra:
        print(f"  {name}.py")

    # import each missing module to see whether anything currently needs it
    print("\n=== does anything in the live tree import a missing module? ===")
    import re
    pattern = re.compile(r"(?:from\s+\.\s+import|from\s+\.(\w+)\s+import|import\s+(\w+))")
    hits = {}
    for source in LIVE.glob("*.py"):
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except Exception:                                          # noqa: BLE001
            continue
        for name in missing:
            if re.search(rf"(?:from\s+\.\s+import[^\n]*\b{name}\b)|(?:from\s+\.{name}\s+import)|(?:from\s+gbox\.{name}\s+import)|(?:from\s+\.\s+import\s+[^\n]*\b{name}\b)", text):
                hits.setdefault(name, []).append(source.name)
    if hits:
        for name, users in sorted(hits.items()):
            print(f"  {name}: imported by {', '.join(users[:5])}")
    else:
        print("  none")
