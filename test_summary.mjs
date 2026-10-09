import test from 'node:test';
import assert from 'node:assert/strict';
import {summaryWindows,snapshotSegments} from './static/summary-state.js';
const item=(id,end,version=1)=>({id,end,start:end-15,version,source:'原文',translation:'译文',final:true});
test('minute draft updates within five minute block, then seals',()=>{
  const items=[item('a',50),item('b',110),item('c',299),item('d',310)];
  assert.equal(summaryWindows(items,59).length,0);
  assert.equal(summaryWindows(items,60)[0].segments.length,1);
  assert.equal(summaryWindows(items,120)[0].final,false);
  const windows=summaryWindows(items,360);assert.equal(windows.length,2);
  assert.equal(windows[0].final,true);assert.equal(windows[1].start,300);
});
test('boundary turns appear once and final partial minute is retained',()=>{
  const items=[item('a',60),item('b',61),item('c',83.4)];
  const windows=summaryWindows(items,83.4,1,true);
  assert.deepEqual(windows.map(w=>w.segments.map(i=>i.id)),[['a'],['b','c']]);
  assert.equal(windows[1].end,83.4);assert.ok(windows.every(w=>w.final));
});
test('late translations and revisions change signature, interim text excluded',()=>{
  const a=item('a',20),before=summaryWindows([a],60)[0].signature;a.version++;
  assert.notEqual(summaryWindows([a],60)[0].signature,before);
  assert.equal(summaryWindows([{...a,final:false}],60).length,0);
  const snapshot=snapshotSegments([a]);a.translation='new';assert.equal(snapshot[0].translation,'译文');
});
test('a provisional translation is not treated as settled summary evidence',()=>{
  const a={...item('a',20),translation:'尚未定稿的译文',translationFinal:false,revisions:[]};
  assert.equal(snapshotSegments([a])[0].translation,'');
  a.translationFinal=true;
  assert.equal(snapshotSegments([a])[0].translation,'尚未定稿的译文');
});
