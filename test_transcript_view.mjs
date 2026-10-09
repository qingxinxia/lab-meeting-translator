import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {nearTranscriptBottom,orderTranscriptRows} from './static/transcript-view.js';

test('speaker feature is absent from UI, transport, export and state',()=>{
  for(const file of ['index.html','meeting-ui.js','transcript-store.js','transcript-view.js']){
    const text=readFileSync(new URL('./static/'+file,import.meta.url),'utf8');
    assert.doesNotMatch(text,/speaker|音色|声纹|发言者|diariz/i,file);
  }
});
test('ordering does not re-append unchanged rows or disrupt their identity',()=>{
  const a={},b={},c={};const list={children:[a,b],changes:0,insertBefore(row,before){this.changes++;this.children=this.children.filter(x=>x!==row);this.children.splice(before?this.children.indexOf(before):this.children.length,0,row);}};
  orderTranscriptRows(list,[a,b]);assert.equal(list.changes,0);
  orderTranscriptRows(list,[a,c,b]);assert.deepEqual(list.children,[a,c,b]);assert.equal(list.changes,1);
});
test('follow is measured before a longer translation expands the list',()=>{
  const list={scrollHeight:500,clientHeight:400,scrollTop:100};
  const follow=nearTranscriptBottom(list);list.scrollHeight=900;
  assert.equal(follow,true);assert.equal(nearTranscriptBottom(list),false);
  if(follow)list.scrollTop=list.scrollHeight;
  assert.equal(list.scrollTop,900);
});
test('conversation markup no longer contains a duplicate large caption or toggle',()=>{
  const html=readFileSync(new URL('./static/index.html',import.meta.url),'utf8');
  const code=readFileSync(new URL('./static/meeting-ui.js',import.meta.url),'utf8');
  for(const id of ['captionWrap','mainCaption','sourceCaption','captionBtn']){assert.ok(!html.includes(`id="${id}"`));assert.ok(!code.includes(`$('${id}')`));}
  assert.ok(html.includes('id="followTranscript"'));
  assert.match(code,/body\.append\(meta,original,translated,error,audit/);
  assert.doesNotMatch(code,/sourceLabel|translationLabel|等待原文…|正在识别…/);
});
