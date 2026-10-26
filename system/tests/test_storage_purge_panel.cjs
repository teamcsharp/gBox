const test = require('node:test'), assert = require('node:assert/strict');
const P = require('../clients/web/viz/storage-purge.js');

const GB = 2 ** 30;
const DRY = {
  job_id: 'j1', deletable: true, dry_run: true, pc: 'i9-NUC', unplayed_days: 14, include: ['games', 'builds'],
  items: [{ kind: 'game', game: 'aaaaaaaaaaaaaaa3', title: 'Old Game', part: 'staged library copy', path: 'D:\\gBox\\cache\\aaaaaaaaaaaaaaa3',
            size: 40 * GB, last_played: 1760000000, reason: 'not a favorite; not played on i9-NUC for 14+ days' },
          { kind: 'build', game: 'aaaaaaaaaaaaaaa3', title: '', build: 'doa3_cast_t1', part: 'build', path: 'D:\\gBox\\cache\\mods\\aaaaaaaaaaaaaaa3\\doa3_cast_t1',
            size: 8 * GB, last_played: null, reason: 'sent automatically (no operator download)' },
          { kind: 'build', game: 'aaaaaaaaaaaaaaa3', title: '', build: 'doa3_cast_t1', part: 'staged copy of the build',
            path: 'D:\\gBox\\cache\\mods\\aaaaaaaaaaaaaaa3\\doa3_cast_t1~ab', size: 4 * GB, reason: 'sent automatically <b>' }],
  kept: [{ kind: 'game', game: 'aaaaaaaaaaaaaaa1', title: 'Fav', part: 'staged library copy', size: GB, reason: 'favorite' }],
  totals: { items: 3, bytes: 52 * GB, freed_bytes: 50 * GB, kept_bytes: GB }, warnings: [] };

test('sizes read like the operator talks about disks', () => {
  assert.equal(P.fmtBytes(0), '0 B'); assert.equal(P.fmtBytes(512), '512 B'); assert.equal(P.fmtBytes(3 * 1024), '3 KB');
  assert.equal(P.fmtBytes(640 * 2 ** 20), '640 MB'); assert.equal(P.fmtBytes(5.25 * GB), '5.3 GB'); assert.equal(P.fmtBytes(182 * GB), '182 GB');
});

test('the menu button shows the newest dry run, else asks to check', () => {
  assert.equal(P.buttonLabel({ storage: { dry_run: true, freed_bytes: 182 * GB } }), '🧹 Free space: 182 GB unplayed');
  assert.equal(P.buttonLabel({ storage: null }), '🧹 Free space (check unplayed games and builds)');
  assert.equal(P.buttonLabel({ storage: { dry_run: false, freed_bytes: 1 } }), '🧹 Free space (check unplayed games and builds)');
});

test('the list groups games and builds, escapes text, and shows what stays', () => {
  const groups = P.group(DRY.items);
  assert.deepEqual(groups.map(g => [g.kind, g.items.length, g.bytes]), [['game', 1, 40 * GB], ['build', 2, 12 * GB]]);
  const html = P.listHTML(DRY);
  assert.match(html, /Games · 1 · 40\.0 GB/); assert.match(html, /Builds · 2 · 12\.0 GB/);
  assert.match(html, /Old Game/); assert.match(html, /never played on this PC/); assert.match(html, /Kept \(1 · 1\.0 GB\)/);
  assert.ok(!html.includes('<b>'), 'reasons are escaped');
  assert.match(P.listHTML({ ...DRY, items: [], kept: [] }), /Nothing to free/);
});

test('Delete these sends exactly the reviewed paths', () => {
  assert.deepEqual(P.deleteBody(DRY), { dry_run: false, unplayed_days: 14, include: ['games', 'builds'], paths: DRY.items.map(i => i.path) });
  assert.equal(P.confirmLabel(DRY), 'Confirm: delete 3 items (50.0 GB)');
});

function fakeApi(results) {
  const calls = [];
  const api = async (path, body, method) => {
    calls.push({ path, body, method });
    if (path.endsWith('/storage-purge') && body) return { job_id: body.dry_run ? 'j1' : 'j2' };
    if (path.startsWith('/api/jobs/')) return { state: 'succeeded', progress: { pct: 100, msg: 'done' } };
    if (path.includes('/storage-purge?job_id=j1')) return results.dry;
    if (path.includes('/storage-purge?job_id=j2')) return results.deleted;
    throw Error('unexpected ' + path);
  };
  return { api, calls };
}

test('check, arm, then delete: nothing is deleted without a second press', async () => {
  const deleted = { ...DRY, dry_run: false, items: DRY.items.map(i => ({ ...i, deleted: true })), skipped: [],
                    totals: { ...DRY.totals, deleted: 3 }, roots: { freed_measured: 49 * GB } };
  const { api, calls } = fakeApi({ dry: DRY, deleted });
  const drawn = [];
  let clock = 1000;
  const ctl = P.create({ api, name: 'i9-NUC', draw: s => drawn.push(s), wait: async () => {}, now: () => clock });
  let s = await ctl.check();
  assert.equal(s.status, 'listing'); assert.ok(s.deletable);
  assert.deepEqual(calls[0], { path: '/api/workers/i9-NUC/storage-purge', body: { dry_run: true, unplayed_days: 14 }, method: undefined });
  assert.match(P.summaryText(s), /3 items on i9-NUC not played for 14\+ days: 50\.0 GB can be freed/);
  s = await ctl.remove();                                      // first press: armed only
  assert.equal(s.status, 'listing'); assert.ok(s.armedAt);
  assert.equal(calls.filter(c => c.body && c.body.dry_run === false).length, 0);
  clock += P.ARM_MS + 1;
  s = await ctl.remove();                                      // too late: armed again, still nothing sent
  assert.equal(calls.filter(c => c.body && c.body.dry_run === false).length, 0);
  clock += 10;
  s = await ctl.remove();                                      // the confirming press
  const del = calls.find(c => c.body && c.body.dry_run === false);
  assert.deepEqual(del.body.paths, DRY.items.map(i => i.path));
  assert.equal(s.status, 'done'); assert.match(P.summaryText(s), /Deleted 3 item\(s\) on i9-NUC: 49\.0 GB freed/);
  assert.ok(drawn.some(d => d.status === 'checking') && drawn.some(d => d.status === 'deleting'));
});

test('a preview without the Spark facts cannot delete, and a failed job says why', async () => {
  const { api } = fakeApi({ dry: { ...DRY, deletable: false, warnings: ['no facts from the Spark'] } });
  const ctl = P.create({ api, name: 'i9-NUC', wait: async () => {} });
  let s = await ctl.check();
  assert.equal(s.deletable, false);
  s = await ctl.remove();
  assert.equal(s.armedAt, 0, 'never armed');
  assert.match(P.render(s), /disabled/); assert.match(P.render(s), /Deleting needs the Spark/);
  const failing = async (path, body) => {
    if (body) return { job_id: 'j9' };
    return { state: 'failed', error: 'worker offline' };
  };
  const bad = await P.create({ api: failing, name: 'X', wait: async () => {} }).check();
  assert.equal(bad.status, 'failed'); assert.match(P.summaryText(bad), /worker offline/);
});

test('follow polls the job until it ends and reports its progress', async () => {
  const states = [{ state: 'queued' }, { state: 'running', progress: { pct: 40, msg: 'Reading this PC\'s cache' } }, { state: 'succeeded' }];
  const seen = [];
  const job = await P.follow(async () => states.shift(), 'j1', (pct, msg) => seen.push([pct, msg]), { wait: async () => {} });
  assert.equal(job.state, 'succeeded'); assert.deepEqual(seen, [[0, ''], [40, 'Reading this PC\'s cache']]);
});
