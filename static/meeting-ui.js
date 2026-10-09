import {TranscriptStore} from './transcript-store.js?v=20261009-streaming';
import {nearTranscriptBottom,orderTranscriptRows} from './transcript-view.js?v=20261009-text-only';
import './glossary-ui.js?v=20261008-audio';
import {EvidenceUI} from './evidence-ui.js';
import {SummaryUI} from './summary-ui.js?v=20261009-streaming';
import {captureConstraints,InputQuality,preferredInput} from './audio-conditioning.js?v=20261008-audio';
const $ = id => document.getElementById(id);
let store = new TranscriptStore(), rows = new Map();
let socket, stream, context, capture, source, sink, timer, startedAt;
let ending = false, running = false, generation = 0, flushResolve;
let speakingAudio = false, latestStats = {}, lastTranslationAt = 0;
let hiddenItems = new Set();
let transmittedBytes=0;
let inputQuality=new InputQuality();
const evidenceUI=new EvidenceUI({store:()=>store,render,onContext:text=>{
  if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'context',text}));
}});
const summaries=new SummaryUI({store:()=>store,locate:id=>{
  hiddenItems.delete(id);render(store.items.get(id));const row=rows.get(id)?.row;
  row?.scrollIntoView({behavior:'smooth',block:'center'});
  row?.animate([{background:'#7c6df255'},{background:'transparent'}],{duration:1800});
},apply:change=>{if(!store.revise(change))return false;render(store.items.get(change.item_id));return true;}});
$('settingsBtn').onclick=()=>$('settingsDialog').showModal();
$('closeSettings').onclick=()=>$('settingsDialog').close();
const setStatus = (kind,text) => { $('status').className = `status ${kind}`; $('statusText').textContent = text; };
const diagnostic = (text, kind='') => { for(const id of ['diagnostic','mainDiagnostic']) { $(id).textContent=text;$(id).className=`diagnostic ${kind}`; } };
const controls = enabled => ['micBtn','audioBtn','endBtn'].forEach(id => { $(id).disabled = !enabled; $(id).setAttribute('aria-disabled',String(!enabled)); });
const seconds = value => `${Math.floor(value/60).toString().padStart(2,'0')}:${Math.floor(value%60).toString().padStart(2,'0')}`;
function displayError(text) {
  $('errorBox').textContent = text; $('errorBox').classList.add('show');
  diagnostic(text,'error'); setStatus('error','需要检查');
}
function render(item) {
  if (!item || hiddenItems.has(item.id)) return;
  const list=$('transcriptList'),follow=$('followTranscript').checked&&nearTranscriptBottom(list);
  if (!item.source && !item.translation && !item.error) { rows.get(item.id)?.row.remove(); rows.delete(item.id); return; }
  $('emptyState')?.remove();
  let dom = rows.get(item.id);
  if (!dom) {
    const row=document.createElement('article'); row.className='segment'; row.dataset.itemId=item.id;
    const body=document.createElement('div'), meta=document.createElement('div'); body.className='segment-body';meta.className='segment-meta';
    const label=document.createElement('span');
    const time=document.createElement('time'); time.textContent=item.at.toLocaleTimeString(); meta.append(label,time);
    const translated=document.createElement('div'); translated.className='segment-translation';
    const original=document.createElement('div'); original.className='segment-source';
    const edit=document.createElement('button');edit.className='segment-edit';edit.textContent='纠错';edit.setAttribute('aria-label','纠错或补充这段对话');edit.onclick=()=>evidenceUI.open(item.id);meta.append(edit);
    const error=document.createElement('div');error.className='segment-error';
    const audit=document.createElement('details');audit.className='revision-audit';
    body.append(meta,original,translated,error,audit); row.append(body); dom={row,translated,original,label,audit,error}; rows.set(item.id,dom);
  }
  dom.label.textContent=item.recovered?'补听（含前文，可能重复）':item.translationFinal?'':item.error?'需检查':'更新中';
  dom.translated.textContent=item.translation;dom.translated.hidden=!item.translation;
  dom.original.textContent=item.source;dom.original.hidden=!item.source;
  dom.error.textContent=item.error;dom.error.hidden=!item.error;
  dom.audit.replaceChildren();dom.audit.hidden=!item.revisions.length;
  if(item.revisions.length){
    const summary=document.createElement('summary');summary.textContent=item.revisions.some(r=>!r.undone)?'已修订 · 查看原文、依据或撤销':'修订已撤销 · 查看历史';
    const text=document.createElement('div');text.style.whiteSpace='pre-wrap';text.textContent=`最初识别：${item.initialSource??item.rawSource}${item.recovered?`\n补听识别（含前文）：${item.rawSource}`:''}\n最初译文：${item.rawTranslation}\n`+item.revisions.map(r=>`${r.undone?'[已撤销] ':''}${r.kind==='user_confirmed'?'用户确认':'辅助修订，待核对'}：${r.reason}\n依据：${r.evidence}`).join('\n');
    const undo=document.createElement('button');undo.className='ghost-btn';undo.textContent='撤销最近修订';undo.onclick=()=>{store.undo(item.id);render(item);};dom.audit.append(summary,text,undo);
  }
  orderTranscriptRows(list,store.ordered().map(entry=>rows.get(entry.id)?.row).filter(Boolean));
  if(follow)list.scrollTop=list.scrollHeight;
  if(item.final)summaries.tick(latestStats.received_seconds||0);
}
function onEvent(event) {
  if(event.type==='memory.warning'){diagnostic(event.message,'warn');return;}
  if(event.type==='audio.ack') {diagnostic(`尾帧已确认：服务端收到 ${(event.received_bytes/48000).toFixed(2)} 秒，正在整理识别结果`);return;}
  if(event.type==='segment.recovering'){diagnostic('此段原文返回为空，正在带前文补听一次','warn');return;}
  if (event.type==='diagnostics') {
    latestStats=event;
    summaries.tick(event.received_seconds);
    $('pipelineStats').textContent=`采音 ${event.received_seconds.toFixed(1)} 秒 · 已送识别 ${event.sent_seconds.toFixed(1)} 秒 · 提交 ${event.submitted} 段 · 确认 ${event.completed} 段 · 翻译 ${event.translated} 段 · 补听恢复 ${event.recovered||0} 段`;
    if(event.submitted>event.completed+3) diagnostic('原文识别积压，正在等待服务返回','warn');
    return;
  }
  if (event.type==='closed') { finish(); return; }
  if (event.type==='error') { displayError(event.message); finish(false); return; }
  const item=store.apply(event); render(item);
  if(event.type==='source.final') diagnostic(event.text ? (event.recovered?'补听有结果（含前文，可能重复），正在翻译':'原文已确认，正在翻译') : item.error || '此段未识别到发言',item.error?'warn':'');
  if(event.type==='translation.final') {
    lastTranslationAt=Date.now(); diagnostic(`中文翻译已更新 · ${(event.translation_ms/1000).toFixed(1)} 秒`);
    if(speakingAudio && 'speechSynthesis' in window) {
      const utterance=new SpeechSynthesisUtterance(event.text); utterance.lang=$('targetLanguage').value==='zh'?'zh-CN':$('targetLanguage').value;
      window.speechSynthesis.speak(utterance);
    }
  }
  if(event.type==='segment.error') diagnostic(item.error,'error');
}
async function openSocket() {
  const url=new URL('/ws/meeting',location.href); url.protocol=location.protocol==='https:'?'wss:':'ws:'; url.searchParams.set('target',$('targetLanguage').value);
  url.searchParams.set('topic',$('topicSelect').value);
  url.searchParams.set('audio_mode',$('audioMode').value);
  socket=new WebSocket(url); socket.binaryType='arraybuffer';
  await new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>{reject(Error('识别连接超时'));},25000);
    socket.onmessage=({data})=>{
      let event; try { event=JSON.parse(data); } catch { reject(Error('服务返回无效事件')); return; }
      if(event.type==='ready') {clearTimeout(timeout); resolve();}
      else if(event.type==='error' && !running) {clearTimeout(timeout); reject(Error(event.message));}
      else onEvent(event);
    };
    socket.onerror=()=>{clearTimeout(timeout); reject(Error('无法连接本机会议服务'));};
    socket.onclose=()=>{
      clearTimeout(timeout);
      if(!running) reject(Error('会议连接已关闭'));
      else {displayError('连接意外中断；已收到的记录仍可导出'); finish(false);}
    };
  });
}
async function start(fixture=false) {
  if(running) return;
  $('joinBtn').disabled=true; $('sampleBtn').disabled=true; $('errorBox').classList.remove('show');
  const epoch=++generation;
  try {
    if(fixture) $('topicSelect').value='indoor';
    ending=false; setStatus('connecting','正在连接');
    context=new AudioContext(); await context.resume();
    await context.audioWorklet.addModule('/static/audio-capture.js?v=20261008-audio');
    let buffer;
    if(fixture) {
      const response=await fetch('/api/debug-fixture'); if(!response.ok)throw Error('测试音频尚未生成');
      buffer=await context.decodeAudioData(await response.arrayBuffer());
    } else {
      const device=$('inputDevice').value;
      stream=await navigator.mediaDevices.getUserMedia(captureConstraints($('audioMode').value,device));
      const track=stream.getAudioTracks()[0];
      $('inputLabel').textContent=track.label || '默认麦克风';
      const settings=track.getSettings();
      const actual=value=>value===undefined?'未报告':value?'开启':'关闭';
      $('captureStats').textContent=`${settings.sampleRate || '自动'} Hz → 24000 Hz · 单声道 · 浏览器降噪 ${actual(settings.noiseSuppression)} · 回声消除 ${actual(settings.echoCancellation)} · 自动增益 ${actual(settings.autoGainControl)}`;
      $('inputQuality').textContent=/Bluetooth/i.test(track.label)?'当前使用蓝牙麦克风；现场会议请确认是否应选择 MacBook 内置麦克风':'正在检查输入电平…';
      track.onended=()=>{ if(running&&!ending){displayError('麦克风已断开'); end();} };
    }
    await openSocket(); if(epoch!==generation) return;
    transmittedBytes=0;
    inputQuality=new InputQuality();
    const mode=$('audioMode').value;
    capture=new AudioWorkletNode(context,'meeting-capture',{processorOptions:{highpassHz:mode==='raw'?0:80}});
    $('processingLabel').textContent=$('audioMode').selectedOptions[0].textContent+' · 弱声不丢帧';
    sink=context.createGain(); sink.gain.value=0; capture.connect(sink).connect(context.destination);
    capture.port.onmessage=({data})=>{
      if(data.type==='flushed') {flushResolve?.(); return;}
      if(data.type==='quality'){$('inputQuality').textContent=inputQuality.update(data);return;}
      if(data.type!=='pcm') return;
      const level=Math.min(100,Math.round(data.rms*1000));
      $('micLevel').style.transform=`scaleX(${level/100})`; $('micPercent').textContent=`${level}%`;
      if(socket?.readyState===WebSocket.OPEN) {
        if(socket.bufferedAmount>2*1024*1024){displayError('音频网络积压超过限额，请检查连接'); finish(false); return;}
        socket.send(data.buffer);transmittedBytes+=data.buffer.byteLength;
      }
    };
    source=fixture?context.createBufferSource():context.createMediaStreamSource(stream);
    if(fixture){source.buffer=buffer; $('inputLabel').textContent='室内定位日英测试音频'; $('captureStats').textContent=`${buffer.duration.toFixed(1)} 秒 · 合成语音（不录音）`;}
    source.connect(capture);
    store=new TranscriptStore(); rows=new Map(); hiddenItems=new Set(); $('transcriptList').replaceChildren();
    $('followTranscript').checked=true;
    summaries.reset();
    evidenceUI.connected();
    latestStats={}; lastTranslationAt=0; running=true; controls(true);
    $('restartBtn').hidden=true;
    $('prejoin').classList.add('closed'); $('targetLabel').textContent=$('targetLanguage').selectedOptions[0].textContent;
    $('topicLabel').textContent=$('topicSelect').selectedOptions[0].textContent;
    $('localParticipant').classList.add('live'); setStatus('live',fixture?'测试中':'会议中'); diagnostic('正在聆听日语和英语');
    startedAt=Date.now(); timer=setInterval(()=>$('meetingTime').textContent=seconds((Date.now()-startedAt)/1000),500);
    if(fixture) { source.onended=()=>{if(running&&!ending)end();}; source.start(); }
  } catch(error) {displayError(error.message); finish(false);}
  finally { $('joinBtn').disabled=false; $('sampleBtn').disabled=false; }
}
async function end() {
  if(!running || ending) return;
  ending=true; controls(false); setStatus('connecting','正在整理最后一段');
  diagnostic('等待最后一段原文和译文；记录会保留');
  // Worklet sends all queued PCM before the stop message on the same socket.
  try { await new Promise((resolve,reject)=>{
    let timeout;
    flushResolve=()=>{clearTimeout(timeout);flushResolve=null;resolve();};
    timeout=setTimeout(()=>{flushResolve=null; reject(Error('音频尾帧未确认，连接暂时保留；请再次点击结束重试。此时不能保证继续采音'));},10000);
    capture?.port.postMessage({type:'flush'});
  }); } catch(error) {ending=false;controls(true);displayError(error.message);return;}
  source?.disconnect(); stream?.getTracks().forEach(t=>t.stop());
  if(socket?.readyState===WebSocket.OPEN) socket.send(JSON.stringify({type:'stop',sent_bytes:transmittedBytes}));
  else {displayError('未能提交最后一段：连接已关闭'); finish(false);}
}
function finish(success=true) {
  summaries.tick(latestStats.received_seconds||transmittedBytes/48000,false,true);
  running=false; ending=false; ++generation;
  clearInterval(timer); controls(false);
  window.speechSynthesis?.cancel();
  if(socket) {socket.onclose=null; socket.close(); socket=null;}
  source?.disconnect(); capture?.disconnect(); sink?.disconnect();
  stream?.getTracks().forEach(t=>t.stop()); stream=null;
  context?.close(); context=null;
  $('localParticipant').classList.remove('live'); $('micLevel').style.transform='scaleX(0)'; $('micPercent').textContent='0%';
  $('micBtn').classList.remove('off'); $('micBtn').setAttribute('aria-pressed','true');
  $('restartBtn').hidden=false;
  $('summaryPeriod').disabled=false;
  if(success){setStatus('','已结束'); diagnostic('原文和译文已接收完成，可导出记录');}
  if(!store.items.size) $('prejoin').classList.remove('closed');
}
async function listDevices() {
  const devices=await navigator.mediaDevices.enumerateDevices(); const select=$('inputDevice');
  for(const device of devices.filter(d=>d.kind==='audioinput')) {
    if(device.deviceId==='default')continue;
    const option=document.createElement('option');option.value=device.deviceId;option.textContent=device.label || `麦克风 ${select.options.length}`;select.append(option);
  }
  if(!select.value)select.value=preferredInput(devices);
}
$('joinBtn').addEventListener('click',()=>start());
$('previewBtn').addEventListener('click',()=>{ $('prejoin').classList.add('closed');$('restartBtn').hidden=false;$('restartBtn').textContent='开始会议'; });
$('sampleBtn').addEventListener('click',()=>start(true));
$('endBtn').addEventListener('click',end);
$('restartBtn').addEventListener('click',()=>{ if(store.items.size)evidenceUI.reset();$('prejoin').classList.remove('closed'); $('restartBtn').hidden=true; });
$('micBtn').addEventListener('click',()=>{const track=stream?.getAudioTracks()[0];if(!track)return;track.enabled=!track.enabled;$('micBtn').classList.toggle('off',!track.enabled);$('micBtn').setAttribute('aria-pressed',String(track.enabled));});
$('followTranscript').addEventListener('change',()=>{if($('followTranscript').checked)$('transcriptList').scrollTop=$('transcriptList').scrollHeight;});
$('transcriptList').addEventListener('scroll',()=>{$('followTranscript').checked=nearTranscriptBottom($('transcriptList'));});
$('audioBtn').addEventListener('click',()=>{speakingAudio=!speakingAudio;$('audioBtn').classList.toggle('active',speakingAudio);$('audioBtn').setAttribute('aria-pressed',String(speakingAudio));if(!speakingAudio)window.speechSynthesis?.cancel();});
$('clearBtn').addEventListener('click',()=>{hiddenItems=new Set(store.items.keys());$('transcriptList').replaceChildren();rows=new Map();});
$('downloadBtn').addEventListener('click',()=>{
  const text=store.ordered().map(i=>`[${i.at.toLocaleTimeString()}]${i.recovered?' 补听（含前文）':''}\n原文：${i.source}\n译文：${i.translation || i.error || '尚未返回'}${i.revisions.length||i.recovered?`\n最初识别：${i.initialSource??i.rawSource}${i.recovered?`\n补听识别（含前文）：${i.rawSource}`:''}\n最初译文：${i.rawTranslation}\n修订历史：${JSON.stringify(i.revisions)}`:''}`).join('\n\n');
  if(!text)return;
  const complete=text+'\n\n分段总结与修订记录：\n'+JSON.stringify(summaries.export(),null,2);
  const link=document.createElement('a');const url=URL.createObjectURL(new Blob([complete],{type:'text/plain;charset=utf-8'}));link.href=url;link.download=`meeting-${new Date().toISOString().slice(0,10)}.txt`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
window.addEventListener('beforeunload',()=>{stream?.getTracks().forEach(t=>t.stop());socket?.close();});
controls(false);listDevices().catch(()=>{});
