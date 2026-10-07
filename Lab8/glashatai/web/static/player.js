/* Проигрыватель: читает текст предложение за предложением.
 *
 * Звук предложений синтезирует сервер (/api/speak) — нейросетевым,
 * собственным или голосом Windows; страница проигрывает его через Web Audio.
 * Пока звучит одно предложение, два следующих уже запрошены — паузы на
 * синтез между предложениями нет. Пауза останавливает звуковой поток
 * целиком (AudioContext.suspend) и продолжает с того же места. Громкость —
 * усилитель в звуковом потоке: её можно менять на ходу, ничего не
 * синтезируя заново. Темп, высота и голос действуют со следующего
 * предложения.
 *
 * Голос браузера (Web Speech API) говорит сам; ему уходит уже
 * нормализованный текст предложения, а браузер сообщает о каждом слове —
 * по этим событиям подсвечивается звучащее слово.
 *
 * Сверху — правила без DOM (паузы, высота для браузера); снизу —
 * проигрыватель.
 */

(function (global) {
  'use strict';

  /* --- правила ------------------------------------------------------------------- */

  /** Пауза после предложения: продолжение длинного — без паузы, конец абзаца — длиннее. */
  function pauseAfter(sentences, index, settings) {
    var current = sentences[index];
    var next = sentences[index + 1];
    if (!current || !next) { return 0; }
    if (current.continued) { return 40; }
    if (current.heading || next.paragraph !== current.paragraph) { return settings.paragraph_pause; }
    return settings.sentence_pause;
  }

  /** Высота в полутонах -> параметр pitch речи браузера (0…2, 1 — как есть). */
  function browserPitch(semitones) {
    return Math.max(0, Math.min(2, Math.pow(2, (semitones || 0) / 12)));
  }

  /** Ключ синтеза: от этого зависит звук предложения (громкость — нет). */
  function synthesisKey(settings, options) {
    return [settings.voice, settings.rate, settings.pitch, settings.liveliness, JSON.stringify(options || {})].join('|');
  }

  var rules = { pauseAfter: pauseAfter, browserPitch: browserPitch, synthesisKey: synthesisKey };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = rules;
    return;
  }

  var G = global.Glashatai;

  /* --- проигрыватель ---------------------------------------------------------------- */

  /**
   * hooks:
   *   prefs()                 — текущие настройки {settings, options}
   *   onState(state, info)    — idle | loading | speaking | paused
   *   onSentence(index)       — начало предложения
   *   onWord(index, at, len)  — слово (только голос браузера): положение в нормализованном тексте
   *   onVoice(info)           — каким голосом сказано на самом деле ({voice, fallback, ms, cached})
   *   onError(message)
   *   onDone()
   */
  function Player(hooks) {
    this.hooks = hooks || {};
    this.sentences = [];
    this.index = -1;
    this.state = 'idle';
    this.token = 0;
    this.cache = {};
    this.context = null;
    this.gain = null;
    this.analyser = null;
    this.source = null;
    this.timer = null;
    this.gap = null;            /* пауза между предложениями: что сделать после неё */
    this.levelRunning = false;
    this.endIndex = null;       /* читать только до этого предложения включительно */
  }

  Player.prototype.prefs = function () { return this.hooks.prefs ? this.hooks.prefs() : { settings: {}, options: {} }; };

  Player.prototype.browser = function () {
    return String(this.prefs().settings.voice || '').indexOf('browser:') === 0;
  };

  Player.prototype.load = function (sentences) {
    this.stop();
    this.sentences = sentences || [];
    this.cache = {};
    this.index = -1;
  };

  Player.prototype.setState = function (state, info) {
    this.state = state;
    if (this.hooks.onState) { this.hooks.onState(state, info || {}); }
    if (G && G.companion) {
      G.companion.mood(state === 'speaking' ? 'speaking' : state === 'loading' ? 'thinking' : 'idle');
      if (state !== 'speaking') { G.companion.level(0); }
    }
  };

  Player.prototype.ensureContext = function () {
    if (this.context) { return this.context; }
    var Context = global.AudioContext || global.webkitAudioContext;
    this.context = new Context();
    this.gain = this.context.createGain();
    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = 512;
    this.gain.connect(this.analyser);
    this.analyser.connect(this.context.destination);
    this.setVolume(this.prefs().settings.volume);
    return this.context;
  };

  Player.prototype.setVolume = function (percent) {
    var value = Math.max(0, Math.min(100, Number(percent) || 0)) / 100;
    if (this.gain) { this.gain.gain.setTargetAtTime(value, this.context.currentTime, 0.03); }
  };

  /* уровень звука для рта Пафнутия */
  Player.prototype.watchLevel = function () {
    if (this.levelRunning) { return; }
    this.levelRunning = true;
    var self = this;
    var data = new Float32Array(512);
    function tick() {
      if (self.state === 'idle') { self.levelRunning = false; return; }
      var level = 0;
      if (self.browser()) {
        level = self.state === 'speaking' ? 0.35 + 0.35 * Math.abs(Math.sin(performance.now() / 95)) : 0;
      } else if (self.analyser) {
        self.analyser.getFloatTimeDomainData(data);
        var sum = 0;
        for (var i = 0; i < data.length; i++) { sum += data[i] * data[i]; }
        var db = 20 * Math.log10(Math.sqrt(sum / data.length) + 1e-9);
        level = Math.max(0, Math.min(1, (db + 48) / 34));
      }
      if (G && G.companion) { G.companion.level(level); }
      if (self.hooks.onLevel) { self.hooks.onLevel(level); }
      global.requestAnimationFrame(tick);
    }
    global.requestAnimationFrame(tick);
  };

  Player.prototype.request = function (index) {
    var sentence = this.sentences[index];
    if (!sentence) { return null; }
    var prefs = this.prefs();
    var key = synthesisKey(prefs.settings, prefs.options) + '#' + index;
    if (this.cache[key]) { return this.cache[key]; }
    var context = this.ensureContext();
    var settings = {
      voice: prefs.settings.voice, rate: prefs.settings.rate, pitch: prefs.settings.pitch,
      liveliness: prefs.settings.liveliness
    };
    var body = { text: sentence.text, options: prefs.options, settings: settings, heading: !!sentence.heading,
                 continued: !!sentence.continued };
    var promise = fetch('/api/speak', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    }).then(function (response) {
      if (!response.ok) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          throw new Error(data.error || ('сервер ответил ' + response.status));
        });
      }
      var info = {
        voice: response.headers.get('X-Voice'), fallback: response.headers.get('X-Fallback') === '1',
        ms: Number(response.headers.get('X-Engine-Ms') || 0), cached: response.headers.get('X-Cached') === '1'
      };
      return response.arrayBuffer().then(function (data) {
        return new Promise(function (resolve, reject) {
          context.decodeAudioData(data, function (buffer) { resolve({ buffer: buffer, info: info }); }, reject);
        });
      });
    }, function () {
      throw new Error('сервер не отвечает');
    });
    var cache = this.cache;
    promise.catch(function () { delete cache[key]; });
    cache[key] = promise;
    return promise;
  };

  /** Читать с предложения index; until — последнее предложение (для «прочитать только это»). */
  Player.prototype.play = function (index, until) {
    this.stop(true);
    if (!this.sentences.length) { return; }
    index = Math.max(0, Math.min(this.sentences.length - 1, index || 0));
    this.endIndex = until === undefined ? null : until;
    var token = ++this.token;
    if (this.browser()) {
      this.speakBrowser(index, token);
    } else {
      var context = this.ensureContext();
      if (context.state === 'suspended') { context.resume(); }
      this.setVolume(this.prefs().settings.volume);
      this.playServer(index, token);
    }
    this.watchLevel();
  };

  Player.prototype.playServer = function (index, token) {
    var self = this;
    if (index >= this.sentences.length || (this.endIndex !== null && index > this.endIndex)) {
      this.finish();
      return;
    }
    this.index = index;
    if (this.hooks.onSentence) { this.hooks.onSentence(index); }
    var pending = this.request(index);
    for (var ahead = 1; ahead <= 2; ahead++) {
      if (this.endIndex === null || index + ahead <= this.endIndex) { this.request(index + ahead); }
    }
    this.setState('loading', { index: index });
    pending.then(function (result) {
      if (token !== self.token) { return; }
      if (self.hooks.onVoice) { self.hooks.onVoice(result.info); }
      var source = self.context.createBufferSource();
      source.buffer = result.buffer;
      source.connect(self.gain);
      source.onended = function () {
        if (token !== self.token) { return; }
        self.source = null;
        var pause = pauseAfter(self.sentences, index, self.prefs().settings);
        self.gap = function () { self.playServer(index + 1, token); };
        self.timer = setTimeout(function () {
          if (token !== self.token || self.state === 'paused') { return; }
          var next = self.gap;
          self.gap = null;
          if (next) { next(); }
        }, pause);
      };
      self.source = source;
      source.start();
      if (self.state !== 'paused') { self.setState('speaking', { index: index }); }
    }).catch(function (problem) {
      if (token !== self.token) { return; }
      self.stop();
      if (self.hooks.onError) { self.hooks.onError(problem.message || String(problem)); }
    });
  };

  /* --- голос браузера -------------------------------------------------------------- */

  Player.germanVoices = function () {
    var synth = global.speechSynthesis;
    if (!synth) { return []; }
    return synth.getVoices().filter(function (voice) {
      return String(voice.lang || '').toLowerCase().indexOf('de') === 0;
    }).sort(function (a, b) {
      /* сначала «естественные» сетевые голоса Edge и Google: они звучат лучше локальных */
      var score = function (voice) { return /natural|online|google/i.test(voice.name) ? 0 : 1; };
      return score(a) - score(b) || String(a.name).localeCompare(String(b.name));
    });
  };

  Player.prototype.browserVoice = function () {
    var wanted = this.prefs().settings.browser_voice;
    var voices = Player.germanVoices();
    for (var i = 0; i < voices.length; i++) {
      if (voices[i].voiceURI === wanted) { return voices[i]; }
    }
    return voices[0] || null;
  };

  Player.prototype.speakBrowser = function (index, token) {
    var self = this;
    var synth = global.speechSynthesis;
    if (index >= this.sentences.length || (this.endIndex !== null && index > this.endIndex)) {
      this.finish();
      return;
    }
    if (!synth) {
      if (this.hooks.onError) { this.hooks.onError('этот браузер не умеет говорить сам — выберите другой голос'); }
      this.stop();
      return;
    }
    var voice = this.browserVoice();
    if (!voice) {
      if (this.hooks.onError) { this.hooks.onError('у браузера нет немецкого голоса — выберите голос системы'); }
      this.stop();
      return;
    }
    var sentence = this.sentences[index];
    var settings = this.prefs().settings;
    this.index = index;
    if (this.hooks.onSentence) { this.hooks.onSentence(index); }
    var utterance = new global.SpeechSynthesisUtterance(sentence.written || sentence.say || sentence.text);
    utterance.voice = voice;
    utterance.lang = voice.lang;
    utterance.rate = settings.rate;
    utterance.pitch = browserPitch(settings.pitch);
    utterance.volume = Math.max(0, Math.min(1, settings.volume / 100));
    utterance.onstart = function () {
      if (token === self.token) {
        self.setState('speaking', { index: index });
        if (self.hooks.onVoice) { self.hooks.onVoice({ voice: 'browser:' + voice.name, fallback: false }); }
      }
    };
    utterance.onboundary = function (event) {
      if (token === self.token && event.name === 'word' && self.hooks.onWord) {
        self.hooks.onWord(index, event.charIndex, event.charLength || 0);
      }
    };
    var done = false;
    utterance.onend = utterance.onerror = function (event) {
      if (done || token !== self.token) { return; }
      done = true;
      if (event && event.error && event.error !== 'interrupted' && event.error !== 'canceled' && self.hooks.onError) {
        self.hooks.onError('голос браузера: ' + event.error);
      }
      var pause = pauseAfter(self.sentences, index, settings);
      self.gap = function () { self.speakBrowser(index + 1, token); };
      self.timer = setTimeout(function () {
        if (token !== self.token || self.state === 'paused') { return; }
        var next = self.gap;
        self.gap = null;
        if (next) { next(); }
      }, pause);
    };
    this.setState('loading', { index: index });
    synth.speak(utterance);
  };

  /* --- управление ------------------------------------------------------------------- */

  Player.prototype.pause = function () {
    if (this.state !== 'speaking' && this.state !== 'loading') { return; }
    if (this.browser()) {
      if (global.speechSynthesis) { global.speechSynthesis.pause(); }
    } else if (this.context) {
      this.context.suspend();
    }
    clearTimeout(this.timer);
    this.setState('paused', { index: this.index });
  };

  Player.prototype.resume = function () {
    if (this.state !== 'paused') { return; }
    if (this.browser()) {
      if (global.speechSynthesis) { global.speechSynthesis.resume(); }
    } else if (this.context) {
      this.context.resume();
    }
    this.setState(this.source || this.browser() ? 'speaking' : 'loading', { index: this.index });
    if (this.gap) {
      var next = this.gap;
      this.gap = null;
      next();
    }
  };

  Player.prototype.toggle = function (fromIndex) {
    if (this.state === 'paused') { this.resume(); }
    else if (this.state === 'speaking' || this.state === 'loading') { this.pause(); }
    else { this.play(fromIndex || 0); }
  };

  Player.prototype.stop = function (quiet) {
    this.token++;
    clearTimeout(this.timer);
    this.gap = null;
    if (this.source) {
      try { this.source.onended = null; this.source.stop(); } catch (e) { /* уже остановлен */ }
      this.source = null;
    }
    if (global.speechSynthesis && (global.speechSynthesis.speaking || global.speechSynthesis.pending)) {
      global.speechSynthesis.cancel();
    }
    if (this.context && this.context.state === 'suspended') { this.context.resume(); }
    if (this.state !== 'idle') { this.setState('idle', { stopped: !quiet }); }
  };

  Player.prototype.finish = function () {
    this.token++;
    this.setState('idle', { finished: true });
    if (this.hooks.onDone) { this.hooks.onDone(); }
  };

  Player.prototype.next = function () {
    if (this.index + 1 < this.sentences.length) { this.play(this.index + 1); }
  };

  Player.prototype.prev = function () {
    this.play(Math.max(0, this.index - 1));
  };

  /** Сбросить готовые записи: изменились голос, темп или правила чтения. */
  Player.prototype.invalidate = function () {
    this.cache = {};
  };

  Player.rules = rules;
  global.Glashatai = global.Glashatai || {};
  global.Glashatai.Player = Player;
})(typeof window !== 'undefined' ? window : globalThis);
