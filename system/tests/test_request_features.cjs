const test = require('node:test');
const assert = require('node:assert/strict');
const {card} = require('../clients/desktop/request-features.js');

test('delivery cards expose all operator fields and escape stored content', () => {
  const html = card({id:'test', number:42, title:'<script>bad</script>', automated:true,
    delivery:{added:['FPS display'], accomplished:['Launch control'], where:['Sessions'],
      test_steps:['Restart'], mods:['<img src=x onerror=bad>'], verification:'Unit tests'},
    documented:true, linked_mods:[{id:'mod', title:'Mod', game_title:'PSO', verified:false}], files_changed:[]});
  for (const label of ['What was added','What was accomplished','Where to find','What to test','New mods','Verification:','Backend subtask','data-feature-mod','data-feature-report']) assert.ok(html.includes(label));
  assert.ok(!html.includes('<script>') && !html.includes('<img'));
  assert.ok(html.includes('&lt;script&gt;') && html.includes('Not verified'));
});
test('legacy completion never invents testing instructions', () => {
  const html = card({id:'old', title:'Old work', delivery:{}, linked_mods:[], completion_note:'Original reply'});
  assert.ok(html.includes('Legacy completion') && html.includes('No reproducible test steps were recorded'));
  assert.ok(html.includes('Original reply'));
});
