"""On the next launch: is the app's virtual pad bound, and does input actually move the character?

Two questions decide whether the bot can play, and both are answerable in one run:

1. **Did the app create its own virtual pad for this session?** `_setup_vpad` writes a comment into the INI when it binds one -
   `# gBox: Player 1 bound to XInput slot N (gBox's virtual pad)` - and its documented failure mode is falling back to the keyboard INI with no
   comment, after which *"every gBox press was silently dropped for the whole session"*. Reading the file answers it without guessing.

2. **Does input move the character?** One held direction through the plane's `send_input` (the branch that uses the pad when it exists) and a measured
   displacement.

Both are printed with the evidence, so the next step is decided by a measurement rather than by which branch was hoped for.
"""
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

INI_CANDIDATES = [
    Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\Config\GCPadNew.ini"),
]


def position():
    pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    if not (0x80000000 <= pointer < 0x81800000):
        return None
    blob = S.read_memory(pointer + 0x38, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def main():
    session = S.session_id()
    pid = S.pid()
    print(f"session {session}  pid {pid}")

    comment, device = None, None
    for path in INI_CANDIDATES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if "gBox: Player 1 bound to XInput slot" in line:
                comment = line.strip()
            if line.startswith("Device ="):
                device = line.strip()
                break
        print(f"{path.name}: {device or 'no Device line'}")
        print(f"  {comment or 'NO gBox virtual-pad comment - the keyboard INI was written'}")
        break

    before = position()
    if before is None:
        print("no player actor - is the game past the title?")
        return 1
    print("position:", tuple(round(v, 1) for v in before))
    S.rpc("send_input", {"events": [{"key": "up", "down": True}]}, timeout=30)
    time.sleep(0.7)
    S.rpc("send_input", {"events": [{"key": "up", "down": False}]}, timeout=30)
    time.sleep(0.3)
    after = position()
    moved = math.dist((before[0], before[2]), (after[0], after[2])) if after else 0.0
    print(f"moved with one held direction: {moved:.2f} units")
    print("VERDICT:", "input works - the bot can play" if moved > 0.5
          else "input still does not arrive - check whether the virtual pad was created")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
