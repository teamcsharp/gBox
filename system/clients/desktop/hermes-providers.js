// Tasks window "Providers" view: which Hermes provider did the work, which is out of credit, and where credit
// buys the most. Pure renderers over GET /api/hermes/providers?window=today|7d, so node tests can run them;
// the desktop page wires them into the Visual tab (cards) and the Technical tab (table).
(function (root) {
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const WINDOWS = [["today", "Today"], ["7d", "7 days"]];
  const STATE = {
    working: "Working", out_of_credit: "Out of credit", usage_limit: "Usage limit", cooling: "Cooling down",
    rate_limited: "Rate limited", failing: "Failing", idle: "Idle",
  };
  function tokens(n) {
    n = Number(n || 0);
    return n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n);
  }
  function duration(s) {
    s = Math.max(0, Math.round(Number(s || 0)));
    if (s < 60) return s + "s";
    const m = Math.round(s / 60);
    return m < 60 ? m + "m" : `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
  }
  function ago(ts, now) {
    if (!ts) return "";
    const s = Math.max(0, (now ?? Date.now() / 1000) - ts);
    return s < 90 ? Math.round(s) + "s ago" : s < 5400 ? Math.round(s / 60) + "m ago" : s < 172800 ? (s / 3600).toFixed(1) + "h ago" : Math.round(s / 86400) + "d ago";
  }
  const usd = v => v == null ? "" : "$" + Number(v).toFixed(Number(v) >= 100 ? 0 : 2);
  // "$0.12 left · $24.85 today" for OpenRouter; the reason a balance is unknown for everything else.
  function balance(b, windowName) {
    if (!b) return "Balance not available";
    if (!b.available) return b.note || "Balance not available";
    const parts = [];
    if (b.remaining_usd != null) parts.push(`${usd(b.remaining_usd)} left`);
    const spent = windowName === "7d" ? b.usage_weekly : b.usage_daily;
    if (spent != null) parts.push(`${usd(spent)} ${windowName === "7d" ? "this week" : "today"}`);
    if (b.total_credits != null) parts.push(`of ${usd(b.total_credits)} credit`);
    if (b.key_limit != null) parts.push(`key limit ${usd(b.key_limit)}`);
    return parts.join(" · ") + (b.stale ? " (refreshing)" : "");
  }
  // "llamacpp · Qwen3.6-35B…" for a run node and its detail; falls back to the model alone.
  function runLabel(run) {
    return [run?.provider, run?.model].filter(Boolean).join(" · ");
  }
  function windowButtons(current) {
    return `<span class="tkp-window" role="group" aria-label="Providers window">${WINDOWS.map(([id, label]) =>
      `<button type="button" data-tkp-window="${id}" aria-pressed="${id === current}">${label}</button>`).join("")}</span>`;
  }
  function tags(r) {
    return [r.current ? '<span class="tkp-tag current">current</span>' : "",
      r.local ? '<span class="tkp-tag local">local model</span>' : "",
      r.in_routes === false ? '<span class="tkp-tag">not in routes</span>' : ""].join("");
  }
  function clock(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }
  // "Hermes is on the local model" (or "Local fallback ready"): the Spark's GPU route, why it is used, what it served.
  function localBanner(local, now) {
    if (!local || local.enabled === false) return "";
    const on = !!local.active;
    const why = on ? (local.reason || "Every paid route is cooling down or out of credit")
      : "Standby: used only when every paid route is out of credit";
    const next = on && local.next_paid_at ? ` · next paid retry ${clock(local.next_paid_at)}` : "";
    const stats = `${local.calls_ok || 0} calls · ${tokens(local.tokens)} tokens · ${local.runs_completed || 0} runs`
      + (local.refused_while_playing ? ` · ${local.refused_while_playing} held while you played` : "")
      + (local.trimmed_calls ? ` · ${local.trimmed_calls} trimmed to fit` : "");
    return `<div class="tkp-local ${on ? "active" : "standby"}" data-tkp-local="${on ? "active" : "standby"}">
      <b>${on ? "Hermes is on the local model" : "Local fallback ready"}</b><span class="tkp-tag local">${esc(local.provider)} · ${esc(local.model)}</span>
      <span class="tkp-local-why">${esc(why + next)}</span><span class="tkp-local-stats">${esc(stats)}</span></div>`;
  }
  // The Spark helper's card: "Spark helper: doing X", or why it waits, and its last finished chore.
  function gruntCard(g, now) {
    if (!g) return "";
    const label = g.label || (g.doing ? `Spark helper: ${g.doing}` : g.waiting ? `Spark helper waiting: ${g.waiting}` : "Spark helper idle");
    const state = g.running ? "working" : g.enabled === false || g.waiting ? "cooling" : "idle";
    const last = (g.chores || []).filter(c => c.last_run).sort((a, b) => b.last_run - a.last_run)[0];
    const failed = (g.chores || []).filter(c => c.last_status === "error").length;
    return `<article class="tkp-card tkp-grunt ${state}" data-tkp-grunt>
      <header><b>Spark helper</b><span class="tkp-tag">no LLM</span></header>
      <div class="tkp-status" title="${esc(label)}"><i></i>${esc(label)}</div>
      ${last ? `<div class="tkp-model" title="${esc(JSON.stringify(last.last_result || {}))}">Last: ${esc(last.title)} · ${ago(last.last_run, now)}</div>` : ""}
      ${failed ? `<div class="tkp-error">${failed} chore${failed === 1 ? "" : "s"} failed last time</div>` : ""}</article>`;
  }
  function errorLine(err, now) {
    return err ? `<div class="tkp-error" title="${esc(err.text)}">${esc(String(err.text).slice(0, 110))} · ${ago(err.ts, now)}</div>` : "";
  }
  // Visual tab: the recommendation and one card per route.
  function cards(data, opts = {}) {
    const win = opts.window || data?.window || "today", now = opts.now;
    if (!data || data.error) return `<div class="tkp-head"><b>Providers</b>${windowButtons(win)}<span class="tkp-rec">${esc(data?.error ? `Providers unavailable: ${data.error}` : "Loading providers…")}</span></div>`;
    const routes = data.routes || [];
    const body = routes.map(r => {
      const s = r.status || {}, credit = r.local ? "Local model: no credit needed" : balance(r.balance, win);
      return `<article class="tkp-card ${esc(s.state || "idle")}${r.current ? " current" : ""}" data-tkp-route="${esc(r.key)}">
        <header><b>${esc(r.provider)}</b>${tags(r)}</header><div class="tkp-model" title="${esc(r.model)}">${esc(r.model)}</div>
        <div class="tkp-status"><i></i>${esc(s.label || STATE[s.state] || "Unknown")}</div>
        <dl><div><dt>Runs done</dt><dd>${r.runs_completed || 0}${r.runs_failed ? ` <small>· ${r.runs_failed} failed</small>` : ""}</dd></div>
          <div><dt>Model calls</dt><dd>${r.calls_ok || 0}${r.calls_failed ? ` <small>· ${r.calls_failed} failed</small>` : ""}</dd></div>
          <div><dt>Tokens</dt><dd>${tokens(r.tokens)}</dd></div><div><dt>Wall time</dt><dd>${duration(r.wall_s)}</dd></div></dl>
        <div class="tkp-balance" title="${esc(credit)}">${esc(credit)}</div>${errorLine(r.last_error, now)}</article>`;
    }).join("") || '<p class="tkp-empty">No Hermes routes or model calls found on the server.</p>';
    return `<div class="tkp-head"><b>Providers · ${esc(data.window_label || win)}</b>${windowButtons(win)}<span class="tkp-rec">${esc(data.recommendation || "")}</span></div>
      ${localBanner(data.local, now)}<div class="tkp-cards">${gruntCard(data.grunt, now)}${body}</div>`;
  }
  // Technical tab: the same numbers as a table, per provider and per route, plus recent run attribution.
  function table(data, opts = {}) {
    const win = opts.window || data?.window || "today", now = opts.now;
    if (!data || data.error) return `<div class="mc"><div class="mh"><b>Hermes providers</b>${windowButtons(win)}</div><p class="mut">${esc(data?.error ? `Providers unavailable: ${data.error}` : "Loading providers…")}</p></div>`;
    const routes = (data.routes || []).map(r => {
      const s = r.status || {};
      return `<tr class="tkp-row ${esc(s.state || "idle")}"><td><b>${esc(r.provider)}</b> ${tags(r)}<div class="mut">${esc(r.model)}</div></td>
        <td><span class="tkp-dot"></span>${esc(s.label || STATE[s.state] || "")}</td><td>${r.runs_completed || 0}</td><td>${r.runs_failed || 0}</td>
        <td>${r.calls_ok || 0} / ${r.calls_failed || 0}</td><td>${tokens(r.tokens)}</td><td>${duration(r.wall_s)}</td>
        <td>${r.local ? '<span class="mut">local</span>' : r.balance?.available ? esc(balance(r.balance, win))
          : `<span class="mut" title="${esc(balance(r.balance, win))}">not available</span>`}</td>
        <td class="tkp-err">${r.last_error ? `${esc(String(r.last_error.text).slice(0, 160))} <span class="mut">${ago(r.last_error.ts, now)}</span>` : '<span class="mut">—</span>'}</td></tr>`;
    }).join("") || '<tr><td colspan="9" class="mut" style="text-align:left">No Hermes routes or model calls found on the server.</td></tr>';
    const providers = (data.providers || []).map(p => `<tr><td><b>${esc(p.provider)}</b>${p.local ? ' <span class="tkp-tag local">local</span>' : ""}</td>
        <td>${esc(p.status?.label || "")}</td><td>${p.runs_completed || 0}</td><td>${p.calls_ok || 0} / ${p.calls_failed || 0}</td>
        <td>${tokens(p.tokens)}</td><td>${duration(p.wall_s)}</td>
        <td>${p.spend_usd != null ? `${usd(p.spend_usd)} <span class="mut">${esc(p.spend_source || "")}</span>` : '<span class="mut">unknown</span>'}</td>
        <td>${p.per_run_usd != null ? usd(p.per_run_usd) : '<span class="mut">—</span>'}</td></tr>`).join("");
    const runs = (data.runs || []).slice(0, 12).map(r => `<tr><td>${ago(r.start, now)}</td><td>${esc(r.name || r.job_id || "")}</td>
        <td>${r.provider ? esc(runLabel(r)) : '<span class="mut">no successful call</span>'}</td><td>${esc(r.status)}</td>
        <td>${tokens(r.tokens)}</td><td>${duration(r.wall_s)}</td><td class="mut">${esc((r.tried || []).join(" → "))}</td></tr>`).join("");
    const g = data.grunt;
    const chores = g ? (g.chores || []).map(c => `<tr><td><b>${esc(c.title)}</b>${c.running ? ' <span class="tkp-tag current">running</span>' : ""}${c.enabled === false ? ' <span class="tkp-tag">off</span>' : ""}</td>
        <td>${c.last_run ? ago(c.last_run, now) : '<span class="mut">never</span>'}</td><td>${esc(c.last_status || "")}</td>
        <td class="tkp-err">${esc(JSON.stringify(c.last_result || {}).slice(0, 160))}</td></tr>`).join("") : "";
    return `<div class="mc tkp-tech"><div class="mh"><b>Hermes providers · ${esc(data.window_label || win)}</b>${windowButtons(win)}</div>
      ${localBanner(data.local, now)}
      <p class="tkp-rec">${esc(data.recommendation || "")}</p>
      ${g ? `<details data-tk-key="tkp-grunt"><summary>${esc(g.label || "Spark helper")}</summary>
        <table><tr><th>Chore</th><th>Last run</th><th>Result</th><th>Details</th></tr>${chores}</table></details>` : ""}
      <table><tr><th>Route</th><th>Status now</th><th>Runs done</th><th>Runs failed</th><th>Calls ok / failed</th><th>Tokens</th><th>Wall time</th><th>Credit</th><th>Last error</th></tr>${routes}</table>
      ${providers ? `<table><tr><th>Provider</th><th>Status</th><th>Runs done</th><th>Calls ok / failed</th><th>Tokens</th><th>Wall time</th><th>Spend</th><th>Per run</th></tr>${providers}</table>` : ""}
      ${runs ? `<details data-tk-key="tkp-runs"><summary>Recent runs and who served them (${data.runs_total || 0} in window${data.runs_unattributed ? `, ${data.runs_unattributed} without a successful call` : ""})</summary>
        <table><tr><th>Started</th><th>Job</th><th>Served by</th><th>Status</th><th>Tokens</th><th>Wall</th><th>Fell through</th></tr>${runs}</table></details>` : ""}</div>`;
  }
  root.GBoxProviders = { cards, table, runLabel, balance, tokens, duration, ago, STATE, localBanner, gruntCard };
})(typeof window !== "undefined" ? window : globalThis);
