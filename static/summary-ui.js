import {summaryWindows,snapshotSegments,timeLabel} from './summary-state.js?v=20261009-streaming';
const $=id=>document.getElementById(id);
async function post(path,body){
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'请求内容无效');return result;
}
function node(tag,text,className){const el=document.createElement(tag);el.textContent=text;if(className)el.className=className;return el;}
export class SummaryUI {
  constructor(adapter){
    this.adapter=adapter;this.epoch=0;this.blocks=new Map();this.busy=false;this.elapsed=0;this.ended=false;this.editing=false;this.correcting=false;this.pendingGeneration=null;
    $('summaryNow').onclick=()=>this.tick(this.elapsed,true);
    $('summaryPeriod').onchange=()=>{$('summaryPeriodJoin').value=$('summaryPeriod').value;if(!this.blocks.size)this.minutes=Number($('summaryPeriod').value);};
    $('summaryPeriodJoin').onchange=()=>{$('summaryPeriod').value=$('summaryPeriodJoin').value;};
    $('closeSummary').onclick=()=>$('summaryDialog').close();
    $('summaryDialog').addEventListener('close',()=>{this.editing=false;this.tick(this.elapsed);});
    $('correctSummary').onclick=()=>this.correct();
    $('summaryFile').onchange=()=>{$('summaryFileConsent').checked=false;};
    this.minutes=5;
  }
  reset(){
    this.epoch++;this.blocks.clear();this.busy=false;this.elapsed=0;this.ended=false;this.selected=null;this.editing=false;this.correcting=false;this.pendingGeneration=null;
    this.minutes=Number($('summaryPeriod').value);$('summaryPeriod').disabled=true;
    $('summaryList').replaceChildren(node('p','每分钟更新草稿，每个周期形成一段总结。','small'));
    $('summaryNote').value='';$('summaryFile').value='';$('summaryFileConsent').checked=false;
    $('summaryDialog').close();$('correctSummary').disabled=false;$('summaryStatus').textContent='等待第一分钟的发言';
  }
  tick(elapsed,force=false,ended=false){
    this.elapsed=Math.max(this.elapsed,elapsed||0);this.ended=this.ended||ended;
    if(this.busy||this.editing)return;
    const windows=summaryWindows(this.adapter.store().ordered(),this.elapsed,this.minutes,this.ended||force);
    const pending=windows.find(w=>{const b=this.blocks.get(w.key);return !b||((b.signature!==w.signature||b.end!==w.end||b.final!==w.final)&&!b.error);});
    if(pending){this.pendingGeneration=this.generate(pending);return;}
    if(force){const failed=[...this.blocks.values()].find(b=>b.error);if(failed){failed.error='';this.tick(this.elapsed);}}
    if(!windows.length&&force)$('summaryStatus').textContent='还没有已确认的原文，暂不能总结';
  }
  payload(w,reference=''){return {topic:$('topicSelect').value,target:$('targetLanguage').value,start:w.start,end:w.end,segments:snapshotSegments(w.segments),reference};}
  async generate(w){
    const epoch=this.epoch,old=this.blocks.get(w.key);this.busy=true;
    const block=old||{key:w.key,history:[],reference:'',version:0};
    Object.assign(block,{start:w.start,end:w.end,final:w.final,segments:w.segments,signature:w.signature,error:'',loading:true});
    this.blocks.set(w.key,block);this.render();$('summaryStatus').textContent='后台整理中 · 录音与翻译继续';
    try{
      const result=await post('/api/summaries',this.payload(w,block.reference));
      if(epoch!==this.epoch)return;
      // Do not apply responses based on older transcript versions.
      if(w.signature!==JSON.stringify(w.segments.map(i=>[i.id,i.version]))){block.signature='';return;}
      block.result=result;block.version++;block.snapshot=snapshotSegments(w.segments);
      $('summaryStatus').textContent='已更新 · 总结不能替代原文核对';
    }catch(error){if(epoch===this.epoch){block.error=error.message;$('summaryStatus').textContent='总结失败，点击重试；录音继续';}}
    finally{if(epoch===this.epoch){block.loading=false;this.busy=false;this.render();this.tick(this.elapsed);}}
  }
  render(){
    const list=$('summaryList'),follow=$('followSummary').checked&&list.scrollHeight-list.scrollTop-list.clientHeight<90;
    list.replaceChildren();
    for(const b of [...this.blocks.values()].sort((a,b)=>a.start-b.start)){
      const card=node('article','', 'summary-card');card.append(node('div',`${timeLabel(b.start)}–${timeLabel(b.end)} · ${b.final?'分段总结':'草稿'}`,'eyebrow'));
      if(b.result){
        card.append(node('h3',b.result.title));
        for(const [key,label] of [['discussion','讨论内容'],['conclusions','明确结论'],['uncertainties','待确认'],['reference_notes','注解 / 材料补充（非原话）']]){
          if(!b.result[key].length)continue;card.append(node('h4',label));const ul=document.createElement('ul');for(const line of b.result[key])ul.append(node('li',line));card.append(ul);
        }
        const links=node('div','','summary-links');
        for(const id of b.result.source_ids){const item=this.adapter.store().items.get(id);if(!item)continue;const link=node('button',timeLabel(item.start||0),'ghost-btn');link.onclick=()=>this.adapter.locate(id);links.append(link);}
        card.append(links);
        const edit=node('button','注解 / 文件纠正这段总结','ghost-btn');edit.onclick=()=>this.open(b.key);card.append(edit);
        if(b.reference&&b.result.correction_ids.length){const button=node('button','查看相关字幕修订建议','ghost-btn');button.onclick=()=>this.suggestions(b);card.append(button);}
        if(b.history.length){const details=document.createElement('details');details.append(node('summary',`修订历史（${b.history.length}）`));for(const h of b.history)details.append(node('p',`${h.undone?'[已撤销] ':''}${h.at} · ${h.reference}\n修订前：${JSON.stringify(h.before)}`,'small'));
          const undo=node('button','撤销最近总结修订','ghost-btn');undo.disabled=this.busy||!b.history.some(h=>!h.undone);undo.onclick=()=>{const h=[...b.history].reverse().find(h=>!h.undone);if(!h)return;h.undone=true;b.result=h.before;b.reference=h.beforeReference||'';b.version++;this.render();};details.append(undo);card.append(details);}
      }
      if(b.loading)card.append(node('p','正在后台整理…','small'));
      if(b.error){card.append(node('p',b.error,'diagnostic error'));const retry=node('button','重试总结','ghost-btn');retry.onclick=()=>{b.error='';b.signature='';this.tick(this.elapsed,true);};card.append(retry);}
      list.append(card);
    }
    if(follow)list.scrollTop=list.scrollHeight;
  }
  open(key){
    if(!this.blocks.get(key)?.result){$('summaryStatus').textContent='这一段总结尚未完成，请生成后再注解';return;}
    this.editing=true;
    this.selected=key;$('summaryRange').textContent=`${timeLabel(this.blocks.get(key).start)}–${timeLabel(this.blocks.get(key).end)}`;
    $('summaryNote').value=this.blocks.get(key).reference;$('summaryFile').value='';$('summaryFileConsent').checked=false;
    $('summaryCorrectionStatus').textContent='只修订右侧总结，左侧字幕需单独查看建议后确认。编辑期间暂停自动总结，录音和实时翻译继续。';$('summarySuggestions').replaceChildren();$('summaryDialog').showModal();
  }
  async correct(){
    if(this.correcting)return;
    const requestEpoch=this.epoch,selected=this.selected;
    if(this.busy&&this.pendingGeneration){
      this.correcting=true;$('correctSummary').disabled=true;$('summaryCorrectionStatus').textContent='正在等待当前后台总结完成，随后自动核对你的注解…';
      await this.pendingGeneration;
      if(requestEpoch!==this.epoch)return;
      this.correcting=false;$('correctSummary').disabled=false;
      if(selected!==this.selected||!this.editing)return;
    }
    if(this.busy){$('summaryCorrectionStatus').textContent='另一项修订正在处理，请完成后再提交';return;}
    const b=this.blocks.get(this.selected);if(!b)return;
    const epoch=this.epoch,signature=JSON.stringify(b.segments.map(i=>[i.id,i.version]));
    let reference=$('summaryNote').value.trim();const file=$('summaryFile').files[0];
    if(!reference&&!file){$('summaryCorrectionStatus').textContent='请输入你对这一段的理解，或选择材料';return;}
    if(file&&(!$('summaryFileConsent').checked||file.size>6*1024*1024)){$('summaryCorrectionStatus').textContent='请确认允许发送这份材料，并选择 6 MB 以内文件';return;}
    this.busy=true;this.correcting=true;$('correctSummary').disabled=true;$('summaryCorrectionStatus').textContent='正在核对这一段，实时录音继续…';
    try{
      if(file){
        const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(Error('文件读取失败'));r.readAsDataURL(file);});
        const material=await post('/api/evidence/material',{filename:file.name,data,topic:$('topicSelect').value,consent:true});
        if(epoch!==this.epoch)return;
        reference+=`\n材料 ${file.name}（不是发言原文）：${material.visible_text}\n概述：${material.summary}\n不确定：${material.uncertainty}`;
      }
      if(reference.length>10000)throw Error('注解与材料提取文字超过 10000 字符，请缩短注解或上传较小片段');
      const result=await post('/api/summaries',this.payload(b,reference));
      if(epoch!==this.epoch)return;
      if(signature!==JSON.stringify(b.segments.map(i=>[i.id,i.version])))throw Error('发言在分析期间已更新，请重新核对；本次未覆盖');
      b.history.push({at:new Date().toISOString(),reference,before:b.result,beforeReference:b.reference});b.reference=reference;b.result=result;b.version++;
      b.snapshot=snapshotSegments(b.segments);
      if(this.selected===b.key){$('summaryNote').value=reference;$('summaryFile').value='';$('summaryFileConsent').checked=false;
        $('summaryCorrectionStatus').textContent='总结已修订，左侧字幕未改动。可关闭窗口，点击该总结的字幕建议入口。';}this.render();
    }catch(error){if(epoch===this.epoch)$('summaryCorrectionStatus').textContent=error.message;}
    finally{if(epoch===this.epoch){this.busy=false;this.correcting=false;$('correctSummary').disabled=false;this.render();this.tick(this.elapsed);}}
  }
  async suggestions(b){
    this.open(b.key);const epoch=this.epoch,version=b.version;
    const ids=new Set(b.result.correction_ids),segments=this.adapter.store().ordered().filter(i=>ids.has(i.id));
    $('summaryCorrectionStatus').textContent='生成字幕建议中；不会自动应用';
    try{
      const result=await post('/api/evidence/review',{topic:$('topicSelect').value,target:$('targetLanguage').value,
        evidence:{kind:'note',text:b.reference},segments:snapshotSegments(segments)});
      if(epoch!==this.epoch||version!==b.version||this.selected!==b.key)return;
      $('summaryCorrectionStatus').textContent=result.summary;
      for(const change of result.changes){const box=node('div','','evidence-change');box.append(node('p',`${change.reason}\n建议译文：${change.translation}`));
        const apply=node('button','仅应用这条字幕修订','ghost-btn');apply.onclick=()=>{apply.disabled=true;apply.textContent=this.adapter.apply(change)?'已应用，可在左侧撤销':'字幕已更新，请重新核对';};box.append(apply);$('summarySuggestions').append(box);}
    }catch(error){if(epoch===this.epoch)$('summaryCorrectionStatus').textContent=error.message;}
  }
  export(){return [...this.blocks.values()].sort((a,b)=>a.start-b.start).map(b=>({start:b.start,end:b.end,final:b.final,result:b.result,error:b.error,reference:b.reference,history:b.history}));}
}
