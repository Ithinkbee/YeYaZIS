/* Обработчик звука с микрофона: работает в звуковом потоке браузера
 * (AudioWorklet), а не в потоке страницы, поэтому не теряет отсчёты, даже
 * когда страница занята.
 *
 * Делает две вещи: каждые 20 мс сообщает уровень сигнала — по нему рисуется
 * шкала и ходит паук в игре — и, если просили, копит отсчёты с частотой
 * 16 кГц и отдаёт их кусками по 100 мс для распознавателя. Если браузер не
 * дал звук сразу на 16 кГц, частота понижается здесь: отсчёты усредняются
 * группами (усреднение заодно срезает частоты, которых на 16 кГц быть не
 * должно).
 */

class CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const settings = (options && options.processorOptions) || {};
    this.target = settings.rate || 16000;
    this.ratio = sampleRate / this.target;       // сколько входных отсчётов на один выходной
    this.sendPcm = settings.pcm !== false;
    this.chunk = new Int16Array(Math.round(this.target * 0.1));
    this.filled = 0;
    this.sum = 0;                                // накопление для понижения частоты
    this.count = 0;
    this.position = 0;
    this.levelEvery = Math.round(sampleRate * 0.02);
    this.squares = 0;
    this.peak = 0;
    this.seen = 0;
    this.port.onmessage = (event) => {
      if (event.data && typeof event.data.pcm === 'boolean') { this.sendPcm = event.data.pcm; }
    };
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) { return true; }
    const data = input[0];
    for (let i = 0; i < data.length; i++) {
      const sample = data[i];

      this.squares += sample * sample;
      const magnitude = sample < 0 ? -sample : sample;
      if (magnitude > this.peak) { this.peak = magnitude; }
      if (++this.seen >= this.levelEvery) {
        this.port.postMessage({ type: 'level', rms: Math.sqrt(this.squares / this.seen), peak: this.peak });
        this.squares = 0;
        this.peak = 0;
        this.seen = 0;
      }

      if (!this.sendPcm) { continue; }
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

registerProcessor('sluhach-capture', CaptureProcessor);
