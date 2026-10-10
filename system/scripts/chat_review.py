"""Review what the operator asked gBox's agent and how it executed it: one compact block per request, failures flagged.

    python scripts/chat_review.py [--hours 24] [--chat ID] [--only-failed] [--full]

Flags a request when the agent errored, gave up ("couldn't find", "I can't"), answered a do-this request with only
web results, repeated itself, or claimed success without a verified/landed result. Reads GBOX_TOKEN (or the data dir's
api_token via --config) and the control plane URL from --server (default http://10.89.1.246:8765).
"""
import argparse, json, os, re, sys, time
import httpx

GIVE_UP = re.compile(r"(could ?n[o']t|can ?not|can't|unable to|not (?:possible|supported)|no (?:specific|reliable) "
                     r"(?:code|address)|I (?:was|am) not able)", re.I)
DO = re.compile(r"^(give|make|set|equip|skip|take|put|turn|spawn|replace|load|start|warp|increase|double|triple|max|"
                r"enable|disable|freeze|change|let me|i want|allow|get me)\b", re.I)
WRITE_TOOLS = {"poke", "write_memory", "freeze_memory", "cheats", "pso_drops", "pso_inventory", "zelda_oot", "mod",
               "script_patch", "autoplay", "session_op"}


def client(server):
    tok = os.environ.get("GBOX_TOKEN")
    if not tok:
        for p in (r"\\10.89.1.246\ehm_eckx\gBox\system\gbox-data\api_token", "/home/ehm_eckx/gBox/system/gbox-data/api_token"):
            if os.path.exists(p):
                tok = open(p).read().strip(); break
    if not tok:
        sys.exit("set GBOX_TOKEN")
    return httpx.Client(base_url=server, headers={"authorization": f"Bearer {tok}"}, timeout=60)


def turns(events):
    """Split a chat's events into (user request, [events until the next request])."""
    cur = None
    for e in events:
        if e.get("type") == "user":
            if cur:
                yield cur
            cur = (e, [])
        elif cur:
            cur[1].append(e)
    if cur:
        yield cur


def judge(req, evs):
    calls = [e for e in evs if e.get("type") == "tool_call"]
    results = [e for e in evs if e.get("type") == "tool_result"]
    answer = " ".join(e.get("text", "") for e in evs if e.get("type") == "assistant")
    names = [c["name"] for c in calls]
    flags = []
    errs = [r for r in results if '"error"' in (r.get("text") or "")[:400] or '"state": "failed"' in (r.get("text") or "")]
    if errs:
        squash = lambda t: re.sub(r"\s+", " ", t)[:140]
        flags.append(f"{len(errs)} tool error(s): " + "; ".join(f"{r['name']}: {squash(r['text'])}" for r in errs[:3]))
    if GIVE_UP.search(answer):
        flags.append("gave up / said it can't")
    text = (req.get("text") or "").strip()
    if DO.search(text) and not WRITE_TOOLS & set(names):
        flags.append("do-request but nothing was changed in the game (" + (", ".join(sorted(set(names))) or "no tools") + ")")
    if names and set(names) <= {"web_search", "recall", "wiki", "image_search", "browse"} and DO.search(text):
        flags.append("answered a do-request with web results only")
    if any('"repeat": true' in (r.get("text") or "") for r in results):
        flags.append("repeated an identical tool call")
    if WRITE_TOOLS & set(names) and re.search(r"\b(done|enabled|activated|now have|is now)\b", answer, re.I) and \
            not any(re.search(r'"(verified|landed)": true', r.get("text") or "") for r in results):
        flags.append("claimed success without a verified result")
    if not answer.strip():
        flags.append("no final answer (still running, crashed, or asked a question)")
    return flags, names, answer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://10.89.1.246:8765")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--end", type=float, help="Unix timestamp ending the audit window (default: now)")
    ap.add_argument("--chat")
    ap.add_argument("--only-failed", action="store_true")
    ap.add_argument("--full", action="store_true", help="print every tool call with args and result")
    a = ap.parse_args()
    c = client(a.server)
    chats = [{"id": a.chat}] if a.chat else c.get("/api/chat").json()
    end = a.end if a.end is not None else time.time()
    since = end - a.hours * 3600
    n_req = n_bad = 0
    for ch in chats:
        d = c.get(f"/api/chat/{ch['id']}").json()
        game = ", ".join(g.get("title", "") for g in d.get("games") or []) or "-"
        for req, evs in turns(d.get("events", [])):
            if not since <= (req.get("ts") or 0) < end:
                continue
            n_req += 1
            flags, names, answer = judge(req, evs)
            n_bad += bool(flags)
            if a.only_failed and not flags:
                continue
            when = time.strftime("%m-%d %H:%M", time.localtime(req.get("ts") or 0))
            print(f"\n=== {when} chat {ch['id']} [{game}] {'FAIL' if flags else 'ok'}")
            print("asked :", (req.get("text") or "").split("\n[context:")[0][:300])
            print("tools :", " > ".join(names) or "-")
            for f in flags:
                print("  !", f)
            if a.full:
                for e in evs:
                    if e.get("type") == "tool_call":
                        print("   call", e["name"], json.dumps(e.get("args"))[:300])
                    elif e.get("type") == "tool_result":
                        print("   ->  ", re.sub(r"\s+", " ", e.get("text") or "")[:300])
            print("answer:", re.sub(r"\s+", " ", answer)[:400])
    print(f"\n{n_req} requests in {a.hours:g} h ending {time.strftime('%m-%d %H:%M', time.localtime(end))}, {n_bad} flagged")


if __name__ == "__main__":
    main()
