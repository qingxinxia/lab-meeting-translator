import {PcmEncoder} from './pcm-encoder.js';
import {AudioConditioner} from './audio-conditioning.js?v=20261008-audio';
class MeetingCapture extends AudioWorkletProcessor {
  constructor(options) {
    super(); this.stopped = false;
    this.conditioner=new AudioConditioner(sampleRate,options?.processorOptions?.highpassHz||0);
    this.quality={samples:0,energy:0,peak:0,clipped:0};
    this.encoder = new PcmEncoder(sampleRate, 24000, 2400, (buffer, level) => {
      this.port.postMessage({type:'pcm', buffer, ...level}, [buffer]);
    });
    this.port.onmessage = ({data}) => {
      if (data.type === 'flush') {
        this.stopped = true; this.encoder.flush(); this.port.postMessage({type:'flushed'});
      }
    };
  }
  process(inputs) {
    if (!this.stopped && inputs[0]?.[0]) {
      const input=inputs[0][0],q=this.quality;
      for(const x of input){q.samples++;q.energy+=x*x;q.peak=Math.max(q.peak,Math.abs(x));if(Math.abs(x)>=.998)q.clipped++;}
      if(q.samples>=sampleRate*.1){this.port.postMessage({type:'quality',rms:Math.sqrt(q.energy/q.samples),peak:q.peak,clipped:q.clipped/q.samples});this.quality={samples:0,energy:0,peak:0,clipped:0};}
      this.encoder.push(this.conditioner.process(input));
    }
    return true;
  }
}
registerProcessor('meeting-capture', MeetingCapture);
