const $=id=>document.getElementById(id);
async function post(path,body){
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'请求内容无效');return result;
}
export class EvidenceUI {
  constructor(adapter){
    this.adapter=adapter;this.epoch=0;
    $('evidenceBtn').onclick=()=>this.open();$('closeEvidence').onclick=()=>$('evidenceDialog').close();
    $('reviewEvidence').onclick=()=>this.review();
    $('clearEvidence').onclick=()=>{this.reset();adapter.onContext('');this.status('已清除当前参考；已产生的修订可在对应段落撤销。');};
  }
  status(text){$('evidenceStatus').textContent=text;}
  reset(){this.epoch++;$('evidenceText').value='';$('evidenceResults').replaceChildren();this.status('');}
  connected(){const text=$('evidenceText').value.trim();if(text)this.adapter.onContext(`参考类型：${$('evidenceKind').value}\n${text}`);}
  open(id){
    const select=$('evidenceSegment'),end=$('evidenceEnd');select.replaceChildren();end.replaceChildren();
    const single=document.createElement('option');single.value='';single.textContent='只核对选中段 / 最近 6 段';end.append(single);
    const recent=document.createElement('option');recent.value='';recent.textContent='最近 6 段（自动寻找相关内容）';select.append(recent);
    for(const item of this.adapter.store().ordered().filter(i=>i.final)){
      const option=document.createElement('option');option.value=item.id;option.textContent=`${item.at.toLocaleTimeString()} · ${item.source.slice(0,75)||'空识别段'}`;select.append(option);end.append(option.cloneNode(true));
    }
    select.value=id||'';$('evidenceKind').value='note';$('evidenceText').value='';$('evidenceResults').replaceChildren();this.status('输入你听懂的大意即可，不需要还原日语原句。');$('evidenceDialog').showModal();
  }
  async review(){
    const epoch=this.epoch, text=$('evidenceText').value.trim(),kind=$('evidenceKind').value,id=$('evidenceSegment').value;
    if(!text){this.status('请输入你听懂的内容或先读取照片。');return;}
    if(kind==='exact_quote'&&!id){this.status('“确认原话”需要明确选择一段；中文大意请选择“补充说明”。');return;}
    const store=this.adapter.store(),all=store.ordered().filter(i=>i.final),endId=$('evidenceEnd').value;
    let items=all.filter(i=>!id||i.id===id).slice(-6);
    if(endId){
      const from=all.findIndex(i=>i.id===id),to=all.findIndex(i=>i.id===endId);
      if(from<0||to<from||to-from>=6){this.status('请选择从起始到结束的连续 1–6 段');return;}
      items=all.slice(from,to+1);
    }
    if(kind==='exact_quote'&&items.length!==1){this.status('确认原话只可针对一段；多句请用大意模式');return;}
    // Explicitly retained for future translation only, never used as an invented ASR result.
    this.adapter.onContext(`参考类型：${kind}\n${text}`);
    if(!items.length){this.status('参考已保留，将用于本场后续翻译；还没有可回溯核对的原文。');return;}
    $('reviewEvidence').disabled=true;this.status('正在对照原文和依据；录音继续…');$('evidenceResults').replaceChildren();
    try{
      const result=await post('/api/evidence/review',{topic:$('topicSelect').value,target:$('targetLanguage').value,
        evidence:{kind,text},segments:items.map(i=>({item_id:i.id,source:i.source,translation:i.translation,version:i.version}))});
      if(epoch!==this.epoch||store!==this.adapter.store())return;
      let applied=0,stale=0;
      for(const change of result.changes){
        const box=document.createElement('article');box.className='evidence-change';
        const description=document.createElement('p');description.textContent=`${change.kind==='user_confirmed'?'用户确认原话':'辅助译文修订（待核对）'}：${change.reason}\n建议译文：${change.translation}`;box.append(description);
        const apply=()=>{if(!store.revise(change)){stale++;return false;}this.adapter.render(store.items.get(change.item_id));applied++;return true;};
        if($('autoRevision').checked){if(!apply())description.append('（该段在分析期间已更新，请重新核对）');}
        else{const button=document.createElement('button');button.className='ghost-btn';button.textContent='应用这条修订';button.onclick=()=>{button.disabled=true;button.textContent=apply()?'已应用，可在段落撤销':'段落已更新，请重新核对';};box.append(button);}
        $('evidenceResults').append(box);
      }
      this.status(`${result.summary}\n${applied?`已应用 ${applied} 条，原始记录及依据保留。`:result.changes.length?'建议已列出，等待应用。':'没有足够依据可安全自动修改。'}${stale?` ${stale} 条因版本已变化而跳过。`:''}`);
    }catch(error){this.status(error.message);}finally{$('reviewEvidence').disabled=false;}
  }
}
