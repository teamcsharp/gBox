"""gBox's reverse-engineering library: what the in-app agent (local LLM) reads before a Ghidra task and writes after it,
so its proficiency on each title (and on each kind of task) grows as the operator works with it.

playbook  (docs kind "playbook")  a how-to for a recurring task (find a value writer, a patch point, a model loader...):
          steps naming the agent's exact tools and arguments, pitfalls, examples, and LESSONS the agent appends after a
          task worked or failed. Seeded from gbox/re_seeds.PLAYBOOKS; a newer seed_version replaces the seed text and keeps
          the lessons.
dossier   (docs kind "dossier", id = game_id)  everything known about one title: its executable (cpu, processor, load
          address, sha256), Ghidra analysis summary, findings (functions / globals / tables / hooks / formats) and open
          questions. Seeded with gbox/re_seeds.TITLE_FACTS (facts engineers verified) the first time it's read.

Accountability (plan §20/§21): an agent finding is a "hypothesis" unless it cites evidence artifacts that exist in the
store, which makes it "validated". "documented" = from the seeds (verified by engineers, cited by file).
"""
from __future__ import annotations

import re
import time

from . import re_seeds

STATUSES = ("hypothesis", "documented", "validated", "wrong")
KINDS = ("function", "global", "table", "hook", "format", "string", "struct", "note")


def _words(q: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (q or "").lower()) if len(w) > 1]


# ---------------------------------------------------------------- playbooks

def seed_playbooks(store) -> None:
    for pb in re_seeds.PLAYBOOKS:
        cur = store.get("playbook", pb["id"])
        if cur and cur.get("seed_version", 0) >= pb.get("seed_version", 1):
            continue
        store.put("playbook", pb["id"], dict(pb) | {"lessons": (cur or {}).get("lessons", []),
                                                    "version": (cur or {}).get("version", 0) + 1, "updated": time.time()})


def playbooks(store, query: str = "", platform: str = "") -> list[dict]:
    """Ranked by how well the task words match the playbook (when / tags / title / goal)."""
    seed_playbooks(store)
    ws, out = _words(query), []
    for pb in store.all("playbook"):
        hay = " ".join([pb.get("title", ""), pb.get("goal", ""), " ".join(pb.get("when", [])), " ".join(pb.get("tags", []))]).lower()
        score = sum(2 if any(w in phrase.lower() for phrase in pb.get("when", [])) else 1 for w in ws if w in hay) if ws else 1
        if platform and "any" not in pb.get("platforms", ["any"]) and platform not in pb.get("platforms", []):
            score -= 1
        if score > 0:
            out.append((score, pb))
    return [{"id": pb["id"], "title": pb.get("title"), "goal": pb.get("goal"), "lessons": len(pb.get("lessons", [])),
             "version": pb.get("version")} for _s, pb in sorted(out, key=lambda x: -x[0])]


def playbook(store, pid: str) -> dict | None:
    seed_playbooks(store)
    return store.get("playbook", pid)


def learn(store, pid: str, lesson: str, outcome: str = "worked", game: str = "", actor: str = "agent") -> dict:
    pb = playbook(store, pid)
    if not pb:
        raise KeyError(f"no playbook {pid!r}; list them with re_playbook op=list")
    if not (lesson or "").strip():
        raise ValueError("lesson: what to do differently / what worked, in one or two sentences")
    pb["lessons"] = (pb.get("lessons") or [])[-49:] + [{"text": lesson.strip()[:1200], "outcome": outcome, "game": game,
                                                        "by": actor, "ts": time.time()}]
    pb["version"], pb["updated"] = pb.get("version", 1) + 1, time.time()
    store.put("playbook", pid, pb)
    return {"playbook": pid, "version": pb["version"], "lessons": len(pb["lessons"])}


def render_playbook(pb: dict) -> str:
    out = [f"# Playbook {pb['id']} (v{pb.get('version', 1)}): {pb.get('title', '')}", f"Goal: {pb.get('goal', '')}", "Steps:"]
    for i, st in enumerate(pb.get("steps", []), 1):
        out.append(f"{i}. {st.get('do', '')}" + (f"  -> tool {st['tool']} {st.get('args', {})}" if st.get("tool") else "")
                   + (f"  (expect: {st['expect']})" if st.get("expect") else ""))
    if pb.get("pitfalls"):
        out += ["Pitfalls:"] + [f"- {p}" for p in pb["pitfalls"]]
    if pb.get("examples"):
        out += ["Worked before:"] + [f"- {e.get('game', '')}: {e.get('note', '')} [{e.get('ref', '')}]" for e in pb["examples"]]
    if pb.get("lessons"):
        out += ["Lessons learned (newest last):"] + [f"- [{l.get('outcome')}{' · ' + l['game'] if l.get('game') else ''}] {l['text']}"
                                                    for l in pb["lessons"][-15:]]
    return "\n".join(out)


# ---------------------------------------------------------------- dossiers

def _seed_facts(game: dict) -> dict | None:
    t, plat = (game.get("title") or "").lower(), game.get("platform") or ""
    for tf in re_seeds.TITLE_FACTS:
        if tf.get("platform") in (plat, "any") and all(w in t for w in tf.get("title_has", [])):
            return tf
    return None


def dossier(store, game: dict) -> dict:
    gid = game["game_id"]
    d = store.get("dossier", gid)
    if d:
        return d
    d = {"game_id": gid, "title": game.get("title"), "platform": game.get("platform"), "created": time.time(),
         "executable": None, "analysis": None, "findings": [], "questions": [], "log": []}
    tf = _seed_facts(game)
    if tf:
        d["label"] = tf.get("label")
        d["executable_hint"] = tf.get("executable")
        d["findings"] = [f | {"status": "documented", "by": "seed", "ts": time.time()} for f in tf.get("facts", [])]
    store.put("dossier", gid, d)
    return d


def _addr(a) -> str:
    if a in (None, ""):
        return ""
    s = str(a).strip()
    try:
        return f"0x{int(s, 16 if s.lower().startswith('0x') or re.search('[a-f]', s.lower()) else 10):08X}"
    except ValueError:
        return s


def record(store, game: dict, kind: str = "note", address="", name: str = "", role: str = "", status: str = "hypothesis",
           evidence: list[str] | None = None, question: str = "", actor: str = "agent") -> dict:
    """Add / update a finding (same kind+address or kind+name = update) or an open question."""
    d = dossier(store, game)
    if question:
        if question not in d["questions"]:
            d["questions"].append(question[:500])
        d["log"].append({"ts": time.time(), "by": actor, "question": question[:200]})
        store.put("dossier", d["game_id"], d)
        return {"questions": len(d["questions"])}
    kind = kind if kind in KINDS else "note"
    status = status if status in STATUSES else "hypothesis"
    ev = [e for e in (evidence or []) if isinstance(e, str) and re.fullmatch(r"[0-9a-f]{64}", e)]
    if status == "validated" and not any(store.get("artifact", e) for e in ev):
        status = "hypothesis"                          # validated needs evidence that exists (plan §20)
    if status == "documented" and actor != "seed":
        status = "hypothesis"                          # documented = engineers' seeds only
    f = {"kind": kind, "address": _addr(address), "name": (name or "")[:160], "role": (role or "")[:800], "status": status,
         "evidence": ev, "by": actor, "ts": time.time()}
    key = (f["kind"], f["address"] or f["name"])
    for i, old in enumerate(d["findings"]):
        if (old.get("kind"), old.get("address") or old.get("name")) == key:
            if old.get("status") in ("documented", "validated") and status == "hypothesis" and not f["role"]:
                return {"kept": old}                   # don't downgrade a verified fact with an empty guess
            d["findings"][i] = old | {k: v for k, v in f.items() if v not in ("", [], None)}
            break
    else:
        d["findings"].append(f)
    d["log"].append({"ts": time.time(), "by": actor, "finding": f"{kind} {f['address']} {f['name']} ({status})"})
    d["log"] = d["log"][-200:]
    store.put("dossier", d["game_id"], d)
    return {"finding": f, "findings": len(d["findings"])}


def set_study(store, game: dict, executable: dict | None, analysis: dict | None) -> dict:
    d = dossier(store, game)
    if executable:
        d["executable"] = executable
    if analysis:
        d["analysis"] = analysis
    d["log"].append({"ts": time.time(), "by": "re_study", "study": (executable or {}).get("sha256", "")[:12]})
    store.put("dossier", d["game_id"], d)
    return d


def render_dossier(d: dict) -> str:
    out = [f"# {d.get('title')} ({d.get('platform')}){' · ' + d['label'] if d.get('label') else ''} · game_id {d['game_id']}"]
    ex = d.get("executable")
    if ex:
        out.append(f"Executable: {ex.get('source_file')} ({ex.get('format')}) cpu {ex.get('cpu')} · Ghidra processor "
                   f"{ex.get('processor') or 'auto'} · base {ex.get('base')} · entry {ex.get('entry')} · sha256 {str(ex.get('sha256'))[:16]}… "
                   f"· ELF {ex.get('rel')}" + (f" · registers {ex['registers']}" if ex.get("registers") else ""))
    elif d.get("executable_hint"):
        out.append(f"Executable: not extracted yet (known setup: {d['executable_hint']}); run re_study")
    else:
        out.append("Executable: not extracted yet; run re_study")
    an = d.get("analysis")
    if an:
        out.append(f"Ghidra analysis: {an.get('functions')} functions, {an.get('strings')} strings (artifact {str(an.get('artifact'))[:16]}…)")
        if an.get("named"):
            out.append("Named functions (sample): " + ", ".join(an["named"][:40]))
        if an.get("strings_sample"):
            out.append("Strings of interest: " + " | ".join(an["strings_sample"][:30]))
    fs = d.get("findings") or []
    if fs:
        out.append(f"Findings ({len(fs)}):")
        rank = {"validated": 0, "documented": 1, "hypothesis": 2, "wrong": 3}
        for f in sorted(fs, key=lambda f: (rank.get(f.get("status"), 9), f.get("kind", ""), f.get("address", ""))):
            out.append(f"- [{f.get('status')}] {f.get('kind')} {f.get('address') or ''} {f.get('name') or ''}: {f.get('role') or ''}"
                       + (f" (evidence {', '.join(e[:12] for e in f['evidence'])})" if f.get("evidence") else "")
                       + (f" [{f['ref']}]" if f.get("ref") else ""))
    if d.get("questions"):
        out += ["Open questions:"] + [f"- {q}" for q in d["questions"][-20:]]
    return "\n".join(out)


def summarize_analysis(a: dict, artifact: str, keywords=("player", "item", "hp", "health", "life", "model", "load", "file",
                                                           "save", "stage", "room", "weapon", "ammo", "enemy", "pad", "input")) -> dict:
    """analysis.json (functions + strings from Ghidra) -> what fits in a dossier."""
    fns = a.get("functions") or []
    names = [f.get("name") if isinstance(f, dict) else str(f) for f in fns]
    named = [n for n in names if n and not re.match(r"^(FUN|LAB|thunk_FUN|SUB|switchD|sub|nullsub|j_sub|loc)_", n)]   # Ghidra + IDA defaults
    strs = [s.get("value") if isinstance(s, dict) else str(s) for s in (a.get("strings") or [])]
    hits = [s for s in strs if s and any(k in s.lower() for k in keywords) and len(s) < 120]
    return {"functions": len(fns), "strings": len(strs), "artifact": artifact, "named": named[:200], "strings_sample": hits[:80],
            "program": a.get("program")}
