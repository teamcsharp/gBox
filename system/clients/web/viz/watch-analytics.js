// Watching a game: what the bot is doing and what gBox is working on, beside the gameplay (operator 2026-10-20: "if
// I'm tuned into the Spark and watching gameplay ... seeing analytics and statistics based on the data that's being
// ran, the tools that are being run, and what Ghidra is doing in the background").
// GBoxWatchAnalytics.show(sid, {api}) mounts a collapsible panel on the right; hide() removes it. It polls every 4 s:
//   GET /api/autoplay/telemetry/{sid}        live autoplay state the worker posts (mode, playbook, fights, jumps...)
//   GET /api/background/workers/{worker}/status   the PC's active jobs, server runs and recent tool results
//   GET /api/sessions/{sid}/coach            the newest coaching note for this game (gbox/coaching.py): "Coach: ..."
// Analysis work (Ghidra, REA, decompilers, binary analysis) is called out on its own. Pure DOM + fetch; no framework.
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const ANALYSIS = /ghidra|re_study|analyze_binary|decomp|rea_|rea$|re_lab|disasm|n64recomp|xenonrecomp|rexglue|assimilate/i;
  const LABELS = { fights_s: "Time in fights (s)", jumps: "Jump-state skips", routes: "Menu walks", saves: "Jump states saved",
    safety: "Health top-ups", fighting: "In a fight", p1_hp: "P1 health", p2_hp: "P2 health", hung: "Hung",
    ff_s: "Fast-forwarded (s)", bursts: "Moves played", novelty: "Novelty", kills: "Kills", score: "Score" };
  let el = null, timer = null, sid = null, io = null, collapsed = false;

  function fmt(v) {
    if (v == null) return "–";
    if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
    if (typeof v === "object") return Object.entries(v).map(([k, x]) => `${k} ${fmt(x)}`).join(" · ");
    return String(v);
  }

  function ago(s) {
    if (s == null || !isFinite(s)) return "";
    if (s < 10) return "just now";
    if (s < 90) return `${Math.round(s)} s ago`;
    if (s < 5400) return `${Math.round(s / 60)} min ago`;
    if (s < 172800) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} days ago`;
  }

  // the rows the panel shows (pure: tests drive it); coach = GET /api/sessions/{sid}/coach
  function model(tel, status, coach) {
    const out = { bot: [], analysis: [], jobs: [], runs: [], results: [] };
    const note = coach && coach.latest;
    if (note && note.text) {
      const text = String(note.text).length > 160 ? String(note.text).slice(0, 159) + "…" : String(note.text);
      out.coach = { line: `Coach: ${text}` + (ago(note.age_s) ? ` · ${ago(note.age_s)}` : ""),
                    detail: [note.note != null && `note ${note.note}`, coach.number != null && `ticket #${coach.number}`,
                             coach.count > 1 && `${coach.count} notes kept`].filter(Boolean).join(" · "),
                    summary: note.summary || "" };
    }
    if (tel && tel.running !== undefined) {
      out.bot.push(["Autoplay", tel.running ? "playing" : "stopped"]);
      if (tel.mission) out.bot.push(["Doing", tel.mission]);
      for (const [k, v] of Object.entries(tel.stats || {})) out.bot.push([LABELS[k] || k.replace(/_/g, " "), fmt(v)]);
      if (tel.age_s != null) out.bot.push(["Updated", `${Math.round(tel.age_s)} s ago`]);
    }
    for (const j of (status && status.active) || []) {
      const row = { tool: j.tool || j.name || "job", what: j.progress?.msg || j.progress || j.state || "" };
      (ANALYSIS.test(row.tool) ? out.analysis : out.jobs).push(row);
    }
    for (const r of (status && status.coordinator && status.coordinator.runs) || []) {
      const row = { tool: r.name || "run", what: r.progress || r.state || "" };
      (ANALYSIS.test(row.tool + " " + row.what) ? out.analysis : out.runs).push(row);
    }
    for (const r of ((status && status.recent_results) || []).slice(0, 5)) out.results.push({ tool: r.tool || "job", what: r.state || "" });
    return out;
  }

  function html(m, title) {
    const list = (rows, empty) => rows.length ? rows.map(r => `<div class="wa-r"><b>${ESC(r.tool)}</b><span>${ESC(fmt(r.what)).slice(0, 140)}</span></div>`).join("")
      : `<div class="wa-e">${ESC(empty)}</div>`;
    const coach = m.coach ? `<section><h4>Coach</h4><div class="wa-r wa-coach"><b>${ESC(m.coach.line)}</b>` +
      (m.coach.detail ? `<span>${ESC(m.coach.detail)}</span>` : "") + (m.coach.summary ? `<span>${ESC(m.coach.summary)}</span>` : "") +
      `</div></section>` : "";
    return `<div class="wa-h"><b>${ESC(title)}</b><button class="wa-x" title="Collapse">${collapsed ? "◂" : "▸"}</button></div>` + (collapsed ? "" :
      coach + `<section><h4>Bot</h4>${m.bot.length ? m.bot.map(([k, v]) => `<div class="wa-kv"><span>${ESC(k)}</span><b>${ESC(v)}</b></div>`).join("") : '<div class="wa-e">No autoplay on this game.</div>'}</section>
       <section><h4>Ghidra / analysis</h4>${list(m.analysis, "No analysis running right now.")}</section>
       <section><h4>Jobs on this PC</h4>${list(m.jobs, "Nothing else running here.")}</section>
       <section><h4>Server runs</h4>${list(m.runs.slice(0, 6), "No server run reported.")}</section>
       <section><h4>Just finished</h4>${list(m.results, "Nothing recent.")}</section>`);
  }

  const CSS = `#watch-analytics{position:fixed;right:12px;top:96px;width:300px;max-height:calc(100vh - 140px);overflow:auto;z-index:40;
    background:#0b1424e8;border:1px solid #33507a;border-radius:10px;color:#dce8ff;font:12px system-ui;padding:10px;box-shadow:0 8px 24px #0008}
    #watch-analytics.wa-c{width:auto}#watch-analytics h4{margin:10px 0 4px;font-size:11px;color:#8fb0e0;text-transform:uppercase;letter-spacing:.04em}
    #watch-analytics .wa-h{display:flex;align-items:center;gap:8px}#watch-analytics .wa-h b{flex:1}
    #watch-analytics .wa-x{background:#193054;border:1px solid #496b9e;color:#dce8ff;border-radius:6px;cursor:pointer}
    #watch-analytics .wa-kv,#watch-analytics .wa-r{display:flex;justify-content:space-between;gap:8px;padding:2px 0;border-top:1px solid #1e3150}
    #watch-analytics .wa-r{flex-direction:column}#watch-analytics .wa-r span{color:#a7b9d9}#watch-analytics .wa-e{color:#7f93b5}
    #watch-analytics .wa-coach b{color:#ffe08a;white-space:normal}`;

  async function tick() {
    if (!el || !sid) return;
    let tel = null, status = null, coach = null;
    try { tel = await io.api(`/api/autoplay/telemetry/${encodeURIComponent(sid)}`); } catch {}
    try { status = await io.api(`/api/background/workers/${encodeURIComponent(io.worker(sid, tel))}/status`); } catch {}
    try { coach = await io.api(`/api/sessions/${encodeURIComponent(sid)}/coach`); } catch {}
    if (!el) return;
    el.classList.toggle("wa-c", collapsed);
    el.innerHTML = html(model(tel, status, coach), tel && tel.title ? tel.title : "Watching");
    el.querySelector(".wa-x").onclick = () => { collapsed = !collapsed; tick(); };
    timer = setTimeout(tick, 4000);
  }

  function show(sessionId, opts) {
    if (sessionId === sid && el) return;
    hide();
    sid = sessionId; io = opts;
    if (!document.getElementById("watch-analytics-css")) {
      const st = document.createElement("style"); st.id = "watch-analytics-css"; st.textContent = CSS; document.head.append(st);
    }
    el = document.createElement("aside"); el.id = "watch-analytics"; document.body.append(el);
    tick();
  }

  function hide() {
    clearTimeout(timer); timer = null;
    if (el) el.remove();
    el = null; sid = null;
  }

  const api = { show, hide, model, html, ago, ANALYSIS };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GBoxWatchAnalytics = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
