"""Mirror gBox's Hermes queue runs into ordinary Hermes sessions, so the Hermes desktop shows them (operator 2026-10-24:
"I need gbox mirrored into hermes so i can monitor it").

gBox dispatches each task as a one-shot cron job; Hermes records the run as a `cron` session, which the desktop hides
from its session list, and the job itself is deleted after the run, so the run never appears under CRON JOBS either.
This copies each recent gBox run (prompt, assistant text, tool calls and results, trimmed) into a session the desktop
lists, titled "gBox ▸ <node> ▸ #<request> <title>", and keeps appending while the run is still going.

Run with Hermes's own interpreter (it writes through Hermes's session API, never into its tables directly):
    ~/.hermes/tools/python-3.14.*/bin/python3 -I ~/gBox/system/scripts/hermes_mirror.py [--hours 6]
State: gbox-data/hermes-dispatch/hermes-mirror.json (cron session id -> mirror session id, messages copied).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get('HERMES_HOME') or Path.home() / '.hermes')
GBOX = Path(__file__).resolve().parent.parent
STATE = GBOX / 'gbox-data' / 'hermes-dispatch' / 'hermes-mirror.json'
QUEUE = GBOX / 'gbox-data' / 'hermes-dispatch' / 'work-queue.json'
TEXT_MAX, TOOL_MAX = 6000, 1500
ASSIGNED = re.compile(r'request #(\d+) \(([0-9a-f]{16})\)')


def node_of(model: str) -> str:
    m = (model or '').lower()
    return 'DeepSeek' if 'deepseek' in m else 'spark2' if 'qwen' in m or 'nvidia' in m or 'sparkdeux' in m else (model or 'Hermes')


def trim(text, limit):
    text = str(text or '')
    return text if len(text) <= limit else text[:limit] + f' … [{len(text) - limit} more characters]'


def turn(row) -> tuple[str, str] | None:
    """One stored message as a (role, text) turn for the mirror; tool calls and results become readable lines."""
    role, content = row['role'], row['content'] or ''
    if role == 'user':
        return 'user', trim(content, TEXT_MAX)
    if role == 'assistant':
        parts = []
        if row['reasoning']:
            parts.append('💭 ' + trim(row['reasoning'], TOOL_MAX))
        if content:
            parts.append(trim(content, TEXT_MAX))
        try:
            calls = json.loads(row['tool_calls'] or '[]') or []
        except ValueError:
            calls = []
        for call in calls:
            fn = (call or {}).get('function') or {}
            parts.append(f"🔧 {fn.get('name') or call.get('name') or 'tool'}({trim(fn.get('arguments') or '', 400)})")
        return ('assistant', '\n\n'.join(parts)) if parts else None
    if role == 'tool':
        return 'assistant', f"↳ {row['tool_name'] or 'result'}: {trim(content, TOOL_MAX)}"
    return None


def titles() -> dict[str, dict]:
    """Queue items by request id and by request number (a favorite-lane prompt names the item's own request)."""
    try:
        items = json.loads(QUEUE.read_text(encoding='utf-8')).get('items') or {}
    except (OSError, ValueError):
        return {}
    out = {i.get('request_id'): i for i in items.values() if i.get('request_id')}
    out.update({str(i.get('number')): i for i in items.values() if i.get('number')})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=float, default=6.0)
    args = ap.parse_args(argv)
    sys.path.insert(0, str(HOME / 'hermes-agent'))
    sys._hermes_pin_default_home = True
    import hermes_bootstrap                                        # noqa: F401 - Hermes's own dependency paths
    from hermes_state_registry import acquire                      # Hermes's own session store API
    from hermes_cli.foreign_sessions import new_session_id

    state = {}
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    src = sqlite3.connect(f'file:{HOME / "state.db"}?mode=ro', uri=True, timeout=10)
    src.row_factory = sqlite3.Row
    since = time.time() - args.hours * 3600
    runs = src.execute("SELECT id, model, started_at, ended_at, message_count FROM sessions WHERE source='cron' "
                       "AND started_at > ? AND message_count > 0 ORDER BY started_at", (since,)).fetchall()
    queue = titles()
    db = acquire()
    copied = 0
    try:
        for run in runs:
            msgs = src.execute('SELECT role, content, tool_calls, tool_name, reasoning FROM messages '
                               'WHERE session_id=? ORDER BY id', (run['id'],)).fetchall()
            first = next((m['content'] for m in msgs if m['role'] == 'user' and m['content']), '') or ''
            if 'Assigned queue task' not in first:
                continue                                           # only gBox's queue runs
            seen = state.get(run['id']) or {}
            if seen.get('done') or len(msgs) <= seen.get('copied', 0):
                continue
            match = ASSIGNED.search(first)
            number, rid = (match.group(1), match.group(2)) if match else ('?', '')
            item = queue.get(rid) or queue.get(number) or {}
            label = (item.get('title') or '').strip()[:70]
            status = 'finished' if run['ended_at'] else 'running'
            node = node_of(item.get('inference_node') or run['model'])
            title = f"gBox ▸ {node} ▸ #{number} {label} ({status})"
            mirror = seen.get('mirror')
            if not mirror:
                mirror = new_session_id()
                origin = {'gbox_mirror': {'cron_session': run['id'], 'request_id': rid, 'request_number': number}}
                db.create_session(mirror, source='claude', cwd=str(GBOX), origin_json=json.dumps(origin))
            for row in msgs[seen.get('copied', 0):]:
                t = turn(row)
                if t:
                    db.append_message(mirror, t[0], t[1])
            try:
                db.set_session_title(mirror, title)
            except Exception:                                      # noqa: BLE001 - the title is cosmetic
                pass
            state[run['id']] = {'mirror': mirror, 'copied': len(msgs), 'done': bool(run['ended_at']), 'at': time.time()}
            copied += 1
    finally:
        try:
            db.close()
        except Exception:                                          # noqa: BLE001
            pass
    cutoff = time.time() - 3 * 86400
    state = {k: v for k, v in state.items() if v.get('at', 0) > cutoff}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state), encoding='utf-8')
    tmp.replace(STATE)
    print(f'mirrored {copied} run(s)')


if __name__ == '__main__':
    main()
