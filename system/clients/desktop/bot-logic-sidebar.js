// The PiP's bot logic sidebar (operator 2026-10-28: "an arrow that shows here in PIP mode on hover that if I click it, a
// sidebar slides out that allows me to customize the bot logic on the fly"; "the bot automatically plays while I control
// the Autobot dynamically on the fly"): the running RE5 / RE6 Switch bot's live switches and dials (gbox.mercs.bot_logic,
// the re5_mods tool's op bot_logic), grouped. Each change is an operator job applied to the bot at once and read back;
// nothing flips optimistically. Settings are saved, so they hold across rounds, hot reloads and restarts.
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const CSS = `#bot-logic-tab{position:fixed;right:0;top:50%;transform:translateY(-50%);z-index:120;display:none;width:22px;
    height:56px;border:1px solid #666;border-right:0;border-radius:6px 0 0 6px;background:#101014dc;color:#fff;cursor:pointer;
    font:16px system-ui;opacity:0;transition:opacity .15s;-webkit-app-region:no-drag}
  body.gbox-compact #bot-logic-tab.ready{display:block}
  body.gbox-compact:hover #bot-logic-tab.ready,#bot-logic-tab.open{opacity:1}
  #bot-logic-panel{position:fixed;top:28px;right:0;bottom:0;width:min(320px,85vw);z-index:119;background:#101014f2;color:#ddd;
    font:11px system-ui;overflow:auto;padding:8px 10px;box-sizing:border-box;transform:translateX(105%);transition:transform .2s;
    border-left:1px solid #444;-webkit-app-region:no-drag}
  #bot-logic-panel.open{transform:none}
  #bot-logic-panel h3{margin:4px 0 6px;font-size:12px}#bot-logic-panel h4{margin:10px 0 4px;font-size:11px;color:#9cf}
  #bot-logic-panel .bl-row{display:grid;grid-template-columns:1fr auto;gap:2px 6px;align-items:center;margin:3px 0}
  #bot-logic-panel .bl-row small{grid-column:1/-1;color:#999}#bot-logic-panel input[type=range]{grid-column:1/-1;width:100%}
  #bot-logic-panel .bl-set{color:#ffd166}#bot-logic-panel .bl-msg{color:#ffadad;min-height:14px}
  #bot-logic-panel button{border:1px solid #666;border-radius:3px;background:#18181d;color:#fff;cursor:pointer;font:11px system-ui}`;

  function html(view, message = "") {
    if (!view) return `<h3>Bot logic</h3><p class="bl-msg">${ESC(message || "Reading the bot's settings…")}</p>`;
    const groups = {};
    for (const k of view.knobs || []) (groups[k.group] = groups[k.group] || []).push(k);
    const rows = Object.entries(groups).map(([g, ks]) => `<h4>${ESC(g)}</h4>` + ks.map(k => {
      const mark = k.set ? ' <span class="bl-set" title="Your setting (saved)">●</span>' : "";
      const tip = ESC(k.help || "");
      if (k.kind === "bool")
        return `<label class="bl-row" title="${tip}"><span>${ESC(k.label)}${mark}</span><input type="checkbox" data-bl="${ESC(k.name)}"${k.value ? " checked" : ""}></label>`;
      return `<div class="bl-row" title="${tip}"><span>${ESC(k.label)}${mark}</span><output data-bl-out="${ESC(k.name)}">${ESC(k.value)}</output>`
        + `<input type="range" data-bl="${ESC(k.name)}" min="${k.min}" max="${k.max}" step="${k.step}" value="${ESC(k.value)}" aria-label="${ESC(k.label)}">`
        + (k.help ? `<small>${tip}</small>` : "") + `</div>`;
    }).join("")).join("");
    return `<h3>Bot logic · ${ESC(String(view.title || "").toUpperCase())}</h3><p class="bl-msg">${ESC(message)}</p>${rows}`
      + `<p><button type="button" data-bl-reset>Reset all to the bot's defaults</button></p>`;
  }

  function create({ api, delay = ms => new Promise(r => setTimeout(r, ms)), doc = root.document }) {
    let tab = null, panel = null, sid = null, open = false, busy = false, view = null, message = "";
    const worker = () => (sid || "").split("-")[0] || undefined;
    function ensure() {
      if (tab || !doc) return;
      const style = doc.createElement("style"); style.textContent = CSS; doc.head.append(style);
      tab = doc.createElement("button"); tab.id = "bot-logic-tab"; tab.type = "button"; tab.textContent = "‹";
      tab.title = "Bot logic: tune the autobot live"; tab.onclick = () => toggle();
      panel = doc.createElement("aside"); panel.id = "bot-logic-panel"; panel.setAttribute("aria-label", "Bot logic");
      panel.addEventListener("change", e => { const n = e.target?.dataset?.bl; if (n) set(n, e.target.type === "checkbox" ? e.target.checked : Number(e.target.value)); });
      panel.addEventListener("input", e => { const n = e.target?.dataset?.bl; const o = n && panel.querySelector(`[data-bl-out="${n}"]`); if (o) o.textContent = e.target.value; });
      panel.addEventListener("click", e => { if (e.target?.dataset && "blReset" in e.target.dataset) send({ reset: true }); });
      doc.body.append(tab, panel);
    }
    function paint() { if (panel) panel.innerHTML = html(view, message); if (tab) tab.textContent = open ? "›" : "‹"; }
    async function job(input) {
      let j = await api("/api/jobs", { tool: "re5_mods", agent_use: false, require_worker: worker(),
        input: { session_id: sid, op: "bot_logic", ...input } }, "POST");
      for (let i = 0; i < 100 && ["queued", "running"].includes(j?.state); i++) {
        await delay(250);
        j = await api("/api/jobs/" + encodeURIComponent(j.id), undefined, "GET");
      }
      if (j?.state !== "succeeded") throw new Error(j?.error?.message || j?.error || "The bot logic job did not succeed.");
      return j.output?.result;
    }
    async function send(input) {
      if (busy || !sid) return;
      busy = true; message = "";
      try { const out = await job(input); if (out?.knobs) view = out; else message = "No settings came back."; }
      catch (e) { message = e.message || String(e); }
      finally { busy = false; paint(); }
    }
    const set = (name, value) => send({ values: { [name]: value } });
    function toggle(force) {
      open = force ?? !open;
      panel?.classList.toggle("open", open); tab?.classList.toggle("open", open);
      if (open && !view) send({});
      paint();
    }
    function update(state) {
      ensure();
      const next = state?.on && state?.sid ? state.sid : null;
      if (next !== sid) { sid = next; view = null; message = ""; if (open && sid) send({}); paint(); }
      tab?.classList.toggle("ready", !!sid);
      if (!sid && open) toggle(false);
    }
    return { update, toggle, set, state: () => ({ sid, open, view, message }) };
  }
  const api = { create, html };
  root.GBoxBotLogicSidebar = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
