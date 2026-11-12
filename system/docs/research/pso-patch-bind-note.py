"""Stop pad_bind overriding the template: port 1 belongs to the bot's virtual pad.

The launch writes the template, then calls:

```python
vpad_ini = pad_bind.bind_note(vpad_ini, pad_bind.choose_slot(pad_bind.probe_pads()))
```

`choose_slot` picks the lowest *live* pad that is not the phantom - which on this machine is **slot 1**, one of the operator's controllers - and rewrites
`GCPad1` to it. So the template's `XInput/2` never survives, and the bot's virtual pad is never read.

`bind_note` becomes a pass-through: the template is already the binding we want (`XInput/2/Gamepad`, where the bot's pad lands because slots 0 and 1 are the
operator's). The probe still runs nowhere and nothing else changes - one line, and port 1 keeps pointing at a pad that exists and needs no focus.

The reason this is safe: the bot creates its pad before the emulator polls, and Dolphin's XInput backend checks every frame for the device the config names -
so `XInput/2` resolves to the bot's pad as soon as it exists.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\gbox\pad_bind.py")
text = path.read_text(encoding="utf-8")

start = text.find("def bind_note(")
if start < 0:
    raise SystemExit("bind_note not found")
end = text.find("\ndef ", start + 1)
end = len(text) if end < 0 else end

body = '''def bind_note(ini: str, slot: int | None, *, created: bool = False) -> str:
    """Leave the INI as it is: the template already binds port 1 to the bot's virtual pad.

    Previously this rewrote GCPad1 to the lowest live XInput slot, which on this machine is one of the operator's controllers - so the bot's pad was never
    read. The launch template names the bot's slot explicitly, and Dolphin resolves it as soon as the pad exists.
    """
    return ini

'''
text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("bind_note is now a pass-through")
