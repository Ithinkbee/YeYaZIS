/* Захват звука с микрофона для «Моего говорящего Пафнутия».
 *
 * Работает в звуковом потоке браузера (AudioWorklet): каждые 20 мс
 * сообщает уровень сигнала — по нему игра замечает начало и конец фразы, —
 * и отдаёт отсчёты с частотой 16 кГц кусками по 100 мс: из них собирается
 * запись, которую Пафнутий повторит. Частота понижается усреднением групп
 * отсчётов (заодно срезаются частоты выше 8 кГц).
 */

class GlashataiCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.target = 16000;
    this.ratio = sampleRate / this.target;
    this.chunk = new Int16Array(1600);
    this.filled = 0;
    this.sum = 0;
    this.count = 0;
    this.position = 0;
    this.levelEvery = Math.round(sampleRate * 0.02);
    this.squares = 0;
    this.seen = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) { return true; }
    const data = input[0];
    for (let i = 0; i < data.length; i++) {
      const sample = data[i];
      this.squares += sample * sample;
      if (++this.seen >= this.levelEvery) {
        this.port.postMessage({ type: 'level', rms: Math.sqrt(this.squares / this.seen) });
        this.squares = 0;
        this.seen = 0;
      }
      this.sum += sample;
      this.count++;
      this.position += 1;
      if (this.position >= this.ratio) {
        this.position -= this.ratio;
        const value = this.sum / this.count;
        this.sum = 0;
        this.count = 0;
        this.chunk[this.filled++] = Math.max(-32768, Math.min(32767, Math.round(value * 32767)));
        if (this.filled === this.chunk.length) {
          const ready = this.chunk;
          this.chunk = new Int16Array(ready.length);
          this.filled = 0;
          this.port.postMessage({ type: 'pcm', samples: ready }, [ready.buffer]);
        }
      }
    }
    return true;
  }
}

registerProcessor('glashatai-capture', GlashataiCapture);
