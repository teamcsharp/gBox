/* A bounded, read-only view of every retained damage event in an Inbox batch. */
(function(root) {
  const PAGE = 25, PATH = /^\/api\/sessions\/[A-Za-z0-9_-]{1,160}\/damage\/runs\/[A-Za-z0-9_-]{8,96}$/;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const count = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
  function button(batch) {
    return PATH.test(batch?.ledger || '') ? `<br><button class="act" data-damage-ledger="${esc(batch.ledger)}">Damage evidence (${count(batch.events)} events)</button>` : '';
  }
  function eventHTML(row, artifact) {
    const at = Number.isFinite(row.observed_at) ? new Date(row.observed_at * 1000).toLocaleString() : 'Time unavailable';
    const state = row.save_state || { state: 'pending', detail: 'Capture status has not arrived.' };
    const evidence = Object.entries(row.evidence || {}).map(([name, item]) => {
      const skew = Number.isFinite(item.source_at) && Number.isFinite(row.observed_at)
        ? `; source ${Math.round((item.source_at - row.observed_at) * 1000)} ms from detected HP loss` : '';
      return `<li>${esc(name)}: ${esc(item.state || 'unknown')}${esc(skew)}${item.detail ? ' — ' + esc(item.detail) : ''}</li>`;
    }).join('');
    const attachments = (row.attachments || []).filter(a => /^[a-f0-9]{64}$/.test(a.sha256 || '')).map(a => {
      const url = esc(artifact(a.sha256)), name = esc(a.name || 'Evidence');
      return /^(image\/(jpeg|png|webp|svg\+xml))$/.test(a.type || '')
        ? `<figure style="margin:8px 0"><a href="${url}" target="_blank" rel="noopener noreferrer"><img loading="lazy" decoding="async" src="${url}" alt="${name}" style="max-width:100%;max-height:360px"></a><figcaption>${name}</figcaption></figure>`
        : `<p><a href="${url}" target="_blank" rel="noopener noreferrer">${name}</a></p>`;
    }).join('');
    const processing = row.state === 'done' ? 'Evidence processed' : 'Evidence ' + (row.state || 'pending');
    return `<details style="margin:10px 0;padding:8px;border:1px solid var(--line,#555)"><summary>${esc(at)} · HP ${esc(row.hp_before)} → ${esc(row.hp_after)} · ${esc(processing)}</summary>
      <p>Event ${esc(row.event_id)} · Round ${esc(row.round_id || 'unknown')}</p>
      <p>Damage cause: ${esc(row.cause || 'unknown')}. Self-damage: ${esc(row.self_damage || 'unknown')}.</p>
      <p>Save state: ${esc(state.state)}${state.detail ? ' — ' + esc(state.detail) : ''}</p>
      ${evidence ? '<ul>' + evidence + '</ul>' : '<p>Evidence is still being processed.</p>'}${attachments}
      ${/^[a-f0-9]{64}$/.test(row.receipt || '') ? `<p><a href="${esc(artifact(row.receipt))}" target="_blank" rel="noopener noreferrer">Original event and capture receipt (JSON)</a></p>` : ''}</details>`;
  }
  function pager(path, api) {
    if (!PATH.test(path)) throw Error('Invalid damage batch.');
    let busy = null, closed = false;
    return {
      close() { closed = true; },
      load(offset = 0) {
        if (closed) return Promise.resolve(null);
        if (busy) return busy;
        offset = count(offset);
        busy = (async () => {
          const reply = await api(`${path}?offset=${offset}&limit=${PAGE}`);
          if (closed) return null;
          if (!reply?.ok) throw Error(reply?.error || 'Damage evidence could not be loaded.');
          const data = reply.data;
          if (!Array.isArray(data?.events) || data.events.length > PAGE || !Number.isSafeInteger(data.total) || data.total < 0)
            throw Error('The damage evidence response is incomplete.');
          return { ...data, offset, previous: Math.max(0, offset - PAGE), next_offset:
            Number.isSafeInteger(data.next_offset) && data.next_offset > offset ? data.next_offset : null };
        })().finally(() => { busy = null; });
        return busy;
      }
    };
  }
  let active = null;
  function open(path, { api, artifact }) {
    const pages = pager(path, api);
    active?.close();
    const dialog = document.createElement('dialog');
    dialog.setAttribute('aria-label', 'Player damage evidence');
    dialog.style.cssText = 'width:min(900px,90vw);max-height:85vh;overflow:auto;background:var(--bg,#171719);color:var(--fg,#eee);border:1px solid var(--line,#555);border-radius:10px;padding:20px';
    dialog.innerHTML = '<button class="act" data-close style="float:right">Close</button><h2>Player damage evidence</h2><p>Each entry is a detected HP loss. Multiple hits between samples can be combined. Evidence timestamps show capture timing; missing captures remain marked. Processing evidence does not mean the gameplay issue is resolved; the Inbox report tracks that investigation.</p><p data-status role="status"></p><div data-events></div><div style="display:flex;gap:8px"><button class="act" data-prev>Previous</button><button class="act" data-next>Next</button><button class="act" data-refresh>Refresh this page</button></div>';
    let offset = 0, next = null, busy = false;
    const status = dialog.querySelector('[data-status]'), events = dialog.querySelector('[data-events]');
    const prev = dialog.querySelector('[data-prev]'), more = dialog.querySelector('[data-next]'), refresh = dialog.querySelector('[data-refresh]');
    const controls = () => { prev.disabled = busy || offset === 0; more.disabled = busy || next === null; refresh.disabled = busy; };
    async function load(wanted) {
      busy = true; controls(); status.textContent = 'Loading damage evidence…';
      try {
        const page = await pages.load(wanted); if (!page) return;
        offset = page.offset; next = page.next_offset;
        events.innerHTML = page.events.map(row => eventHTML(row, artifact)).join('');
        status.textContent = page.total ? `Events ${offset + 1}–${offset + page.events.length} of ${page.total}` : 'No damage events have arrived yet.';
      } catch (error) { status.textContent = error.message + ' Use Refresh this page to retry.'; }
      finally { busy = false; controls(); }
    }
    const current = { close: () => { pages.close(); dialog.remove(); if (active === current) active = null; } };
    active = current;
    dialog.querySelector('[data-close]').onclick = current.close;
    dialog.addEventListener('cancel', event => { event.preventDefault(); current.close(); });
    prev.onclick = () => load(Math.max(0, offset - PAGE)); more.onclick = () => load(next); refresh.onclick = () => load(offset);
    document.body.append(dialog); dialog.showModal(); load(0);
    return current;
  }
  const api = { button, eventHTML, pager, open };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxPlayerDamage = api;
})(globalThis);
