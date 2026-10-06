/* Микрофон: захват звука, уровень сигнала, отсчёты для распознавателя.
 *
 * Один и тот же захват нужен пульту (звук уходит на сервер, уровень рисуется
 * на шкале) и прогулке с Пафнутием (нужен только уровень). Сверху — пересчёт
 * уровня в децибелы, он проверяется в node вместе с правилами игры; снизу —
 * работа со звуковой подсистемой браузера и канал распознавания: микрофон
 * вместе с соединением, по которому звук уходит на сервер.
 */

(function (global) {
  'use strict';

  /* --- правила -------------------------------------------------------------- */

  var SILENCE_DB = -100;

  /** Среднеквадратичное значение сигнала (0…1) в дБ относительно полной шкалы. */
  function toDb(rms) {
    if (!(rms > 0)) { return SILENCE_DB; }
    return Math.max(SILENCE_DB, 20 * Math.log(rms) / Math.LN10);
  }

  /** Доля шкалы от low до high дБ, 0…1. */
  function scale(db, low, high) {
    return Math.max(0, Math.min(1, (db - low) / (high - low)));
  }

  var rules = { SILENCE_DB: SILENCE_DB, toDb: toDb, scale: scale };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = rules;
    return;
  }

  /* --- захват ----------------------------------------------------------------- */

  var RATE = 16000;

  /**
   * options:
   *   pcm         — нужны ли отсчёты (false — только уровень)
   *   processing  — включить ли обработку сигнала браузером: подавление шума и
   *                 автоматическую регулировку усиления. Распознаванию она
   *                 помогает, а игре вредит: выравнивает тихий и громкий голос.
   *   onLevel(db, peakDb)   — уровень сигнала, каждые 20 мс
   *   onChunk(Int16Array)   — 100 мс звука на частоте 16 кГц
   */
  function Mic(options) {
    this.options = options || {};
    this.stream = null;
    this.context = null;
    this.node = null;
    this.active = false;
  }

  Mic.supported = function () {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia &&
      (global.AudioContext || global.webkitAudioContext) && global.AudioWorkletNode);
  };

  /** Причина отказа человеческим языком. */
  Mic.describe = function (problem) {
    var name = problem && problem.name;
    if (name === 'NotAllowedError' || name === 'SecurityError') {
      return 'браузер не дал доступ к микрофону: разрешите его в адресной строке (значок замка или микрофона)';
    }
    if (name === 'NotFoundError' || name === 'OverconstrainedError') { return 'микрофон не найден'; }
    if (name === 'NotReadableError' || name === 'AbortError') { return 'микрофон занят другой программой'; }
    return 'микрофон недоступен' + (problem && problem.message ? ': ' + problem.message : '');
  };

  Mic.prototype.start = function () {
    var self = this;
    if (!Mic.supported()) {
      return Promise.reject(new Error('этот браузер не умеет записывать звук — нужен Chrome, Edge или Firefox'));
    }
    var processing = self.options.processing !== false;
    var constraints = {
      audio: {
        channelCount: 1,
        echoCancellation: processing,
        noiseSuppression: processing,
        autoGainControl: processing
      }
    };
    return navigator.mediaDevices.getUserMedia(constraints).then(function (stream) {
      self.stream = stream;
      return self._build(true).catch(function () {
        /* звуковой поток не на 16 кГц не со всяким микрофоном соединяется —
           тогда берётся родная частота устройства, и её понижает обработчик */
        self._closeContext();
        return self._build(false);
      });
    }).then(function () {
      self.active = true;
    }, function (problem) {
      self.stop();
      throw problem;
    });
  };

  Mic.prototype._build = function (native16k) {
    var self = this;
    var Context = global.AudioContext || global.webkitAudioContext;
    var context = native16k ? new Context({ sampleRate: RATE }) : new Context();
    self.context = context;
    var url = (global.SLUHACH && global.SLUHACH.worklet) || '/static/capture-worklet.js';
    return context.audioWorklet.addModule(url).then(function () {
      var source = context.createMediaStreamSource(self.stream);
      var node = new global.AudioWorkletNode(context, 'sluhach-capture', {
        numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1,
        processorOptions: { rate: RATE, pcm: self.options.pcm !== false }
      });
      node.port.onmessage = function (event) {
        var data = event.data;
        if (data.type === 'level') {
          if (self.options.onLevel) { self.options.onLevel(toDb(data.rms), toDb(data.peak)); }
        } else if (data.type === 'pcm') {
          if (self.options.onChunk) { self.options.onChunk(data.samples); }
        }
      };
      /* обработчик считается, только пока его выход куда-то подключён; чтобы
         микрофон не звучал в колонках, выход идёт через нулевое усиление */
      var mute = context.createGain();
      mute.gain.value = 0;
      source.connect(node);
      node.connect(mute);
      mute.connect(context.destination);
      self.node = node;
      return context.state === 'suspended' ? context.resume() : null;
    });
  };

  Mic.prototype._closeContext = function () {
    if (this.node) {
      try { this.node.port.onmessage = null; this.node.disconnect(); } catch (e) { /* уже отключён */ }
      this.node = null;
    }
    if (this.context) {
      try { this.context.close(); } catch (e) { /* уже закрыт */ }
      this.context = null;
    }
  };

  Mic.prototype.stop = function () {
    this.active = false;
    this._closeContext();
    if (this.stream) {
      this.stream.getTracks().forEach(function (track) { track.stop(); });
      this.stream = null;
    }
  };

  /* --- канал распознавания ------------------------------------------------------
   *
   * Микрофон и соединение с /ws/listen вместе: звук уходит на сервер, обратно
   * приходят события детектора речи и распознавателя. Каналом пользуются
   * пульт и проверка своим голосом.
   *
   * options:
   *   language, margin, pause — язык и настройки детектора речи на сервере
   *   onLevel(db)             — уровень сигнала, каждые 20 мс
   *   onEvent(event)          — событие сервера: level, speech_start, partial,
   *                             speech_end, final, error
   *   onReady()               — соединение открыто, можно говорить
   *   onClose()               — соединение оборвалось не по нашей воле
   */
  function Channel(options) {
    this.options = options || {};
    this.mic = null;
    this.socket = null;
    this.muted = false;
    this.stopped = false;
  }

  /* Включает микрофон и открывает соединение; отказ микрофона — отказ обещания. */
  Channel.prototype.start = function () {
    var self = this;
    var options = self.options;
    self.mic = new Mic({
      pcm: true, processing: true,
      onLevel: options.onLevel,
      onChunk: function (samples) {
        if (self.socket && self.socket.readyState === 1 && !self.muted) { self.socket.send(samples.buffer); }
      }
    });
    return self.mic.start().then(function () {
      if (self.stopped) {                       /* пока микрофон включался, слушать передумали */
        self.mic.stop();
        return;
      }
      var socket = new global.WebSocket((global.location.protocol === 'https:' ? 'wss://' : 'ws://') +
        global.location.host + '/ws/listen');
      self.socket = socket;
      socket.onopen = function () {
        self.send({ type: 'language', code: options.language });
        self.send({ type: 'config', margin: options.margin, pause: options.pause });
        if (options.onReady) { options.onReady(); }
      };
      socket.onmessage = function (message) {
        if (self.socket === socket && options.onEvent) { options.onEvent(JSON.parse(message.data)); }
      };
      socket.onclose = function () {
        if (self.socket === socket && !self.stopped && options.onClose) { options.onClose(); }
      };
    });
  };

  Channel.prototype.send = function (message) {
    if (this.socket && this.socket.readyState === 1) { this.socket.send(JSON.stringify(message)); }
  };

  /* Пока система говорит сама, звук на сервер не идёт, а начатая фраза бросается. */
  Channel.prototype.mute = function (on) {
    this.muted = !!on;
    this.send({ type: 'mute', on: this.muted });
  };

  Channel.prototype.stop = function () {
    this.stopped = true;
    if (this.socket) {
      var socket = this.socket;
      this.socket = null;
      try { socket.close(); } catch (e) { /* уже закрыт */ }
    }
    if (this.mic) { this.mic.stop(); }
  };

  Object.defineProperty(Channel.prototype, 'active', {
    get: function () { return !!(this.mic && this.mic.active); }
  });

  global.Sluhach = global.Sluhach || {};
  global.Sluhach.Mic = Mic;
  global.Sluhach.Channel = Channel;
  global.Sluhach.micRules = rules;
})(typeof window !== 'undefined' ? window : globalThis);
