/* Visual cast review only. The caller owns loading, model inspection and build submission. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.GBoxCastMapper = factory();
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  let sequence = 0;
  function roster(items, side) {
    const seen = new Set();
    return (Array.isArray(items) ? items : []).filter(item => item && (item.id || item.slug || item.slot))
      .map(item => ({ ...item, id: String(side === 'donor' ? item.slug || item.id : item.id || item.slug || item.slot),
        name: String(item.name || item.id || item.slug || item.slot),
        ...(side === 'target' ? { slot: typeof item.slot === 'string' && item.slot ? item.slot : null } :
          { slug: String(item.slug || item.id) }) }))
      .filter(item => { if (seen.has(item.id)) return false; seen.add(item.id); return true; });
  }
  function random(seed) {
    let h = 2166136261;
    for (const c of String(seed ?? '')) h = Math.imul(h ^ c.codePointAt(0), 16777619) >>> 0;
    return () => { h = (h + 0x6D2B79F5) >>> 0; let t = h; t = Math.imul(t ^ t >>> 15, t | 1);
      t ^= t + Math.imul(t ^ t >>> 7, t | 61); return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  }
  // Deterministic bags: no repeated donor until every selected donor has been dealt once.
  function deal(targets, donors, seed) {
    const pool = [...new Set((donors || []).filter(Boolean))], result = Object.create(null);
    if (!pool.length) return result;
    const rng = random(`${seed ?? ''}|${pool.join(',')}`); let bag = [];
    for (const id of targets || []) {
      if (!bag.length) {
        bag = pool.slice();
        for (let i = bag.length - 1; i > 0; i--) { const j = Math.floor(rng() * (i + 1)); [bag[i], bag[j]] = [bag[j], bag[i]]; }
      }
      result[id] = bag.shift();
    }
    return result;
  }
  function safeImage(value) {
    const text = String(value || '').trim();
    if (!text || /[\u0000-\u001f]/.test(text)) return '';
    if (/^(?:\/(?!\/)|https?:\/\/|blob:|data:image\/(?:png|jpeg|webp|gif);base64,)/i.test(text)) return text;
    return '';
  }
  const style = `
    .gbox-cast-mapper{color:#eef0f9;font:13px system-ui;min-width:0;--cm-line:#434d65;--cm-accent:#a5acff}
    .gbox-cast-mapper *{box-sizing:border-box}.gbox-cast-mapper button,.gbox-cast-mapper input{font:inherit;color:inherit}
    .gbox-cast-mapper button{cursor:pointer;border:1px solid var(--cm-line);border-radius:6px;background:#252b3a;padding:6px 9px}.gbox-cast-mapper button:disabled{opacity:.48;cursor:default}
    .gbox-cast-mapper :is(button,input):focus-visible,.gbox-cast-mapper [tabindex]:focus-visible{outline:2px solid #c3c7ff;outline-offset:2px}
    .gbox-cast-mapper input[type=search],.gbox-cast-mapper input[type=text]{background:#10151f;border:1px solid var(--cm-line);border-radius:6px;padding:7px;min-width:0}
    .gbox-cast-mapper .cm-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0}.gbox-cast-mapper .cm-toolbar label{display:flex;gap:5px;align-items:center}.gbox-cast-mapper .cm-toolbar input[type=text]{width:105px}
    .gbox-cast-mapper .cm-caption{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.gbox-cast-mapper .cm-caption strong{font-size:16px}.gbox-cast-mapper .cm-caption span,.gbox-cast-mapper .cm-hint{color:#b6c2d8}
    .gbox-cast-mapper .cm-board{position:relative;display:grid;grid-template-columns:minmax(0,1fr) 78px minmax(0,1fr);min-width:0}
    .gbox-cast-mapper .cm-panel{min-width:0;border:1px solid var(--cm-line);border-radius:9px;background:#131925e8;z-index:1;overflow:hidden}
    .gbox-cast-mapper .cm-panel[data-side=donor]{grid-column:3}.gbox-cast-mapper .cm-panel-header{padding:10px;border-bottom:1px solid var(--cm-line)}
    .gbox-cast-mapper .cm-panel h3{font-size:14px;margin:0 0 4px;overflow-wrap:anywhere}.gbox-cast-mapper .cm-panel-header small{display:block;color:#b6c2d8;margin:0 0 8px}
    .gbox-cast-mapper .cm-search{width:100%}.gbox-cast-mapper .cm-panel-meta{display:flex;align-items:center;justify-content:space-between;gap:5px;margin-top:6px;font-size:11px;color:#bec9df}
    .gbox-cast-mapper .cm-panel-meta button{font-size:11px;padding:3px 5px}.gbox-cast-mapper .cm-list{height:350px;overflow:auto;overscroll-behavior:contain;padding:7px;scrollbar-gutter:stable}
    .gbox-cast-mapper .cm-card{position:relative;border:1px solid #374158;border-radius:7px;background:#1c2433;margin-bottom:7px;min-width:0;transition:border-color .12s}
    .gbox-cast-mapper .cm-card[data-selected=true]{border-color:var(--cm-accent);box-shadow:0 0 0 1px var(--cm-accent)}.gbox-cast-mapper .cm-card[data-connected=true]{background:#202b41}
    .gbox-cast-mapper .cm-card[data-drop=true]{outline:2px solid #85d4b8;outline-offset:1px}.gbox-cast-mapper .cm-card[hidden]{display:none}
    .gbox-cast-mapper .cm-main{display:flex;align-items:center;width:100%;gap:9px;border:0;background:transparent;text-align:left;padding:8px;border-radius:6px}
    .gbox-cast-mapper .cm-thumb{display:flex;flex:0 0 58px;width:58px;height:65px;align-items:center;justify-content:center;flex-direction:column;border-radius:5px;background:#0e1420;color:#aebcd6;text-align:center;overflow:hidden}
    .gbox-cast-mapper .cm-thumb img{width:100%;height:100%;object-fit:contain}.gbox-cast-mapper .cm-fallback{display:flex;flex-direction:column;align-items:center;justify-content:center;width:100%;gap:2px}.gbox-cast-mapper .cm-fallback[hidden]{display:none}.gbox-cast-mapper .cm-initial{font-size:19px}.gbox-cast-mapper .cm-thumb small{display:block;font-size:9px}
    .gbox-cast-mapper .cm-copy{flex:1;min-width:0}.gbox-cast-mapper .cm-copy strong{display:block;overflow-wrap:anywhere;font-size:13px}.gbox-cast-mapper .cm-copy small{display:block;color:#b7c3d9;font-size:10.5px;margin-top:4px;overflow-wrap:anywhere}
    .gbox-cast-mapper .cm-tools{display:flex;align-items:center;gap:5px;flex-wrap:wrap;padding:0 8px 7px}.gbox-cast-mapper .cm-tools button{font-size:11px;padding:4px 6px}.gbox-cast-mapper .cm-tools label{display:flex;align-items:center;gap:3px;font-size:11px}
    .gbox-cast-mapper .cm-assignment{padding:0 8px 7px;font-size:11px;color:#d1d7ff;overflow-wrap:anywhere}.gbox-cast-mapper .cm-tools .cm-remove{margin-left:auto}
    .gbox-cast-mapper .cm-port{position:absolute;width:8px;height:8px;top:35px;border-radius:50%;background:#acb5ff;pointer-events:none}.gbox-cast-mapper [data-side=target] .cm-port{right:-5px}.gbox-cast-mapper [data-side=donor] .cm-port{left:-5px}
    .gbox-cast-mapper .cm-lines{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:hidden;z-index:2}.gbox-cast-mapper .cm-lines path{fill:none;stroke:#9eaaff;stroke-width:1.8;opacity:.8}.gbox-cast-mapper .cm-lines path[data-active=true]{stroke:#e4c690;stroke-width:2.7;opacity:1}
    .gbox-cast-mapper .cm-empty{color:#b8c4da;text-align:center;padding:35px 10px}.gbox-cast-mapper .cm-status{min-height:20px;margin:9px 0 0;color:#d1daf0;overflow-wrap:anywhere}
    .gbox-cast-mapper .cm-capability{padding:8px 10px;border:1px solid #605540;background:#30291b77;border-radius:6px;color:#e2d4b6;font-size:11px;margin-top:9px;white-space:pre-wrap;overflow-wrap:anywhere}
    .gbox-cast-mapper .cm-summary{margin-top:9px;color:#b9c6df;font-size:12px}.gbox-cast-mapper .cm-error{color:#ffbcbc}
    @media(max-width:720px){.gbox-cast-mapper .cm-board{grid-template-columns:minmax(0,1fr) 35px minmax(0,1fr)}.gbox-cast-mapper .cm-thumb{flex-basis:42px;width:42px;height:54px}.gbox-cast-mapper .cm-main{gap:6px;padding:6px}.gbox-cast-mapper .cm-list{padding:5px}.gbox-cast-mapper .cm-tools{padding:0 6px 6px;gap:4px}.gbox-cast-mapper .cm-panel-header{padding:8px}.gbox-cast-mapper .cm-copy strong{font-size:12px}}
    @media(prefers-reduced-motion:reduce){.gbox-cast-mapper .cm-card{transition:none}}
  `;
  // io: onChange(canonicalRows), inspect(card, 'target'|'donor'), img(previewURL).
  // Every snapshot includes unchanged targets; slot:null remains an engineering mapping,
  // never a fabricated writable native slot. This component makes no network requests.
  function mount(host, data, io = {}) {
    if (!host || !host.ownerDocument) throw new Error('Cast mapper needs a host element.');
    const doc = host.ownerDocument, win = doc.defaultView, uid = `cast-map-${++sequence}`;
    const targets = roster(data?.targets, 'target'), donors = roster(data?.donors, 'donor');
    const targetMap = new Map(targets.map(c => [c.id, c])), donorMap = new Map(donors.map(c => [c.slug, c]));
    const picks = new Map(targets.map(c => [c.id, ''])), locks = new Set(), pool = new Set(donors.map(c => c.slug));
    let selected = targets[0]?.id || '', disposed = false, frame = null, drag = null, inspectSequence = 0, changeSequence = 0;
    const node = doc.createElement('section'); node.className = 'gbox-cast-mapper';
    node.setAttribute('aria-label', 'Cast replacement chart');
    const photo = card => {
      let url = ''; try { url = safeImage(io.img ? io.img(card.preview_url || '') : card.preview_url); } catch { /* use name fallback */ }
      const initial = (card.name.match(/\b[\p{L}\p{N}]/gu) || ['?']).slice(0, 2).join('').toUpperCase();
      return `<span class="cm-thumb"><span class="cm-fallback"><span class="cm-initial">${esc(initial)}</span><small>No preview</small></span>${url ? `<img alt="${esc(card.name)} preview" loading="lazy" src="${esc(url)}">` : ''}</span>`;
    };
    const cardHTML = (card, side, index) => {
      const format = String(card.format || String(card.model || '').split('.').slice(1).pop() || '').toLowerCase();
      const model = !!(card.model_url && card.slug && (!format || ['glb', 'gltf'].includes(format)) && typeof io.inspect === 'function'), target = side === 'target';
      const availability = target ? (card.slot ? 'Native slot available' : 'Planning only · native slot needed') :
        (card.ready === false ? `Needs extraction/support${card.reason ? ` · ${card.reason}` : ''}` : 'Replacement character');
      return `<article class="cm-card" data-cm-card="${side}" data-key="${esc(target ? card.id : card.slug)}" data-index="${index}">
        <span class="cm-port" aria-hidden="true"></span><button type="button" class="cm-main" data-action="${target ? 'target' : 'donor'}" draggable="true" aria-pressed="false" aria-label="${esc(target ? 'Select original ' : 'Use replacement ')}${esc(card.name)}">${photo(card)}<span class="cm-copy"><strong>${esc(card.name)}</strong><small>${esc(availability)}</small></span></button>
        <div class="cm-tools"><button type="button" data-action="inspect" ${model ? '' : 'disabled'} aria-label="Inspect ${esc(card.name)} in 3D">Inspect 3D</button>
          ${target ? `<label><input type="checkbox" data-action="lock" aria-label="Lock mapping for ${esc(card.name)}">Lock</label><button type="button" data-action="remove" class="cm-remove" aria-label="Remove replacement for ${esc(card.name)}" hidden>Unlink</button>` :
            `<label><input type="checkbox" data-action="pool" checked aria-label="Include ${esc(card.name)} in random cast">Shuffle pool</label>`}</div>
        ${target ? '<div class="cm-assignment">Keep original</div>' : ''}</article>`;
    };
    const panelHTML = (side, title, cards) => `<section class="cm-panel" data-side="${side}" aria-label="${side === 'target' ? 'Original cast' : 'Replacement cast'}"><header class="cm-panel-header"><h3>${esc(title)}</h3><small>${side === 'target' ? 'Original cast · choose a character' : 'Replacement cast · connect to the selected original'}</small><input type="search" class="cm-search" data-search="${side}" aria-label="Search ${side === 'target' ? 'original' : 'replacement'} cast" placeholder="Search characters"><div class="cm-panel-meta"><span data-count="${side}"></span>${side === 'donor' ? '<span><button type="button" data-action="pool-all">All</button> <button type="button" data-action="pool-none">None</button></span>' : ''}</div></header><div class="cm-list" data-list="${side}">${cards.map((c, i) => cardHTML(c, side, i)).join('')}<div class="cm-empty" hidden>No matching characters.</div></div></section>`;
    node.innerHTML = `<style>${style}</style><div class="cm-caption"><strong>Original → Replacement</strong><span>Choose an original, then a replacement. Drag between cards to connect them.</span></div>
      <div class="cm-toolbar"><label>Seed <input type="text" data-seed value="" maxlength="100" placeholder="Any seed" aria-label="Random cast seed"></label><button type="button" data-action="shuffle">Shuffle cast</button><button type="button" data-action="clear">Clear connections</button><label><input type="checkbox" data-auto-lock checked>Lock manual choices</label></div>
      <div class="cm-board">${panelHTML('target', data?.game?.title || 'Original title', targets)}${panelHTML('donor', data?.source?.label || 'Replacement title', donors)}<svg class="cm-lines" aria-hidden="true"><defs><marker id="${uid}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" style="fill:#b3bdff;stroke:none"></path></marker></defs><g data-lines></g></svg></div>
      <p class="cm-status" role="status" aria-live="polite"></p><div class="cm-summary"></div><div class="cm-capability" hidden></div>`;
    host.appendChild(node);
    const q = selector => node.querySelector(selector), all = selector => [...node.querySelectorAll(selector)];
    const cards = { target: new Map(), donor: new Map() };
    for (const side of ['target', 'donor']) for (const el of all(`[data-cm-card="${side}"]`)) cards[side].set(el.dataset.key, el);
    const listeners = [];
    function listen(el, name, fn, options) { el.addEventListener(name, fn, options); listeners.push(() => el.removeEventListener(name, fn, options)); }
    function status(text, error = false) { if (!disposed) { q('.cm-status').textContent = text; q('.cm-status').classList.toggle('cm-error', error); } }
    function getAssignments() { return targets.map(t => ({ target_id: t.id, slot: t.slot, character: picks.get(t.id) || '' })); }
    function notify() {
      if (disposed || typeof io.onChange !== 'function') return;
      const token = ++changeSequence;
      try { Promise.resolve(io.onChange(getAssignments())).catch(error => { if (!disposed && token === changeSequence) status(`Could not update review: ${error.message || error}`, true); }); }
      catch (error) { status(`Could not update review: ${error.message || error}`, true); }
    }
    function draw() {
      frame = null; if (disposed) return;
      const board = q('.cm-board').getBoundingClientRect(), paths = [];
      const visiblePoint = (el, side) => {
        if (!el || el.hidden) return null;
        const port = el.querySelector('.cm-port').getBoundingClientRect(), clip = q(`[data-list="${side}"]`).getBoundingClientRect();
        const y = port.y + port.height / 2;
        if (y < clip.top || y > clip.bottom) return null;
        return { x: port.x + port.width / 2 - board.x, y: y - board.y };
      };
      for (const t of targets) {
        const donor = picks.get(t.id); if (!donor) continue;
        const a = visiblePoint(cards.target.get(t.id), 'target'), b = visiblePoint(cards.donor.get(donor), 'donor');
        if (!a || !b) continue;
        const bend = Math.max(24, (b.x - a.x) * .45);
        paths.push(`<path data-target-id="${esc(t.id)}" data-active="${t.id === selected}" marker-end="url(#${uid}-arrow)" d="M${a.x},${a.y} C${a.x + bend},${a.y} ${b.x - bend},${b.y} ${b.x},${b.y}"></path>`);
      }
      q('[data-lines]').innerHTML = paths.join('');
    }
    function scheduleDraw() { if (!disposed && frame === null) frame = win.requestAnimationFrame(draw); }
    function render() {
      if (disposed) return;
      const counts = new Map(); for (const value of picks.values()) if (value) counts.set(value, (counts.get(value) || 0) + 1);
      for (const t of targets) {
        const el = cards.target.get(t.id), donor = donorMap.get(picks.get(t.id));
        el.dataset.selected = String(t.id === selected); el.dataset.connected = String(!!donor);
        el.querySelector('.cm-main').setAttribute('aria-pressed', String(t.id === selected));
        el.querySelector('.cm-assignment').textContent = donor ? `→ ${donor.name}` : 'Keep original';
        el.querySelector('[data-action=remove]').hidden = !donor;
        el.querySelector('[data-action=lock]').checked = locks.has(t.id);
      }
      for (const d of donors) {
        const el = cards.donor.get(d.slug); el.dataset.connected = String(counts.has(d.slug));
        el.dataset.selected = String(picks.get(selected) === d.slug);
        el.querySelector('.cm-main').setAttribute('aria-pressed', String(picks.get(selected) === d.slug));
        el.querySelector('[data-action=pool]').checked = pool.has(d.slug);
      }
      const assigned = [...picks.values()].filter(Boolean).length;
      q('.cm-summary').textContent = `${assigned} of ${targets.length} originals connected · ${targets.length - assigned} kept original · ${locks.size} locked · ${pool.size} in shuffle pool`;
      q('[data-action=shuffle]').disabled = !targets.length || !pool.size;
      filter(); scheduleDraw();
    }
    function filter() {
      for (const side of ['target', 'donor']) {
        const term = q(`[data-search="${side}"]`).value.trim().toLocaleLowerCase(); let visible = 0;
        const list = side === 'target' ? targets : donors;
        for (const card of list) {
          const el = cards[side].get(side === 'target' ? card.id : card.slug);
          el.hidden = term !== '' && !`${card.name} ${card.kind || ''} ${card.source_game_id || ''}`.toLocaleLowerCase().includes(term);
          if (!el.hidden) visible++;
        }
        q(`[data-count="${side}"]`).textContent = `${visible} of ${list.length} characters`;
        q(`[data-list="${side}"] .cm-empty`).hidden = visible > 0;
      }
      scheduleDraw();
    }
    function connect(target, donor) {
      if (disposed || !targetMap.has(target) || !donorMap.has(donor)) return;
      picks.set(target, donor);
      if (q('[data-auto-lock]').checked) locks.add(target);
      selected = target; render(); notify();
      status(`${targetMap.get(target).name} → ${donorMap.get(donor).name}. ${locks.has(target) ? 'Locked during shuffle.' : ''}`);
    }
    function shuffle(seed) {
      if (disposed) return getAssignments();
      const enteredSeed = seed === undefined ? q('[data-seed]').value : String(seed);
      const effectiveSeed = enteredSeed || (win.crypto?.randomUUID ? win.crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
      q('[data-seed]').value = effectiveSeed;
      const eligible = targets.filter(t => !locks.has(t.id)).map(t => t.id), chosen = deal(eligible, [...pool], effectiveSeed);
      for (const [id, character] of Object.entries(chosen)) picks.set(id, character);
      render(); notify(); status(pool.size ? `Shuffled ${eligible.length} originals; ${locks.size} locked choices kept.` : 'Select replacements for the shuffle pool.');
      return getAssignments();
    }
    function clear() {
      if (disposed) return;
      for (const t of targets) picks.set(t.id, ''); locks.clear(); render(); notify(); status('Connections cleared. Every original is kept.');
    }
    function setAssignments(rows) {
      if (disposed) return;
      const next = new Map(targets.map(t => [t.id, '']));
      for (const row of Array.isArray(rows) ? rows : []) {
        if (!row || !targetMap.has(String(row.target_id))) continue;
        const character = String(row.character || '');
        if (!character || donorMap.has(character)) next.set(String(row.target_id), character);
      }
      for (const [id, character] of next) picks.set(id, character);
      locks.clear(); render(); notify();
    }
    function inspect(card, side) {
      if (disposed || typeof io.inspect !== 'function') return;
      const token = ++inspectSequence;
      try { Promise.resolve(io.inspect({ ...card }, side)).catch(error => {
        if (!disposed && token === inspectSequence) status(`Could not inspect ${card.name}: ${error.message || error}`, true);
      }); } catch (error) { status(`Could not inspect ${card.name}: ${error.message || error}`, true); }
    }
    listen(node, 'click', event => {
      const button = event.target.closest('[data-action]'); if (!button || button.disabled) return;
      const action = button.dataset.action, el = button.closest('[data-cm-card]'), key = el?.dataset.key, side = el?.dataset.cmCard;
      if (action === 'target') { selected = key; render(); status(`Choose a replacement for ${targetMap.get(key).name}.`); }
      else if (action === 'donor') { if (selected) connect(selected, key); else status('Choose an original character first.'); }
      else if (action === 'inspect') inspect(side === 'target' ? targetMap.get(key) : donorMap.get(key), side);
      else if (action === 'remove') { picks.set(key, ''); locks.delete(key); render(); notify(); status(`${targetMap.get(key).name} will stay original.`); }
      else if (action === 'shuffle') shuffle();
      else if (action === 'clear') clear();
      else if (action === 'pool-all' || action === 'pool-none') { pool.clear(); if (action === 'pool-all') donors.forEach(d => pool.add(d.slug)); render(); }
    });
    listen(node, 'change', event => {
      const el = event.target.closest('[data-cm-card]'), key = el?.dataset.key;
      if (event.target.dataset.action === 'lock') { if (event.target.checked) locks.add(key); else locks.delete(key); render(); }
      if (event.target.dataset.action === 'pool') { if (event.target.checked) pool.add(key); else pool.delete(key); render(); }
    });
    listen(node, 'input', event => { if (event.target.matches('[data-search]')) filter(); });
    listen(node, 'keydown', event => {
      if (!event.target.matches('.cm-main')) return;
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); if (!event.repeat) event.target.click(); return; }
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
      const list = event.target.closest('.cm-list'), buttons = [...list.querySelectorAll('.cm-card:not([hidden]) .cm-main')], index = buttons.indexOf(event.target);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : Math.max(0, Math.min(buttons.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
      event.preventDefault(); buttons[next]?.focus();
    });
    listen(node, 'dragstart', event => {
      const el = event.target.closest('[data-cm-card]'); if (!el || !event.dataTransfer) return;
      drag = { side: el.dataset.cmCard, key: el.dataset.key };
      event.dataTransfer.effectAllowed = 'link'; event.dataTransfer.setData('text/plain', `${uid}:${drag.side}:${drag.key}`);
      status(drag.side === 'donor' ? 'Drop on an original character to replace it.' : 'Drop on a replacement character to connect it.');
    });
    listen(node, 'dragover', event => {
      const el = event.target.closest('[data-cm-card]');
      if (drag && el && el.dataset.cmCard !== drag.side) { event.preventDefault(); event.dataTransfer.dropEffect = 'link'; el.dataset.drop = 'true'; }
    });
    listen(node, 'dragleave', event => { const el = event.target.closest('[data-cm-card]'); if (el && !el.contains(event.relatedTarget)) delete el.dataset.drop; });
    const endDrag = () => { drag = null; all('[data-drop]').forEach(el => delete el.dataset.drop); };
    listen(node, 'dragend', endDrag);
    listen(node, 'drop', event => {
      const el = event.target.closest('[data-cm-card]');
      if (drag && el && el.dataset.cmCard !== drag.side) {
        event.preventDefault(); connect(drag.side === 'target' ? drag.key : el.dataset.key, drag.side === 'donor' ? drag.key : el.dataset.key);
      }
      endDrag();
    });
    listen(node, 'error', event => {
      if (event.target.tagName === 'IMG') { event.target.hidden = true; event.target.previousElementSibling.hidden = false; }
    }, true);
    for (const img of all('.cm-thumb img')) { img.previousElementSibling.hidden = true; listen(img, 'load', () => { if (!disposed) img.previousElementSibling.hidden = true; }); }
    for (const list of all('.cm-list')) listen(list, 'scroll', scheduleDraw, { passive: true });
    listen(win, 'resize', scheduleDraw);
    const observer = typeof win.ResizeObserver === 'function' ? new win.ResizeObserver(scheduleDraw) : null;
    observer?.observe(q('.cm-board'));
    const capability = data?.capability || {}, reasons = Array.isArray(capability.blocking_reasons) ? capability.blocking_reasons.filter(Boolean) : [];
    if (reasons.length || targets.some(t => !t.slot) || capability.combined_writer === false) {
      q('.cm-capability').hidden = false;
      q('.cm-capability').textContent = ['Mapping review is available. Building still requires verified native slots and a combined cast writer.', ...reasons.map(r => `• ${typeof r === 'string' ? r : r.reason || r.message || String(r)}`)].join('\n');
    }
    render();
    status(targets.length && donors.length ? `Select an original, then choose its replacement. Inspect 3D opens either model.` :
      !targets.length ? 'No original character roster is available yet. Extract or register the title’s cast first.' : 'No replacement characters are available yet. Choose another source or extract its cast.');
    const api = { getAssignments, setAssignments, shuffle, clear,
      getDraft() { return {version: 1, rows: getAssignments(), locks: [...locks], pool: [...pool],
        seed: q('[data-seed]').value, autoLock: q('[data-auto-lock]').checked}; },
      restoreDraft(draft) {
        if (disposed || draft?.version !== 1 || !Array.isArray(draft.rows)) return;
        setAssignments(draft.rows);
        for (const id of Array.isArray(draft.locks) ? draft.locks : []) if (targetMap.has(id)) locks.add(id);
        if (Array.isArray(draft.pool)) { pool.clear(); for (const slug of draft.pool) if (donorMap.has(slug)) pool.add(slug); }
        q('[data-seed]').value = String(draft.seed || '').slice(0, 100);
        q('[data-auto-lock]').checked = draft.autoLock !== false;
        render(); notify();
      },
      dispose() { if (disposed) return; disposed = true; inspectSequence++; endDrag(); if (frame !== null) win.cancelAnimationFrame(frame); frame = null; observer?.disconnect(); listeners.splice(0).forEach(remove => remove()); node.remove(); } };
    api.ready = Promise.resolve(api);
    return api;
  }
  return { mount, deal, roster };
});
