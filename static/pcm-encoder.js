// Stateful area resampling: output is independent of AudioWorklet block size.
export class PcmEncoder {
  constructor(inputRate, outputRate = 24000, frameSamples = 2400, emit = () => {}) {
    this.ratio = inputRate / outputRate;
    this.frameSamples = frameSamples; this.emit = emit;
    this.weight = 0; this.sum = 0; this.frame = [];
  }
  push(samples) {
    for (const sample of samples) {
      let left = 1;
      while (left > 1e-9) {
        const use = Math.min(left, this.ratio - this.weight);
        this.sum += sample * use; this.weight += use; left -= use;
        if (this.weight >= this.ratio - 1e-9) {
          const value = Math.max(-1, Math.min(1, this.sum / this.ratio));
          this.frame.push(Math.round(value * (value < 0 ? 32768 : 32767)));
          this.weight = 0; this.sum = 0;
          if (this.frame.length === this.frameSamples) this.emitFrame();
        }
      }
    }
  }
  emitFrame() {
    if (!this.frame.length) return;
    const buffer = new ArrayBuffer(this.frame.length * 2);
    const view = new DataView(buffer);
    let energy = 0; let peak = 0;let clipped=0;
    this.frame.forEach((value, i) => { view.setInt16(i*2, value, true); energy += (value/32768)**2; peak = Math.max(peak, Math.abs(value)/32768);if(Math.abs(value)>=32700)clipped++; });
    this.emit(buffer, {rms: Math.sqrt(energy/this.frame.length), peak,clipped:clipped/this.frame.length});
    this.frame = [];
  }
  flush() { this.emitFrame(); }
}
