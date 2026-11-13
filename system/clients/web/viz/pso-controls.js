// PSO controls for the Live controls sidebar: named weapons, a clickable item gallery with real stats, a paralysis
// button, and drops. The operator asked for three things this serves directly:
//   * "every option that I use in the sidebar I'm able to use to click and map and interact with the game"
//   * "instead of them being vague numericals, I need to be able to see what the stats are and what the stats are going
//     to be"
//   * "anytime we're referring to items, I need to see the names of the items and I need to be able to click on them
//     from a gallery of items instead of just having a list of numbers"
// So nothing here shows a raw item code: every item is its name plus its stats, and every control is a real click that
// posts a job and reports what the worker verified.
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);

  // Weapon ceilings are per weapon in PSO, not a flat 99: the catalog carries max_grind and the game clamps to it.
  const weapons = rows => (rows || []).filter(r => r.cat === "Weapons");
  const byPower = rows => weapons(rows).slice().sort((a, b) => (b.atp_max || 0) - (a.atp_max || 0));

  function stats(row) {
    if (!row) return "";
    const bits = [];
    if (row.atp_max) bits.push(`ATP ${row.atp_min ?? 0}–${row.atp_max}`);
    if (row.ata) bits.push(`ATA ${row.ata}`);
    if (row.max_grind) bits.push(`grind +${row.max_grind}`);
    if (row.stars) bits.push(`${row.stars}★`);
    return bits.join(" · ");
  }

  function weaponOptions(rows, currentCode) {
    const list = byPower(rows);
    if (!list.length) return `<option value="">No weapons in the catalog</option>`;
    return `<option value="">Equip a weapon…</option>` + list.map(w =>
      `<option value="${ESC(w.code)}"${w.code === currentCode ? " selected" : ""}>`
      + `${ESC(w.name)} — ${ESC(stats(w))}</option>`).join("");
  }

  // The gallery: one clickable tile per item, name first, stats under it. Categorised so it can be browsed.
  function gallery(rows, filterText, cat) {
    const q = String(filterText || "").trim().toLowerCase();
    const pool = (rows || []).filter(r => (cat ? r.cat === cat : true))
      .filter(r => !q || String(r.name || "").toLowerCase().includes(q))
      .slice(0, 240);
    if (!pool.length) return `<p class="pso-empty">Nothing matches that search.</p>`;
    return `<div class="pso-gal">` + pool.map(r =>
      `<button type="button" class="pso-tile" data-pso-give="${ESC(r.code)}" `
      + `title="Give ${ESC(r.name)} — ${ESC(stats(r))}">`
      + `<b>${ESC(r.name)}</b><small>${ESC(stats(r) || r.cat || "")}</small></button>`).join("") + `</div>`;
  }

  function html(view = {}, state = {}) {
    const rows = view.items || [];
    const cats = [...new Set(rows.map(r => r.cat).filter(Boolean))].sort();
    const locked = !!(state.busy || state.pending);
    const dis = locked ? " disabled" : "";
    const room = view.room;
    const enemies = Number(view.enemies || 0);
    const selected = state.cat || "Weapons";
    const current = view.equipped;
    return `<h3>Live controls · PSO</h3>`
      + `<p class="bl-target">${ESC(view.title || "Phantasy Star Online")}`
      + (room ? ` · room ${ESC(room)}` : "") + ` · ${enemies} enem${enemies === 1 ? "y" : "ies"}</p>`
      + `<p class="${state.ok && state.message ? "bl-ok" : "bl-msg"}" role="status">${ESC(state.message || (locked ? "Working…" : ""))}</p>`
      + `<button type="button" data-pso-refresh${dis}>Refresh</button>`
      + `<h4>Weapon in hand</h4>`
      + (current ? `<p class="bl-target">Now: <b>${ESC(current.name || current.code)}</b> · ${ESC(stats(current))}</p>` : "")
      + `<select data-pso-equip${dis} aria-label="Equip a weapon" title="Every weapon with its real stats">`
      + weaponOptions(rows, current && current.code) + `</select>`
      + `<p class="bl-note">Stats are the item's own: ATP range, ATA, and the grind ceiling the game allows (per weapon — not always +99).</p>`
      + `<h4>Emulator</h4>`
      + `<p class="pso-emu">`
      + `<button type="button" data-pso-emu="pause"${dis}>Pause</button> `
      + `<button type="button" data-pso-emu="resume"${dis}>Resume</button> `
      + `<button type="button" data-pso-emu="reset"${dis}>Reset</button></p>`
      + `<p class="pso-emu">`
      + `<button type="button" data-pso-emu="fast_forward"${dis}>Fast-forward on</button> `
      + `<button type="button" data-pso-emu="normal_speed"${dis}>Normal speed</button> `
      + `<button type="button" data-pso-emu="menu"${dis}>Emulator menu</button></p>`
      + `<p class="bl-note">These are the emulator's own controls, mirrored here so the top bar can stay clear.</p>`
      + `<h4>Paralyze the room</h4>`
      + `<p><button type="button" data-pso-paralyze${dis || (enemies ? "" : " disabled")}>Freeze ${enemies} enem${enemies === 1 ? "y" : "ies"} for training</button></p>`
      + `<p class="bl-note">${enemies ? "Holds each enemy at its own position so it cannot travel, and reports whether it actually froze." : "No enemies here — walk into a room with enemies first."}</p>`
      + `<h4>Drops</h4>`
      + `<p><button type="button" data-pso-drops="floor"${dis}>Floor rares</button> `
      + `<button type="button" data-pso-drops="enemy"${dis}>Enemy drops</button></p>`
      + `<h4>Give an item</h4>`
      + `<input type="search" data-pso-search value="${ESC(state.q || "")}" placeholder="Search ${rows.length} items by name…"${dis}>`
      + `<select data-pso-cat${dis}>` + cats.map(c =>
        `<option value="${ESC(c)}"${c === selected ? " selected" : ""}>${ESC(c)}</option>`).join("") + `</select>`
      + gallery(rows, state.q, selected)
      + `<p class="bl-note">Click a tile to give that item. Weapons arrive ground to their own maximum.</p>`;
  }

  const CSS = `#bot-logic-panel .pso-gal{display:grid;grid-template-columns:1fr 1fr;gap:4px;max-height:38vh;overflow:auto;margin:4px 0}
#bot-logic-panel .pso-tile{display:flex;flex-direction:column;gap:1px;text-align:left;padding:4px 5px;background:#18181d;
  border:1px solid #444;border-radius:4px;color:#eee;cursor:pointer;font:11px system-ui;line-height:1.25}
#bot-logic-panel .pso-tile:hover{border-color:#ffd166;background:#20202a}
#bot-logic-panel .pso-tile b{font-weight:600;color:#fff}
#bot-logic-panel .pso-tile small{color:#9ab}
#bot-logic-panel .pso-empty{color:#aaa}
#bot-logic-panel .pso-emu{margin:2px 0 4px}
#bot-logic-panel .pso-emu button{min-width:0}
#bot-logic-panel input[type=search]{width:100%;box-sizing:border-box;background:#18181d;color:#fff;
  border:1px solid #666;border-radius:3px;padding:2px 4px;margin:0 0 4px}`;

  const api = { html, CSS, weaponOptions, gallery, stats, byPower };
  root.GBoxPsoControls = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
