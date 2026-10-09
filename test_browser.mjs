import test from 'node:test';
import assert from 'node:assert/strict';
import {PcmEncoder} from './static/pcm-encoder.js';
import {TranscriptStore} from './static/transcript-store.js';

test('rolling translations replace in place, reject older revisions and lose to final',()=>{
  const store=new TranscriptStore();
  store.apply({type:'source.delta',item_id:'a',delta:'We use'});
  store.apply({type:'translation.preview',item_id:'a',text:'我们',revision:1});
  store.apply({type:'translation.preview',item_id:'a',text:'我们使用',revision:3});
  store.apply({type:'translation.preview',item_id:'a',text:'旧结果',revision:2});
  assert.equal(store.items.get('a').translation,'我们使用');
  assert.equal(store.ordered().length,1);
  store.apply({type:'source.final',item_id:'a',text:'We use Wi-Fi.'});
  store.apply({type:'translation.final',item_id:'a',text:'我们使用 Wi-Fi。'});
  store.apply({type:'translation.preview',item_id:'a',text:'迟到结果',revision:4});
  assert.equal(store.items.get('a').translation,'我们使用 Wi-Fi。');
});

test('empty final discards provisional text instead of retaining phantom translation',()=>{
  const store=new TranscriptStore();
  store.apply({type:'translation.preview',item_id:'quiet',text:'错误猜测',revision:1});
  store.apply({type:'source.final',item_id:'quiet',text:''});
  assert.equal(store.items.get('quiet').translation,'');
});

function encode(input,rate,block) {
  const chunks=[];const encoder=new PcmEncoder(rate,24000,2400,buffer=>chunks.push(Buffer.from(buffer)));
  for(let i=0;i<input.length;i+=block)encoder.push(input.subarray(i,i+block));
  encoder.flush();return Buffer.concat(chunks);
}
for(const rate of [24000,44100,48000])test(`PCM ${rate}: sample count, block independence, flush`,()=>{
  const samples=Float32Array.from({length:rate*3},(_,i)=>Math.sin(i/rate*2*Math.PI*440)*.3);
  const bytes=encode(samples,rate,128);
  assert.equal(bytes.length,24000*3*2);assert.deepEqual(bytes,encode(samples,rate,8192));
});
test('PCM clips and writes little endian',()=>{
  const bytes=encode(new Float32Array([-2,-.5,0,.5,2]),24000,2);
  assert.deepEqual([0,1,2,3,4].map(i=>bytes.readInt16LE(i*2)),[-32768,-16384,0,16384,32767]);
});
test('Transcript keeps item mapping when outputs interleave',()=>{
  const store=new TranscriptStore();
  store.apply({type:'segment.started',item_id:'a',sequence:0});
  store.apply({type:'source.delta',item_id:'a',delta:'測位'});
  store.apply({type:'segment.started',item_id:'b',sequence:1});
  store.apply({type:'source.final',item_id:'b',text:'Wi-Fi'});
  store.apply({type:'translation.final',item_id:'a',text:'定位误差'});
  store.apply({type:'source.final',item_id:'a',text:'測位誤差'});
  store.apply({type:'source.delta',item_id:'a',delta:'late duplicate'});
  assert.equal(store.items.get('a').source,'測位誤差');assert.equal(store.items.get('a').translation,'定位误差');
  assert.equal(store.latest().id,'b');assert.equal(store.items.get('b').translation,'');
});
test('Translation error preserves confirmed original',()=>{
  const store=new TranscriptStore();store.apply({type:'source.final',item_id:'a',text:'日本語'});
  store.apply({type:'segment.error',item_id:'a',module:'translation',message:'retry needed'});
  assert.equal(store.latest().source,'日本語');assert.match(store.latest().error,/retry needed/);
});
test('Evidence revisions preserve raw text, reject stale responses, and undo',()=>{
  const store=new TranscriptStore();const item=store.apply({type:'source.final',item_id:'a',text:'測位誤差'});
  store.apply({type:'translation.final',item_id:'a',text:'速度测量'});
  const change={item_id:'a',version:item.version,source:'測位誤差',translation:'定位误差',kind:'assisted',reason:'术语',evidence:'slide'};
  assert.equal(store.revise({...change,source:'invented source'}),false);
  assert.equal(store.revise(change),true);assert.equal(item.rawTranslation,'速度测量');
  assert.equal(store.revise(change),false);assert.equal(item.translation,'定位误差');
  store.undo('a');assert.equal(item.translation,'速度测量');assert.equal(item.revisions[0].undone,true);
});
test('Late machine translation cannot overwrite user-confirmed revision',()=>{
  const store=new TranscriptStore();const item=store.apply({type:'source.final',item_id:'a',text:'wrong'});
  store.revise({item_id:'a',version:item.version,source:'confirmed',translation:'已确认',kind:'user_confirmed'});
  store.apply({type:'translation.final',item_id:'a',text:'late wrong translation'});
  assert.equal(item.translation,'已确认');assert.equal(item.rawTranslation,'late wrong translation');
  store.undo('a');assert.equal(item.translation,'late wrong translation');assert.equal(item.source,'wrong');
});
