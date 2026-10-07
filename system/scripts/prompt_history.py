"""Rebuild docs/prompt_history.md: every operator prompt in this project, verbatim, newest first.

Sources
* Claude Code transcripts for this project (~/.claude/projects/c---tools-gBox/*.jsonl): direct prompts and the
  messages sent while a turn was running (embedded in tool results as "The user sent a new message while you were
  working:").
* The gBox operator inbox (/api/requests): reports filed from the app.

Per prompt: Central time, tokens in/out (sum over the assistant replies until the next prompt; "in" includes cached
context reads), model(s), time to execute (prompt -> last reply in that window) and files adjusted (distinct paths
written by Write/Edit/NotebookEdit or reported "patched <file>" by patch scripts in that window).

Run by the Claude Code Stop hook (.claude/settings.json) so the file stays current; safe to run any time.
"""
import collections
import datetime as dt
import glob
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent                 # system/
CANON = Path("//10.89.1.246/ehm_eckx/gBox/system")                 # canonical tree on the Spark share; C:\_tools\gBox mirrors it
OUT = (CANON if CANON.exists() else HERE) / "docs" / "prompt_history.md"
PROJECT_DIRS = [Path.home() / ".claude" / "projects" / "c---tools-gBox"]
MIDTURN = re.compile(r"The user sent a new message while you were working:\n(.*?)\n\nThis is how Claude Code surfaces", re.S)
NOISE = ("<task-notification", "<local-command", "<system-reminder", "<command-name>", "[Request interrupted")

try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:                                              # Windows without tzdata: fixed offsets by season
    CT = None


def central(ts: str) -> str:
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if CT:
        t = t.astimezone(CT)
        tz = t.tzname()
    else:
        dst = 3 <= t.month <= 10
        t = t.astimezone(dt.timezone(dt.timedelta(hours=-5 if dst else -6)))
        tz = "CDT" if dst else "CST"
    return t.strftime("%m-%d-%y / %I:%M %p ") + tz


IDE = re.compile(r"<(ide_[a-z_]+)>.*?</\1>\s*", re.S)      # editor context Claude Code attaches, not the operator's words


def _text(content) -> str:
    if isinstance(content, list):
        content = "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return IDE.sub("", content).strip() if isinstance(content, str) else ""


def _tool_result_texts(content):
    if not isinstance(content, list):
        return []
    out = []
    for x in content:
        if isinstance(x, dict) and x.get("type") == "tool_result":
            c = x.get("content")
            out.append(c if isinstance(c, str) else _text(c))
    return out


def transcript_prompts() -> list[dict]:
    events, prompts = [], []
    for d in PROJECT_DIRS:
        for f in sorted(glob.glob(str(d / "*.jsonl"))):
            for ln in open(f, encoding="utf-8"):
                try:
                    e = json.loads(ln)
                except ValueError:
                    continue
                if e.get("type") in ("user", "assistant", "attachment") and e.get("timestamp"):
                    events.append(e)
    events.sort(key=lambda e: e["timestamp"])
    seen = set()
    for i, e in enumerate(events):
        if e["type"] == "attachment":                    # message typed while a turn was running
            a = e.get("attachment") or {}
            if a.get("type") == "queued_command":
                t = (_text(a.get("prompt")) if not isinstance(a.get("prompt"), str) else a["prompt"]).strip()
                imgs = sum(1 for x in a.get("prompt") or [] if isinstance(x, dict) and x.get("type") == "image")
                t = (t + "\n[image attached]" * imgs).strip()
                if t and not t.startswith(NOISE) and t[:200] not in seen:
                    seen.add(t[:200])
                    prompts.append({"i": i, "ts": e["timestamp"], "text": t, "kind": "sent mid-turn"})
            continue
        if e["type"] != "user":
            continue
        msg = e.get("message") or {}
        txt = _text(msg.get("content")).strip()
        if txt and not e.get("isMeta") and not txt.startswith(NOISE) and "summary below covers the earlier portion" not in txt:
            imgs = sum(1 for x in msg.get("content") or [] if isinstance(x, dict) and x.get("type") == "image")
            if txt[:200] not in seen:
                seen.add(txt[:200])
                prompts.append({"i": i, "ts": e["timestamp"], "text": txt + "\n[image attached]" * imgs, "kind": "direct"})
        for tr in _tool_result_texts(msg.get("content")):
            for m in MIDTURN.finditer(tr or ""):
                t = m.group(1).strip()
                key = t[:200]
                if key not in seen:                             # the same message can be echoed in several results
                    seen.add(key)
                    prompts.append({"i": i, "ts": e["timestamp"], "text": t, "kind": "sent mid-turn"})
    prompts.sort(key=lambda p: p["i"])
    # attribute assistant work to the prompt window [this prompt, next prompt)
    for n, p in enumerate(prompts):
        end = prompts[n + 1]["i"] if n + 1 < len(prompts) else len(events)
        tin = tout = 0
        models, files, last = collections.Counter(), set(), p["ts"]
        for e in events[p["i"]:end]:
            msg = e.get("message") or {}
            if e["type"] == "assistant":
                u = msg.get("usage") or {}
                tin += u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                tout += u.get("output_tokens", 0)
                if msg.get("model") and msg["model"] != "<synthetic>":
                    models[msg["model"]] += 1
                last = e["timestamp"]
                for c in msg.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") in ("Write", "Edit", "NotebookEdit"):
                        fp = (c.get("input") or {}).get("file_path") or (c.get("input") or {}).get("notebook_path")
                        if fp and "scratchpad" not in fp.replace("\\", "/"):
                            files.add(fp.replace("\\", "/").lower())
            else:
                for tr in _tool_result_texts(msg.get("content")):
                    for m in re.finditer(r"^patched (\S+)", tr or "", re.M):
                        files.add(m.group(1).lower())
        secs = (dt.datetime.fromisoformat(last.replace("Z", "+00:00")) - dt.datetime.fromisoformat(p["ts"].replace("Z", "+00:00"))).total_seconds()
        p.update(tokens_in=tin, tokens_out=tout, models=[m for m, _ in models.most_common()], secs=max(0, secs), files=len(files), file_list=sorted(files))
    return prompts


def inbox_prompts() -> list[dict]:
    """gBox operator inbox (app reports); metrics are recorded on the request by the agent ledger."""
    try:
        import httpx
        tok = (HERE / "gbox-data" / "api_token")
        tok = tok.read_text().strip() if tok.exists() else os.environ.get("GBOX_TOKEN", "")
        if not tok:
            p = Path("//10.89.1.246/ehm_eckx/gBox/system/gbox-data/api_token")
            tok = p.read_text().strip() if p.exists() else ""
        reqs = httpx.get("http://10.89.1.246:8765/api/requests", headers={"authorization": f"Bearer {tok}"}, timeout=10).json()
    except Exception:
        return []
    out = []
    for r in reqs if isinstance(reqs, list) else []:
        if r.get("source") == "chat":                   # mirrored Claude Code prompts: already logged from the transcript
            continue
        m = r.get("metrics") or {}
        created = r.get("created")
        ts = dt.datetime.fromtimestamp(created, dt.timezone.utc).isoformat() if created else None
        if not ts:
            continue
        out.append({"ts": ts, "text": ((r.get("messages") or [{}])[0].get("text") or r.get("body") or r.get("title") or "").strip(),
                    "kind": f"inbox #{r.get('number', r.get('id'))} ({r.get('source')})",
                    "tokens_in": m.get("tokens_in", 0), "tokens_out": m.get("tokens_out", 0),
                    "models": [m["model"]] if m.get("model") else [], "secs": m.get("duration_s") or 0,
                    "files": len(m.get("files_changed") or []), "status": r.get("status")})
    return out


SECRET = re.compile(r"(?i)\b(pw|pwd|pass(?:word)?|passcode|token|api[_ -]?key)(\s*[:=]?\s*)(\S+)")


def redact(t: str) -> str:
    """Credentials typed into a prompt ('ssh user@host / pw ...') never go into the history file or the inbox."""
    return SECRET.sub(lambda m: m[1] + m[2] + "[redacted]", t)


def fmt_secs(s: float) -> str:
    s = int(s)
    return f"{s // 3600}h {s % 3600 // 60:02d}m {s % 60:02d}s" if s >= 3600 else f"{s // 60}m {s % 60:02d}s"


def build() -> str:
    rows = transcript_prompts() + inbox_prompts()
    rows.sort(key=lambda p: p["ts"], reverse=True)                    # newest first
    lines = ["# Prompt history", "",
             "Every operator prompt in this project, verbatim, newest first. Generated by `system/scripts/prompt_history.py`",
             "after every Claude Code request (Stop hook) from the session transcripts and the gBox inbox; do not edit by hand.",
             "Tokens: in = input incl. cached context read per model call (summed over the request), out = generated tokens.",
             "Time = prompt → last reply before the next prompt. Files = distinct files written in that window.", "",
             f"Total prompts: {len(rows)}", ""]
    for n, p in enumerate(rows):
        lines += [f"## {len(rows) - n}. {central(p['ts'])} · {p['kind']}", "",
                  f"* Tokens in / out: {p['tokens_in']:,} / {p['tokens_out']:,}",
                  f"* Model: {', '.join(p['models']) or 'n/a'}",
                  f"* Time to execute: {fmt_secs(p['secs'])}",
                  f"* Files adjusted: {p['files']}", ""]
        body = redact(p["text"].replace("\r", ""))
        lines += ["```text", body.replace("```", "ʼʼʼ"), "```", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    md = build()
    OUT.write_text(md, encoding="utf-8")
    if "-q" not in sys.argv:
        print(f"wrote {OUT} ({md.count(chr(10) + '## ')} prompts)")
