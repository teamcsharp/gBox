"""DOA3's virtual controller: gBox's pad on the game's 4th controller port, written into the game's own RAM.

Why a pad in RAM. The pinned native runner (doa3-re v0.2) reads SDL gamepads and, only while runner.exe owns the
foreground window, the keyboard (GetAsyncKeyState). Docked in the gBox app it never owns the foreground, a virtual
gamepad needs a driver (ViGEmBus) that gBox must not install, and window messages don't reach GetAsyncKeyState.

How the game reads its pads (DOA3 USA XBE, capstone over the reviewed executable, 2026-10-20):
  * every frame the main loop (0x000A06D0) calls 0x0009EE80: poll 0x0009EAF0, convert 0x0009EB90, rumble 0x0009EDC0;
  * the poll calls XInputGetState(handle, state) for each port whose handle slot (0x5E5D48 + port * 0x80) is non-zero,
    and marks that port connected (0x5E5ED0) whatever the call returns;
  * the runner's XInputGetState (input_adapter.c) answers only handles it issued (0x5849000N) for ports it has a host
    device on; for any other handle it returns ERROR_DEVICE_NOT_CONNECTED and leaves the game's 22-byte XINPUT_STATE
    buffer (0x5E5CE9 + port * 0x80) untouched;
  * the conversion maps every connected port's buffer through the port's button table (0x219798 + port * 20) into the
    per-port masks (0x5E5ED8 + port * 0x2C) and the all-port masks (0x5E5F88: held, 0x5E5F90: newly pressed) that the
    menus read; a fighter reads the port the player-to-port table (0x2FD550) gives it, and the title gives P1 the port
    that pressed START.

So gBox claims port 4 (index 3): a handle the runner never issues goes into its slot (SENTINEL) and the buttons into its
state buffer. The game reads it like a real pad, with real press / release edges, from the next poll: at most one frame.

Why it cannot touch the operator's pad. It writes only these 26 bytes of port 4 (Doa3NativeAdapter allows its fast
channel nothing else). The operator's controller and the keyboard are SDL host input on port 1 (the runner gives the
first gamepad port 1); their slots, buffers and masks are never written, so both play on side by side. A real pad on
port 4 (a fourth controller plugged into the PC) carries a runner handle: claim() then refuses rather than take it.

During a fight a START press on a port that is not a player's lets that port join as a challenger (0x000822BB), so
the bot presses START only where the player-to-port table already gives P1 port 4 (doa3_bot)."""
from __future__ import annotations

import struct

PORT = 3                                     # the game's 4th controller port
HANDLE_AT = 0x5E5D48 + PORT * 0x80           # 0x5E5EC8: the game's XInput handle for that port (0 = no pad)
STATE_AT = 0x5E5CE9 + PORT * 0x80            # 0x5E5E69: XINPUT_STATE {dwPacketNumber u32, XINPUT_GAMEPAD 18 bytes}
STATE_SIZE = 22
CONNECTED_AT = 0x5E5ED0                      # u32: the ports the game polled this frame (bit 3 = port 4)
PLAYER_PORT_AT = 0x2FD550                    # u8 per player: the port it reads
SENTINEL = 0x47420004                        # "GB" + port 4; runner handles are 0x58490000 | (port + 1)
RUNNER_HANDLE = 0x58490000
BLOCK = ((HANDLE_AT, 4), (STATE_AT, STATE_SIZE))   # everything the pad ever writes

# XINPUT_GAMEPAD wButtons
DIGITAL = {"up": 0x1, "down": 0x2, "left": 0x4, "right": 0x8, "start": 0x10, "select": 0x20, "back": 0x20,
           "l3": 0x40, "r3": 0x80}
# gBox pad names are RetroPad positions (b south, a east, y west, x north); the Xbox analog buttons in XINPUT order
# A B X Y Black White LT RT. l / r = White / Black (Cxbx's layout), l2 / r2 the triggers.
ANALOG = {"b": 0, "a": 1, "y": 2, "x": 3, "r": 4, "l": 5, "l2": 6, "r2": 7,
          "xa": 0, "xb": 1, "xx": 2, "xy": 3, "black": 4, "white": 5, "lt": 6, "rt": 7}
KEYS = frozenset(DIGITAL) | frozenset(ANALOG)


class PadTaken(RuntimeError):
    """A real controller (a runner handle) is in port 4."""


def encode(held) -> bytes:
    """XINPUT_GAMEPAD's first 10 bytes (wButtons, 8 analog buttons) for a set of gBox pad names."""
    buttons, analog = 0, bytearray(8)
    for key in held:
        k = str(key).lower()
        if k in DIGITAL:
            buttons |= DIGITAL[k]
        elif k in ANALOG:
            analog[ANALOG[k]] = 0xFF
        else:
            raise ValueError(f"{key!r} is not a DOA3 pad button ({', '.join(sorted(KEYS))})")
    return struct.pack("<H", buttons) + bytes(analog)


class VirtualPad:
    """Port 4's state, through a memory with read(address, n) and write(address, data) (the adapter's fast channel)."""

    def __init__(self, mem):
        self.mem = mem
        self.held: set[str] = set()
        self.packet = 0
        self.claimed = False

    def claim(self) -> bool:
        """Put gBox's handle in port 4's slot (once). False when it already was there."""
        slot = struct.unpack("<I", bytes(self.mem.read(HANDLE_AT, 4)))[0]
        if slot == SENTINEL:
            self.claimed = True
            return False
        if slot & 0xFFFF0000 == RUNNER_HANDLE or slot not in (0, SENTINEL):
            raise PadTaken(f"port 4 holds a controller handle {slot:#x}: gBox's pad stays off it")
        self._write(bytes(10))                       # neutral before the game first polls the port
        self.mem.write(HANDLE_AT, struct.pack("<I", SENTINEL))
        self.claimed = True
        return True

    def connected(self) -> bool:
        """The game polled port 4 this frame (it shows the claim took)."""
        return bool(struct.unpack("<I", bytes(self.mem.read(CONNECTED_AT, 4)))[0] & (1 << PORT))

    def _write(self, gamepad: bytes):
        self.packet = (self.packet + 1) & 0xFFFFFFFF
        self.mem.write(STATE_AT, struct.pack("<I", self.packet) + gamepad)

    def set(self, held) -> None:
        """Hold exactly these buttons (gBox pad names) from the game's next poll on."""
        held = {str(k).lower() for k in held}
        data = encode(held)
        if not self.claimed:
            self.claim()
        self._write(data)
        self.held = held

    TAP_S = 0.035                                    # two frames: a press released in the same batch is still seen

    def apply(self, events: list[dict], sleep=None) -> dict:
        """send_input rows ({key, down}) in order. A key pressed and released in the same batch is held for TAP_S
        first (the game samples once a frame)."""
        import time
        sleep = sleep or time.sleep
        rows = [ev for ev in events if int(ev.get("player", 1)) == 1 and str(ev["key"]).lower() in KEYS]
        if not self.claimed and not any(ev.get("down", True) for ev in rows):
            return {"sent": 0, "via": "doa3 virtual pad (port 4, guest RAM)", "held": []}   # nothing to release
        held, pressed, sent = set(self.held), set(), 0
        for i, ev in enumerate(rows):
            key = str(ev["key"]).lower()
            if ev.get("down", True):
                held.add(key)
                pressed.add(key)
            else:
                if key in pressed:                   # down + up in one batch: let the game see the press
                    self.set(held)
                    sleep(self.TAP_S)
                    pressed.clear()
                    held.discard(key)
                    if i + 1 < len(rows):            # and its release, before anything that follows
                        self.set(held)
                        sleep(self.TAP_S)
                held.discard(key)
            sent += 1
        if sent:
            self.set(held)
        return {"sent": sent, "via": "doa3 virtual pad (port 4, guest RAM)", "held": sorted(self.held)}

    def release(self) -> None:
        if self.claimed:
            self._write(bytes(10))
        self.held = set()

    def unclaim(self) -> None:
        """Neutral, then the slot back to empty: the game drops the port at its next poll."""
        if not self.claimed:
            return
        self.release()
        if struct.unpack("<I", bytes(self.mem.read(HANDLE_AT, 4)))[0] == SENTINEL:
            self.mem.write(HANDLE_AT, bytes(4))
        self.claimed = False

    def player_port(self, player: int = 0) -> int:
        return bytes(self.mem.read(PLAYER_PORT_AT + player, 1))[0]
