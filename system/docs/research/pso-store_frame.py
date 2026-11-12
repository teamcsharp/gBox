"""Read the untruncated `get_frame` output out of the store, so the screen can finally be seen.

The API clips a job's output and sets `_gbox_truncated`, but the store keeps what the worker returned: `store.db` is
`<data_dir>/gbox.sqlite3` (`store.py`: `self.path = self.dir / "gbox.sqlite3"`). Reading it read-only cannot disturb the running app.

The value is a PNG rendered with `repr` inside `output["result"]["value"]`, so `ast.literal_eval` recovers the bytes.
"""
import ast
import json
import sqlite3
import urllib.request

DB = r"C:\_tools\gBox\system\gbox-data\gbox.sqlite3"
OUT = r"D:\gBox\pso-ds\pso_screen.png"


def latest_frame_job() -> str:
    token = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/jobs?limit=30",
        headers={"authorization": "Bearer " + token, "x-gbox-actor": "agent"})
    rows = json.loads(urllib.request.urlopen(request, timeout=30).read() or b"[]")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    for row in rows:
        if row.get("tool") == "session_op" and (row.get("input") or {}).get("op") == "get_frame":
            return row["id"]
    return ""


if __name__ == "__main__":
    connection = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=10)
    try:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print("tables:", tables[:12])

        job_id = latest_frame_job()
        print("frame job:", job_id or "(none found via the API)")

        # the store's shape: find the table that holds rows keyed by an id and containing 'output'
        for table in tables:
            try:
                columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]
            except sqlite3.Error:
                continue
            if not columns:
                continue
            print(f"  {table}: {columns[:8]}")

        # try the common shapes
        candidates = []
        for table in tables:
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]
            text_columns = [name for name in columns if name.lower() in ("value", "body", "row", "data", "json")]
            key_columns = [name for name in columns if name.lower() in ("key", "id", "name")]
            if text_columns and key_columns:
                candidates.append((table, key_columns[0], text_columns[0]))
        print("candidates:", candidates)

        for table, key_column, value_column in candidates:
            try:
                row = connection.execute(
                    f"SELECT {value_column} FROM {table} WHERE {key_column} = ?", (job_id,)).fetchone() if job_id else None
                if not row:
                    continue
                body = row[0]
                if isinstance(body, (bytes, bytearray)):
                    body = body.decode("utf-8", "replace")
                record = json.loads(body)
                value = ((record.get("output") or {}).get("result") or {}).get("value")
                if isinstance(value, str) and value.startswith("b'"):
                    raw = ast.literal_eval(value)
                    open(OUT, "wb").write(raw)
                    is_png = raw[:8] == bytes.fromhex("89504e470d0a1a0a")
                    print(f"wrote {len(raw)} bytes from {table} to {OUT} | PNG: {is_png}")
                    break
            except Exception as exc:                               # noqa: BLE001
                print(f"  {table}: {type(exc).__name__} {str(exc)[:70]}")
    finally:
        connection.close()
