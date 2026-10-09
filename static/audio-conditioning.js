// Gentle rumble removal, not a speech gate: every sample survives.
export class AudioConditioner {
  constructor(rate,hz=0){this.enabled=hz>0;this.alpha=Math.exp(-2*Math.PI*hz/rate);this.previous=0;this.state=0;}
  process(input){
    if(!this.enabled)return input;
    const output=new Float32Array(input.length);
    for(let i=0;i<input.length;i++){const x=input[i];this.state=this.alpha*(this.state+x-this.previous);this.previous=x;output[i]=this.state;}
    return output;
  }
}
export function captureConstraints(mode,device=''){
  return {audio:{...(device?{deviceId:{exact:device}}:{}),channelCount:1,
    echoCancellation:true,noiseSuppression:mode==='browser',autoGainControl:true},video:false};
}
export function preferredInput(devices){
  return devices.find(d=>d.kind==='audioinput'&&d.deviceId&&d.deviceId!=='default'&&/MacBook|Built-in|内置/i.test(d.label))?.deviceId||'';
}
export class InputQuality {
  constructor(){this.frames=[];}
  update({rms,peak,clipped=0}){
    this.frames.push({rms,peak,clipped});if(this.frames.length>30)this.frames.shift();
    if(this.frames.length<20)return '正在检查输入电平…';
    const average=this.frames.reduce((sum,f)=>sum+f.rms,0)/this.frames.length;
    const clips=this.frames.reduce((sum,f)=>sum+f.clipped,0)/this.frames.length;
    if(clips>.005)return '输入削顶 / 可能爆音：请降低输入增益或远离碰撞声';
    if(average<.0001)return '几乎没有输入：若有人在说话，请检查设备与权限';
    if(average<.002)return '输入较弱：请让电脑靠近说话的人；弱声仍会保留';
    return '输入有信号 · 电平不能证明人声清晰或收音完整';
  }
}
