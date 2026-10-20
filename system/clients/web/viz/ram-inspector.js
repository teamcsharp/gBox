// RAM inspector (operator 2026-10-20: "some sort of RAM inspector that lets us see in real time what's happening in the
// game and to identify the hex codes associated with QTE events and door opening events and map navigation ... Vision
// analysis to me should be the last level that we have to fall back to"). A chip button in the running session's
// header, after the pick whip, opens a floating panel over the session (drag it by its title; it remembers where):
//   Live    the game's RAM map (profiles/gamedata/<id>-ram.json) read now, by group; a value that changes flashes;
//           click an address to open it in Hex
//   Events  the state changes the server logged while watching (enum / flags fields: a prompt, a room, the pad),
//           with the frame of that moment when one was kept
//   Hex     bytes at an address (or at the end of a pointer chain "base,off,off"), live; click a word to follow it
//   Search  Cheat Engine style search of main RAM plus labels: "Event on" / "Event off" while the thing happens or
//           not, or a labeler (the screen-prompt watcher, a RAM-map field) doing it; candidates show their values per
//           label (on 3 · 5 / off 0: 3 = TAKE, 5 = JUMP OVER) and "Add to map" files one under the game's map
// Server: gbox/ram_inspector.py (GET /api/sessions/{sid}/ram/live, /hex, /search...). Read-only: nothing here
// writes game memory or presses a button. The desktop app embeds this shell, so the panel is there too.
//   GBoxRamInspector.button(sid)               the header button
//   GBoxRamInspector.mount(head, {sid, api, url})  wires it; reopens the panel when it was open for this session
//   GBoxRamInspector.detach()                  the session view went away: the panel goes (and stops polling)
//   GBoxRamInspector.create({sid, api, render})    the panel's logic without a DOM (tests)
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const KEY = "gbox_ram_inspector";
  const TYPES = ["u8", "u16", "u32", "s8", "s16", "s32", "f32"];
  const OPS = [["changed", "changed"], ["unchanged", "unchanged"], ["increased", "increased"], ["decreased", "decreased"],
    ["equals", "= value"], ["not_equals", "≠ value"], ["range", "in range"]];
  const TABS = ["Live", "Events", "Hex", "Search"];
  const LIVE_MS = 250, BACKGROUND_MS = 2000, HEX_MS = 500, SEARCH_MS = 1500;
  const hex8 = n => "0x" + (Number(n) >>> 0).toString(16).toUpperCase().padStart(8, "0");
  const hex2 = n => n.toString(16).toUpperCase().padStart(2, "0");

  function num(s) {
    const t = String(s ?? "").trim().replace(/_/g, "");
    if (!t) return NaN;
    return /^-?0x[0-9a-f]+$/i.test(t) ? (t.startsWith("-") ? -parseInt(t.slice(1), 16) : parseInt(t, 16))
      : /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : NaN;
  }

  function bytes(n) {
    if (n == null) return "";
    const one = x => String(Math.round(x * 10) / 10);
    if (n >= 1 << 20) return `${one(n / (1 << 20))} MiB`;
    if (n >= 1024) return `${one(n / 1024)} KiB`;
    return `${n} B`;
  }

  function clock(t) {
    const d = new Date(t * 1000);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:` +
      `${String(d.getSeconds()).padStart(2, "0")}.${Math.floor(d.getMilliseconds() / 100)}`;
  }

  // ---- what the panel shows (pure: the tests drive these) ----
  // live rows grouped as the map orders them; changed = its display differs from the previous poll's
  function liveModel(out, prev) {
    const groups = new Map(), shown = {};
    for (const g of Object.keys((out && out.groups) || {})) groups.set(g, { name: g, desc: out.groups[g], rows: [] });
    for (const r of (out && out.rows) || []) {
      const g = r.group || "other";
      if (!groups.has(g)) groups.set(g, { name: g, desc: "", rows: [] });
      const display = r.rows ? JSON.stringify(r.rows.map(x => [x.index, ...Object.values(x)])) : r.display;
      shown[r.name] = display;
      groups.get(g).rows.push({ ...r, short: r.name.startsWith(g + ".") ? r.name.slice(g.length + 1) : r.name,
        changed: !!prev && prev[r.name] !== undefined && prev[r.name] !== display });
    }
    const reader = (out && out.reader) || {};
    const foot = [out && out.map ? `${out.title || out.map}` : "", reader.kind ? `${reader.kind} read` : "",
      out && out.hz ? `${out.hz} Hz` : "", out && out.reads != null ? `${out.reads} reads · ${bytes(out.bytes)}` : "",
      out && out.age_s != null ? `${Math.round(out.age_s * 1000)} ms old` : ""].filter(Boolean).join(" · ");
    return { groups: [...groups.values()].filter(g => g.rows.length), shown, foot,
      error: (out && (out.error || out.map_error)) || "" };
  }

  function cell(v, fmt) {
    if (v == null) return "–";
    if (Array.isArray(v)) return v.map(x => cell(x, fmt)).join(", ");
    if (typeof v === "number" && fmt === "hex" && Number.isInteger(v)) return "0x" + (v >>> 0).toString(16).toUpperCase();
    if (typeof v === "number" && fmt === "deg") return `${Math.round(v * 1800 / Math.PI) / 10}°`;
    if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
    return String(v);
  }

  function liveHTML(m) {
    if (!m.groups.length) return `<p class="ri-e">${ESC(m.error || "Reading…")}</p>`;
    const row = r => {
      const addr = r.address ? `<a href="#" class="ri-addr" data-addr="${ESC(r.address)}" title="Open in Hex">${ESC(r.address)}</a>` : "";
      if (r.rows) {
        const cols = Object.keys(r.sub || {});
        const table = r.rows.length ? `<table class="ri-t"><tr><th>#</th>${cols.map(c => `<th>${ESC(c)}</th>`).join("")}</tr>` +
          r.rows.slice(0, 40).map(x => `<tr><td><a href="#" class="ri-addr" data-addr="${ESC(x.address)}">${x.index}</a></td>` +
            cols.map(c => `<td>${ESC(cell(x[c], (r.sub[c] || {}).format))}</td>`).join("") + "</tr>").join("") + "</table>" : "";
        return `<div class="ri-row${r.changed ? " chg" : ""}"><span class="ri-n">${ESC(r.short)}</span><b>${ESC(r.display)}</b>${addr}</div>${table}`;
      }
      return `<div class="ri-row${r.changed ? " chg" : ""}${r.error ? " err" : ""}${r.suspect ? " sus" : ""}" title="${ESC([r.name, r.type, r.error].filter(Boolean).join(" · "))}">` +
        `<span class="ri-n">${ESC(r.short)}</span><b>${ESC(r.error ? "?" : r.display)}</b>${addr}</div>`;
    };
    return m.groups.map(g => `<section><h5>${ESC(g.name)}${g.desc ? ` <span>${ESC(g.desc)}</span>` : ""}</h5>${g.rows.map(row).join("")}</section>`).join("") +
      (m.error ? `<p class="ri-e">${ESC(m.error)}</p>` : "");
  }

  function eventText(e) {
    const side = (v, l) => l != null ? l : cell(v);
    return `${e.field}: ${side(e.old, e.old_label)} → ${side(e.new, e.new_label)}`;
  }

  function eventsHTML(events, frameUrl) {
    if (!events.length) return '<p class="ri-e">No state changes yet. Events are the map\'s enum and flag fields changing while the panel watches.</p>';
    return events.slice().reverse().map(e => `<div class="ri-ev"><span>${ESC(clock(e.t))}</span><b>${ESC(eventText(e))}</b>` +
      (e.frame && frameUrl ? `<a href="${ESC(frameUrl(e.frame))}" target="_blank" rel="noopener" title="The frame at that moment">frame</a>` : "") + "</div>").join("");
  }

  // 16 bytes a row; chg = the byte differs from the previous read of the same address
  function hexRows(hex, address, prevHex) {
    const b = (hex.match(/../g) || []).map(h => parseInt(h, 16)), p = (prevHex || "").match(/../g) || [];
    const rows = [];
    for (let o = 0; o < b.length; o += 16) {
      const slice = b.slice(o, o + 16);
      rows.push({ addr: address + o, bytes: slice.map((v, i) => ({ v, o: o + i, chg: p.length > o + i && parseInt(p[o + i], 16) !== v })),
        ascii: slice.map(v => v >= 32 && v < 127 ? String.fromCharCode(v) : ".").join("") });
    }
    return rows;
  }

  function hexHTML(rows) {
    return rows.map(r => `<div class="ri-hr"><span class="ri-ha">${hex8(r.addr).slice(2)}</span> ` +
      r.bytes.map(x => `<span class="ri-hb${x.chg ? " chg" : ""}" data-o="${x.o}">${hex2(x.v)}</span>`).join("") +
      ` <span class="ri-hs">${ESC(r.ascii)}</span></div>`).join("");
  }

  function word(hex, o, big = true) {           // the 4-byte word a click lands in (aligned), as the game reads it
    const at = o - (o % 4), b = (hex.match(/../g) || []).slice(at, at + 4).map(h => parseInt(h, 16));
    if (b.length < 4) return null;
    const v = big ? (b[0] * 2 ** 24 + (b[1] << 16) + (b[2] << 8) + b[3]) : (b[3] * 2 ** 24 + (b[2] << 16) + (b[1] << 8) + b[0]);
    return { at, value: v >>> 0 };
  }

  function valuesText(list) {
    return (list || []).map(x => `${x.value}${x.n > 1 ? ` ×${x.n}` : ""}`).join(" · ") || "–";
  }

  // "Add to map": an enum table to fill in, from the values each label saw ("3 = ", "5 = ", "0 = " for on 3 5 / off 0)
  function enumDraft(c) {
    const seen = [];
    for (const lab of ["on", "off"]) for (const x of (c && c[lab]) || []) if (!seen.includes(x.value)) seen.push(x.value);
    return seen.map(v => `${v} = `).join("\n");
  }

  function parseEnum(text) {
    const out = {};
    for (const line of String(text || "").split(/\n/)) {
      const m = line.match(/^\s*(-?(?:0x[0-9a-f]+|\d+))\s*[=:]\s*(.*\S)\s*$/i);
      if (m) out[String(num(m[1]))] = m[2];
    }
    return out;
  }

  function searchLine(st) {
    if (!st || !st.active) return "No search running.";
    const s = st.samples || {};
    return [`${st.type} · ${hex8(st.base)} + ${bytes(st.size)}`,
      `${(st.candidates || 0).toLocaleString("en-US")} candidate${st.candidates === 1 ? "" : "s"} (${st.mode})`,
      `on ${s.on || 0} · off ${s.off || 0} · plain ${s.plain || 0}`, st.tolerance ? `${st.tolerance} mislabel${st.tolerance === 1 ? "" : "s"} ok` : "",
      bytes(st.memory)].filter(Boolean).join(" · ");
  }

  function autoLine(a) {
    if (!a) return "";
    const what = a.source === "field" ? `field ${a.field || ""}` : a.source === "screen_prompt" ? `screen prompt${a.button ? " " + a.button.toUpperCase() : ""}` : a.source;
    return `Auto: ${what} · now ${a.label || "?"} · sampled on ${a.samples?.on || 0} / off ${a.samples?.off || 0}` +
      (a.discarded ? ` · ${a.discarded} not confirmed` : "") + (a.note ? ` · ${a.note}` : "") + (a.error ? ` · ${a.error}` : "") +
      (a.running ? "" : " · stopped");
  }

  function candidatesHTML(st, limit = 60) {
    const list = (st && st.candidates_list) || [];
    if (!st || !st.active) return "";
    if (!list.length) return `<p class="ri-e">${st.candidates ? "Too many candidates to list: label more samples or filter." : "No candidates left."}</p>`;
    const labeled = list.some(c => c.on || c.off), loose = list.some(c => c.mislabeled != null);
    return `<table class="ri-t"><tr><th>address</th><th>now</th>${labeled ? "<th>on</th><th>off</th>" : ""}` +
      `${loose ? '<th title="labeled samples on the wrong side">±</th>' : ""}<th></th></tr>` +
      list.slice(0, limit).map((c, i) => `<tr><td><a href="#" class="ri-addr" data-addr="${ESC(c.address_hex)}">${ESC(c.address_hex)}</a></td>` +
        `<td>${ESC(cell(c.value))}</td>${labeled ? `<td>${ESC(valuesText(c.on))}</td><td>${ESC(valuesText(c.off))}</td>` : ""}` +
        `${loose ? `<td>${ESC(c.mislabeled ?? "")}</td>` : ""}` +
        `<td><button class="ri-b ri-add" data-i="${i}" title="Name this address and add it to the game's RAM map">Add to map</button></td></tr>`).join("") + "</table>";
  }

  // ---- the panel's logic (no DOM) ----
  function create({ sid, api, render = () => {}, onError = () => {} }) {
    const S = { sid, tab: "Live", live: null, model: null, shown: null, events: [], seq: 0, hex: { address: null, length: 256,
      pointer: "", data: null, prev: null, chain: [], big: true, error: "" }, search: null, error: "", busy: false };
    const base = `/api/sessions/${encodeURIComponent(sid)}/ram`;
    const fail = e => { S.error = String(e && e.message || e).slice(0, 300); onError(S.error); render(S, "error"); return null; };

    async function refreshLive() {
      try {
        const out = await api(`${base}/live?since=${S.seq}`);
        S.model = liveModel(out, S.shown);
        S.shown = S.model.shown;
        S.live = out;
        if ((out.seq || 0) < S.seq) { S.events = []; S.seq = 0; }        // the server started over (a restart)
        const fresh = (out.events || []).filter(e => e.seq > S.seq);
        if (fresh.length) S.events = S.events.concat(fresh).slice(-300);
        S.seq = Math.max(S.seq, out.seq || 0);
        S.error = "";
        render(S, "live");
        return out;
      } catch (e) { return fail(e); }
    }

    async function readHex(opts = {}) {
      Object.assign(S.hex, opts);
      const h = S.hex;
      const q = h.pointer ? `pointer=${encodeURIComponent(h.pointer)}` : `address=${encodeURIComponent(hex8(h.address ?? 0x80000000))}`;
      try {
        const out = await api(`${base}/hex?${q}&length=${h.length}`);
        h.prev = h.data && h.at === out.address ? h.data : null;
        h.data = out.hex; h.at = out.address; h.chain = out.chain || []; h.big = out.big_endian !== false; h.error = "";
        if (!h.pointer) h.address = out.address;
        render(S, "hex");
        return out;
      } catch (e) { h.error = String(e && e.message || e).slice(0, 300); render(S, "hex"); return null; }
    }

    function follow(offset) {                   // a clicked word as a pointer: open where it points
      const w = word(S.hex.data || "", offset, S.hex.big);
      if (!w) return null;
      return readHex({ address: w.value, pointer: "" });
    }

    async function searchCall(path, body, method) {
      if (S.busy) return null;
      S.busy = true; render(S, "search");
      try { S.search = await api(`${base}/search${path}`, body, method); S.error = ""; return S.search; }
      catch (e) { return fail(e); }
      finally { S.busy = false; render(S, "search"); }
    }

    const start = (type, b, size, tolerance) => searchCall("", { type, ...(b != null && !isNaN(b) ? { base: b } : {}),
      ...(size ? { size } : {}), ...(tolerance ? { tolerance } : {}) });
    const sample = label => searchCall("/sample", label ? { label } : {});
    const filter = (op, value, lo, hi) => searchCall("/sample", { op, ...(value !== "" && value != null ? { value } : {}),
      ...(lo !== "" && lo != null ? { lo } : {}), ...(hi !== "" && hi != null ? { hi } : {}) });
    async function auto(opts) {
      try { await api(`${base}/search/auto`, opts); return refreshSearch(); } catch (e) { return fail(e); }
    }
    async function refreshSearch() {
      try { S.search = await api(`${base}/search?limit=60`); render(S, "search"); return S.search; } catch (e) { return fail(e); }
    }
    async function end() {
      try { await api(`${base}/search`, undefined, "DELETE"); S.search = { active: false }; render(S, "search"); } catch (e) { fail(e); }
    }
    async function promote(c, form) {
      const body = { name: String(form.name || "").trim(), type: form.type || (S.search && S.search.type) || "u8",
        address: c.address, description: form.description || "", group: form.group || "", enum: parseEnum(form.enum) };
      if (!/^[a-z0-9_]+(\.[a-z0-9_]+)*$/.test(body.name)) return fail(new Error("Name it like group.name (lowercase: prompt.action)"));
      try { const out = await api(`${base}/promote`, body); S.promoted = out; render(S, "promoted"); return out; } catch (e) { return fail(e); }
    }

    return { S, refreshLive, readHex, follow, start, sample, filter, auto, refreshSearch, end, promote };
  }

  // ---- the DOM ----
  const CSS = `#ram-inspector{position:fixed;z-index:45;width:min(470px,calc(100vw - 24px));max-height:calc(100vh - 120px);display:flex;
    flex-direction:column;background:var(--card,#1f1f25);color:var(--fg,#e8e8ee);border:1px solid var(--line,#2c2c34);border-radius:10px;
    box-shadow:0 10px 30px #0009;font:12px/1.4 system-ui,sans-serif}
    #ram-inspector .ri-h{display:flex;gap:6px;align-items:center;padding:6px 8px;border-bottom:1px solid var(--line,#2c2c34);cursor:move;user-select:none}
    #ram-inspector .ri-h b{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    #ram-inspector .ri-tabs{display:flex;gap:2px;padding:4px 8px 0}
    #ram-inspector .ri-tabs button{background:none;border:0;border-bottom:2px solid transparent;color:var(--mut,#9a9aa6);padding:4px 8px;cursor:pointer;font:inherit}
    #ram-inspector .ri-tabs button.on{color:var(--fg,#e8e8ee);border-bottom-color:var(--acc,#7c96ff)}
    #ram-inspector .ri-body{overflow:auto;padding:6px 10px 10px;flex:1;min-height:120px}
    #ram-inspector .ri-pane[hidden]{display:none}
    #ram-inspector h5{margin:8px 0 2px;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--acc,#7c96ff)}
    #ram-inspector h5 span{text-transform:none;letter-spacing:0;color:var(--mut,#9a9aa6);font-weight:400}
    #ram-inspector .ri-row{display:grid;grid-template-columns:minmax(80px,32%) 1fr auto;gap:6px;padding:1px 4px;border-radius:4px;align-items:baseline}
    #ram-inspector .ri-row b{font-weight:500;font-family:ui-monospace,Consolas,monospace;overflow-wrap:anywhere}
    #ram-inspector .ri-row.err b{color:var(--bad,#ff6b6b)} #ram-inspector .ri-row.sus b{color:#f5c542}
    #ram-inspector .ri-n{color:var(--mut,#9a9aa6);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    #ram-inspector .chg{animation:ri-flash 1.2s ease-out}
    @keyframes ri-flash{from{background:#f5c54266}to{background:transparent}}
    #ram-inspector a{color:var(--acc,#7c96ff);text-decoration:none;font-family:ui-monospace,Consolas,monospace;font-size:11px}
    #ram-inspector .ri-t{width:100%;border-collapse:collapse;margin:2px 0 6px;font-family:ui-monospace,Consolas,monospace;font-size:11px}
    #ram-inspector .ri-t td,#ram-inspector .ri-t th{padding:1px 4px;border-bottom:1px solid var(--line,#2c2c34);text-align:left}
    #ram-inspector .ri-e{color:var(--mut,#9a9aa6);margin:6px 0}
    #ram-inspector .ri-f{color:var(--mut,#9a9aa6);font-size:11px;padding:4px 10px;border-top:1px solid var(--line,#2c2c34)}
    #ram-inspector .ri-ev{display:grid;grid-template-columns:auto 1fr auto;gap:8px;padding:2px 0;border-bottom:1px solid var(--line,#2c2c34)}
    #ram-inspector .ri-ev span{color:var(--mut,#9a9aa6);font-family:ui-monospace,Consolas,monospace}
    #ram-inspector .ri-ev b{font-weight:500}
    #ram-inspector .ri-bar{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:4px 0}
    #ram-inspector input,#ram-inspector select,#ram-inspector textarea{font:inherit;padding:3px 6px;border:1px solid var(--line,#2c2c34);
      background:var(--bg,#16161a);color:var(--fg,#e8e8ee);border-radius:4px}
    #ram-inspector .ri-b{font:inherit;padding:3px 8px;border:1px solid var(--line,#2c2c34);background:var(--bg,#16161a);color:var(--fg,#e8e8ee);border-radius:4px;cursor:pointer}
    #ram-inspector .ri-b.on{background:#1a7f37;border-color:#1a7f37;color:#fff} #ram-inspector .ri-b.off{background:#5a2424;border-color:#7a3030;color:#fff}
    #ram-inspector .ri-b:disabled{opacity:.5;cursor:default} #ram-inspector .ri-add{white-space:nowrap;padding:1px 6px}
    #ram-inspector .ri-hex{font-family:ui-monospace,Consolas,monospace;font-size:11px;white-space:pre;overflow-x:auto}
    #ram-inspector .ri-hb{padding:0 2px;cursor:pointer;border-radius:2px} #ram-inspector .ri-hb:hover{background:var(--line,#2c2c34)}
    #ram-inspector .ri-ha{color:var(--mut,#9a9aa6)} #ram-inspector .ri-hs{color:var(--mut,#9a9aa6)}
    #ram-inspector .ri-form{border:1px solid var(--line,#2c2c34);border-radius:6px;padding:6px;margin:4px 0;display:grid;gap:4px}
    #ram-inspector .ri-form textarea{min-height:56px}
    #ram-inspector .ri-st{color:var(--mut,#9a9aa6);margin:2px 0}
    #ram-inspector.ri-c .ri-tabs,#ram-inspector.ri-c .ri-body,#ram-inspector.ri-c .ri-f{display:none}
    #session-head #ramibtn[aria-pressed=true]{border-color:var(--acc,#7c96ff);color:var(--acc,#7c96ff)}`;

  const CHIP = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">' +
    '<rect x="6" y="6" width="12" height="12" rx="1.5"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/><path d="M10 10h4v4h-4z"/></svg>';

  function button(sid) {
    return `<button class="act" id="ramibtn" data-sid="${ESC(sid)}" style="padding:5px 7px;line-height:0" aria-pressed="false" ` +
      `aria-label="RAM inspector" title="RAM inspector: the game's memory by name, live; its state changes; hex; search with labels (read-only)">${CHIP}</button>`;
  }

  function prefs() { try { return JSON.parse(root.localStorage.getItem(KEY) || "{}") || {}; } catch { return {}; } }
  function savePrefs(p) { try { root.localStorage.setItem(KEY, JSON.stringify({ ...prefs(), ...p })); } catch {} }

  let panel = null;                             // {el, sid, ctl, timer, io}

  function style(doc) {
    if (doc && doc.head && !doc.getElementById("ram-inspector-css")) {
      const st = doc.createElement("style"); st.id = "ram-inspector-css"; st.textContent = CSS; doc.head.append(st);
    }
  }

  function skeleton(sid) {
    return `<div class="ri-h"><b>RAM · <span class="ri-title">reading…</span></b>` +
      `<button class="ri-b ri-min" title="Fold">▾</button><button class="ri-b ri-x" title="Close">✕</button></div>` +
      `<div class="ri-tabs">${TABS.map(t => `<button data-tab="${t}">${t}${t === "Events" ? ' <span class="ri-evn"></span>' : ""}</button>`).join("")}</div>` +
      `<div class="ri-body">` +
      `<div class="ri-pane" data-pane="Live"><div class="ri-live"><p class="ri-e">Reading…</p></div></div>` +
      `<div class="ri-pane" data-pane="Events"><div class="ri-bar"><button class="ri-b ri-clear">Clear</button></div><div class="ri-events"></div></div>` +
      `<div class="ri-pane" data-pane="Hex"><div class="ri-bar">0x<input class="ri-hexaddr" size="9" placeholder="80000000" data-nomic>` +
      `<select class="ri-hexlen">${[64, 128, 256, 512, 1024].map(n => `<option${n === 256 ? " selected" : ""}>${n}</option>`).join("")}</select>` +
      `<input class="ri-ptr" size="18" placeholder="pointer: base,off,off" data-nomic><button class="ri-b ri-go">Go</button>` +
      `<label><input type="checkbox" class="ri-hexlive" checked> live</label></div>` +
      `<div class="ri-st ri-chain"></div><div class="ri-hex"></div><div class="ri-st">Click a byte: follow the 4-byte word there as a pointer.</div></div>` +
      `<div class="ri-pane" data-pane="Search"><div class="ri-sstart"></div><div class="ri-sstatus"></div><div class="ri-cands"></div></div>` +
      `</div><div class="ri-f"></div>`;
  }

  function startHTML(st, live) {
    if (st && st.active) {
      const fields = ((live && live.rows) || []).filter(r => !r.rows).map(r => r.name);
      return `<div class="ri-bar"><button class="ri-b on ri-lab" data-l="on" title="Sample now: the event is happening (the prompt is up, the door is open)">Event on</button>` +
        `<button class="ri-b off ri-lab" data-l="off" title="Sample now: the event is not happening">Event off</button>` +
        `<button class="ri-b ri-lab" data-l="" title="Sample without a label (for the filters)">Sample</button>` +
        `<button class="ri-b ri-end" title="End the search and free its memory">End search</button></div>` +
        `<div class="ri-bar"><select class="ri-op">${OPS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>` +
        `<input class="ri-v" size="7" placeholder="value" data-nomic><input class="ri-lo" size="6" placeholder="lo" hidden data-nomic>` +
        `<input class="ri-hi" size="6" placeholder="hi" hidden data-nomic>` +
        `<button class="ri-b ri-filter">Filter</button></div>` +
        `<div class="ri-bar">Auto-label: <select class="ri-src"><option value="off">off</option><option value="screen_prompt">screen prompt (vision)</option>` +
        `<option value="field">RAM-map field</option></select>` +
        `<select class="ri-btn" hidden><option value="">any button</option><option value="a">A</option><option value="b">B</option></select>` +
        `<select class="ri-fld" hidden>${fields.map(f => `<option>${ESC(f)}</option>`).join("")}</select>` +
        `<select class="ri-cop" hidden><option value="ne">≠</option><option value="eq">=</option><option value="gt">&gt;</option><option value="lt">&lt;</option></select>` +
        `<input class="ri-cv" size="5" value="0" hidden data-nomic><input class="ri-cm" size="7" placeholder="mask" hidden data-nomic>` +
        `<label title="Labeled samples a candidate may have on the wrong side: a labeler from the picture is a little late at the edges">` +
        `<input class="ri-atol" size="2" value="2" data-nomic> mislabels ok</label><button class="ri-b ri-auto">Start</button></div>`;
    }
    return `<div class="ri-bar"><select class="ri-type">${TYPES.map(t => `<option>${t}</option>`).join("")}</select>` +
      `0x<input class="ri-base" size="9" placeholder="main RAM" data-nomic><input class="ri-size" size="9" placeholder="size (hex)" data-nomic>` +
      `<label title="Labeled samples a candidate may have on the wrong side (0: exact)"><input class="ri-tol" size="2" value="0" data-nomic> mislabels ok</label>` +
      `<button class="ri-b ri-start">Start search</button></div>` +
      `<p class="ri-e">A snapshot of the game's main RAM (GameCube: MEM1, 24 MiB). Then label samples while the event happens and while it ` +
      `does not (or let a labeler do it), or filter like Cheat Engine. Values that never overlap between on and off are the event's.</p>`;
  }

  function open(sid, io) {
    const doc = root.document;
    if (!doc) return null;
    if (panel && panel.sid === sid) return panel;
    close(false);
    style(doc);
    const el = doc.createElement("aside");
    el.id = "ram-inspector"; el.innerHTML = skeleton(sid); doc.body.append(el);
    const p = prefs(), watch = doc.getElementById("watch-analytics");
    const right = watch ? Math.max(12, root.innerWidth - watch.getBoundingClientRect().left + 8) : 12;
    const x = Math.max(8, Math.min((p.x ?? (root.innerWidth - 470 - right)), root.innerWidth - 120));
    const head = doc.getElementById("session-head");     // first opened: just under the session's header
    const y = Math.max(56, Math.min((p.y ?? (head ? head.getBoundingClientRect().bottom + 8 : 110)), root.innerHeight - 60));
    el.style.left = x + "px"; el.style.top = y + "px";
    const $ = s => el.querySelector(s);
    let promoting = null;
    const render = (S, what) => {
      if (!panel || panel.el !== el) return;
      if (what === "live" || what === "error") {
        $(".ri-title").textContent = S.live ? `${S.live.title || S.live.map || "no RAM map yet"}` : "…";
        if (S.model) $(".ri-live").innerHTML = liveHTML(S.model);
        $(".ri-events").innerHTML = eventsHTML(S.events, fid => io.url(`/api/sessions/${encodeURIComponent(sid)}/ram/frames/${fid}.jpg`));
        $(".ri-evn").textContent = S.events.length ? `(${S.events.length})` : "";
        $(".ri-f").textContent = S.error ? `⚠ ${S.error}` : (S.model ? S.model.foot : "");
      }
      if (what === "hex") {
        const h = S.hex;
        $(".ri-hex").innerHTML = h.error ? `<p class="ri-e">${ESC(h.error)}</p>` : h.data ? hexHTML(hexRows(h.data, h.at, h.prev)) : "";
        $(".ri-chain").textContent = h.chain.length ? h.chain.map(c => `[${c.at}] = ${c.value} + ${c.offset}`).join(" → ") + ` → ${hex8(h.at)}` : "";
        if (doc.activeElement !== $(".ri-hexaddr") && h.at != null) $(".ri-hexaddr").value = hex8(h.at).slice(2);
      }
      if (what === "search" || what === "error" || what === "promoted") {
        const st = S.search;
        const key = `${!!(st && st.active)}:${((S.live && S.live.rows) || []).length}`;    // the field picker fills once live is in
        if ($(".ri-sstart").dataset.key !== key) {
          $(".ri-sstart").innerHTML = startHTML(st, S.live);
          $(".ri-sstart").dataset.key = key;
          const a = st && st.auto, src = $(".ri-src");
          if (a && a.running && src) {                 // the labeler that runs, as the picker shows it
            src.value = a.source;
            src.dispatchEvent(new Event("change", { bubbles: true }));
            if (a.button && $(".ri-btn")) $(".ri-btn").value = a.button;
            if (a.field && $(".ri-fld")) $(".ri-fld").value = a.field;
          }
        }
        $(".ri-sstatus").innerHTML = `<div class="ri-st">${ESC(searchLine(st))}${S.busy ? " · reading…" : ""}</div>` +
          (st && st.auto ? `<div class="ri-st">${ESC(autoLine(st.auto))}</div>` : "") +
          (S.promoted ? `<div class="ri-st">Added <b>${ESC(S.promoted.field && S.promoted.field.name)}</b> to ${ESC(S.promoted.map)} (${ESC(S.promoted.overlay)})</div>` : "") +
          (S.error && what === "error" ? `<div class="ri-st" style="color:var(--bad,#ff6b6b)">${ESC(S.error)}</div>` : "");
        if (!promoting) $(".ri-cands").innerHTML = candidatesHTML(st);
        el.querySelectorAll(".ri-lab,.ri-filter,.ri-end").forEach(b => { b.disabled = !!S.busy; });
      }
    };
    const ctl = create({ sid, api: io.api, render });
    panel = { el, sid, ctl, io, timer: null, tab: TABS.includes(p.tab) ? p.tab : "Live" };
    const show = tab => {
      panel.tab = tab; savePrefs({ tab });
      el.querySelectorAll(".ri-tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
      el.querySelectorAll(".ri-pane").forEach(d => { d.hidden = d.dataset.pane !== tab; });
      if (tab === "Hex" && !ctl.S.hex.data) ctl.readHex({ address: ctl.S.hex.address ?? 0x80000000 });
      if (tab === "Search") ctl.refreshSearch();
    };
    el.querySelector(".ri-tabs").onclick = e => { const t = e.target.closest("button"); if (t) show(t.dataset.tab); };
    $(".ri-x").onclick = () => close(true);
    $(".ri-min").onclick = () => { el.classList.toggle("ri-c"); $(".ri-min").textContent = el.classList.contains("ri-c") ? "▸" : "▾"; };
    $(".ri-clear").onclick = () => { ctl.S.events = []; render(ctl.S, "live"); };
    // drag by the title bar
    $(".ri-h").onpointerdown = e => {
      if (e.target.closest("button")) return;
      const r = el.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      const move = ev => { el.style.left = Math.max(0, ev.clientX - dx) + "px"; el.style.top = Math.max(40, ev.clientY - dy) + "px"; };
      const up = () => { doc.removeEventListener("pointermove", move); doc.removeEventListener("pointerup", up);
        savePrefs({ x: parseInt(el.style.left, 10), y: parseInt(el.style.top, 10) }); };
      doc.addEventListener("pointermove", move); doc.addEventListener("pointerup", up);
    };
    const openHex = a => { show("Hex"); $(".ri-ptr").value = ""; ctl.readHex({ address: num(a), pointer: "" }); };
    el.addEventListener("click", e => {
      const a = e.target.closest(".ri-addr");
      if (a) { e.preventDefault(); openHex(a.dataset.addr); return; }
      const hb = e.target.closest(".ri-hb");
      if (hb) { ctl.follow(+hb.dataset.o); return; }
      const lab = e.target.closest(".ri-lab");
      if (lab) { ctl.sample(lab.dataset.l || null); return; }
      if (e.target.closest(".ri-start")) {
        const rawb = $(".ri-base").value.trim().replace(/^0x/i, ""), raws = $(".ri-size").value.trim().replace(/^0x/i, "");
        const b = rawb ? num("0x" + rawb) : NaN, size = raws ? num("0x" + raws) : NaN, tol = num($(".ri-tol").value);
        ctl.start($(".ri-type").value, isNaN(b) ? null : b, isNaN(size) ? null : size, isNaN(tol) ? 0 : tol); return;
      }
      if (e.target.closest(".ri-end")) { promoting = null; ctl.end(); return; }
      if (e.target.closest(".ri-filter")) { ctl.filter($(".ri-op").value, $(".ri-v").value, $(".ri-lo").value, $(".ri-hi").value); return; }
      if (e.target.closest(".ri-auto")) {
        const src = $(".ri-src").value, opts = { source: src }, tol = num($(".ri-atol").value);
        if (src !== "off" && !isNaN(tol)) opts.tolerance = tol;
        if (src === "screen_prompt" && $(".ri-btn").value) opts.button = $(".ri-btn").value;
        if (src === "field") {
          opts.field = $(".ri-fld").value;
          const v = num($(".ri-cv").value), m = num($(".ri-cm").value);
          opts.cond = { [$(".ri-cop").value]: isNaN(v) ? 0 : v, ...(isNaN(m) ? {} : { mask: m }) };
        }
        ctl.auto(opts); return;
      }
      const add = e.target.closest(".ri-add");
      if (add) {
        const c = ((ctl.S.search && ctl.S.search.candidates_list) || [])[+add.dataset.i];
        if (!c) return;
        promoting = c;
        const row = add.closest("tr"), tr = doc.createElement("tr");
        tr.innerHTML = `<td colspan="5"><div class="ri-form"><input class="ri-pn" placeholder="name: group.name (prompt.action)">` +
          `<input class="ri-pd" placeholder="what it is"><input class="ri-pg" placeholder="group (optional)">` +
          `<select class="ri-pt">${TYPES.map(t => `<option${t === ctl.S.search.type ? " selected" : ""}>${t}</option>`).join("")}</select>` +
          `<textarea class="ri-pe" placeholder="value = label, one per line">${ESC(enumDraft(c))}</textarea>` +
          `<div class="ri-bar"><button class="ri-b ri-psave">Add ${ESC(c.address_hex)}</button><button class="ri-b ri-pcancel">Cancel</button></div></div></td>`;
        row.after(tr);
        tr.querySelector(".ri-pn").focus();
        tr.querySelector(".ri-pcancel").onclick = () => { promoting = null; tr.remove(); };
        tr.querySelector(".ri-psave").onclick = async () => {
          const out = await ctl.promote(c, { name: tr.querySelector(".ri-pn").value, description: tr.querySelector(".ri-pd").value,
            group: tr.querySelector(".ri-pg").value, type: tr.querySelector(".ri-pt").value, enum: tr.querySelector(".ri-pe").value });
          if (out) { promoting = null; tr.remove(); render(ctl.S, "search"); }
        };
      }
    });
    el.addEventListener("change", e => {
      if (e.target.matches(".ri-op")) {
        const r = e.target.value === "range", v = ["equals", "not_equals"].includes(e.target.value);
        $(".ri-lo").hidden = $(".ri-hi").hidden = !r; $(".ri-v").hidden = !v;
      }
      if (e.target.matches(".ri-src")) {
        const f = e.target.value === "field";
        $(".ri-btn").hidden = e.target.value !== "screen_prompt";
        $(".ri-fld").hidden = $(".ri-cop").hidden = $(".ri-cv").hidden = $(".ri-cm").hidden = !f;
        if (e.target.value === "off") ctl.auto({ source: "off" });
      }
    });
    el.addEventListener("keydown", e => {
      e.stopPropagation();                       // typing here is never a page shortcut or game input
      if (e.key === "Enter" && e.target.matches(".ri-hexaddr,.ri-ptr,.ri-hexlen")) $(".ri-go").click();
    });
    for (const ev of ["keyup", "keypress"]) el.addEventListener(ev, e => e.stopPropagation());
    $(".ri-go").onclick = () => {
      const raw = $(".ri-hexaddr").value.trim().replace(/^0x/i, ""), a = raw ? num("0x" + raw) : NaN;
      ctl.readHex({ address: isNaN(a) ? 0x80000000 : a, length: +$(".ri-hexlen").value, pointer: $(".ri-ptr").value.trim() });
    };
    $(".ri-hexlen").onchange = () => ctl.readHex({ length: +$(".ri-hexlen").value });
    show(panel.tab);
    render(ctl.S, "search");
    savePrefs({ open: sid });
    const tick = async () => {
      if (!panel || panel.el !== el) return;
      const t = panel.tab;
      let wait = BACKGROUND_MS;
      if (t === "Live" || t === "Events") { await ctl.refreshLive(); wait = LIVE_MS; }
      else {
        if (t === "Hex" && $(".ri-hexlive").checked && ctl.S.hex.data) { await ctl.readHex(); wait = HEX_MS; }
        if (t === "Search" && ctl.S.search && ctl.S.search.auto && ctl.S.search.auto.running) { await ctl.refreshSearch(); wait = Math.min(wait, SEARCH_MS); }
        await ctl.refreshLive();                 // the event list (and the server's watcher) keep going
      }
      if (panel && panel.el === el) panel.timer = setTimeout(tick, wait);
    };
    tick();
    const btn = doc.getElementById("ramibtn");
    if (btn) btn.setAttribute("aria-pressed", "true");
    return panel;
  }

  function close(forget = true) {
    if (!panel) return;
    clearTimeout(panel.timer);
    panel.el.remove();
    panel = null;
    if (forget) savePrefs({ open: null });
    const btn = root.document && root.document.getElementById("ramibtn");
    if (btn) btn.setAttribute("aria-pressed", "false");
  }

  function mount(head, io) {
    style(head && head.ownerDocument);
    const btn = head && head.querySelector("#ramibtn");
    if (!btn) return null;
    btn.onclick = () => panel && panel.sid === io.sid ? close(true) : open(io.sid, io);
    if (prefs().open === io.sid) open(io.sid, io);             // it was open for this session: the header was redrawn
    else if (panel && panel.sid !== io.sid) close(false);
    btn.setAttribute("aria-pressed", String(!!panel && panel.sid === io.sid));
    return { close: () => close(true) };
  }

  function detach() { close(false); }

  const api = { button, mount, detach, open, close, create, liveModel, liveHTML, eventText, eventsHTML, hexRows, hexHTML,
    word, valuesText, enumDraft, parseEnum, searchLine, autoLine, candidatesHTML, num, KEY };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GBoxRamInspector = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
