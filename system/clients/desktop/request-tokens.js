/* Requests token accounting + finite odometer animation. Uses the existing ledger snapshot, never another poller. */
(function (root, factory) {
  const lib = factory();
  if (typeof module === 'object' && module.exports) module.exports = lib;
  else root.GBoxRequestTokens = lib;
})(globalThis, function () {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const count = v => typeof v === 'bigint' ? (v >= 0n ? v : null)
    : typeof v === 'number' ? (Number.isSafeInteger(v) && v >= 0 ? BigInt(v) : null)
    : typeof v === 'string' && /^\d+$/.test(v) ? BigInt(v) : null;
  const format = n => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const empty = () => ({ input: 0n, output: 0n, total: 0n, requests: 0, reported: 0, missing: 0 });
  function add(a, b) {
    for (const k of ['input', 'output', 'total', 'requests', 'reported', 'missing']) a[k] += b[k];
    return a;
  }
  function usage(row) {
    const m = row.metrics || {}, input = count(m.tokens_in), output = count(m.tokens_out), detail = m.tokens_detail || {};
    const unavailable = !!detail.token_count_unavailable || (m.usage_by_solver || []).some(u => !!u.token_count_unavailable);
    const recorded = input !== null && output !== null && (input + output > 0n || detail.availability === 'measured_final');
    const positive = (input || 0n) + (output || 0n) > 0n;
    return { input: input || 0n, output: output || 0n, total: (input || 0n) + (output || 0n), requests: 1,
      reported: +(recorded || positive), missing: +(!recorded || unavailable) };
  }
  function analyze(rows) {
    const unique = new Map();
    (rows || []).forEach((r, i) => { const id = String(r.id ?? `anonymous:${i}`); if (!unique.has(id)) unique.set(id, r); });
    const all = empty(), completed = empty(), children = new Map(), tasks = new Map(), visiting = new Set();
    for (const [id, row] of unique) {
      const own = usage(row); add(all, own); if (row.status === 'done') add(completed, own);
      const parent = row.parent_request_id || row.context?.parent_request_id;
      if (parent && String(parent) !== id && unique.has(String(parent))) {
        const list = children.get(String(parent)) || []; list.push(id); children.set(String(parent), list);
      }
    }
    function task(id) {
      if (tasks.has(id)) return tasks.get(id);
      if (visiting.has(id)) return { own: empty(), combined: empty(), cycle: true };
      visiting.add(id);
      const own = usage(unique.get(id)), combined = add(empty(), own); let cycle = false;
      for (const child of children.get(id) || []) { const result = task(child); add(combined, result.combined); cycle ||= result.cycle; }
      visiting.delete(id);
      const result = { own, combined, cycle }; tasks.set(id, result); return result;
    }
    for (const id of unique.keys()) task(id);
    return { ...all, completed, tasks };
  }
  function taskHTML(id, snapshot) {
    const item = snapshot.tasks.get(String(id)); if (!item) return '';
    const { own, combined: u } = item, linked = u.requests > 1;
    const missing = u.missing ? ` · ${u.missing} ${u.missing === 1 ? 'entry has' : 'entries have'} unreported usage` : '';
    const title = `${format(u.input)} input + ${format(u.output)} output. Input includes recorded cache usage; detail and solver subtotals are not added twice.${missing}`;
    return `<details class="rt-task" data-group-key="token-usage-${esc(id)}"><summary title="${esc(title)}">${u.reported ? `${format(u.total)} tokens spent${linked ? ' · includes linked work' : ''}` : 'Token usage not recorded'}${u.reported && u.missing ? ' · partial' : ''}</summary>
      <div class="rt-breakdown"><span>Recorded input <b>${format(u.input)}</b></span><span>Recorded output <b>${format(u.output)}</b></span>
      ${linked ? `<span>This task <b>${own.reported ? format(own.total) : 'Not recorded'}</b></span><span>Recorded linked work <b>${format(u.total - own.total)}</b></span>` : ''}
      <small>${u.reported} of ${u.requests} ${u.requests === 1 ? 'entry reports' : 'entries report'} usage${missing}. Cache reads/writes are already part of recorded input. ${item.cycle ? 'A linked-task cycle prevents a complete rollup.' : ''}</small></div></details>`;
  }
  const CSS = `
    .rt-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:22px;margin-bottom:12px;flex-wrap:wrap;position:sticky;top:0;z-index:3;background:var(--bg,#16161b);padding:8px 0 12px}
    .rt-heading h2{margin:0 0 9px}.rt-heading-actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
    .rt-counter{margin-left:auto;text-align:right;max-width:100%;font-variant-numeric:tabular-nums}
    .rt-kicker{font-size:10px;color:var(--mut,#a2a6b5);letter-spacing:.15em;text-transform:uppercase;margin-bottom:5px}
    .rt-number{display:flex;justify-content:flex-end;align-items:center;line-height:1;height:1.1em;font:600 clamp(25px,3.1vw,45px)/1 ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:-.045em;color:var(--fg,#f3f3f8)}
    .rt-digit{display:inline-block;height:1em;width:.66em;overflow:hidden;position:relative;transform-origin:50% 65%}
    .rt-track{display:flex;flex-direction:column;will-change:transform}.rt-track span{display:block;height:1em;flex:0 0 1em;text-align:center}
    .rt-comma{width:.37em;color:var(--mut,#9a9db0)}.rt-label-clip{overflow:hidden;min-height:1.55em;margin-top:5px}
    .rt-label{display:block;font-size:12px;font-weight:600;color:var(--accent,#8c9bff);transform:translateY(0)}
    .rt-coverage{border:0;background:none;color:var(--mut,#a2a6b5);font:inherit;font-size:10px;text-align:right;cursor:pointer;padding:2px 0}
    .rt-analysis{font-size:12px;margin-bottom:14px;border:1px solid var(--line,#353541);border-radius:8px;padding:10px 12px}
    .rt-analysis summary{cursor:pointer}.rt-breakdown{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 18px;margin:9px 0;max-width:520px}
    .rt-breakdown span{display:flex;justify-content:space-between;gap:12px}.rt-breakdown small{grid-column:1/-1;color:var(--mut,#a2a6b5);font-size:11px;line-height:1.5}
    .rt-task{display:inline-block;vertical-align:top;font-size:11px;color:var(--mut,#a2a6b5);margin-top:5px}.rt-task summary{cursor:pointer;color:var(--fg,#eee);font-variant-numeric:tabular-nums}
    .rt-task[open]{display:block}.rt-task .rt-breakdown{padding:8px 10px;border-radius:5px;background:var(--bg,#17171c)}
    @media(max-width:640px){.rt-counter{width:100%;text-align:left;margin-left:0}.rt-number{justify-content:flex-start}.rt-coverage{text-align:left}}
    @media(prefers-reduced-motion:reduce){.rt-track{will-change:auto}}`;
  function mount(host, options = {}) {
    const doc = host.ownerDocument, win = doc.defaultView, media = win.matchMedia('(prefers-reduced-motion: reduce)');
    if (!doc.getElementById('request-token-styles')) { const style = doc.createElement('style'); style.id = 'request-token-styles'; style.textContent = CSS; doc.head.append(style); }
    host.classList.add('rt-counter');
    host.innerHTML = '<div class="rt-kicker">Project total · all requests</div><div class="rt-number" aria-hidden="true">—</div><span class="rt-accessible" role="status" aria-live="polite" style="position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)"></span><div class="rt-label-clip"><span class="rt-label">Tokens spent</span></div><button class="rt-coverage" type="button" aria-label="Show token usage analysis">Waiting for recorded usage</button>';
    const digits = host.querySelector('.rt-number'), label = host.querySelector('.rt-label'), accessible = host.querySelector('.rt-accessible'), coverage = host.querySelector('.rt-coverage');
    const analysis = options.analysis;
    coverage.onclick = () => { if (analysis) { analysis.open = !analysis.open; if (analysis.open) analysis.scrollIntoView({ block: 'nearest', behavior: media.matches ? 'auto' : 'smooth' }); } };
    let data = null, shown = null, visible = false, reveal = true, animations = [], generation = 0;
    const cancel = () => { generation++; animations.forEach(a => a.cancel()); animations = []; };
    function animate(element, frames, timing) {
      if (!element.animate) return null;
      const animation = element.animate(frames, { fill: 'both', ...timing }); animations.push(animation); return animation;
    }
    function paint(force = false) {
      if (!visible || !data || !host.isConnected) return;
      const value = format(data.total), previous = shown;
      if (!force && value === shown) return;
      cancel(); const run = generation; shown = value;
      accessible.textContent = `${value} recorded tokens spent on this project${data.missing ? '; some usage is unreported' : ''}.`;
      const old = (previous || '').replace(/,/g, '').padStart(String(data.total).length, '0'); let index = 0, lastFinish = 0;
      const settled = [];
      digits.replaceChildren();
      for (const char of value) {
        const el = doc.createElement('span');
        if (char === ',') { el.className = 'rt-comma'; el.textContent = ','; digits.append(el); continue; }
        el.className = 'rt-digit'; el.dataset.digit = char;
        const track = doc.createElement('span'); track.className = 'rt-track';
        const shouldRoll = !media.matches && (force || char !== old[index]);
        const target = shouldRoll ? 20 + Number(char) : Number(char);
        for (let n = 0; n <= (shouldRoll ? 29 : 9); n++) { const face = doc.createElement('span'); face.textContent = String(n % 10); track.append(face); }
        track.style.transform = `translateY(-${target}em)`; el.append(track); digits.append(el);
        if (shouldRoll) {
          const duration = 620 + index * 70, start = force ? 0 : Number(old[index] || 0);
          lastFinish = Math.max(lastFinish, duration + 150);
          const roll = animate(track, [{ transform: `translateY(-${start}em)` }, { transform: `translateY(-${target}em)` }], { duration, easing: 'cubic-bezier(.16,.7,.25,1)' });
          if (roll) settled.push(roll.finished.then(() => { if (generation === run) animate(el, [{ transform: 'scale(1)' }, { transform: 'scale(1.16)', color: 'var(--accent,#8c9bff)' }, { transform: 'scale(1)' }], { duration: 150 }); }).catch(() => {}));
        }
        index++;
      }
      if (!media.matches && force) animate(label, [{ transform: 'translateY(120%)', opacity: 0 }, { transform: 'translateY(0)', opacity: 1 }], { delay: lastFinish, duration: 270, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'both' });
      // Deterministic completion for tests and callers. No timers or animation frame loop survives the finite reveal.
      host._tokenRevealDone = Promise.all(settled);
    }
    function update(snapshot) {
      data = snapshot;
      coverage.textContent = `${data.reported.toLocaleString()} / ${data.requests.toLocaleString()} entries report usage${data.missing ? ' · partial total' : ''}`;
      coverage.title = `${data.missing.toLocaleString()} entries have missing or incomplete usage. The total counts each request once, across every filter. Input includes cached tokens.`;
      if (analysis) {
        const c = data.completed, average = c.reported ? c.total / BigInt(c.reported) : null;
        analysis.innerHTML = `<summary>Token usage analysis</summary><div class="rt-breakdown"><span>Recorded input <b>${format(data.input)}</b></span><span>Recorded output <b>${format(data.output)}</b></span><span>Completed work <b>${format(c.total)}</b></span><span>Average per reporting completed entry <b>${average === null ? '—' : format(average)}</b></span><small>${c.reported} of ${c.requests} completed entries report usage; ${c.missing} have missing/incomplete usage. Unreported tokens are not treated as zero spend. Project totals include pending and automated work. Linked work is included in task rollups but counted only once in the project total. Cache and reasoning details are not added again.</small></div>`;
      }
      paint(reveal); if (visible) reveal = false;
    }
    function enter() { if (visible) return; visible = true; reveal = true; if (data) { paint(true); reveal = false; } }
    function leave() { visible = false; reveal = true; cancel(); }
    const motion = () => { if (data && visible) paint(true); };
    media.addEventListener?.('change', motion);
    const sync = () => options.section?.classList.contains('on') && !doc.hidden ? enter() : leave();
    let observer;
    if (options.section) { observer = new win.MutationObserver(sync); observer.observe(options.section, { attributes: true, attributeFilter: ['class'] }); doc.addEventListener('visibilitychange', sync); sync(); }
    return { update, enter, leave, dispose() { leave(); observer?.disconnect(); media.removeEventListener?.('change', motion); doc.removeEventListener('visibilitychange', sync); } };
  }
  return { count, format, usage, analyze, taskHTML, mount };
});
