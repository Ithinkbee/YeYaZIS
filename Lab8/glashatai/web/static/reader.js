/* Чтец: ввод текста, разбор, чтение с подсветкой, сохранение записи.
 *
 * Текст разбирается на сервере (/api/prepare) каждый раз, когда он
 * изменился или изменились правила чтения; разбор показывает вкладка «Как
 * прочтёт». Чтение идёт по предложениям (player.js). Страница слушает поток
 * событий сервера: текст, скопированный в другой программе или выделенный
 * по Ctrl+Alt+R, приходит сюда и сразу читается.
 */

(function (global) {
  'use strict';

  var G = global.Glashatai;

  G.ready(function () {
    var $ = function (id) { return document.getElementById(id); };
    var boot = JSON.parse($('boot').textContent);
    var input = $('text');
    var parsed = null;          /* {text, key, doc, view} */
    var view = null;
    var lastVoice = '';

    var settings = G.Settings(boot, function (kind) {
      if (kind === 'volume') { player.setVolume(settings.prefs().settings.volume); }
      if (kind === 'synthesis' || kind === 'options') { player.invalidate(); }
      if (kind === 'options') {
        var resume = player.state !== 'idle' ? player.index : null;
        parsed = null;
        if (resume !== null) { start(resume); }
        else if (activeTab !== 'text') { ensureParsed().catch(function () {}); }
      }
    });

    var player = new G.Player({
      prefs: settings.prefs,
      onState: function (state, info) {
        var status = $('status');
        status.className = 'status-line state-' + (state === 'idle' ? 'ready' : state);
        $('play-label').textContent = state === 'speaking' || state === 'loading' ? 'Пауза' : state === 'paused' ? 'Дальше' : 'Читать';
        document.querySelector('#play .glyph').textContent = state === 'speaking' || state === 'loading' ? '⏸' : '▶';
        var text = { idle: info.finished ? 'Дочитано' : 'Готов читать', loading: 'Синтезирую…',
                     speaking: 'Читаю', paused: 'Пауза' }[state];
        if (state === 'speaking' && lastVoice) { text += ' · ' + lastVoice; }
        $('status-text').textContent = text;
        if (view) {
          if (state === 'idle' && info.finished) { view.mark(-1); }
          else if (state === 'loading' || state === 'speaking') { view.mark(player.index, state); }
        }
        if (state === 'idle' && info.finished) { G.say(pick(['Дочитал. Ещё?', 'Всё. Ни одной мухи не пропустил.'])); }
      },
      onSentence: function (index) {
        var total = player.sentences.length;
        $('progress').style.width = (100 * index / Math.max(1, total)) + '%';
        $('progress-text').textContent = (index + 1) + ' из ' + total;
        if (view) { view.mark(index, 'loading'); }
      },
      onWord: function (index, at, length) {
        if (view) { view.word(index, at, length, (player.sentences[index] || {}).written); }
      },
      onVoice: function (info) {
        var known = settings.voice(info.voice);
        lastVoice = known ? known.title : String(info.voice || '').replace(/^browser:/, '');
        if (info.fallback) {
          G.toast('Выбранный голос недоступен — читает ' + lastVoice);
        }
      },
      onError: function (message) {
        G.toast('Не прочитано: ' + message, 4500);
      },
      onDone: function () {
        $('progress').style.width = '100%';
      }
    });

    function pick(list) { return list[Math.floor(Math.random() * list.length)]; }

    /* --- вкладки ------------------------------------------------------------------- */

    var activeTab = 'text';
    function showTab(name) {
      activeTab = name;
      document.querySelectorAll('[data-tab]').forEach(function (button) {
        button.classList.toggle('on', button.dataset.tab === name);
      });
      document.querySelectorAll('[data-pane]').forEach(function (pane) {
        pane.hidden = pane.dataset.pane !== name;
      });
      if (name !== 'text') {
        ensureParsed().then(function () {
          if (name === 'phonetics') { loadPhonetics(); }
        }, function () {});
      }
    }
    document.querySelectorAll('[data-tab]').forEach(function (button) {
      button.addEventListener('click', function () { showTab(button.dataset.tab); });
    });

    /* --- разбор ---------------------------------------------------------------------- */

    function key() {
      return input.value + '\u0000' + JSON.stringify(settings.prefs().options);
    }

    function ensureParsed() {
      if (parsed && parsed.key === key()) { return Promise.resolve(parsed); }
      var text = input.value;
      var currentKey = key();
      return G.api('POST', '/api/prepare', { text: text, options: settings.prefs().options }).then(function (doc) {
        if (doc.error) { G.toast(doc.error); throw new Error(doc.error); }
        parsed = { text: text, key: currentKey, doc: doc };
        view = G.DocView.render($('reading'), text, doc, {
          onPick: function (index) { player.play(index); }
        });
        G.DocView.spoken($('spoken'), text, doc);
        renderKinds(doc.stats);
        player.load(view.sentences);
        phoneticsFor = null;
        return parsed;
      });
    }

    function renderKinds(stats) {
      var box = $('kinds');
      box.textContent = '';
      box.appendChild(G.element('span', 'note', stats.sentences + ' предл. · ' + stats.tokens + ' слов и знаков · переписано ' +
        stats.changed + ':'));
      (stats.kinds || []).forEach(function (kind) {
        box.appendChild(G.element('span', 'kind-chip', kind.name + ' — ' + kind.count));
      });
    }

    /* --- чтение ---------------------------------------------------------------------- */

    function start(from) {
      if (!input.value.trim()) { G.toast('Сначала текст — потом чтение.'); return; }
      ensureParsed().then(function () {
        if (!player.sentences.length) { G.toast('В тексте нечего читать.'); return; }
        if (activeTab === 'text') { showTab('reading'); }
        player.play(from || 0);
      }, function () {});
    }

    $('play').addEventListener('click', function () {
      if (player.state === 'idle') { start(0); }
      else { player.toggle(); }
    });
    $('stop').addEventListener('click', function () { player.stop(); if (view) { view.clear(); } });
    $('next').addEventListener('click', function () { if (player.sentences.length) { player.next(); } });
    $('prev').addEventListener('click', function () { if (player.sentences.length) { player.prev(); } });

    document.addEventListener('keydown', function (event) {
      if (event.ctrlKey && event.key === 'Enter') { event.preventDefault(); start(0); }
      else if (event.key === 'Escape') { player.stop(); }
      else if (event.key === ' ' && document.activeElement === document.body && player.state !== 'idle') {
        event.preventDefault();
        player.toggle();
      }
    });

    input.addEventListener('input', function () {
      counter();
      if (player.state !== 'idle') { player.stop(); }
    });

    function counter() {
      var text = input.value;
      var words = (text.match(/[\wÄÖÜäöüß]+/g) || []).length;
      $('counter').textContent = text.length.toLocaleString('ru') + ' знаков · ' + words.toLocaleString('ru') +
        ' слов · около ' + Math.max(1, Math.round(words / 150)) + ' мин чтения';
    }
    counter();

    /* --- откуда взять текст ------------------------------------------------------------- */

    function setText(text, origin) {
      player.stop();
      input.value = text;
      counter();
      parsed = null;
      showTab('text');
      if (origin) { G.toast(origin); }
    }

    $('sample').addEventListener('click', function () { setText(input.defaultValue); });
    $('clear').addEventListener('click', function () { setText(''); input.focus(); });

    $('paste').addEventListener('click', function () {
      if (!navigator.clipboard || !navigator.clipboard.readText) {
        G.toast('Браузер не даёт читать буфер обмена — нажмите Ctrl+V в поле.');
        input.focus();
        return;
      }
      navigator.clipboard.readText().then(function (text) {
        if (!text.trim()) { G.toast('В буфере обмена нет текста.'); return; }
        setText(text, 'Текст из буфера обмена');
        start(0);
      }, function () {
        G.toast('Браузер не разрешил прочитать буфер обмена — нажмите Ctrl+V в поле.');
        input.focus();
      });
    });

    function upload(file) {
      if (!file) { return; }
      if (file.size > boot.maxUpload) { G.toast('Файл больше 20 МБ.'); return; }
      var form = new FormData();
      form.append('file', file);
      $('status-text').textContent = 'Открываю «' + file.name + '»…';
      fetch('/api/extract', { method: 'POST', body: form }).then(function (response) {
        return response.json().then(function (data) { data.ok = response.ok; return data; });
      }).then(function (data) {
        $('status-text').textContent = 'Готов читать';
        if (!data.ok) { G.toast(data.error || 'Файл не открылся.', 4500); return; }
        setText(data.text, '«' + data.title + '»' + (data.truncated ? ' — начало, текст слишком длинный' : ''));
      }, function () { G.toast('Сервер не отвечает.'); });
    }

    $('open-file').addEventListener('click', function () { $('file').click(); });
    $('file').addEventListener('change', function () { upload($('file').files[0]); $('file').value = ''; });
    input.addEventListener('dragover', function (event) { event.preventDefault(); input.classList.add('is-drop'); });
    input.addEventListener('dragleave', function () { input.classList.remove('is-drop'); });
    input.addEventListener('drop', function (event) {
      input.classList.remove('is-drop');
      if (event.dataTransfer && event.dataTransfer.files.length) {
        event.preventDefault();
        upload(event.dataTransfer.files[0]);
      }
    });

    $('open-url').addEventListener('click', function () {
      var url = global.prompt('Адрес страницы со статьёй (http… или https…):', 'https://de.wikipedia.org/wiki/Compiler');
      if (!url) { return; }
      $('status-text').textContent = 'Загружаю страницу…';
      G.api('POST', '/api/fetch', { url: url }).then(function (data) {
        $('status-text').textContent = 'Готов читать';
        if (data.error) { G.toast(data.error, 4500); return; }
        setText(data.text, '«' + data.title + '»');
      });
    });

    /* --- сохранить запись ------------------------------------------------------------- */

    $('save').addEventListener('click', function () {
      if (!input.value.trim()) { G.toast('Нечего сохранять.'); return; }
      var button = $('save');
      button.disabled = true;
      button.textContent = 'Синтезирую…';
      var prefs = settings.prefs();
      fetch('/api/render', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: input.value, options: prefs.options, settings: prefs.settings })
      }).then(function (response) {
        if (!response.ok) { return response.json().then(function (data) { throw new Error(data.error); }); }
        var disposition = response.headers.get('Content-Disposition') || '';
        var match = disposition.match(/filename\*=UTF-8''([^;]+)/);
        var name = match ? decodeURIComponent(match[1]) : 'glashatai.wav';
        return response.blob().then(function (blob) {
          var link = document.createElement('a');
          link.href = URL.createObjectURL(blob);
          link.download = name;
          document.body.appendChild(link);
          link.click();
          setTimeout(function () { URL.revokeObjectURL(link.href); link.remove(); }, 2000);
          G.toast('Сохранено: ' + name);
        });
      }).catch(function (problem) {
        G.toast('Не сохранено: ' + (problem.message || problem), 4500);
      }).then(function () {
        button.disabled = false;
        button.textContent = 'Сохранить WAV';
      });
    });

    /* --- транскрипция ---------------------------------------------------------------- */

    var phoneticsFor = null;
    function loadPhonetics() {
      if (!parsed || phoneticsFor === parsed.key) { return; }
      phoneticsFor = parsed.key;
      var box = $('phonetics');
      box.innerHTML = '<p class="muted">Строю транскрипцию…</p>';
      G.api('POST', '/api/transcribe', { text: parsed.text.slice(0, 3000), options: settings.prefs().options }).then(function (data) {
        box.textContent = '';
        if (data.error) { box.appendChild(G.element('p', 'bad', data.error)); return; }
        if (data.score && data.score.length) {
          box.appendChild(G.element('h3', '', 'Партитура первого предложения'));
          var score = G.element('div', 'score');
          data.score.forEach(function (item) {
            var cell = G.element('span', item.symbol === '_' ? 'pause' : item.stress === 1 ? 'stress' : '');
            cell.appendChild(G.element('b', '', item.symbol === '_' ? '·' : item.symbol));
            cell.appendChild(G.element('i', '', item.ms + ' мс'));
            cell.title = 'тон: ' + item.f0.map(function (v) { return v.toFixed(2); }).join(' → ');
            score.appendChild(cell);
          });
          box.appendChild(score);
        }
        box.appendChild(G.element('h3', '', 'Слова'));
        var table = G.element('table', 'grid trans-table');
        table.innerHTML = '<thead><tr><th>В тексте</th><th>Читается</th><th>Транскрипция (МФА)</th><th>Вид</th></tr></thead>';
        var body = G.element('tbody');
        data.words.slice(0, 400).forEach(function (word) {
          var row = G.element('tr');
          row.appendChild(G.element('td', '', word.source));
          row.appendChild(G.element('td', '', word.word));
          row.appendChild(G.element('td', 'ipa', '[' + word.ipa + ']'));
          row.appendChild(G.element('td', 'muted small', word.kind_ru + (word.rule === 'exception' ? ' · из таблицы' : '')));
          body.appendChild(row);
        });
        table.appendChild(body);
        box.appendChild(table);
        if (data.espeak) {
          box.appendChild(G.element('h3', '', 'Для сравнения: eSpeak NG'));
          box.appendChild(G.element('p', 'ipa', data.espeak));
        }
      });
    }

    /* --- голоса ------------------------------------------------------------------------- */

    var neural = (boot.voices || []).filter(function (voice) { return voice.engine === 'piper' && voice.available; });
    if (!neural.length) {
      var banner = $('voices-banner');
      banner.hidden = false;
      banner.textContent = 'Нейросетевые голоса не скачаны — сейчас читает собственный синтезатор системы. ' +
        'Чтобы появились Thorsten, Kerstin и Eva K: pip install piper-tts и python tools/get_voices.py.';
    }

    /* --- тексты из других программ ------------------------------------------------------ */

    if (global.EventSource) {
      var events = new global.EventSource('/api/events?role=reader');
      events.onmessage = function (message) {
        var event;
        try { event = JSON.parse(message.data); } catch (e) { return; }
        if (event.type === 'read' && event.text) {
          var origin = event.source === 'selection' ? 'Выделенное в другой программе' : 'Скопировано в буфер обмена';
          var banner = $('desk-banner');
          banner.hidden = false;
          banner.textContent = origin + ' — читаю. Остановить: Esc здесь или ' + 'Ctrl+Alt+S в любой программе.';
          setText(event.text);
          start(0);
        } else if (event.type === 'stop') {
          player.stop();
        }
      };
    }

    global.Glashatai.reader = { player: player, settings: settings, start: start, setText: setText,
                                parsed: function () { return parsed; } };
  });
})(window);
