import test from 'node:test';
import assert from 'node:assert/strict';
import {AudioConditioner,InputQuality,captureConstraints,preferredInput} from './static/audio-conditioning.js';
test('prefer concrete built-in device, not the default alias or virtual input',()=>{
  assert.equal(preferredInput([
    {kind:'audioinput',deviceId:'default',label:'Default - MacBook Pro麦克风'},
    {kind:'audioinput',deviceId:'virtual',label:'Microsoft Teams Audio Device'},
    {kind:'audioinput',deviceId:'built-in',label:'MacBook Pro麦克风 (Built-in)'}]),'built-in');
  assert.equal(preferredInput([{kind:'audioinput',deviceId:'unlabelled',label:''}]),'');
});
test('filter preserves every sample and is independent of block sizes',()=>{
  const x=Float32Array.from({length:48513},(_,i)=>.003+Math.sin(i*.13)*.0001);
  const full=new AudioConditioner(48000,80).process(x),chunked=new AudioConditioner(48000,80),parts=[];
  for(let i=0;i<x.length;i+=128)parts.push(...chunked.process(x.subarray(i,i+128)));
  assert.equal(parts.length,x.length);assert.deepEqual(parts,Array.from(full));
  assert.ok(full.some(v=>v!==0),'Weak speech must not be gated');
});
test('raw path unchanged; low-frequency hum reduced without removing speech-band tone',()=>{
  const gain=hz=>{const x=Float32Array.from({length:24000},(_,i)=>Math.sin(2*Math.PI*hz*i/24000));const y=new AudioConditioner(24000,80).process(x);return Math.sqrt(y.slice(12000).reduce((a,v)=>a+v*v,0)/6000);};
  assert.ok(gain(50)<.6);assert.ok(gain(1000)>.97);
  const x=Float32Array.of(.1,-.2,0);assert.equal(new AudioConditioner(24000).process(x),x);
});
test('browser suppression is explicit, room mode does not stack suppression',()=>{
  assert.equal(captureConstraints('room').audio.noiseSuppression,false);
  assert.equal(captureConstraints('browser','built-in').audio.noiseSuppression,true);
  assert.deepEqual(captureConstraints('raw','built-in').audio.deviceId,{exact:'built-in'});
});
test('quality flags clipping and no input without claiming recognition accuracy',()=>{
  const quality=new InputQuality();let message;
  for(let i=0;i<30;i++)message=quality.update({rms:0,peak:0});assert.match(message,/几乎没有输入/);
  for(let i=0;i<30;i++)message=quality.update({rms:.5,peak:1,clipped:.1});assert.match(message,/削顶/);
  for(let i=0;i<30;i++)message=quality.update({rms:.02,peak:.1});assert.match(message,/不能证明/);
});
