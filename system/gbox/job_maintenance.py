"""Retire abandoned, read-only frame requests without stopping a game."""
from __future__ import annotations

import json
import time


def retire_stalled_snapshots(store, *, now: float | None = None, timeout: int = 120) -> list[str]:
    now = time.time() if now is None else now
    retired = []
    with store.lock:
        rows = store.db.execute("SELECT id,body FROM docs WHERE kind='job' "
                                "AND json_extract(body,'$.state')='running' "
                                "AND json_extract(body,'$.tool')='get_frame'").fetchall()
        for jid, original in rows:
            job = json.loads(original)
            started = job.get('started') or job.get('created') or now
            if now - started <= timeout:
                continue
            reason = f'Frame capture timed out after {timeout}s; no screenshot was produced. The game was not stopped.'
            job.update(state='failed', finished=now, error=reason, cancel=True)
            # A separate worker may have just posted its result. Never overwrite
            # that result from an earlier snapshot of the document.
            changed = store.db.execute("UPDATE docs SET body=? WHERE kind='job' AND id=? AND body=?",
                                       (json.dumps(job), jid, original)).rowcount
            store.db.commit()
            if changed:
                retired.append(jid)
                store.audit('scheduler', 'job.failed', jid, {'reason': reason, 'read_only_capture': True})
    return retired
