/* Голосовой вывод: ответ системы произносит синтезатор речи браузера
 * (Web Speech API, speechSynthesis). Голоса берутся из системы: в Windows это
 * голоса SAPI (Hedda — немецкий, Irina и Pavel — русский), в Chrome к ним
 * добавляются сетевые голоса Google, в Edge — голоса Microsoft.
 *
 * Сверху — разбиение текста на части, оно не зависит от браузера и
 * проверяется в node (tests/voice_rules.test.js); снизу — сам синтезатор.
 */

(function (global) {
  'use strict';

  /* --- правила -------------------------------------------------------------- */

  /* Длинный текст синтезаторы читают плохо: сетевые голоса Chrome обрывают
     реплику длиннее четверти минуты. Поэтому текст произносится по частям. */
  var CHUNK = 220;

  /**
   * Делит текст на части не длиннее limit: по предложениям, а слишком длинное
   * предложение — по запятым и, в крайнем случае, по словам.
   */
  function chunks(text, limit) {
    limit = limit || CHUNK;
    var result = [];
    var current = '';

    function push(piece) {
      piece = piece.trim();
      if (!piece) { return; }
      if (current && (current + ' ' + piece).length > limit) {
        result.push(current);
        current = '';
      }
      current = current ? current + ' ' + piece : piece;
    }

    function cut(piece, pattern) {
      return piece.match(pattern) || [piece];
    }

    cut(String(text || '').replace(/\s+/g, ' ').trim(), /[^.!?…]+[.!?…]+["»“”)]*|[^.!?…]+$/g).forEach(function (sentence) {
      if (sentence.trim().length <= limit) { push(sentence); return; }
      cut(sentence, /[^,;:—–]+[,;:—–]?/g).forEach(function (clause) {
        if (clause.trim().length <= limit) { push(clause); return; }
        clause.trim().split(' ').forEach(push);
      });
    });
    if (current) { result.push(current); }
    return result;
  }

  /** Голоса языка: сначала те, что работают без сети, внутри — по имени. */
  function rank(voices, tag) {
    var prefix = String(tag || '').slice(0, 2).toLowerCase();
    return (voices || []).filter(function (voice) {
      return String(voice.lang || '').slice(0, 2).toLowerCase() === prefix;
    }).sort(function (a, b) {
      if (!!a.localService !== !!b.localService) { return a.localService ? -1 : 1; }
      return String(a.name).localeCompare(String(b.name));
    });
  }

  var rules = { CHUNK: CHUNK, chunks: chunks, rank: rank };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = rules;
    return;
  }

  /* --- синтезатор ------------------------------------------------------------- */

  var synth = global.speechSynthesis;
  var STORE = 'sluhach-voice';
  var prefs = { enabled: true, rate: 1, chosen: {} };
  try {
    var saved = JSON.parse(global.localStorage.getItem(STORE) || '{}');
    if (typeof saved.enabled === 'boolean') { prefs.enabled = saved.enabled; }
    if (saved.rate >= 0.5 && saved.rate <= 2) { prefs.rate = saved.rate; }
    if (saved.chosen && typeof saved.chosen === 'object') { prefs.chosen = saved.chosen; }
  } catch (e) { /* настройки не сохранялись */ }

  function save() {
    try { global.localStorage.setItem(STORE, JSON.stringify(prefs)); } catch (e) { /* без хранилища */ }
  }

  var listeners = [];
  var token = 0;                /* номер текущей реплики: по нему отменённые части узнают, что они лишние */
  var active = false;
  var watchdog = null;

  function voices(tag) {
    return synth ? rank(synth.getVoices(), tag) : [];
  }

  /** Голос для языка: выбранный пользователем или первый подходящий. */
  function choose(tag) {
    var list = voices(tag);
    var wanted = prefs.chosen[String(tag).slice(0, 2)];
    for (var i = 0; i < list.length; i++) {
      if (list[i].voiceURI === wanted) { return list[i]; }
    }
    return list[0] || null;
  }

  function finish(mine, callbacks, reason) {
    if (mine !== token || !active) { return; }
    active = false;
    clearTimeout(watchdog);
    if (callbacks && callbacks.onend) { callbacks.onend(reason || 'end'); }
  }

  /**
   * Произносит текст на языке tag (de-DE, ru-RU).
   * callbacks: onstart(), onend(причина) — «end», «cancel», «off», «no-voice».
   * onend вызывается всегда, даже если говорить нечем: от него зависит, когда
   * система снова начнёт слушать.
   */
  function speak(text, tag, callbacks) {
    cancel();
    var mine = ++token;
    if (!prefs.enabled) {
      if (callbacks && callbacks.onend) { callbacks.onend('off'); }
      return;
    }
    var voice = choose(tag);
    if (!synth || !voice) {
      if (callbacks && callbacks.onend) { callbacks.onend('no-voice'); }
      return;
    }
    var parts = chunks(text);
    if (!parts.length) {
      if (callbacks && callbacks.onend) { callbacks.onend('end'); }
      return;
    }
    active = true;
    var started = false;

    function next(index) {
      if (mine !== token) { return; }
      if (index >= parts.length) { finish(mine, callbacks, 'end'); return; }
      var utterance = new global.SpeechSynthesisUtterance(parts[index]);
      utterance.voice = voice;
      utterance.lang = voice.lang || tag;
      utterance.rate = prefs.rate;
      utterance.onstart = function () {
        if (mine !== token || started) { return; }
        started = true;
        if (callbacks && callbacks.onstart) { callbacks.onstart(); }
      };
      utterance.onend = function () { next(index + 1); };
      utterance.onerror = function (event) {
        if (event && (event.error === 'canceled' || event.error === 'interrupted')) { return; }
        next(index + 1);
      };
      /* событие «конец» иногда не приходит — тогда часть считается прочитанной по времени */
      clearTimeout(watchdog);
      watchdog = setTimeout(function () { next(index + 1); }, 4000 + parts[index].length * 130 / prefs.rate);
      synth.speak(utterance);
    }
    next(0);
  }

  function cancel() {
    var was = active;
    token++;
    active = false;
    clearTimeout(watchdog);
    if (synth) { synth.cancel(); }
    return was;
  }

  if (synth && synth.addEventListener) {
    /* список голосов браузер отдаёт не сразу */
    synth.addEventListener('voiceschanged', function () {
      listeners.forEach(function (callback) { callback(); });
    });
  }

  global.Sluhach = global.Sluhach || {};
  global.Sluhach.voice = {
    supported: !!synth,
    prefs: prefs,
    save: save,
    voices: voices,
    choose: choose,
    speak: speak,
    cancel: cancel,
    speaking: function () { return active; },
    onvoices: function (callback) { listeners.push(callback); },
    rules: rules
  };
})(typeof window !== 'undefined' ? window : globalThis);
