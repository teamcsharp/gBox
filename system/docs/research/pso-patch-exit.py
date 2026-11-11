"""Wire exit seeking into the play loop: when there is nothing left to do, look for a way out.

The play loop currently explores rooms when no enemy is alive, and stops there. With `exit_seek` it now finishes the job: if the area has a warp, it
walks to it and takes it; if it does not, it explores instead of standing around. That is the difference between clearing an area and completing one.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_when_focused.py")
text = path.read_text(encoding="utf-8")

old = """        if visiting is not None:
            if math.dist((me[0], me[2]), visiting) < 25:
                visiting = None
            else:
                RUN.run_to(ME.read_pos, visiting, tolerance=20.0, budget=25.0)
        time.sleep(0.15)"""

new = """        if visiting is not None:
            if math.dist((me[0], me[2]), visiting) < 25:
                visiting = None
            else:
                RUN.run_to(ME.read_pos, visiting, tolerance=20.0, budget=25.0)
                continue
        # nothing alive, nothing left to visit: look for the way out of the area
        try:
            import exit_seek
            found = exit_seek.warps()
            if found:
                log(f"  area exit present: {found[0]['class']} at "
                    f"{found[0]['distance']:.0f} units - taking it")
                exit_seek.seek(60.0)
        except Exception as exc:                                  # noqa: BLE001
            log(f"  exit seek unavailable: {type(exc).__name__}: {str(exc)[:60]}")
        time.sleep(0.15)"""

if text.count(old) != 1:
    raise SystemExit(f"loop pattern count {text.count(old)}")
text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("play loop now takes an area exit when one exists")
