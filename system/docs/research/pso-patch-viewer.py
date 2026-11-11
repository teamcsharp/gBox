"""Patch map_viewer.state() to be crash-proof: every read guarded, short blobs skipped, and the endpoint always answers.

The viewer died mid-request with a forcibly-closed connection, which happens when a read returns fewer bytes than struct.unpack needs.
All parsing now goes through small helpers that return None on a short or failed read, and the HTTP handler can never raise.
"""
import pathlib

PATH = pathlib.Path(r"C:\_tools\gBox\.tmp\map_viewer.py")
text = PATH.read_text(encoding="utf-8")

OLD_STATE = '''def state():
    payload = {"t": time.time(), "floor": int.from_bytes(_read(FLOOR, 4), "big"),
               "player": None, "hp": None, "doors": [], "enemies": []}
    actor = int.from_bytes(_read(0x8050EA10, 4), "big")
    if actor:
        blob = _read(actor + 0x38, 12)
        if len(blob) == 12:
            x, y, z = struct.unpack(">fff", blob)
            payload["player"] = {"x": round(x, 1), "y": round(y, 1), "z": round(z, 1)}
        payload["hp"] = int.from_bytes(_read(actor + HP, 2), "big")'''

NEW_STATE = '''def _u32(address):
    blob = _read(address, 4)
    return int.from_bytes(blob, "big") if len(blob) == 4 else 0


def _u16(address):
    blob = _read(address, 2)
    return int.from_bytes(blob, "big") if len(blob) == 2 else None


def _vec3(address):
    blob = _read(address, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def state():
    payload = {"t": time.time(), "floor": _u32(FLOOR), "player": None, "hp": None, "doors": [], "enemies": []}
    actor = _u32(0x8050EA10)
    if actor:
        point = _vec3(actor + 0x38)
        if point:
            x, y, z = point
            payload["player"] = {"x": round(x, 1), "y": round(y, 1), "z": round(z, 1)}
        payload["hp"] = _u16(actor + HP)'''

assert text.count(OLD_STATE) == 1, text.count(OLD_STATE)
text = text.replace(OLD_STATE, NEW_STATE)

OLD_LOOP = '''    raw = _read(TABLE, MAX_ENTRIES * 4)
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(_read(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = _cstring(name_pointer)
        if name.startswith("TObjDoor"):
            blob = _read(pointer, 0x190)
            if len(blob) >= 0x190:
                x, _y, z = struct.unpack(">fff", blob[0x38:0x44])
                payload["doors"].append({"i": index, "class": name, "x": round(x, 1), "z": round(z, 1),
                                         "state": struct.unpack(">i", blob[0x18C:0x190])[0]})
        elif name.startswith("TObjEne"):
            blob = _read(pointer + 0x38, 12)
            if len(blob) == 12:
                x, y, z = struct.unpack(">fff", blob)
                payload["enemies"].append({"class": name, "x": round(x, 1), "z": round(z, 1),
                                           "hp": int.from_bytes(_read(pointer + HP, 2), "big")})
    return payload'''

NEW_LOOP = '''    raw = _read(TABLE, MAX_ENTRIES * 4)
    if len(raw) < MAX_ENTRIES * 4:
        return payload
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(_read(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = _cstring(name_pointer)
        if name.startswith("TObjDoor"):
            blob = _read(pointer, 0x190)
            if len(blob) >= 0x190:
                x, _y, z = struct.unpack(">fff", blob[0x38:0x44])
                payload["doors"].append({"i": index, "class": name, "x": round(x, 1), "z": round(z, 1),
                                         "state": struct.unpack(">i", blob[0x18C:0x190])[0]})
        elif name.startswith("TObjEne"):
            point = _vec3(pointer + 0x38)
            if point:
                x, y, z = point
                hp = _u16(pointer + HP)
                payload["enemies"].append({"class": name, "x": round(x, 1), "z": round(z, 1), "hp": hp})
    return payload'''

assert text.count(OLD_LOOP) == 1, text.count(OLD_LOOP)
text = text.replace(OLD_LOOP, NEW_LOOP)

OLD_HANDLER = '''        if self.path == "/api/state":
            return self._send(200, json.dumps(state()))'''
NEW_HANDLER = '''        if self.path == "/api/state":
            try:
                return self._send(200, json.dumps(state()))
            except Exception as exc:                             # noqa: BLE001
                return self._send(200, json.dumps({"error": str(exc)[:120]}))'''
assert text.count(OLD_HANDLER) == 1, text.count(OLD_HANDLER)
text = text.replace(OLD_HANDLER, NEW_HANDLER)

PATH.write_text(text, encoding="utf-8")
print("map_viewer hardened")
