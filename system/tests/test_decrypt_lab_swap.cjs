const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {request} = require('../clients/desktop/decrypt-lab-swap.js');

const fields = {title:'re5_switch', arc_path:'target.arc', entry:'same', donor_arc:'donor.arc', donor_entry:'same'};

test('unique-name requests omit blank indices and default the build', () => {
  assert.deepEqual(request({...fields, entry_index:' ', donor_index:''}), {...fields, build:'gbox-lab'});
});

test('both explicit indices survive, including the first archive entry', () => {
  assert.deepEqual(request({...fields, entry_index:'0', donor_index:' 17 ', build:' native '}),
    {...fields, entry_index:0, donor_index:17, build:'native'});
});

test('invalid explicit indices and missing names fail before the request', () => {
  for (const key of ['entry_index', 'donor_index']) {
    for (const value of ['-1', '1.5', 'NaN', '0x10', '1e2', '9007199254740992']) {
      assert.throws(() => request({...fields, [key]:value}), /index must be a nonnegative whole number/);
    }
  }
  assert.throws(() => request({...fields, entry:' '}), /give the title/);
});

test('the desktop form loads its request helper and forwards both index controls', () => {
  const root = path.join(__dirname, '../clients/desktop');
  const html = fs.readFileSync(path.join(root, 'decrypt-lab.html'), 'utf8');
  const js = fs.readFileSync(path.join(root, 'decrypt-lab.js'), 'utf8');
  assert.ok(html.indexOf('src="decrypt-lab-swap.js"') < html.indexOf('src="decrypt-lab.js"'));
  for (const id of ['swap-entry-index', 'swap-donor-index']) {
    assert.match(html, new RegExp(`id="${id}"[^>]+min="0"`));
    assert.ok(js.includes(`$('${id}').value`));
  }
  assert.match(js, /window\.GBoxArchiveSwap\.request\(/);
});
