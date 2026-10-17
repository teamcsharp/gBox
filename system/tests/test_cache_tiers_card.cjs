// Settings card for the Spark's two-tier game cache (GET /api/cache/tiers, docs/cache-tiers.md).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');

function fixture(reply) {
  const calls = [], toasts = [], box = { innerHTML: '', addEventListener: (ev, fn) => { box.on = fn; } };
  const ctx = { gbox: { api: async (url, body) => { calls.push({ url, body }); return typeof reply === 'function' ? reply(url, body) : reply; } },
    toast: t => toasts.push(t), $: () => box, Date, Math,
    esc: s => String(s ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`) };
  vm.createContext(ctx);
  const start = desktop.indexOf("// The Spark's two-tier game cache");
  vm.runInContext(desktop.slice(start, desktop.indexOf('// ---------------- system eyedropper', start)), ctx);
  return { ctx, calls, toasts, box };
}

const GB = 2 ** 30;
const status = {
  enabled: true, hot: { used: 80 * GB, cap: 100 * GB, pinned: 12 * GB }, cold: { available: true },
  units: { hot: 3, cold: 40, mixed: 0 }, idle_minutes: 30, idle: 'idle', warnings: [], error: '',
  moving: [{ unit: 'g9', op: 'promote', done: 1, total: 4 }],
  moves: [{ unit: 'g2', op: 'demote', bytes: 8 * GB, at: Date.now() / 1000 - 600 }],
  top: [{ unit: '78ab9efa2e310db4', tier: 'hot', size: 5 * GB, last_used: Date.now() / 1000 - 120, pin: true },
        { unit: 'g2', tier: 'cold', size: null, last_used: null, pin: false }],
};

test('the card shows used/cap, pinned size, counts, moves and a keep-on-NVMe box per game', async () => {
  const f = fixture({ ok: true, data: status });
  await f.ctx.loadCacheTiers();
  const html = f.box.innerHTML;
  assert.match(html, /<b>80 GB<\/b> of 100 GB/);
  assert.match(html, /12 GB is the character library/);
  assert.match(html, /on the NVMe: 3 · on the HDD: 40/);
  assert.match(html, /width:80\.0%/);
  assert.match(html, /To the NVMe: g9 25%/);
  assert.match(html, /To the HDD: g2, 8\.0 GB, 10 min ago/);
  assert.match(html, /data-tier-pin="78ab9efa2e310db4" checked/);
  assert.match(html, /<td>HDD<\/td><td>\?<\/td><td>never<\/td>/);
});

test('ticking the box pins the game; a failed call puts the box back', async () => {
  const f = fixture((url) => url === '/api/cache/tiers/pin' ? { ok: false, error: '409 single tier' } : { ok: true, data: status });
  await f.ctx.loadCacheTiers();
  const target = { dataset: { tierPin: 'g2' }, checked: true };
  await f.box.on({ target });
  assert.deepEqual(JSON.parse(JSON.stringify(f.calls[1])), { url: '/api/cache/tiers/pin', body: { unit: 'g2', pin: true } });
  assert.equal(target.checked, false);
  assert.match(f.toasts[0], /Could not change g2/);
});

test('a single-drive node says so', async () => {
  const f = fixture({ ok: true, data: { enabled: false, cache: 'D:/gBox/cache', cap: 250 * GB } });
  await f.ctx.loadCacheTiers();
  assert.match(f.box.innerHTML, /One drive: D:\/gBox\/cache \(up to 250 GB\)/);
});
