// F5's "update the gBox app" (operator 2026-10-26: "I just want to press F5 reconnect it to the source and reboot the
// stream and build and update the gbox app"): clients/desktop/app-update.cjs fast-forwards this PC's checkout to GitHub's
// main, never discarding anything, and main.js's client:update answers the renderer's update step (reconnect-flow.js).
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path'), vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const U = require('../clients/desktop/app-update.cjs');

// a fake git: the first answer whose key starts the command line, else success with no output
function fake(answers = {}) {
  const calls = [];
  const run = async (_cwd, args) => {
    const line = args.join(' '); calls.push(line);
    const key = Object.keys(answers).find(k => line.startsWith(k));
    const a = key === undefined ? { ok: true, out: '' } : answers[key];
    return typeof a === 'function' ? a(line) : a;
  };
  return { run, calls };
}
const ON_MAIN = { 'rev-parse --show-toplevel': { ok: true, out: 'C:/_tools/gBox' }, 'symbolic-ref': { ok: true, out: 'main' },
  'status --porcelain': { ok: true, out: '' }, 'rev-parse --verify HEAD': { ok: true, out: 'a'.repeat(40) },
  'rev-parse --verify FETCH_HEAD': { ok: true, out: 'b'.repeat(40) }, 'merge-base --is-ancestor': { ok: true, out: '' },
  'rev-list --count': { ok: true, out: '3' }, 'diff --name-only': { ok: true, out: 'clients/desktop/index.html\nclients/web/viz/mercmode.js' } };

test('only a checkout on main without local changes is fast-forwarded; anything else is left alone with the reason', async () => {
  const none = fake({ 'rev-parse --show-toplevel': { ok: false, err: 'fatal: not a git repository' } });
  let out = await U.pull({ root: '\\\\10.89.1.246\\ehm_eckx\\gBox\\system', run: none.run });
  assert.equal(out.state, 'skipped'); assert.equal(out.reason, 'not-git'); assert.match(out.detail, /not a git checkout.*Spark's deploy/);
  assert.equal(none.calls.length, 1);
  const branch = fake({ ...ON_MAIN, 'symbolic-ref': { ok: true, out: 're4-fire-80x' } });
  out = await U.pull({ root: 'C:/_tools/gBox/system', run: branch.run });
  assert.deepEqual([out.state, out.reason, out.branch], ['skipped', 'branch', 're4-fire-80x']);
  assert.equal(out.detail, 'This PC\'s copy is on branch re4-fire-80x, not main: nothing was pulled (switch it to main to let F5 update it)');
  assert.ok(!branch.calls.some(c => /^(fetch|merge|switch|checkout|reset|stash)/.test(c)), branch.calls.join(' | '));
  const detached = fake({ ...ON_MAIN, 'symbolic-ref': { ok: false, err: '' } });
  assert.match((await U.pull({ root: 'x', run: detached.run })).detail, /is not on a branch, not main/);
  const dirty = fake({ ...ON_MAIN, 'status --porcelain': { ok: true, out: ' M system/clients/desktop/index.html' } });
  out = await U.pull({ root: 'x', run: dirty.run });
  assert.deepEqual([out.state, out.reason], ['skipped', 'changes']); assert.match(out.detail, /local changes: nothing was pulled \(they are kept\)/);
  assert.ok(!dirty.calls.some(c => /^(fetch|merge)/.test(c)));
  const offline = fake({ ...ON_MAIN, fetch: { ok: false, err: 'fatal: unable to access \'https://github.com/teamcsharp/gBox.git/\': Could not resolve host: github.com\nmore' } });
  out = await U.pull({ root: 'x', run: offline.run });
  assert.deepEqual([out.state, out.reason], ['skipped', 'fetch']); assert.match(out.detail, /^GitHub did not answer \(fatal: unable to access .*Could not resolve host: github\.com\): nothing was pulled$/);
  const diverged = fake({ ...ON_MAIN, 'merge-base --is-ancestor': { ok: false, err: '' } });
  out = await U.pull({ root: 'x', run: diverged.run });
  assert.deepEqual([out.state, out.reason], ['skipped', 'diverged']); assert.ok(!diverged.calls.some(c => c.startsWith('merge ')));
  const current = fake({ ...ON_MAIN, 'rev-parse --verify FETCH_HEAD': { ok: true, out: 'a'.repeat(40) } });
  out = await U.pull({ root: 'x', run: current.run });
  assert.deepEqual([out.state, out.detail], ['current', 'Up to date with GitHub main (aaaaaaa)']);
  assert.ok(current.calls.includes('fetch --quiet --no-tags origin main'));
});

test('client files are pulled at once; gBox\'s own code only while this PC is idle; packages are flagged', async () => {
  let asked = 0;
  const client = fake(ON_MAIN);
  let out = await U.pull({ root: 'x', run: client.run, busy: async () => { asked++; return 'A game runs.'; } });
  assert.equal(out.state, 'updated'); assert.equal(out.runtime, false); assert.equal(out.packages, false); assert.equal(asked, 0);
  assert.equal(out.detail, 'Pulled 3 new commits from GitHub main (aaaaaaa → bbbbbbb)');
  assert.ok(client.calls.includes(`merge --ff-only --quiet ${'b'.repeat(40)}`));
  const worker = { ...ON_MAIN, 'diff --name-only': { ok: true, out: 'gbox/server.py\nclients/desktop/index.html' } };
  const busy = fake(worker);
  out = await U.pull({ root: 'x', run: busy.run, busy: async () => 'A native game or pending game-window operation still belongs to this desktop.' });
  assert.deepEqual([out.state, out.reason, out.commits], ['waiting', 'busy', 3]);
  assert.match(out.detail, /^3 new commits change gBox's own code and this PC is busy \(A native game .*\): nothing was pulled yet; press F5 again when no local game or task runs$/);
  assert.ok(!busy.calls.some(c => c.startsWith('merge ')), 'nothing merged while busy');
  const idle = fake(worker);
  out = await U.pull({ root: 'x', run: idle.run, busy: async () => null });
  assert.deepEqual([out.state, out.runtime], ['updated', true]);
  const own = fake({ ...ON_MAIN, 'diff --name-only': { ok: true, out: 'clients/desktop/compact-window.cjs' } });
  out = await U.pull({ root: 'x', run: own.run, runtimeFiles: ['clients/desktop/compact-window.cjs'], busy: async () => null });
  assert.equal(out.runtime, true, 'the desktop main process\'s own modules count as gBox\'s code');
  const pkgs = fake({ ...ON_MAIN, 'diff --name-only': { ok: true, out: 'clients/desktop/package.json' } });
  assert.equal((await U.pull({ root: 'x', run: pkgs.run })).packages, true);
  const locked = fake({ ...ON_MAIN, 'merge ': { ok: false, err: 'error: unable to unlink old \'system/gBox.exe\': Permission denied' } });
  out = await U.pull({ root: 'x', run: locked.run });
  assert.deepEqual([out.state, out.reason], ['failed', 'merge']); assert.match(out.detail, /did not apply \(error: unable to unlink/);
});

function sh(cwd, ...args) {
  return execFileSync('git', ['-C', cwd, '-c', 'user.name=gBox test', '-c', 'user.email=test@example.invalid',
    '-c', 'commit.gpgsign=false', '-c', 'core.autocrlf=false', ...args], { encoding: 'utf8', windowsHide: true }).trim();
}
const put = (dir, file, text) => { fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true }); fs.writeFileSync(path.join(dir, file), text); };
const get = (dir, file) => fs.readFileSync(path.join(dir, file), 'utf8');

test('a real checkout: main is fast-forwarded, gBox\'s own code waits for an idle PC, local changes and branches are kept', async t => {
  try { execFileSync('git', ['--version'], { windowsHide: true }); } catch { t.skip('git is not installed'); return; }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gbox-app-update-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true, maxRetries: 3 }));
  const up = path.join(dir, 'github'), pc = path.join(dir, 'pc'), root = path.join(pc, 'system');
  execFileSync('git', ['init', '-q', '-b', 'main', up], { windowsHide: true });
  put(up, 'system/clients/desktop/index.html', 'v1'); put(up, 'system/gbox/server.py', 'v1'); put(up, 'gBox.sh', 'root');
  sh(up, 'add', '-A'); sh(up, 'commit', '-q', '-m', 'one');
  execFileSync('git', ['-c', 'core.autocrlf=false', 'clone', '-q', up, pc], { windowsHide: true });
  sh(pc, 'config', 'core.autocrlf', 'false');
  const git = U.git({ timeoutMs: 20000 });
  put(up, 'system/clients/desktop/index.html', 'v2'); sh(up, 'commit', '-q', '-am', 'two');      // the app's page only
  let asked = 0;
  const page = await U.pull({ root, run: git, busy: async () => { asked++; return 'A game runs.'; } });
  assert.deepEqual([page.state, page.commits, page.runtime, asked], ['updated', 1, false, 0]);
  assert.equal(get(root, 'clients/desktop/index.html'), 'v2');
  put(up, 'system/gbox/server.py', 'v2'); sh(up, 'commit', '-q', '-am', 'three');               // the worker's code
  const waiting = await U.pull({ root, run: git, busy: async () => 'A native game still belongs to this desktop.' });
  assert.equal(waiting.state, 'waiting'); assert.equal(get(root, 'gbox/server.py'), 'v1');
  const pulled = await U.pull({ root, run: git, busy: async () => null });
  assert.deepEqual([pulled.state, pulled.runtime], ['updated', true]); assert.equal(get(root, 'gbox/server.py'), 'v2');
  put(up, 'system/clients/desktop/index.html', 'v3'); sh(up, 'commit', '-q', '-am', 'four');
  put(root, 'clients/desktop/index.html', 'mine');                                              // a local edit: kept
  const dirty = await U.pull({ root, run: git });
  assert.deepEqual([dirty.state, dirty.reason], ['skipped', 'changes']); assert.equal(get(root, 'clients/desktop/index.html'), 'mine');
  sh(pc, 'checkout', '-q', '--', 'system/clients/desktop/index.html');
  sh(pc, 'switch', '-q', '-c', 'work');                                                        // another branch: left alone
  const other = await U.pull({ root, run: git });
  assert.deepEqual([other.state, other.branch], ['skipped', 'work']); assert.equal(get(root, 'clients/desktop/index.html'), 'v2');
  assert.equal(sh(pc, 'rev-parse', '--abbrev-ref', 'HEAD'), 'work');
});

const main = fs.readFileSync(path.join(__dirname, '../clients/desktop/main.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));     // objects made inside the vm context

const DESKTOP = path.resolve('/gbox/system/clients/desktop');
function updateHandler(over = {}) {
  const src = main.slice(main.indexOf('const APP_CHECKOUT = '), main.indexOf("ipcMain.handle('client:version'"));
  const r = { pulls: [], inspects: 0, logs: [] };
  const ctx = vm.createContext({ path, __dirname: DESKTOP, String, Object,
    require: { cache: { [path.join(DESKTOP, 'main.js')]: 1, [path.join(DESKTOP, 'compact-window.cjs')]: 1, [path.resolve('/elsewhere/x.js')]: 1 } },
    ipcMain: { handle: (name, fn) => { r.name = name; r.handler = fn; } }, assertClientSender: () => {},
    clientHandoffBusy: false, clientReloading: false, clientActivation: { state: 'active' },
    logPush: (src, text) => r.logs.push(text),
    inspectClientIdle: async () => { r.inspects++; return over.busy ?? null; },
    clientVersions: { read: async options => { r.read = options; return over.version || { renderer: 'r', runtime: 'x', remote: 'm', restart: false }; } },
    appUpdate: { pull: async options => { r.pulls.push(options); return over.pull || { state: 'current', detail: 'Up to date with GitHub main (aaaaaaa)' }; } },
    ...over.ctx });
  vm.runInContext(src, ctx);
  r.ctx = ctx;
  return r;
}

test('main.js client:update pulls the app\'s own checkout and says whether gBox itself must (and may) restart', async () => {
  const r = updateHandler();
  assert.equal(r.name, 'client:update');
  let out = await r.handler({});
  assert.equal(r.pulls[0].root, path.resolve(DESKTOP, '..', '..'));
  assert.deepEqual(plain(r.pulls[0].runtimeFiles), ['clients/desktop/main.js', 'clients/desktop/compact-window.cjs']);
  assert.deepEqual(plain(r.read), { freshBackend: true });
  assert.deepEqual([out.state, out.restart, out.busy], ['current', false, null]); assert.equal(r.inspects, 0);
  // runtime code pulled while idle: the relaunch is due (client:reload honours runtimeUpdatePending) and not asked again
  const pulled = updateHandler({ pull: { state: 'updated', runtime: true, detail: 'Pulled 1 new commit' } });
  out = await pulled.handler({});
  assert.deepEqual([out.restart, out.busy], [true, null]); assert.equal(vm.runInContext('runtimeUpdatePending', pulled.ctx), true);
  assert.equal(pulled.inspects, 0, 'the pull itself asked busy() (here a stub): no second inspection');
  // new code already on disk while a local game runs: the restart waits, and the answer says why
  const busy = updateHandler({ version: { restart: true }, busy: 'An owned local game is active.' });
  out = await busy.handler({});
  assert.deepEqual([out.restart, out.busy], [true, 'An owned local game is active.']);
  assert.deepEqual(out.activation, { state: 'active' });
  assert.match(busy.logs[0], /^F5 update: current: Up to date .* \(restart waits: An owned local game is active\.\)$/);
  // a refresh already running refuses a second one
  const running = updateHandler({ ctx: { clientReloading: true } });
  await assert.rejects(running.handler({}), /already in progress/);
  // the pull's busy() is this desktop's own idle check
  const probe = updateHandler({ busy: 'A task runs.' }); await probe.handler({});
  assert.equal(await probe.pulls[0].busy(), 'A task runs.');
});

test('client:reload relaunches for an F5 pull of runtime code even when the client identity did not change', async () => {
  const src = main.slice(main.indexOf('function assertClientSender('), main.indexOf('let clientVersions ='));
  let handler, performed = 0; const wc = { mainFrame: {}, reloadIgnoringCache: () => {} };
  const ctx = vm.createContext({ ipcMain: { handle: (_n, fn) => { handler = fn; } }, win: { webContents: wc }, clientReloading: false,
    runtimeUpdatePending: true, clientVersions: { read: async () => ({ restart: false }) }, clientActivation: {},
    clientHandoff: { perform: async () => { performed++; return { state: 'pending', reason: 'An owned local game is active.' }; } },
    inspectClientIdle: async () => null, worker: null, process: { pid: 1 }, mini: null, settings: () => ({}) });
  vm.runInContext(src, ctx);
  const out = await handler({ sender: wc, senderFrame: wc.mainFrame }, { v: 1, sid: 'w1-s1', compact: true });
  assert.equal(performed, 1); assert.equal(out.state, 'pending');
  assert.match(main, /const appUpdate = require\('\.\/app-update\.cjs'\);/);
});
