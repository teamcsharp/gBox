const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const profile = require('../clients/desktop/desktop-profile.cjs');

test('recovery selection survives ordinary startup without changing standalone installations', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'gbox-profile-'));
  t.after(() => fs.rmSync(root, {recursive:true, force:true}));
  const fallback = path.join(root, 'gbox-desktop');
  assert.equal(profile.resolve(root), fallback);
  const directory = 'gbox-desktop-recovery-0123456789abcdef';
  fs.mkdirSync(path.join(root, directory));
  const selector = path.join(root, 'gbox-desktop-profile.json');
  fs.writeFileSync(selector, JSON.stringify({v:1, directory}));
  assert.equal(profile.resolve(root), path.join(root, directory));
  assert.equal(profile.resolve(root, 'standalone'), path.join('standalone', '.tools', 'desktop-profile'));
  for (const value of [{v:2,directory}, {v:1,directory:'../elsewhere'}, {v:1,directory:'gbox-desktop-recovery-ffffffffffffffff'}]) {
    fs.writeFileSync(selector, JSON.stringify(value));
    assert.equal(profile.resolve(root), fallback);
  }
  fs.writeFileSync(selector, '{invalid');
  assert.equal(profile.resolve(root), fallback);
});
