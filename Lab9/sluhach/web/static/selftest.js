/* Проверка своим голосом на странице «Проверка».
 *
 * Страница показывает фразу, человек читает её вслух, система распознаёт
 * (тем же путём, что пульт: микрофон → /ws/listen → Vosk) и тут же
 * показывает, какие слова расслышала неверно и что бы сделала в ответ. После
 * десятой фразы — итог: доля ошибок в словах (WER), сколько фраз распознано
 * дословно, сколько команд выполнено верно — и те же числа у синтезатора.
 *
 * Круг одной фразы:
 *
 *   жду речь → слышу речь → распознаю → показываю разбор → «Дальше»
 *
 * Сервер ничего не запоминает: прочитанное хранится здесь и уходит на
 * оценку вместе с идентификаторами фраз.
 */

(function (global) {
  'use strict';

  var S = global.Sluhach;
  var METER_LOW = -70;
  var STATES = {
    starting: 'включаю микрофон…',
    waiting: 'жду речь',
    hearing: 'слышу речь',
    thinking: 'распознаю…',
    shown: 'разобрано'
  };
  /* настроение Пафнутия в углу, пока идёт проверка */
  var MOODS = { starting: 'idle', waiting: 'listening', hearing: 'hearing', thinking: 'thinking', shown: 'idle' };

  function percent(value, digits) {
    if (value === null || value === undefined) { return '—'; }
    return (100 * value).toFixed(digits === undefined ? 0 : digits).replace('.', ',') + ' %';
  }

  S.ready(function () {
    var root = document.getElementById('selftest');
    if (!root) { return; }
    var $ = function (id) { return document.getElementById(id); };
    var el = S.element;
    var boot = JSON.parse($('selftest-data').textContent);

    var stage = $('selftest-stage');
    var result = $('selftest-result');
    var idle = $('selftest-idle');
    var banner = $('selftest-banner');
    var heardBox = $('selftest-heard');
    var nextButton = $('selftest-next');
    var againButton = $('selftest-again');

    var language = boot.language;
    try {
      /* язык тот же, что выбран на пульте */
      var saved = JSON.parse(global.localStorage.getItem('sluhach-console') || '{}');
      if (boot.languages[saved.language]) { language = saved.language; }
    } catch (e) { /* настройки не сохранялись */ }

    var channel = null;
    var phrases = [];
    var index = 0;
    var answers = [];             /* распознанное по номерам фраз; пропущенная фраза — пустая строка */
    var state = 'idle';

    function setState(name) {
      state = name;
      stage.dataset.state = name;
      $('selftest-state').textContent = STATES[name] || '';
      if (S.companion && MOODS[name]) { S.companion.mood(MOODS[name]); }
    }

    function showBanner(text) {
      banner.hidden = !text;
      banner.textContent = text || '';
    }

    function markLanguage() {
      document.querySelectorAll('#selftest-language button').forEach(function (button) {
        button.classList.toggle('on', button.dataset.language === language);
      });
      var status = boot.status.languages[language];
      $('selftest-start').disabled = !(status && status.available);
      $('selftest-note').textContent = status && status.available
        ? 'Понадобится микрофон. Фразы каждый раз новые.'
        : 'Vosk для языка «' + boot.languages[language].name + '» не готов: ' + (status ? status.text : 'нет модели') +
          '. Скачайте модели: python tools/get_models.py.';
    }

    /* --- слова фразы с пометками ошибок ----------------------------------------- */

    function diff(alignment) {
      var box = el('span', 'diff');
      alignment.forEach(function (item, position) {
        if (position) { box.appendChild(document.createTextNode(' ')); }
        if (item.op === 'ok') {
          box.appendChild(document.createTextNode(item.said));
        } else if (item.op === 'sub') {
          var pair = el('span', 'w-sub');
          pair.appendChild(el('s', '', item.said));
          pair.appendChild(document.createTextNode(item.heard));
          pair.title = 'вместо «' + item.said + '» услышано «' + item.heard + '»';
          box.appendChild(pair);
        } else if (item.op === 'del') {
          var lost = el('span', 'w-del', item.said);
          lost.title = 'слово не услышано';
          box.appendChild(lost);
        } else {
          var extra = el('span', 'w-ins', item.heard);
          extra.title = 'лишнее слово';
          box.appendChild(extra);
        }
      });
      return box;
    }

    function verdict(entry) {
      var ok = entry.reaction_ok;
      /* у команды верна своя операция с тем же итогом, у предложения из сочинения — отсутствие операции */
      var text = (ok ? 'верно: ' : entry.kind === 'command' ? 'неверно: ' : 'ложное срабатывание: ') + entry.did;
      return el('span', ok ? 'verdict-ok' : 'verdict-bad', text);
    }

    /* --- одна фраза ----------------------------------------------------------------- */

    function showPhrase() {
      var phrase = phrases[index];
      $('selftest-count').textContent = 'Фраза ' + (index + 1) + ' из ' + phrases.length;
      $('selftest-kind').textContent = phrase.kind === 'command' ? 'команда «' + phrase.title + '»'
        : 'предложение из сочинения';
      $('selftest-phrase').textContent = phrase.text;
      heardBox.textContent = 'Прочитайте фразу вслух.';
      heardBox.classList.remove('is-partial');
      nextButton.hidden = true;
      againButton.hidden = true;
      $('selftest-skip').hidden = false;
      if (channel) { channel.mute(false); }
      setState(channel && channel.active ? 'waiting' : 'starting');
    }

    function accept(text) {
      answers[index] = text;
      if (channel) { channel.mute(true); }          /* пока показан разбор, микрофон не слушается */
      setState('thinking');
      var mine = index;
      S.api('POST', '/api/selftest/score', { items: [{ id: phrases[index].id, heard: text }] }).then(function (data) {
        if (index !== mine || state !== 'thinking') { return; }
        heardBox.textContent = '';
        heardBox.classList.remove('is-partial');
        var entry = data.items && data.items[0];
        if (!entry) {
          heardBox.textContent = 'Сервер не оценил фразу' + (data.error ? ': ' + data.error : '') + '.';
        } else {
          heardBox.appendChild(document.createTextNode(text ? 'Услышано: ' : 'Фраза пропущена. '));
          if (text) { heardBox.appendChild(diff(entry.alignment)); }
          heardBox.appendChild(document.createTextNode(' — '));
          heardBox.appendChild(verdict(entry));
        }
        nextButton.hidden = false;
        nextButton.textContent = index + 1 < phrases.length ? 'Дальше' : 'К итогу';
        againButton.hidden = false;
        $('selftest-skip').hidden = true;
        setState('shown');
        nextButton.focus();
      });
    }

    function next() {
      if (state !== 'shown') { return; }
      index++;
      if (index >= phrases.length) { finish(); } else { showPhrase(); }
    }

    function again() {
      if (state !== 'shown') { return; }
      answers[index] = undefined;
      showPhrase();
    }

    function onEvent(event) {
      if (state !== 'waiting' && state !== 'hearing') { return; }
      if (event.type === 'speech_start') {
        setState('hearing');
        heardBox.textContent = '…';
        heardBox.classList.add('is-partial');
      } else if (event.type === 'partial') {
        setState('hearing');
        heardBox.textContent = event.text;
        heardBox.classList.add('is-partial');
      } else if (event.type === 'speech_end' && event.dropped) {
        setState('waiting');
        heardBox.textContent = 'Короткий звук — не речь. Прочитайте фразу вслух.';
        heardBox.classList.remove('is-partial');
      } else if (event.type === 'final') {
        if (!event.text) {
          setState('waiting');
          heardBox.textContent = 'Слов не разобрал. Прочитайте фразу ещё раз.';
          heardBox.classList.remove('is-partial');
        } else {
          accept(event.text);
        }
      } else if (event.type === 'error') {
        abort(event.message);
      }
    }

    /* --- начало и конец ---------------------------------------------------------------- */

    function closeChannel() {
      if (channel) {
        var old = channel;
        channel = null;
        old.stop();
      }
      $('selftest-meter').style.width = '0';
    }

    function abort(message) {
      closeChannel();
      stage.hidden = true;
      idle.hidden = false;
      setState('idle');
      if (S.companion) { S.companion.mood('idle'); }
      showBanner(message);
    }

    function start() {
      showBanner('');
      result.hidden = true;
      $('selftest-start').disabled = true;
      /* ?seed=… в адресе страницы — всегда один и тот же набор фраз: для показа и автоматических проверок */
      var seed = new global.URLSearchParams(global.location.search).get('seed');
      S.api('GET', '/api/selftest/phrases?language=' + encodeURIComponent(language) +
        (seed ? '&seed=' + encodeURIComponent(seed) : '')).then(function (data) {
        $('selftest-start').disabled = false;
        if (data.error || !(data.phrases && data.phrases.length)) {
          showBanner('Не удалось получить фразы' + (data.error ? ': ' + data.error : '') + '.');
          return;
        }
        phrases = data.phrases;
        answers = [];
        index = 0;
        idle.hidden = true;
        stage.hidden = false;
        showPhrase();
        var line = S.pick(boot.lines, 'selftest_start');
        if (line) { S.say(line, { fresh: true }); }

        var mine = new S.Channel({
          language: language, pause: boot.pause,
          onLevel: function (db) {
            if (channel === mine) {
              $('selftest-meter').style.width = (100 * S.micRules.scale(db, METER_LOW, 0)) + '%';
            }
          },
          onEvent: function (event) { if (channel === mine) { onEvent(event); } },
          onReady: function () { if (channel === mine && state === 'starting') { setState('waiting'); } },
          onClose: function () { if (channel === mine) { abort('Связь с сервером распознавания прервалась.'); } }
        });
        channel = mine;
        mine.start().catch(function (problem) {
          if (channel === mine) {
            abort('Микрофон не включился: ' + (problem && problem.name ? S.Mic.describe(problem)
              : String((problem && problem.message) || problem)) + '.');
          }
        });
      });
    }

    function finish() {
      closeChannel();
      stage.hidden = true;
      idle.hidden = false;
      setState('idle');
      if (S.companion) { S.companion.mood('idle'); }
      $('selftest-start').textContent = 'Проверить ещё раз';
      var items = [];
      phrases.forEach(function (phrase, position) {
        if (answers[position] !== undefined) { items.push({ id: phrase.id, heard: answers[position] }); }
      });
      if (!items.length) { return; }
      S.api('POST', '/api/selftest/score', { items: items }).then(function (data) {
        if (data.error || !data.totals) {
          showBanner('Сервер не посчитал итог' + (data.error ? ': ' + data.error : '') + '.');
          return;
        }
        render(data);
      });
    }

    /* --- итог ------------------------------------------------------------------------- */

    function card(title, big, note) {
      var box = el('div', 'card');
      box.appendChild(el('h3', '', title));
      box.appendChild(el('span', 'big', big));
      box.appendChild(el('p', 'note', note));
      return box;
    }

    function render(data) {
      var all = data.totals.all;
      var commands = data.totals.command;
      var sentences = data.totals.sentence;
      var synthetic = data.synthetic;
      result.textContent = '';
      result.appendChild(el('h3', '', 'Ваш результат — ' + boot.languages[data.language || language].name +
        ', фраз прочитано: ' + all.phrases));

      var cards = el('div', 'cards');
      cards.appendChild(card('Ошибок в словах (WER)', percent(all.wer, 1),
        'ошибок — ' + all.errors + ' на ' + all.words + ' слов' + (synthetic
          ? '; у синтезатора: команды ' + percent(synthetic.command.wer, 1) + ', предложения ' +
            percent(synthetic.sentence.wer, 1) : '')));
      cards.appendChild(card('Распознано дословно', all.exact + ' из ' + all.phrases,
        'остальные фразы — с ошибкой хотя бы в одном слове'));
      if (commands.phrases) {
        cards.appendChild(card('Команды выполнены верно', commands.reaction_ok + ' из ' + commands.phrases,
          'та же операция с тем же итогом, что по эталонной фразе' + (synthetic
            ? '; у синтезатора — ' + percent(synthetic.command.reaction, 1) : '')));
      }
      if (sentences.phrases) {
        cards.appendChild(card('Без ложных срабатываний', sentences.reaction_ok + ' из ' + sentences.phrases,
          'предложение из сочинения система должна повторить, а не принять за команду'));
      }
      result.appendChild(cards);

      var table = el('table', 'grid');
      var head = el('tr');
      ['№', 'Фраза и что в ней услышано', 'Ошибок', 'Реакция системы'].forEach(function (title, position) {
        head.appendChild(el('th', position === 2 ? 'num' : '', title));
      });
      table.appendChild(el('thead')).appendChild(head);
      var body = el('tbody');
      data.items.forEach(function (entry, position) {
        var row = el('tr');
        row.appendChild(el('td', 'num', String(position + 1)));
        var cell = el('td');
        if (entry.heard) { cell.appendChild(diff(entry.alignment)); }
        else {
          cell.appendChild(el('span', 'w-del', entry.text));
          cell.appendChild(el('span', 'note', ' — пропущена'));
        }
        cell.appendChild(el('div', 'small muted', entry.kind === 'command' ? 'команда «' + entry.title + '»'
          : 'предложение из сочинения'));
        row.appendChild(cell);
        row.appendChild(el('td', 'num', entry.errors + ' из ' + entry.words));
        row.appendChild(el('td')).appendChild(verdict(entry));
        body.appendChild(row);
      });
      table.appendChild(body);
      result.appendChild(table);
      result.appendChild(el('p', 'note selftest-legend', 'Зачёркнутое слово не услышано; красным — услышанное ' +
        'вместо него; слово с плюсом — лишнее. Результат нигде не сохраняется: это проверка для вас, а не для отчёта ' +
        'системы.'));
      result.hidden = false;

      /* оценка для реплики: по командам, а если их не было — по словам */
      var share = commands.phrases ? commands.reaction_ok / commands.phrases : 1 - Math.min(1, all.wer || 0);
      var line = S.pick(boot.lines, share >= 0.9 && (all.wer || 0) <= 0.15 ? 'selftest_good'
        : share >= 0.6 ? 'selftest_fair' : 'selftest_poor');
      if (line) { S.say(line, { fresh: true }); }
    }

    /* --- управление --------------------------------------------------------------------- */

    document.querySelectorAll('#selftest-language button').forEach(function (button) {
      button.addEventListener('click', function () {
        if (button.dataset.language === language) { return; }
        if (state !== 'idle') { abort(''); }
        language = button.dataset.language;
        result.hidden = true;
        markLanguage();
      });
    });
    $('selftest-start').addEventListener('click', start);
    nextButton.addEventListener('click', next);
    againButton.addEventListener('click', again);
    $('selftest-skip').addEventListener('click', function () {
      if (state === 'waiting' || state === 'hearing' || state === 'starting') { accept(''); }
    });
    $('selftest-stop').addEventListener('click', finish);
    global.addEventListener('pagehide', closeChannel);

    markLanguage();

    /* для проверок из консоли браузера и автоматических снимков */
    global.Sluhach.selftest = {
      state: function () { return { state: state, index: index, answers: answers.slice(), language: language }; },
      start: start, next: next, finish: finish,
      hear: function (text) { if (state === 'waiting' || state === 'hearing' || state === 'starting') { accept(text); } }
    };
  });
})(window);
