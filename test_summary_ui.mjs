import test from 'node:test';
import assert from 'node:assert/strict';
import {SummaryUI} from './static/summary-ui.js';
function harness(){
  const elements=new Map();
  const element=()=>({children:[],files:[],scrollHeight:0,scrollTop:0,clientHeight:100,
    append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},
    events:{},addEventListener(type,callback){this.events[type]=callback;},
    showModal(){this.open=true;},close(){this.open=false;this.events.close?.();}});
  globalThis.document={getElementById:id=>{if(!elements.has(id))elements.set(id,Object.assign(element(),{value:id.startsWith('summaryPeriod')?'5':'',checked:true}));return elements.get(id);},createElement:element};
  document.getElementById('topicSelect').value='indoor';document.getElementById('targetLanguage').value='zh';
  const requests=[];globalThis.fetch=(url,options)=>new Promise(resolve=>requests.push({body:JSON.parse(options.body),resolve}));
  const items=[{id:'a',start:0,end:45,source:'原文',translation:'译文',version:1,final:true}];
  const ui=new SummaryUI({store:()=>({ordered:()=>items,items:new Map(items.map(i=>[i.id,i]))})});ui.render=()=>{};
  const respond=(index,ok=true)=>requests[index].resolve({ok,json:async()=>ok?{title:'测试',discussion:['讨论'],conclusions:[],uncertainties:[],reference_notes:[],source_ids:['a'],correction_ids:[]}:{detail:'模拟失败'}});
  return {ui,items,requests,respond,elements};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('summary scheduler does not duplicate an in-flight minute request',async()=>{
  const {ui,requests,respond}=harness();ui.tick(60);ui.tick(61);ui.tick(62);
  assert.equal(requests.length,1);respond(0);await settle();assert.equal(requests.length,1);
  assert.equal(ui.blocks.get('0').end,60);
});
test('late transcript version discards obsolete summary then regenerates',async()=>{
  const {ui,items,requests,respond}=harness();ui.tick(60);items[0].version++;respond(0);await settle();
  assert.equal(requests.length,2);assert.equal(ui.blocks.get('0').result,undefined);
  respond(1);await settle();assert.equal(ui.blocks.get('0').result.title,'测试');
});
test('reset rejects old meeting response and final tail is still summarized',async()=>{
  const {ui,requests,respond}=harness();ui.tick(60);ui.reset();respond(0);await settle();assert.equal(ui.blocks.size,0);
  ui.tick(46,false,true);assert.equal(requests.length,2);respond(1);await settle();
  assert.equal(ui.blocks.get('0').end,46);assert.equal(ui.blocks.get('0').final,true);
});
test('summary failures do not loop or discard transcripts, retry is explicit',async()=>{
  const {ui,items,requests,respond}=harness();ui.tick(60);respond(0,false);await settle();ui.tick(120);
  assert.equal(requests.length,1);assert.equal(items[0].source,'原文');assert.equal(ui.busy,false);
  ui.tick(120,true);assert.equal(requests.length,2);respond(1);await settle();
});
test('annotation entry opens even while a background summary is updating',async()=>{
  const {ui,requests,respond,elements}=harness();ui.tick(60);respond(0);await settle();
  ui.tick(120);assert.equal(ui.busy,true);SummaryUI.prototype.render.call(ui);
  const button=elements.get('summaryList').children[0].children.find(n=>n.textContent==='注解 / 文件纠正这段总结');
  assert.notEqual(button.disabled,true);button.onclick();assert.equal(elements.get('summaryDialog').open,true);
  elements.get('summaryNote').value='定位误差，不是速度';
  ui.tick(180);assert.equal(requests.length,2);
  respond(1);await settle();assert.equal(requests.length,2);
  assert.equal(elements.get('summaryNote').value,'定位误差，不是速度');
  elements.get('summaryDialog').close();assert.equal(requests.length,3);
  respond(2);await settle();
});
test('submit waits for current generation and applies annotation once, without changing source',async()=>{
  const {ui,items,requests,respond,elements}=harness();ui.tick(60);respond(0);await settle();
  ui.tick(120);ui.open('0');elements.get('summaryNote').value='这是定位误差';
  const correction=ui.correct();await ui.correct();assert.equal(requests.length,2);
  assert.match(elements.get('summaryCorrectionStatus').textContent,/等待/);
  respond(1);await settle();assert.equal(requests.length,3);assert.equal(requests[2].body.reference,'这是定位误差');
  respond(2);await correction;
  assert.equal(ui.blocks.get('0').history.length,1);assert.equal(ui.busy,false);
  assert.equal(items[0].source,'原文');assert.match(elements.get('summaryCorrectionStatus').textContent,/总结已修订/);
});
