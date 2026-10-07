/* Панель настроек чтения: голос, темп, громкость, высота, живость, паузы, правила.
 *
 * Настройки общие для всех страниц (хранятся в браузере) и уходят на
 * сервер: ими читаются тексты из буфера обмена, по горячей клавише и с
 * чужих страниц. Каждое изменение сообщает, что изменилось: громкость
 * применяется на ходу, голос и темп — со следующего предложения, правила
 * чтения — после нового разбора текста.
 */

(function (global) {
  'use strict';

  var G = global.Glashatai;

  var ENGINES = {
    piper: 'Нейросетевые голоса (Piper)',
    formant: 'Собственный синтезатор системы',
    sapi: 'Голоса Windows',
    browser: 'Голос браузера'
  };

  function format(name, value) {
    value = Number(value);
    if (name === 'rate') { return '×' + value.toFixed(2).replace('.', ','); }
    if (name === 'volume') { return Math.round(value) + ' %'; }
    if (name === 'pitch') { return (value > 0 ? '+' : value < 0 ? '−' : '') + Math.abs(value).toString().replace('.', ',') + ' пт'; }
    if (name === 'liveliness') { return Math.round(value * 100) + ' %'; }
    return Math.round(value) + ' мс';
  }

  /**
   * boot — данные страницы (голоса, настройки по умолчанию);
   * onChange(kind) — kind: volume | synthesis | pause | options.
   */
  function Settings(boot, onChange) {
    var $ = function (id) { return document.getElementById(id); };
    var defaults = { settings: boot.settings, options: boot.options };
    var prefs = G.loadPrefs(defaults);
    var voices = boot.voices || [];

    function voiceInfo(id) {
      for (var i = 0; i < voices.length; i++) { if (voices[i].id === id) { return voices[i]; } }
      return null;
    }

    var chosen = voiceInfo(prefs.settings.voice);
    if (!chosen || !chosen.available) { prefs.settings.voice = boot.default; }

    var select = $('voice');
    if (select) {
      select.textContent = '';
      Object.keys(ENGINES).forEach(function (engine) {
        var group = document.createElement('optgroup');
        group.label = ENGINES[engine];
        voices.filter(function (voice) { return voice.engine === engine; }).forEach(function (voice) {
          var option = document.createElement('option');
          option.value = voice.id;
          option.textContent = voice.title + (voice.gender ? ' · ' + voice.gender : '') + (voice.available ? '' : ' — нет');
          option.disabled = !voice.available;
          group.appendChild(option);
        });
        if (group.children.length) { select.appendChild(group); }
      });
      select.value = prefs.settings.voice;
      select.addEventListener('change', function () {
        prefs.settings.voice = select.value;
        describeVoice();
        changed('synthesis');
      });
    }

    function describeVoice() {
      var note = $('voice-note');
      var info = voiceInfo(prefs.settings.voice);
      var browserRow = $('browser-voice-row');
      if (browserRow) { browserRow.hidden = !(info && info.engine === 'browser'); }
      if (!note || !info) { return; }
      var native = info.native || [];
      var parts = [info.note];
      if (info.engine !== 'browser' && native.indexOf('pitch') < 0) { parts.push('высоту меняет обработка звука'); }
      if (info.engine !== 'browser' && native.indexOf('rate') < 0) { parts.push('темп — обработкой звука'); }
      note.textContent = parts.filter(Boolean).join('; ');
      if (info.engine === 'browser') { fillBrowserVoices(); }
    }

    function fillBrowserVoices() {
      var list = $('browser-voice');
      if (!list || !G.Player) { return; }
      var found = G.Player.germanVoices();
      list.textContent = '';
      if (!found.length) {
        var none = document.createElement('option');
        none.textContent = 'немецких голосов в браузере нет';
        list.appendChild(none);
        list.disabled = true;
        return;
      }
      list.disabled = false;
      found.forEach(function (voice) {
        var option = document.createElement('option');
        option.value = voice.voiceURI;
        option.textContent = voice.name + (voice.localService ? '' : ' · по сети');
        list.appendChild(option);
      });
      if (prefs.settings.browser_voice) { list.value = prefs.settings.browser_voice; }
      if (!list.value && found[0]) { list.value = found[0].voiceURI; }
    }
    var browserList = $('browser-voice');
    if (browserList) {
      browserList.addEventListener('change', function () {
        prefs.settings.browser_voice = browserList.value;
        changed('synthesis');
      });
      if (global.speechSynthesis && global.speechSynthesis.addEventListener) {
        global.speechSynthesis.addEventListener('voiceschanged', function () {
          var info = voiceInfo(prefs.settings.voice);
          if (info && info.engine === 'browser') { fillBrowserVoices(); }
        });
      }
    }

    document.querySelectorAll('[data-setting]').forEach(function (input) {
      var name = input.dataset.setting;
      var output = $(name + '-value');
      input.value = prefs.settings[name];
      if (output) { output.textContent = format(name, input.value); }
      input.addEventListener('input', function () {
        prefs.settings[name] = Number(input.value);
        if (output) { output.textContent = format(name, input.value); }
        changed(name === 'volume' ? 'volume' : /pause/.test(name) ? 'pause' : 'synthesis');
      });
    });

    document.querySelectorAll('[data-option]').forEach(function (input) {
      var name = input.dataset.option;
      if (input.type === 'checkbox') { input.checked = !!prefs.options[name]; }
      else { input.value = prefs.options[name]; }
      input.addEventListener('change', function () {
        prefs.options[name] = input.type === 'checkbox' ? input.checked : input.value;
        changed('options');
      });
    });

    var reset = $('settings-reset');
    if (reset) {
      reset.addEventListener('click', function () {
        prefs.settings = JSON.parse(JSON.stringify(defaults.settings));
        prefs.settings.voice = boot.default;
        prefs.options = JSON.parse(JSON.stringify(defaults.options));
        document.querySelectorAll('[data-setting]').forEach(function (input) {
          input.value = prefs.settings[input.dataset.setting];
          input.dispatchEvent(new Event('input'));
        });
        document.querySelectorAll('[data-option]').forEach(function (input) {
          if (input.type === 'checkbox') { input.checked = !!prefs.options[input.dataset.option]; }
          else { input.value = prefs.options[input.dataset.option]; }
        });
        if (select) { select.value = prefs.settings.voice; }
        describeVoice();
        changed('options');
      });
    }

    function changed(kind) {
      G.savePrefs(prefs);
      if (onChange) { onChange(kind); }
    }

    describeVoice();
    G.savePrefs(prefs);

    return {
      prefs: function () { return prefs; },
      voice: voiceInfo,
      setVoice: function (id) {
        if (!voiceInfo(id)) { return; }
        prefs.settings.voice = id;
        if (select) { select.value = id; }
        describeVoice();
        changed('synthesis');
      }
    };
  }

  G.Settings = Settings;
})(window);
