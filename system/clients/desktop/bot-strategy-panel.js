// The PiP's bot strategy panel (operator #5250: "enable strategies ... check and uncheck them in a panel ... dragging and
// dropping and reordering them in an important stack ... adjust the priority and the intensity"). Backed by
// GET/POST /api/mercs/strategy (gbox/mercs/strategy.py). Every change is POSTed and the stack re-read from the reply;
// nothing flips optimistically. The bots read the saved stack each round.
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const CSS = `#bot-strategy-panel{position:fixed;top:40px;left:50%;transform:translateX(-50%);width:min(360px,92vw);max-height:80vh;
    overflow:auto;z-index:130;background:#101014f2;color:#ddd;font:11px system-ui;padding:8px 10px;border:1px solid #555;border-radius:6px;display:none}
  #bot-strategy-panel.open{display:block}#bot-strategy-panel h3{margin:2px 0 6px;font-size:12px}
  #bot-strategy-panel .bs-row{display:grid;grid-template-columns:auto 1fr auto;gap:2px 6px;align-items:center;margin:3px 0;padding:3px;border:1px solid #333;border-radius:4px;background:#18181d}
  #bot-strategy-panel .bs-row.drag{opacity:.4}#bot-strategy-panel .bs-grip{cursor:grab;color:#888}
  #bot-strategy-panel .bs-row.off{opacity:.55}#bot-strategy-panel input[type=range]{grid-column:2/-1;width:100%}
  #bot-strategy-panel small{grid-column:1/-1;color:#999}#bot-strategy-panel .bs-msg{color:#ffadad;min-height:14px}
  #bot-strategy-panel button{border:1px solid #666;border-radius:3px;background:#18181d;color:#fff;cursor:pointer;font:11px system-ui}`;

  function html(view, message = "") {
    if (!view) return `<h3>Bot strategy</h3><p class="bs-msg">${ESC(message || "Reading the strategy stack…")}</p>`;
    const rows = (view.strategies || []).map((s, i) => {
      const pct = Math.round(Number(s.intensity) * 100);
      return `<div class="bs-row${s.enabled ? "" : " off"}" draggable="true" data-bs-name="${ESC(s.name)}" title="${ESC(s.help)}">`
        + `<span class="bs-grip" aria-hidden="true">⠿ ${i + 1}</span>`
        + `<label><input type="checkbox" data-bs-on="${ESC(s.name)}"${s.enabled ? " checked" : ""}> ${ESC(s.label)}</label>`
        + `<output data-bs-out="${ESC(s.name)}">${pct}%</output>`
        + `<input type="range" data-bs-int="${ESC(s.name)}" min="0" max="1" step="0.05" value="${ESC(s.intensity)}" aria-label="${ESC(s.label)} intensity">`
        + `<small>${ESC(s.help)}</small></div>`;
    }).join("");
    return `<h3>Bot strategy · ${ESC(String(view.title || "").toUpperCase())} <button type="button" data-bs-close>✕</button></h3>`
      + `<p class="bs-msg">${ESC(message || "Top is highest priority. Drag to reorder.")}</p>${rows}`
      + `<p><button type="button" data-bs-reset>Reset all to defaults</button></p>`;
  }

  // New top-to-bottom order after dropping `name` onto `target` (before it); unchanged when either is unknown.
  function reorder(names, name, target) {
    const out = names.filter(n => n !== name);
    const at = out.indexOf(target);
    if (at < 0 || !names.includes(name) || name === target) return names.slice();
    out.splice(at, 0, name);
    return out;
  }

  function create({ api, doc = root.document }) {
    let panel = null, title = null, view = null, message = "", busy = false, dragging = null;
    const names = () => (view?.strategies || []).map(s => s.name);
    function paint() { if (panel) panel.innerHTML = html(view, message); }
    async function send(body) {
      if (busy || !title) return;
      busy = true; message = "";
      try {
        const out = body ? await api("/api/mercs/strategy", { title, ...body }, "POST")
                         : await api("/api/mercs/strategy?title=" + encodeURIComponent(title), undefined, "GET");
        if (out?.strategies) view = out; else message = "No strategies came back.";
      } catch (e) { message = e.message || String(e); }
      finally { busy = false; paint(); }
    }
    const setValue = (name, patch) => send({ values: { [name]: patch } });
    const move = (name, target) => { const o = reorder(names(), name, target); return o.join() === names().join() ? undefined : send({ reorder: o }); };
    function ensure() {
      if (panel || !doc) return;
      const style = doc.createElement("style"); style.textContent = CSS; doc.head.append(style);
      panel = doc.createElement("aside"); panel.id = "bot-strategy-panel"; panel.setAttribute("aria-label", "Bot strategy");
      panel.addEventListener("change", e => {
        const d = e.target?.dataset || {};
        if (d.bsOn) setValue(d.bsOn, { enabled: e.target.checked });
        else if (d.bsInt) setValue(d.bsInt, { intensity: Number(e.target.value) });
      });
      panel.addEventListener("input", e => {
        const n = e.target?.dataset?.bsInt, o = n && panel.querySelector(`[data-bs-out="${n}"]`);
        if (o) o.textContent = Math.round(Number(e.target.value) * 100) + "%";
      });
      panel.addEventListener("click", e => {
        const d = e.target?.dataset || {};
        if ("bsReset" in d) send({ reset: true }); else if ("bsClose" in d) close();
      });
      panel.addEventListener("dragstart", e => { const r = e.target.closest?.("[data-bs-name]"); if (r) { dragging = r.dataset.bsName; r.classList.add("drag"); if (e.dataTransfer) e.dataTransfer.effectAllowed = "move"; } });
      panel.addEventListener("dragover", e => { if (dragging) e.preventDefault(); });
      panel.addEventListener("drop", e => { const r = e.target.closest?.("[data-bs-name]"); e.preventDefault(); const n = dragging; dragging = null; if (r && n) move(n, r.dataset.bsName); });
      panel.addEventListener("dragend", () => { dragging = null; paint(); });
      doc.body.append(panel);
    }
    function open(t) { ensure(); title = t; view = null; message = ""; panel?.classList.add("open"); paint(); return send(); }
    function close() { panel?.classList.remove("open"); }
    return { open, close, set: setValue, move, reset: () => send({ reset: true }), state: () => ({ title, view, message }) };
  }
  // The strategy stack's title for a game name (the PiP knows only the game's name).
  const titleFor = name => /resident evil 6|biohazard 6|\bre6\b/i.test(name || "") ? "re6" : /resident evil 5|biohazard 5|\bre5\b/i.test(name || "") ? "re5" : null;
  const api = { create, html, reorder, titleFor };
  root.GBoxBotStrategyPanel = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
