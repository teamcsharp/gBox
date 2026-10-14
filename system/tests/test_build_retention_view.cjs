const {test}=require('node:test');
const assert=require('node:assert/strict');
const {retentionHTML}=require('../clients/web/viz/builds.js');
test('per game slider defaults to three and exposes limits one through ten',()=>{
 const st={game:'a',retention:{default:3,games:{}},data:{items:[{game_id:'a',game_title:'Soul Calibur II'}]}};
 const html=retentionHTML(st,'JAYBUILTFINALE');
 assert.match(html,/min="1" max="10" step="1" value="3"/);
 assert.match(html,/Soul Calibur II/);assert.match(html,/Apply limit and clean up/);
 st.retention.games.a=10;assert.match(retentionHTML(st,'JAYBUILTFINALE'),/value="10"/);
 st.game='b';assert.match(retentionHTML(st,'JAYBUILTFINALE'),/value="3"/);
});
test('unknown machine cannot present an actionable deletion control',()=>{
 assert.equal(retentionHTML({},'auto'),'');
 assert.doesNotMatch(retentionHTML({},'PC'),/type="range"/);
});
