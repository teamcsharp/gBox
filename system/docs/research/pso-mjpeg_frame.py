"""Read one frame from the session's MJPEG viewer stream (`GET /api/sessions/{sid}/mjpeg`).

The earlier attempt posted to `/api/sessions/{sid}/stream`, which is the **worker's upload** endpoint - the wrong direction. The viewer route is
`/mjpeg`, `multipart/x-mixed-replace; boundary=f`, which is what the web client puts in an `<img>`. Reading one part yields a real JPEG of the emulator's
current picture, which settles what PSO is actually showing.
"""
import json
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
OUT = r"D:\gBox\pso-ds\pso_screen.jpg"


def session_id() -> str:
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    rows = json.loads(urllib.request.urlopen(request, timeout=20).read() or b"[]")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    if not live:
        raise SystemExit("no live session")
    return live[0]["session_id"]


if __name__ == "__main__":
    sid = session_id()
    print("session:", sid)
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/mjpeg?fps=2" % sid,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    response = urllib.request.urlopen(request, timeout=25)
    print("content-type:", response.headers.get("content-type"))

    buffer = b""
    frame = None
    try:
        deadline = 40
        while len(buffer) < 2_000_000 and deadline:
            chunk = response.read(32768)
            if not chunk:
                break
            buffer += chunk
            start = buffer.find(b"\xff\xd8")
            if start >= 0:
                end = buffer.find(b"\xff\xd9", start + 2)
                if end > start:
                    frame = buffer[start:end + 2]
                    break
            deadline -= 1
    finally:
        response.close()

    if frame:
        open(OUT, "wb").write(frame)
        print("wrote", len(frame), "bytes to", OUT)
    else:
        print("no JPEG found; buffer head:", buffer[:120])
