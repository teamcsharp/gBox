const {test} = require('node:test');
const assert = require('node:assert/strict');
const {read} = require('../clients/desktop/stream-health.cjs');
test('remote picture health goes directly to its authority even with a local library', async () => {
  const calls=[];
  const data=await read('http://spark:8765/api/sessions/worker-run/mjpeg?token=DO_NOT_USE&fps=30', {
    origins:['http://127.0.0.1:18765','http://spark:8765'],
    token: async origin => {calls.push(origin);return 'remote-credential';},
    fetch: async (url,options) => {
      assert.equal(url,'http://spark:8765/api/sessions/worker-run/stream/health');
      assert.equal(options.headers.authorization,'Bearer remote-credential');
      assert.equal(options.redirect,'error');
      return {ok:true,json:async()=>({session_id:'worker-run',age_s:0.05})};
    }
  });
  assert.equal(data.age_s,0.05); assert.deepEqual(calls,['http://spark:8765']);
});
test('unpaired origins and malformed session paths receive no credential',async()=>{
  for(const src of ['http://evil/api/sessions/w-s/mjpeg','http://spark:8765/api/sessions/w%2Fs/mjpeg',
    'http://name@ spark:8765/api/sessions/w-s/mjpeg','http://spark:8765/api/tasks'])
    await assert.rejects(read(src,{origins:['http://spark:8765'],token:()=>assert.fail('credential leaked')}));
});
test('wrong-session replies and failed source requests stay failures',async()=>{
  for(const result of [{ok:false,status:503},{ok:true,json:async()=>({session_id:'other'})}])
    await assert.rejects(read('http://spark:8765/api/sessions/w-s/mjpeg',{
      origins:['http://spark:8765'],token:async()=> 'secret',fetch:async()=>result}));
});
