"""Wire play recording into the relay.

The relay's imports are `os`, `pathlib`, `sys`, `time`, then `pygame` and `from pso_pad import Pad, call` - there is no
`import singleton` line, which is why the first attempt found no anchor. The tracer goes after the `pso_pad` import so it
sits with the other local module.
"""
import pathlib
import py_compile

RELAY = pathlib.Path(r"C:\_tools\gBox\.tmp\controller_relay.py")
text = RELAY.read_text(encoding="utf-8")
py_compile.compile(str(RELAY), doraise=True)
print("compiles BEFORE")

# 1. import the tracer after the pso_pad import
if "import play_trace" not in text:
    anchor = "from pso_pad import Pad, call                                       # noqa: E402"
    if text.count(anchor) != 1:
        raise SystemExit("pso_pad import anchor count: %d" % text.count(anchor))
    text = text.replace(
        anchor,
        anchor + "\n\ntry:\n    import play_trace                      # record the operator's play so it can be replayed\n"
        "except Exception:                             # noqa: BLE001\nexcept_placeholder = None\n    play_trace = None",
        1)
    # tidy the placeholder the template above leaves behind
    text = text.replace("except Exception:                             # noqa: BLE001\nexcept_placeholder = None\n    play_trace = None",
                        "except Exception:                             # noqa: BLE001\n    play_trace = None", 1)
    print("play_trace imported")

# 2. record each forwarded input together with the state at that moment
OLD = '''            send(pad, events)
            print(f"  relayed {len(events)} event(s): {[e['key'] for e in events]}", flush=True)'''
NEW = '''            send(pad, events)
            print(f"  relayed {len(events)} event(s): {[e['key'] for e in events]}", flush=True)
            if play_trace is not None:
                # Snapshot the state with the input, so a row means "pressed X while at Y facing Z" rather than just
                # "pressed X". A failed read still records the input - losing the press is worse than losing position.
                try:
                    _snap = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
                except Exception:                # noqa: BLE001
                    _snap = {}
                play_trace.record(pad.sid, events, _snap)'''
count = text.count(OLD)
print("relay send anchor count:", count)
if count != 1:
    raise SystemExit("relay send block not unique")
text = text.replace(OLD, NEW, 1)
print("the relay records every forwarded input with its state")

RELAY.write_text(text, encoding="utf-8")
py_compile.compile(str(RELAY), doraise=True)
print("compiles AFTER")
