"""`re_agent`: ReAgent's reverse -> check -> fix loop, ported onto gBox's own Ghidra Bridge and LLM router.

Upstream: Dryxio/reagent (MIT, https://github.com/Dryxio/reagent). ReAgent reconstructs C/C++ for one function at a
time from Ghidra evidence: a reverser model writes a candidate (and may first ask for more read-only evidence), an
independent checker model compares it with the decompilation (PASS/FAIL + issues + fix instructions), a conservative
structural verifier (call / branch counts, constant returns) can veto a PASS, and the loop feeds the issues back for a
bounded number of rounds, stopping early when a round repeats the same candidate and diagnostics. Function selection
uses three strategies: high-impact (most callers first), easiest-first (fewest callers first) and dependency-order
(callees before callers).

What gBox ports (no upstream package, CLI, setup wizard or LLM provider is vendored):
  * the loop, its stop rules and call budget            -> run_loop()
  * the reverser's evidence requests ({"actions": ...})  -> served by gBox's ghidra_bridge (decompile / xrefs / strings)
  * the checker's JSON or VERDICT: verdict format        -> parse_verdict()
  * the structural verifier                              -> objective()
  * the three selection strategies                       -> pick()
Models come from gBox's llm_endpoints (OpenAI-compatible, same as llm_complete). The results are hypotheses: a PASS is
"the checker and verifier found no mismatch", not proof of equivalence. Record what holds up with re_dossier.

Register with:  from . import re_agent  # noqa: F401
"""
import hashlib
import json
import re

import httpx
from pydantic import BaseModel, Field

from .models import Permission as P
from .registry import ToolUnavailable, tool

STRATEGIES = {
    "high-impact": "most callers first: reconstructing widely used helpers unblocks the most other functions",
    "easiest-first": "fewest callers first: small leaf-like functions build momentum and evidence",
    "dependency-order": "callees before callers: each function's dependencies are reconstructed before it",
}
EVIDENCE_TOOLS = {"decompile", "xrefs_to", "xrefs_from", "strings", "containing"}

REVERSER_SYSTEM = """You are an expert reverse engineer. Convert Ghidra's decompiled native code into clean C/C++ that keeps
the binary's observable behaviour exactly.
- Match the logic EXACTLY: every branch, every call, every arithmetic operation, integer widths, signedness, offsets.
- Floating-point expression order matters (A*x + B*y is not B*y + A*x).
- Use names and types only where the evidence supports them; call out unresolved types or symbols instead of guessing.
If essential evidence is missing you may first request read-only tools by answering ONLY with
{"actions":[{"tool":"decompile","target":"0x..."}]}  (tools: decompile, xrefs_to, xrefs_from, strings, containing).
Otherwise give the function in one ```cpp block and end with: REVERSED_FUNCTION: <Class::Name> (<0xADDRESS>)"""

CHECKER_SYSTEM = """You are a reverse-engineering quality checker. Verify that the reversed C/C++ matches Ghidra's
decompilation: every line of Ghidra logic has corresponding source, every struct offset maps to a member, every call is
identified, expression order matches, no branch or edge case is missing.
Answer with a single JSON object and nothing else:
{"verdict": "PASS or FAIL", "summary": "one short line", "issues": ["..."], "fix_instructions": ["..."]}"""


# --- parsing ---------------------------------------------------------------------------------------------------------------

VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|FAIL)", re.I)
SUMMARY_RE = re.compile(r"SUMMARY:\s*(.+)")
LIST_RE = {k: re.compile(k + r":\s*\n((?:\s*-\s*.+\n?)+)", re.I) for k in ("ISSUES", "FIX_INSTRUCTIONS")}


def parse_verdict(text: str) -> dict:
    """Checker reply -> {verdict PASS|FAIL|UNKNOWN, summary, issues, fix_instructions} (JSON first, then labelled lines)."""
    t = (text or "").strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", t, re.S)
    if m:
        t = m.group(1)
    if t.startswith("{"):
        try:
            d = json.loads(t)
        except ValueError:
            d = None
        if isinstance(d, dict):
            v = str(d.get("verdict", "")).upper()
            lst = lambda x: [str(i) for i in x] if isinstance(x, list) else []
            return {"verdict": v if v in ("PASS", "FAIL") else "UNKNOWN", "summary": str(d.get("summary", "")),
                    "issues": lst(d.get("issues")), "fix_instructions": lst(d.get("fix_instructions"))}
    v = VERDICT_RE.search(t)
    s = SUMMARY_RE.search(t)

    def items(key):
        m2 = LIST_RE[key].search(t + "\n")
        return [x.strip().lstrip("- ").strip() for x in m2.group(1).strip().splitlines()
                if x.strip().lstrip("- ").strip().lower() not in ("", "none")] if m2 else []
    return {"verdict": v.group(1).upper() if v else "UNKNOWN", "summary": s.group(1).strip() if s else "",
            "issues": items("ISSUES"), "fix_instructions": items("FIX_INSTRUCTIONS")}


def extract_code(text: str) -> str:
    blocks = re.findall(r"```(?:cpp|c\+\+|c)?\s*\n(.*?)```", text or "", re.S)
    return max(blocks, key=len).strip() if blocks else ""


def parse_actions(text: str) -> list[dict] | None:
    t = (text or "").strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", t, re.S)
    if m:
        t = m.group(1)
    if not t.startswith("{"):
        return None
    try:
        d = json.loads(t)
    except ValueError:
        return None
    acts = d.get("actions") if isinstance(d, dict) else None
    return [a for a in acts if isinstance(a, dict) and a.get("tool") in EVIDENCE_TOOLS] if isinstance(acts, list) else None


def _strip_comments(code: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", code or "", flags=re.S)


def _body(code: str) -> str:
    i = (code or "").find("{")
    return code[i:] if i >= 0 else (code or "")


KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "do", "else", "case"}


def count_calls(code: str) -> int:
    return sum(1 for m in re.finditer(r"\b([A-Za-z_][\w:]*)\s*\(", code) if m.group(1) not in KEYWORDS
               and not re.match(r"^(u?int\d*_t|char|short|int|long|float|double|bool|void|unsigned|undefined\d*)$", m.group(1)))


def count_flow(code: str) -> int:
    return len(re.findall(r"\b(if|for|while|case|goto)\b|\?", code))


def objective(code: str, decompiled: str, callees: int | None, call_tol: int = 3, flow_tol: int = 2) -> dict:
    """ReAgent's conservative structural verifier: FAIL only on strong mismatches, else PASS (or UNKNOWN with no checks)."""
    if not (code or "").strip():
        return {"verdict": "FAIL", "findings": ["candidate code is empty"]}
    src = _strip_comments(_body(code))
    dec = _strip_comments(_body(decompiled or ""))
    findings, checks = [], 0
    const = re.compile(r"\{\s*return\s+(-?(?:0x[0-9a-fA-F]+|[0-9]+))\s*;\s*\}")
    a, b = const.fullmatch(dec.strip()), const.fullmatch(src.strip())
    if a and b:
        checks += 1
        if int(a.group(1), 0) != int(b.group(1), 0):
            findings.append("constant return value differs from the decompilation")
    calls = count_calls(src)
    if callees is not None:
        checks += 1
        if calls < callees and callees - calls >= call_tol:
            findings.append(f"call count mismatch: the decompilation calls {callees} functions, the candidate makes {calls} calls")
    df, sf = count_flow(dec), count_flow(src)
    if df >= 2:
        checks += 1
        if sf < df and df - sf >= flow_tol:
            findings.append(f"control-flow mismatch: the decompilation has {df} branches/loops, the candidate {sf}")
    return {"verdict": "FAIL" if findings else ("PASS" if checks else "UNKNOWN"), "findings": findings, "checks": checks}


# --- selection --------------------------------------------------------------------------------------------------------------

def pick(functions: list[dict], strategy: str = "high-impact", done=(), attempts=None, max_attempts: int = 3,
         deps=None) -> list[dict]:
    """Order candidates like ReAgent's function picker. functions: [{address, name, callers}]; deps(address) -> callee
    addresses (dependency-order only)."""
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {sorted(STRATEGIES)}")
    attempts = attempts or {}
    norm = lambda a: str(a).lower().removeprefix("0x").lstrip("0")
    done_n = {norm(a) for a in done}
    cand = [f for f in functions if norm(f["address"]) not in done_n and attempts.get(f["address"], 0) < max_attempts]
    key_easy = lambda f: (f.get("callers") or 0, str(f.get("name")), str(f["address"]))
    if strategy == "easiest-first":
        return sorted(cand, key=key_easy)
    if strategy == "high-impact":
        return sorted(cand, key=lambda f: (-(f.get("callers") or 0), str(f.get("name")), str(f["address"])))
    by, order, seen, active = {norm(f["address"]): f for f in cand}, [], set(), set()

    def visit(a):
        if a in seen or a in active:
            return
        active.add(a)
        for d in sorted({norm(x) for x in (deps(by[a]["address"]) if deps else [])}):
            if d in by:
                visit(d)
        active.discard(a)
        seen.add(a)
        order.append(by[a])
    for f in sorted(cand, key=key_easy):
        visit(norm(f["address"]))
    return order


# --- the loop ---------------------------------------------------------------------------------------------------------------

class Budget(Exception):
    pass


def run_loop(target: str, query, llm, checker_llm=None, max_rounds: int = 4, max_investigations: int = 8,
             max_llm_calls: int = 40, label: str = "", progress=None) -> dict:
    """target: 0x address or name. query(op, **args) -> ghidra_bridge result. llm(messages) -> text."""
    if max_rounds < 1:
        raise ValueError("max_rounds must be positive")
    checker_llm = checker_llm or llm
    calls = {"n": 0}
    latest_excerpt = ''
    def report(message, code=None):
        nonlocal latest_excerpt
        if progress:
            if code:
                latest_excerpt = '\nLatest inspected code excerpt:\n' + '\n'.join(str(code).splitlines()[:24])[:2400]
            progress((message + latest_excerpt).replace(' #fit{', ' # fit{'))

    def ask(model, messages):
        if calls["n"] >= max_llm_calls:
            raise Budget(f"LLM call budget of {max_llm_calls} spent")
        calls["n"] += 1
        report(f'Analyzing {target}: model call {calls["n"]}/{max_llm_calls}')
        return model(messages)

    d = query("decompile", target=target)
    if not d.get("decompiled"):
        raise RuntimeError(f"Ghidra could not decompile {target}: {d.get('error')}")
    name = label or d.get("name") or target
    addr = d.get("address") or target
    report(f'Ghidra decompiled {name} ({addr}); inspecting source evidence', d['decompiled'])
    evidence, investigations = [], 0
    transcript, rounds = [], []
    verdict = obj = None
    code, seen = "", set()
    task = (f"Reverse {name} ({addr}).\n\nGhidra decompilation:\n```c\n{d['decompiled']}\n```\n\n"
            f"Callers: {json.dumps([c.get('function') for c in d.get('callers', [])][:20])}\n"
            f"Callees: {json.dumps([(c.get('name'), c.get('address')) for c in d.get('callees', [])][:40])}")
    history = [{"role": "system", "content": REVERSER_SYSTEM}, {"role": "user", "content": task}]
    stop = None
    try:
        for rnd in range(1, max_rounds + 1):
            report(f'Reconstruction round {rnd}/{max_rounds}: {name}')
            # reverse / fix, answering evidence requests first (bounded)
            while True:
                reply = ask(llm, list(history))
                transcript.append({"round": rnd, "role": "reverser", "text": reply})
                acts = parse_actions(reply)
                if acts is None or investigations >= max_investigations:
                    break
                answers = []
                for a in acts[:max(0, max_investigations - investigations)]:
                    investigations += 1
                    report(f'Inspecting {a["tool"]}: {a.get("target", "")} ({investigations}/{max_investigations})')
                    args = {"pattern": a.get("target", "")} if a["tool"] == "strings" else \
                        {"address": a.get("target", "")} if a["tool"] == "containing" else {"target": a.get("target", "")}
                    try:
                        res = query(a["tool"], **args)
                    except Exception as e:  # noqa: BLE001 - an evidence gap is reported to the model, not fatal
                        res = {"error": str(e)}
                    evidence.append({"tool": a["tool"], "target": a.get("target"), "result": res})
                    answers.append({"tool": a["tool"], "target": a.get("target"), "result": res})
                history += [{"role": "assistant", "content": reply},
                            {"role": "user", "content": "Evidence:\n" + json.dumps(answers, default=str)[:24000] +
                             "\nNow give the function in one ```cpp block."}]
            code = extract_code(reply) or code
            report(f'Candidate reconstruction for {name}; checking against Ghidra (hypothesis)', code)
            history.append({"role": "assistant", "content": reply})
            # independent check + structural verifier
            check_reply = ask(checker_llm, [{"role": "system", "content": CHECKER_SYSTEM},
                                            {"role": "user", "content": f"Function {name} ({addr}).\n\nReversed code:\n```cpp\n{code}\n```"
                                                                        f"\n\nGhidra decompilation:\n```c\n{d['decompiled']}\n```"}])
            transcript.append({"round": rnd, "role": "checker", "text": check_reply})
            verdict = parse_verdict(check_reply)
            obj = objective(code, d["decompiled"], len(d.get("callees") or []) if d.get("callees") is not None else None)
            report(f'Round {rnd}: checker {verdict["verdict"]}, structural checks {obj["verdict"]}; gameplay verification pending')
            rounds.append({"round": rnd, "checker": verdict, "objective": obj, "code_sha256": hashlib.sha256(code.encode()).hexdigest()})
            if verdict["verdict"] == "PASS" and obj["verdict"] != "FAIL":
                break
            key = hashlib.sha256(json.dumps([code, verdict, obj["findings"]], sort_keys=True).encode()).hexdigest()
            if key in seen:
                stop = "identical candidate and diagnostics without progress"
                break
            seen.add(key)
            if rnd < max_rounds:
                history.append({"role": "user", "content": "The checker found issues. Fix all of them; output the complete "
                                f"function in one ```cpp block.\nChecker: {verdict['summary']}\nIssues:\n- " +
                                "\n- ".join(verdict["issues"] + obj["findings"] or ["(none listed)"]) +
                                "\nFix instructions:\n- " + "\n- ".join(verdict["fix_instructions"] or ["(none listed)"])})
    except Budget as e:
        stop = str(e)
    success = bool(verdict and verdict["verdict"] == "PASS" and obj and obj["verdict"] != "FAIL")
    return {"target": addr, "name": name, "success": success, "status": "hypothesis", "code": code,
            "checker": verdict, "objective": obj, "rounds": rounds, "rounds_used": len(rounds), "stopped": stop,
            "llm_calls": calls["n"], "investigations": investigations, "evidence": evidence, "transcript": transcript,
            "note": "PASS = the checker and the structural verifier found no mismatch; not a proof of equivalence."}


# --- gBox glue --------------------------------------------------------------------------------------------------------------

def llm_for(config, endpoint: str | None = None, model: str | None = None):
    """An OpenAI-compatible chat function over config.llm_endpoints (the same routing as llm_complete)."""
    import os
    eps = config.llm_endpoints
    ep = next((e for e in eps if e.name == endpoint), None) if endpoint else (eps[0] if eps else None)
    if ep is None:
        raise ToolUnavailable(f"no llm_endpoints entry {endpoint!r} on this worker" if endpoint else
                              "re_agent needs an llm_endpoints entry (OpenAI-compatible) on this worker")
    headers = {"Authorization": f"Bearer {os.environ[ep.api_key_env]}"} if ep.api_key_env else {}

    def chat(messages):
        r = httpx.post(f"{ep.url.rstrip('/')}/chat/completions", json={"model": model or ep.model, "messages": messages},
                       headers=headers, timeout=600)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""
    return chat


def bridge_query(inp, config, worker):
    from .ghidra_bridge_tool import GhidraBridgeIn, run

    def q(op, **args):
        return run(GhidraBridgeIn(op=op, export_dir=inp.export_dir, **args), config, worker)["result"]
    return q


class ReAgentIn(BaseModel):
    op: str = Field("strategies", description="strategies | pick | reverse | check | verify")
    target: str | None = None            # reverse/check/verify: 0x address or function name (open in ghidra_bridge)
    query: str = ""                      # pick: function-name filter, e.g. 'CPed::' or 'Weather'
    strategy: str = "high-impact"
    limit: int = Field(20, ge=1, le=200)
    done: list[str] = []                 # pick: addresses already reconstructed
    code: str | None = None              # check/verify: a candidate written elsewhere (e.g. by the chat model)
    endpoint: str | None = None          # llm_endpoints name (default: first)
    checker_endpoint: str | None = None  # independent checker model (default: same endpoint)
    model: str | None = None
    max_rounds: int = Field(4, ge=1, le=10)
    max_investigations: int = Field(8, ge=0, le=40)
    max_llm_calls: int = Field(40, ge=1, le=200)
    export_dir: str | None = None        # query an offline Ghidra Bridge export instead of the live bridge


class ReAgentOut(BaseModel):
    op: str
    worker_id: str
    result: dict


def run(inp: ReAgentIn, config, worker="local", query=None, llm=None, checker_llm=None, progress=None) -> dict:
    q = query or bridge_query(inp, config, worker)
    if inp.op == "strategies":
        return {"strategies": STRATEGIES, "loop": ["reverse (evidence requests served by ghidra_bridge)", "independent check",
                                                   "structural verifier", "fix with issues", "stop on PASS, budget or repeat"],
                "upstream": "https://github.com/Dryxio/reagent (MIT)"}
    if inp.op == "pick":
        fns = q("functions", query=inp.query, limit=max(inp.limit * 5, 50))["functions"]
        rows = []
        for f in fns[:inp.limit * 5]:
            callers = f.get("callers")
            if callers is None:
                callers = len({x.get("function_address") for x in q("xrefs_to", target=f["address"], limit=500)["xrefs"]
                               if x.get("function_address")})
            rows.append({"address": f["address"], "name": f["name"], "callers": callers})
        deps = (lambda a: [c["address"] for c in q("xrefs_from", target=a)["callees"]]) if inp.strategy == "dependency-order" else None
        ordered = pick(rows, inp.strategy, inp.done, deps=deps)[:inp.limit]
        return {"strategy": inp.strategy, "why": STRATEGIES[inp.strategy], "candidates": ordered}
    if not inp.target:
        raise ValueError(f"op={inp.op} needs target (0x address or function name)")
    if inp.op == "verify":
        d = q("decompile", target=inp.target)
        return {"target": d.get("address"), "objective": objective(inp.code or "", d.get("decompiled") or "", len(d.get("callees") or []))}
    if inp.op == "check":
        d = q("decompile", target=inp.target)
        chk = checker_llm or llm or llm_for(config, inp.checker_endpoint or inp.endpoint, inp.model)
        reply = chk([{"role": "system", "content": CHECKER_SYSTEM},
                     {"role": "user", "content": f"Function {d.get('name')} ({d.get('address')}).\n\nReversed code:\n```cpp\n"
                                                 f"{inp.code or ''}\n```\n\nGhidra decompilation:\n```c\n{d.get('decompiled')}\n```"}])
        return {"target": d.get("address"), "checker": parse_verdict(reply),
                "objective": objective(inp.code or "", d.get("decompiled") or "", len(d.get("callees") or [])), "status": "hypothesis"}
    if inp.op == "reverse":
        rev = llm or llm_for(config, inp.endpoint, inp.model)
        chk = checker_llm or (llm_for(config, inp.checker_endpoint, inp.model) if inp.checker_endpoint else None)
        return run_loop(inp.target, q, rev, chk, inp.max_rounds, inp.max_investigations, inp.max_llm_calls, progress=progress)
    raise ValueError(f"unknown op {inp.op!r}: strategies | pick | reverse | check | verify")


@tool("re_agent", "1.0", ReAgentIn, ReAgentOut, capabilities=["reverse-engineering", "ghidra", "llm"],
      platforms=["windows", "linux", "darwin"], permissions=[P.READ, P.EXECUTE, P.NETWORK], timeout_s=3600,
      artifacts=["re_agent.json"], validation="output schema; reconstructions are hypotheses until validated in game")
def re_agent(inp: ReAgentIn, ctx):
    """ReAgent's loop on gBox: pick functions to reconstruct (high-impact | easiest-first | dependency-order), reverse one
    to C/C++ with a reverser model that can request Ghidra evidence, an independent checker verdict, a structural verifier
    and bounded fix rounds; or check/verify a candidate you wrote. Runs on the worker whose ghidra_bridge has the program
    open (or over export_dir)."""
    ctx.progress(1, f"re_agent {inp.op} {inp.target or inp.query}")
    ctx.nowait = True  # Display output must not add synchronous network waits to every inspected function.
    res = run(inp, ctx.config, ctx.worker, progress=lambda text:ctx.progress(1, text))
    ctx.artifact("re_agent.json", json.dumps(res, default=str).encode(), "application/json", op=inp.op,
                 upstream="https://github.com/Dryxio/reagent")
    if "transcript" in res:
        res = {k: v for k, v in res.items() if k not in ("transcript", "evidence")} | \
              {"evidence_calls": len(res["evidence"]), "full_report": "re_agent.json"}
    return {"op": inp.op, "worker_id": ctx.worker, "result": res}
