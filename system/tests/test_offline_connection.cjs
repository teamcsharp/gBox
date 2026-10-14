const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createConnection } = require('../clients/desktop/offline-connection');

test('healthy Spark keeps remote mode without starting a local server', async () => {
  const connect = createConnection({ configured: () => ({ apiUrl: 'spark' }),
    probe: async url => { assert.equal(url, 'spark'); return true; },
    startLocal: () => { throw Error('must not start'); } });
  assert.deepEqual(await connect(), { mode: 'remote' });
});

test('concurrent startup uses one fallback and remains local after Spark recovers', async () => {
  let starts = 0, probes = 0, healthy = false;
  const connect = createConnection({ configured: () => ({ apiUrl: 'spark' }),
    probe: async () => { probes++; return healthy; },
    startLocal: async () => { starts++; return { apiUrl: 'localhost', token: 'local' }; } });
  const answers = await Promise.all([connect(), connect(), connect()]);
  assert.ok(answers.every(x => x.mode === 'local' && x.token === 'local'));
  healthy = true;
  assert.equal((await connect()).mode, 'local');
  assert.equal(starts, 1);
  assert.equal(probes, 1);
});

test('failed local startup can be retried', async () => {
  let starts = 0;
  const connect = createConnection({ configured: () => ({}), probe: async () => false,
    startLocal: async () => { if (++starts === 1) throw Error('missing runtime'); return {}; } });
  await assert.rejects(connect(), /missing runtime/);
  assert.equal((await connect()).mode, 'local');
  assert.equal(starts, 2);
});

test('standalone installs retain their existing startup path', async () => {
  const connect = createConnection({ standalone: true, configured: () => ({}),
    probe: () => { throw Error('must not probe'); }, startLocal: () => { throw Error('must not start'); } });
  assert.equal((await connect()).mode, 'remote');
});
