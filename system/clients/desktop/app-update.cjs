'use strict';
/* F5's "update the gBox app" (operator 2026-10-26: "I just want to press F5 reconnect it to the source and reboot the
   stream and build and update the gbox app"): this PC's gBox checkout is fast-forwarded to GitHub's main.

   Only a checkout on main with no local changes is touched, and only by a fast-forward (git merge --ff-only): nothing is
   ever discarded, stashed, reset or switched. A copy on another branch, with local changes, with commits GitHub does not
   have, or that is not a git checkout at all (a share copy: the Spark's deploy keeps it current) is left as it is, and
   the answer says why. Code the running gBox itself loads (the worker's Python, the desktop main process) is pulled only
   while this PC is idle (busy(): main.js inspectClientIdle): the guarded relaunch that loads it (client:reload) can only
   run then, and a busy worker would otherwise import new files next to its old modules. Packages (pip / npm) are left to
   Rebuild & relaunch (gbox/node_rebuild.py): the answer flags them. */
const { execFile } = require('node:child_process');

// files (relative to the app's system folder) that the running worker or main process loads: their change needs gBox
// relaunched. deploy_main.sh restarts gbox.service for the same set on the Spark.
const RUNTIME = [/^gbox\//, /^adapters\//, /^profiles\//, /^gbox\.toml$/, /^pyproject\.toml$/];
// ... and those that need packages installed (pip: the bootstrap's list and pyproject; npm: the Electron runtime)
const PACKAGES = [/^pyproject\.toml$/, /^scripts\/bootstrap-windows\.ps1$/, /^clients\/desktop\/package\.json$/];

// git as this app runs it: never a prompt (no terminal, no credential window), bounded by a timeout
function git({ timeoutMs = 15000, env = process.env } = {}) {
  return (cwd, args, ms = timeoutMs) => new Promise(resolve => execFile('git', ['-C', cwd, ...args], {
    windowsHide: true, timeout: ms, maxBuffer: 8 << 20,
    env: { ...env, GIT_TERMINAL_PROMPT: '0', GCM_INTERACTIVE: 'never' },
  }, (error, stdout, stderr) => resolve({ ok: !error, out: String(stdout || '').trim(),
    err: String(stderr || '').trim() || (error ? String(error.message || error) : '') })));
}

const short = sha => String(sha || '').slice(0, 7);
const first = text => String(text || '').split(/\r?\n/).map(s => s.trim()).find(Boolean) || 'no answer';
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

// {state: updated | current | skipped | waiting | failed, detail, ...}. root: the app's system folder (it may be a
// subfolder of the repository); run: git(); busy(): why this PC may not relaunch now, or null when it is idle;
// runtimeFiles: the desktop main process's own modules, relative to root.
async function pull({ root, run = git(), busy = async () => null, runtimeFiles = [], branch = 'main', remote = 'origin',
                      fetchMs = 15000, mergeMs = 60000 }) {
  const top = await run(root, ['rev-parse', '--show-toplevel']);
  if (!top.ok) return { state: 'skipped', reason: 'not-git',
    detail: `This PC's gBox is not a git checkout (${root}): nothing to pull here (a copy on the Spark's share follows the Spark's deploy)` };
  const head = await run(root, ['symbolic-ref', '--quiet', '--short', 'HEAD']);
  const on = head.ok ? head.out : '';
  if (on !== branch) return { state: 'skipped', reason: 'branch', branch: on || null,
    detail: `This PC's copy is ${on ? `on branch ${on}` : 'not on a branch'}, not ${branch}: nothing was pulled (switch it to ${branch} to let F5 update it)` };
  const changes = await run(root, ['status', '--porcelain', '--untracked-files=no']);
  if (!changes.ok) return { state: 'failed', reason: 'status', detail: `git could not read this PC's copy (${first(changes.err)}): nothing was pulled` };
  if (changes.out) return { state: 'skipped', reason: 'changes', detail: 'This PC\'s copy has local changes: nothing was pulled (they are kept)' };
  const fetched = await run(root, ['fetch', '--quiet', '--no-tags', remote, branch], fetchMs);
  if (!fetched.ok) return { state: 'skipped', reason: 'fetch', detail: `GitHub did not answer (${first(fetched.err)}): nothing was pulled` };
  const [from, to] = await Promise.all([run(root, ['rev-parse', '--verify', 'HEAD^{commit}']),
    run(root, ['rev-parse', '--verify', 'FETCH_HEAD^{commit}'])]);
  if (!from.ok || !to.ok || !from.out || !to.out) return { state: 'failed', reason: 'rev', detail: `git could not name the commits to compare (${first(from.err || to.err)}): nothing was pulled` };
  if (from.out === to.out) return { state: 'current', from: from.out, to: to.out, detail: `Up to date with GitHub ${branch} (${short(from.out)})` };
  const behind = await run(root, ['merge-base', '--is-ancestor', 'HEAD', to.out]);
  if (!behind.ok) return { state: 'skipped', reason: 'diverged', from: from.out, to: to.out,
    detail: `This PC's ${branch} has commits that GitHub does not: nothing was pulled` };
  const [count, names] = await Promise.all([run(root, ['rev-list', '--count', `HEAD..${to.out}`]),
    run(root, ['diff', '--name-only', '--relative', 'HEAD', to.out])]);
  const commits = Number(count.out) || 0;
  const files = names.ok && names.out ? names.out.split(/\r?\n/).map(s => s.trim()).filter(Boolean) : [];
  const runtime = files.filter(f => RUNTIME.some(r => r.test(f)) || runtimeFiles.includes(f));
  const packages = files.some(f => PACKAGES.some(r => r.test(f)));
  if (runtime.length || !names.ok) {
    const why = await busy();
    if (why) return { state: 'waiting', reason: 'busy', busy: why, commits, from: from.out, to: to.out,
      detail: `${plural(commits, 'new commit')} change gBox's own code and this PC is busy (${why}): nothing was pulled yet; press F5 again when no local game or task runs` };
  }
  const merged = await run(root, ['merge', '--ff-only', '--quiet', to.out], mergeMs);
  if (!merged.ok) return { state: 'failed', reason: 'merge', from: from.out, to: to.out,
    detail: `The fast-forward to ${short(to.out)} did not apply (${first(merged.err)}); check this PC's copy with git status` };
  return { state: 'updated', from: from.out, to: to.out, commits, files: files.length, runtime: runtime.length > 0 || !names.ok, packages,
    detail: `Pulled ${plural(commits, 'new commit')} from GitHub ${branch} (${short(from.out)} → ${short(to.out)})` };
}

module.exports = { pull, git, RUNTIME, PACKAGES };
