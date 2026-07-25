/** Small low-latency PCM queue used for assistant TTS playback. */
export class PcmAudioPlayer {
  private context: AudioContext | null = null;
  private nextStartTime = 0;
  private sources = new Set<AudioBufferSourceNode>();

  enqueue(base64: string, sampleRate: number): void {
    const bytes = decodeBase64(base64);
    if (bytes.byteLength < 2) return;
    const context = this.getContext(sampleRate);
    if (!context) return;
    const frames = Math.floor(bytes.byteLength / 2);
    const buffer = context.createBuffer(1, frames, sampleRate);
    const channel = buffer.getChannelData(0);
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let index = 0; index < frames; index += 1) channel[index] = view.getInt16(index * 2, true) / 0x8000;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    const startAt = Math.max(context.currentTime + 0.03, this.nextStartTime);
    this.nextStartTime = startAt + buffer.duration;
    source.onended = () => this.sources.delete(source);
    this.sources.add(source);
    source.start(startAt);
  }

  stop(): void {
    for (const source of this.sources) {
      try { source.stop(); } catch { /* already stopped */ }
    }
    this.sources.clear();
    this.nextStartTime = 0;
  }

  dispose(): void {
    this.stop();
    const context = this.context;
    this.context = null;
    if (context) void context.close().catch(() => undefined);
  }

  private getContext(sampleRate: number): AudioContext | null {
    if (this.context) return this.context;
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return null;
    this.context = new Ctor({ sampleRate });
    void this.context.resume().catch(() => undefined);
    return this.context;
  }
}

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}
