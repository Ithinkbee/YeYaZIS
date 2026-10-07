/* Пульт «Слухача»: микрофон, распознавание, реакция и уведомления.
 *
 * Страница ведёт разговор по кругу:
 *
 *   жду речь → слышу речь → распознаю → отвечаю → жду речь
 *
 * и о каждом шаге сообщает — надписью и цветом монитора, шкалой уровня,
 * позой Пафнутия, строкой в журнале. Звук идёт на сервер по WebSocket; там
 * детектор находит в нём речь, а Vosk распознаёт (второй способ —
 * распознаватель самого браузера). Готовая фраза уходит на /api/react,
 * сервер возвращает реакцию: что сказать, что показать, что изменить на
 * странице. Ответ звучит голосом и дублируется в облачке Пафнутия.
 *
 * Состояние разговора (язык, открытое сочинение, абзац, черновик диктовки)
 * хранится здесь и передаётся серверу с каждой фразой.
 *
 * Во время диктовки круг короче: записанная фраза не произносится, поэтому
 * после «распознаю» система сразу снова ждёт речь.
 */

(function (global) {
  'use strict';

  var S = global.Sluhach;
  var STORE = 'sluhach-console';
  var DRAFT_STORE = 'sluhach-draft';
  var METER_LOW = -70;          /* левый край шкалы уровня, дБ */

  /* состояние -> [заголовок, пояснение, настроение Пафнутия] */
  var PHASES = {
    off: ['Микрофон выключен', 'Нажмите «Слушать» и говорите — или введите фразу с клавиатуры.', 'sleeping'],
    starting: ['Включаюсь…', 'Запрашиваю микрофон и готовлю распознаватель.', 'idle'],
    waiting: ['Жду речь', 'Говорите {language} — начало фразы я замечу сам.', 'listening'],
    hearing: ['Слышу речь', 'Распознаю на лету; конец фразы определю по паузе.', 'hearing'],
    thinking: ['Распознаю', 'Фраза закончилась — подбираю операцию.', 'thinking'],
    speaking: ['Отвечаю', 'Ответ звучит голосом и показан текстом.', 'speaking'],
    error: ['Не получилось', '', 'dizzy']
  };
  /* то же во время диктовки: [заголовок, пояснение] */
  var DICTATION = {
    waiting: ['Жду диктовку', 'Диктуйте {language}: каждая фраза дописывается в текст.'],
    hearing: ['Слышу речь', 'Фраза уйдёт в текст после паузы.'],
    thinking: ['Записываю', 'Фраза закончилась — дописываю её в текст.']
  };
  var SOURCES = { vosk: 'микрофон · Vosk', browser: 'микрофон · браузер', keyboard: 'клавиатура', click: 'щелчок' };
  var KINDS = { echo: 'повтор фразы', egg: 'особый ответ', dictation: 'диктовка', noise: 'не речь', silence: 'тишина' };
  var SAMPLES = { de: 'Guten Tag. Ich bin Pafnuti und höre zu.', ru: 'Здравствуйте. Я Пафнутий, слушаю вас.' };

  S.ready(function () {
    var root = document.getElementById('console');
    if (!root) { return; }
    var $ = function (id) { return document.getElementById(id); };
    var boot = JSON.parse($('console-data').textContent);
    var el = S.element;

    var monitor = $('monitor');
    var listenButton = $('listen-toggle');
    var engineBox = $('engine');
    var banner = $('console-banner');
    var heardBox = $('heard');
    var answerBox = $('answer');
    var stopButton = $('answer-stop');
    var panel = $('essay-panel');
    var journal = $('journal');
    var cheat = $('cheat');
    var meter = $('meter');
    var meterFill = $('meter-fill');
    var meterMark = $('meter-mark');
    var meterCaption = $('meter-caption');

    /* --- настройки и состояние -------------------------------------------- */

    var prefs = { engine: boot.engine, language: boot.language, duplex: false, margin: boot.vad.margin, pause: boot.vad.pause };
    try {
      var saved = JSON.parse(global.localStorage.getItem(STORE) || '{}');
      if (boot.engines[saved.engine]) { prefs.engine = saved.engine; }
      if (boot.languages[saved.language]) { prefs.language = saved.language; }
      if (typeof saved.duplex === 'boolean') { prefs.duplex = saved.duplex; }
      if (saved.margin >= boot.vad.marginRange[0] && saved.margin <= boot.vad.marginRange[1]) { prefs.margin = saved.margin; }
      if (saved.pause >= boot.vad.pauseRange[0] && saved.pause <= boot.vad.pauseRange[1]) { prefs.pause = saved.pause; }
    } catch (e) { /* настройки не сохранялись */ }

    function savePrefs() {
      try { global.localStorage.setItem(STORE, JSON.stringify(prefs)); } catch (e) { /* без хранилища */ }
    }

    var session = { language: prefs.language, essay: '', paragraph: 0, last_reply: '', last_language: '', draft: null };
    /* черновик диктовки переживает перезагрузку страницы: надиктованное жалко терять */
    try {
      var kept = JSON.parse(global.localStorage.getItem(DRAFT_STORE) || 'null');
      if (kept && kept.draft && typeof kept.draft.text === 'string' && boot.languages[kept.language]) {
        session.language = prefs.language = kept.language;
        session.draft = kept.draft;
      }
    } catch (e) { /* черновика не было */ }

    function saveDraft() {
      try {
        if (session.draft) {
          global.localStorage.setItem(DRAFT_STORE, JSON.stringify({ language: session.language, draft: session.draft }));
        } else {
          global.localStorage.removeItem(DRAFT_STORE);
        }
      } catch (e) { /* без хранилища */ }
    }
    var phase = 'off';
    var listening = false;        /* пользователь включил «Слушать» */
    var muted = false;            /* система говорит сама и себя не слушает */
    var mic = null;               /* микрофон ради шкалы уровня, когда распознаёт браузер */
    var channel = null;           /* микрофон и соединение с сервером, когда распознаёт Vosk */
    var recognition = null;
    var restartTimer = null;
    var essays = {};              /* сочинения, уже полученные с сервера */
    var shown = { essay: null, marks: '' };
    var marks = [];               /* словоформы, отмеченные поиском */
    var reading = -1;             /* абзац, который сейчас читается вслух */
    var after = null;             /* что сделать, когда ответ отзвучит */
    var level = S.micRules.SILENCE_DB;
    var levelShown = METER_LOW;
    var threshold = null;
    var voiceless = {};           /* языки, о нехватке голоса для которых уже сказано */

    /* --- уведомления --------------------------------------------------------- */

    function languageWord(code) {
      return code === 'de' ? 'по-немецки' : 'по-русски';
    }

    function setPhase(name, note) {
      phase = name;
      monitor.dataset.state = name;
      var texts = (session.draft && DICTATION[name]) || PHASES[name];
      $('state-title').textContent = texts[0];
      $('state-note').textContent = (note || texts[1]).replace('{language}', languageWord(session.language));
      S.companion.mood(PHASES[name][2]);
      meter.classList.toggle('is-speech', name === 'hearing');
      stopButton.hidden = name !== 'speaking';
    }

    function rest(note) {
      setPhase(listening ? 'waiting' : 'off', note);
    }

    function showBanner(text, kind) {
      banner.hidden = !text;
      banner.className = 'banner ' + (kind || 'warn-banner');
      banner.textContent = text || '';
    }

    function showHeard(text, partial) {
      heardBox.textContent = text;
      heardBox.classList.toggle('is-partial', !!partial);
    }

    function clock() {
      var now = new Date();
      var two = function (value) { return ('0' + value).slice(-2); };
      return two(now.getHours()) + ':' + two(now.getMinutes()) + ':' + two(now.getSeconds());
    }

    function percent(value) {
      return Math.round(value * 100) + ' %';
    }

    /* Запись в журнал: что услышано, чем это сочтено и что отвечено. */
    function record(kind, label, details, heard, reply, gloss, who) {
      var empty = journal.querySelector('.journal-empty');
      if (empty) { empty.remove(); }
      var item = el('li');
      var head = el('div', 'j-head');
      head.appendChild(el('span', 'j-time', clock()));
      head.appendChild(el('span', 'j-kind j-kind-' + kind, label));
      head.appendChild(el('span', 'j-details', details.filter(Boolean).join(' · ')));
      item.appendChild(head);
      if (heard) { item.appendChild(el('div', 'j-heard', '«' + heard + '»')); }
      if (reply) {
        var line = el('div', 'j-reply', '«' + reply + '»');
        line.dataset.who = who || boot.voice;
        item.appendChild(line);
      }
      if (gloss) { item.appendChild(el('div', 'j-gloss', gloss)); }
      journal.insertBefore(item, journal.firstChild);
      while (journal.children.length > 60) { journal.removeChild(journal.lastChild); }
    }

    function note(text, kind) {
      record(kind || 'note', kind === 'error' ? 'ошибка' : 'сообщение', [], '', '', text);
    }

    /* --- шкала уровня ---------------------------------------------------------- */

    function micOn() {
      return !!((mic && mic.active) || (channel && channel.active));
    }

    function drawMeter() {
      var target = micOn() ? level : METER_LOW;
      levelShown += (Math.max(METER_LOW, target) - levelShown) * 0.35;
      meterFill.style.width = (100 * S.micRules.scale(levelShown, METER_LOW, 0)) + '%';
      meterCaption.textContent = micOn() ? String(Math.round(levelShown)).replace('-', '−') + ' дБ' : '';
      if (threshold !== null && micOn() && prefs.engine === 'vosk') {
        meterMark.style.left = (100 * S.micRules.scale(threshold, METER_LOW, 0)) + '%';
        meterMark.title = 'порог речи: ' + Math.round(threshold) + ' дБ';
      } else {
        meterMark.style.left = '-10px';
      }
      global.requestAnimationFrame(drawMeter);
    }

    /* --- микрофон и распознавание ------------------------------------------- */

    function fail(message) {
      stopListening();
      setPhase('error', message);
      note(message, 'error');
    }

    function send(message) {
      if (channel) { channel.send(message); }
    }

    function onServerEvent(event) {
      if (event.type === 'level') {
        threshold = event.threshold;
      } else if (event.type === 'speech_start') {
        threshold = event.threshold;
        if (phase === 'waiting') { setPhase('hearing'); }
        showHeard('…', true);
      } else if (event.type === 'partial') {
        if (phase === 'waiting') { setPhase('hearing'); }
        showHeard(event.text, true);
      } else if (event.type === 'speech_end') {
        if (event.dropped) {
          showHeard('', false);
          if (phase === 'hearing') { rest('Короткий звук — не речь. Жду дальше.'); }
        } else if (phase === 'hearing') {
          setPhase('thinking');
        }
      } else if (event.type === 'final') {
        if (!event.text) {
          showHeard('', false);
          record('noise', KINDS.noise, [SOURCES.vosk], '', '', 'Звук был, а слов в нём распознаватель не нашёл — порог речи поднят.');
          rest('Слов не разобрал. Жду дальше.');
          return;
        }
        submit(event.text, {
          source: 'vosk', confidence: event.confidence,
          timing: 'фраза ' + (event.duration_ms / 1000).toFixed(1).replace('.', ',') + ' с, распознавание ' +
            Math.round(event.recognition_ms) + ' мс'
        });
      } else if (event.type === 'error') {
        fail(event.message);
      }
    }

    function startVosk() {
      var state = boot.status.languages[session.language];
      if (!state || !state.available) {
        fail('Vosk не готов: ' + (state ? state.text : 'нет модели') + '. Скачайте модели (python tools/get_models.py) ' +
          'или выберите распознавание в браузере.');
        return;
      }
      var mine = new S.Channel({
        language: session.language, margin: prefs.margin, pause: prefs.pause,
        onLevel: function (db) { level = db; },
        onEvent: function (event) { if (channel === mine) { onServerEvent(event); } },
        onReady: function () { if (channel === mine) { setPhase('waiting'); } },
        onClose: function () {
          if (channel === mine && listening) { fail('Связь с сервером распознавания прервалась.'); }
        }
      });
      channel = mine;
      mine.start().catch(function (problem) {
        if (channel === mine) {
          fail(problem && problem.name ? S.Mic.describe(problem) : String((problem && problem.message) || problem));
        }
      });
    }

    function createRecognition() {
      var Recognition = global.SpeechRecognition || global.webkitSpeechRecognition;
      var mine = new Recognition();
      mine.lang = boot.languages[session.language].tag;
      mine.continuous = true;
      mine.interimResults = true;
      mine.maxAlternatives = 1;
      mine.onstart = function () {
        if (recognition === mine && (phase === 'starting' || phase === 'off')) { setPhase('waiting'); }
      };
      mine.onspeechstart = function () {
        if (recognition === mine && phase === 'waiting') { setPhase('hearing'); }
      };
      mine.onresult = function (event) {
        if (recognition !== mine || muted) { return; }
        var interim = '';
        for (var i = event.resultIndex; i < event.results.length; i++) {
          var result = event.results[i];
          if (result.isFinal) {
            var text = result[0].transcript.trim();
            if (text) { submit(text, { source: 'browser', confidence: result[0].confidence || null }); }
            interim = '';
          } else {
            interim += result[0].transcript;
          }
        }
        if (interim) {
          if (phase === 'waiting') { setPhase('hearing'); }
          showHeard(interim.trim(), true);
        }
      };
      mine.onerror = function (event) {
        if (recognition !== mine) { return; }
        var code = event.error;
        if (code === 'no-speech' || code === 'aborted') { return; }       /* тишина и наша собственная остановка */
        if (code === 'not-allowed' || code === 'service-not-allowed') {
          fail('Браузер не дал доступ к микрофону или к распознаванию речи.');
        } else if (code === 'network') {
          fail('Распознаватель браузера не достучался до сети — он работает только с интернетом. Выберите Vosk.');
        } else if (code === 'language-not-supported') {
          fail('Распознаватель браузера не знает этого языка.');
        } else {
          fail('Распознаватель браузера сообщил об ошибке: ' + code + '.');
        }
      };
      mine.onend = function () {
        /* браузер сам останавливает распознавание после паузы — запускаем снова */
        if (recognition === mine && listening && !muted) {
          clearTimeout(restartTimer);
          restartTimer = setTimeout(function () {
            if (recognition === mine && listening && !muted) { runRecognition(); }
          }, 250);
        }
      };
      return mine;
    }

    function runRecognition() {
      if (recognition) {
        var old = recognition;
        recognition = null;
        try { old.abort(); } catch (e) { /* уже остановлен */ }
      }
      recognition = createRecognition();
      try { recognition.start(); } catch (e) { /* уже запущен */ }
    }

    function startBrowser() {
      if (!(global.SpeechRecognition || global.webkitSpeechRecognition)) {
        fail('В этом браузере нет распознавания речи (Web Speech API есть в Chrome и Edge). Выберите Vosk.');
        return;
      }
      /* микрофон здесь нужен только для шкалы уровня: звук распознаёт сам браузер */
      mic = new S.Mic({ pcm: false, processing: true, onLevel: function (db) { level = db; } });
      mic.start().catch(function () { /* без шкалы можно обойтись */ });
      runRecognition();
    }

    function startListening() {
      if (listening) { return; }
      listening = true;
      listenButton.classList.add('on');
      $('listen-label').textContent = 'Не слушать';
      showBanner('');
      setPhase('starting');
      if (prefs.engine === 'browser') { startBrowser(); } else { startVosk(); }
    }

    function stopListening(message) {
      listening = false;
      muted = false;
      clearTimeout(restartTimer);
      listenButton.classList.remove('on');
      $('listen-label').textContent = 'Слушать';
      if (channel) {
        var old = channel;
        channel = null;
        old.stop();
      }
      if (recognition) {
        var stale = recognition;
        recognition = null;
        try { stale.abort(); } catch (e) { /* уже остановлен */ }
      }
      if (mic) { mic.stop(); mic = null; }
      threshold = null;
      if (phase !== 'speaking') { setPhase('off', message); }
    }

    /* Пока звучит ответ, система себя не слушает: иначе она распознала бы
       собственный голос из колонок и ответила бы сама себе. */
    function mute(on) {
      if (prefs.duplex) { on = false; }
      if (on === muted) { return; }
      muted = on;
      if (channel) { channel.mute(on); }
      if (prefs.engine === 'browser' && listening) {
        if (on) {
          if (recognition) { try { recognition.abort(); } catch (e) { /* уже остановлен */ } }
        } else {
          runRecognition();
        }
      }
    }

    /* --- реакция ----------------------------------------------------------------- */

    function submit(text, meta) {
      showHeard(text, false);
      setPhase('thinking', 'Услышал: «' + text + '». ' + (session.draft ? 'Записываю.' : 'Подбираю операцию.'));
      S.api('POST', '/api/react', {
        text: text, session: session, source: meta.source, confidence: meta.confidence
      }).then(function (reaction) {
        if (reaction.error) {
          note('Сервер не ответил на фразу: ' + reaction.error + '.', 'error');
          rest();
          return;
        }
        react(reaction, meta);
      });
    }

    /* Операция, вызванная кнопкой страницы, а не фразой. */
    function act(action) {
      S.api('POST', '/api/react', { text: '', action: action, session: session }).then(function (reaction) {
        if (reaction.error) {
          note('Сервер не ответил: ' + reaction.error + '.', 'error');
          return;
        }
        react(reaction, { source: 'click' });
      });
    }

    function react(reaction, meta) {
      var previous = session.language;
      session = reaction.session;
      saveDraft();
      var details = [SOURCES[meta.source] || meta.source];
      if (typeof meta.confidence === 'number') { details.push('уверенность ' + percent(meta.confidence)); }
      if (reaction.score !== null && reaction.kind === 'operation') { details.push('сходство ' + percent(reaction.score)); }
      if (meta.timing) { details.push(meta.timing); }

      if (reaction.kind === 'noise' || reaction.kind === 'silence') {
        record('noise', KINDS[reaction.kind], details, reaction.heard, '', 'Слишком коротко для фразы — не отвечаю.');
        rest('«' + reaction.heard + '» — не похоже на фразу. Жду дальше.');
        return;
      }

      if (reaction.kind === 'dictation') {
        /* фраза ушла в текст: вслух она не повторяется, чтобы не перебивать диктующего */
        record('dictation', KINDS.dictation, details, reaction.heard, reaction.display, '', 'в текст');
        render();
        answerBox.textContent = '✎ ' + reaction.display;
        S.say('✎ ' + reaction.display, { fresh: true });
        rest();
        return;
      }

      var gloss = reaction.gloss ? 'перевод: ' + reaction.gloss : '';
      if (reaction.kind === 'echo' && reaction.near.length) {
        gloss = (gloss ? gloss + ' · ' : '') + 'операция не найдена; ближе всего «' + reaction.near[0].title + '» — ' +
          percent(Math.max(0, reaction.near[0].score)) + ' при пороге ' + percent(boot.threshold);
      }
      var label = reaction.kind === 'operation' ? reaction.title : KINDS[reaction.kind];
      record(reaction.kind, label, details, reaction.heard, reaction.display, gloss);

      marksFrom(reaction);
      reaction.effects.forEach(function (effect) {
        if (effect.type === 'language') { applyLanguage(effect.code, previous); }
        else if (effect.type === 'read') { reading = effect.index; }
        else if (effect.type === 'silence') { S.voice.cancel(); }
        else if (effect.type === 'sleep') { after = { sleep: true }; }
        else if (effect.type === 'navigate') { after = { url: effect.url }; }
        else if (effect.type === 'cheatsheet') { flashCheat(); }
        else if (effect.type === 'essays') { boot.essays[effect.language] = effect.items; essays = {}; }
      });
      render();
      answer(reaction, label);
    }

    function marksFrom(reaction) {
      var changed = shown.essay !== session.essay;
      reaction.effects.forEach(function (effect) {
        if (effect.type === 'highlight') { marks = effect.forms || []; changed = false; }
      });
      if (changed) { marks = []; }
    }

    function answer(reaction, label) {
      answerBox.textContent = '';
      answerBox.appendChild(document.createTextNode(reaction.display));
      if (reaction.gloss) { answerBox.appendChild(el('span', 'answer-gloss', reaction.gloss)); }
      if (!reaction.speech) {
        /* ответ без голоса — так отвечают операции диктовки: показан текстом, и сразу слушаем дальше */
        S.say(reaction.display, { fresh: true });
        rest();
        return;
      }
      /* тот же ответ — текстом от лица Пафнутия */
      S.say(reaction.display, { sticky: true, fresh: true });
      setPhase('speaking', reaction.kind === 'operation' ? 'Операция «' + label + '» выполнена — отвечаю.'
        : reaction.kind === 'egg' ? 'На эту фразу у меня особый ответ.' : 'Такой операции нет — повторяю услышанное.');
      mute(true);
      var language = reaction.speech_language || session.language;
      S.voice.speak(reaction.speech, boot.languages[language].tag, {
        onend: function (reason) {
          if (reason === 'no-voice' && !voiceless[language]) {
            voiceless[language] = true;
            note('В браузере нет голоса для языка «' + boot.languages[language].name + '» — ответ показан только текстом. ' +
              'Голоса ставятся в параметрах Windows: «Время и язык» → «Речь».');
          }
          spoken(reason === 'end' ? 2500 : 5000);
        }
      });
    }

    /* Ответ отзвучал (или оборван): снова слушаем. */
    function spoken(hold) {
      reading = -1;
      updateParagraphs();
      S.hush(hold);
      var todo = after;
      after = null;
      if (todo && todo.url) {
        stopListening();
        global.location.href = todo.url;
        return;
      }
      /* хвост ответа ещё звучит в комнате — микрофон открывается чуть позже */
      setTimeout(function () { mute(false); }, 350);
      if (todo && todo.sleep) {
        stopListening('Микрофон выключен по команде. Нажмите «Слушать», когда понадоблюсь.');
        setPhase('off', 'Микрофон выключен по команде. Нажмите «Слушать», когда понадоблюсь.');
        return;
      }
      rest();
    }

    function stopSpeaking() {
      if (S.voice.cancel() || phase === 'speaking') { spoken(1500); }
    }

    /* Обрывает ответ без продолжения: пользователь сам сменил язык или сочинение. */
    function silence() {
      S.voice.cancel();
      after = null;
      reading = -1;
      mute(false);
      S.hush(600);
    }

    /* --- язык ---------------------------------------------------------------------- */

    function applyLanguage(code, previous) {
      if (!boot.languages[code]) { return; }
      session.language = code;
      prefs.language = code;
      savePrefs();
      document.querySelectorAll('#language-switch button').forEach(function (button) {
        button.classList.toggle('on', button.dataset.language === code);
      });
      send({ type: 'language', code: code });
      if (prefs.engine === 'browser' && listening && !muted) { runRecognition(); }
      if (previous !== code) { marks = []; }
      renderCheat();
      checkEngine();
    }

    function chooseLanguage(code) {
      if (code === session.language) { return; }
      silence();
      /* черновик диктовки при смене языка остаётся: дальше диктуют на новом языке */
      session = { language: code, essay: '', paragraph: 0, last_reply: '', last_language: '', draft: session.draft };
      saveDraft();
      shown = { essay: null, marks: '' };
      applyLanguage(code, null);
      render();
      rest('Язык речи: ' + boot.languages[code].name + '.');
      note('Язык речи и ответов — ' + boot.languages[code].name + '.');
    }

    function checkEngine() {
      var state = boot.status.languages[session.language];
      if (prefs.engine === 'vosk' && (!state || !state.available)) {
        showBanner('Для языка «' + boot.languages[session.language].name + '» Vosk не готов: ' +
          (state ? state.text : 'нет модели') + '. Скачайте модели командой python tools/get_models.py или выберите ' +
          'распознавание в браузере.');
      } else if (prefs.engine === 'browser' && !(global.SpeechRecognition || global.webkitSpeechRecognition)) {
        showBanner('В этом браузере нет распознавания речи (Web Speech API есть в Chrome и Edge). Выберите Vosk.');
      } else {
        showBanner('');
      }
    }

    /* --- сочинения ----------------------------------------------------------------- */

    function plural(number, one, few, many) {
      var tail = number % 100;
      if (number % 10 === 1 && tail !== 11) { return one; }
      if (number % 10 >= 2 && number % 10 <= 4 && (tail < 12 || tail > 14)) { return few; }
      return many;
    }

    function renderList() {
      var list = boot.essays[session.language] || [];
      panel.textContent = '';
      var head = el('div', 'block-head');
      head.appendChild(el('h2', '', 'Сочинения'));
      head.appendChild(el('span', 'tag tag-' + session.language, boot.languages[session.language].name));
      var open = boot.examples[session.language].open;
      var dictate = boot.examples[session.language].dictate;
      var start = el('button', 'ghost small-button', '✎ Диктовать');
      start.type = 'button';
      start.id = 'dictate-start';
      start.title = 'Надиктовать своё сочинение' + (dictate ? ': то же, что сказать «' + dictate + '»' : '');
      start.addEventListener('click', function () { act('dictate'); });
      head.appendChild(start);
      panel.appendChild(head);
      panel.appendChild(el('p', 'note', (open
        ? 'Скажите «' + open + '» — или назовите произведение, героя, автора. Можно и щёлкнуть.'
        : 'Операция «Открыть сочинение» выключена — сочинение открывается щелчком.') +
        (dictate ? ' Своё сочинение можно надиктовать: «' + dictate + '».' : '')));
      var items = el('ol', 'essay-list');
      list.forEach(function (essay) {
        var item = el('li');
        var button = el('button', 'essay-item');
        button.type = 'button';
        button.appendChild(el('span', 'essay-title', essay.title));
        button.appendChild(el('span', 'essay-size', essay.paragraphs + ' ' +
          plural(essay.paragraphs, 'абзац', 'абзаца', 'абзацев')));
        button.appendChild(el('span', 'essay-about', essay.dictated ? 'надиктовано ' + essay.created
          : essay.language === 'ru' ? essay.about : essay.about + ' · «' + essay.title_ru + '», ' + essay.about_ru));
        if (essay.dictated) { button.classList.add('is-dictated'); }
        button.addEventListener('click', function () { openEssay(essay.id); });
        item.appendChild(button);
        items.appendChild(item);
      });
      if (!list.length) { panel.appendChild(el('p', 'note', 'На этом языке сочинений нет.')); }
      panel.appendChild(items);
      shown = { essay: '', marks: '' };
    }

    function openEssay(id) {
      silence();
      session.essay = id;
      session.paragraph = 0;
      marks = [];
      render();
      rest();
    }

    /* Текст абзаца с отмеченными словоформами, найденными поиском. */
    function fill(node, text) {
      node.textContent = '';
      if (!marks.length) { node.textContent = text; return; }
      var escaped = marks.map(function (form) { return form.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); });
      var pattern;
      try {
        pattern = new RegExp('(?<![\\p{L}])(' + escaped.join('|') + ')(?![\\p{L}])', 'gu');
      } catch (e) {
        node.textContent = text;
        return;
      }
      var last = 0;
      text.replace(pattern, function (match, _group, offset) {
        node.appendChild(document.createTextNode(text.slice(last, offset)));
        node.appendChild(el('mark', '', match));
        last = offset + match.length;
        return match;
      });
      node.appendChild(document.createTextNode(text.slice(last)));
    }

    function renderEssay() {
      var essay = essays[session.essay];
      if (!essay) {
        panel.textContent = '';
        panel.appendChild(el('p', 'note', 'Загружаю сочинение…'));
        var wanted = session.essay;
        S.api('GET', '/api/essay/' + encodeURIComponent(wanted)).then(function (data) {
          if (data.error) { note('Сочинение не загрузилось: ' + data.error + '.', 'error'); return; }
          essays[wanted] = data;
          if (session.essay === wanted) { render(); }
        });
        shown = { essay: null, marks: '' };
        return;
      }
      var key = marks.join('|');
      if (shown.essay === essay.id && shown.marks === key) { updateParagraphs(); return; }

      panel.textContent = '';
      var head = el('div', 'essay-head');
      var title = el('div');
      title.appendChild(el('h2', '', essay.title));
      title.appendChild(el('p', 'essay-meta', (essay.language === 'ru' ? essay.about
        : essay.about + ' · ' + essay.about_ru) + ' · ' + essay.paragraphs + ' ' +
        plural(essay.paragraphs, 'абзац', 'абзаца', 'абзацев') + ', ' + essay.words + ' ' +
        plural(essay.words, 'слово', 'слова', 'слов')));
      head.appendChild(title);
      var back = el('button', 'ghost small-button', '← К списку');
      back.type = 'button';
      back.addEventListener('click', function () {
        silence();
        session.essay = '';
        session.paragraph = 0;
        marks = [];
        render();
        rest();
      });
      head.appendChild(back);
      panel.appendChild(head);

      var text = el('div', 'essay-text');
      text.id = 'essay-text';
      essay.items.forEach(function (item) {
        if (item.section) { text.appendChild(el('h3', 'essay-section', item.section)); }
        var block = el('div', 'par');
        block.dataset.index = String(item.index);
        block.appendChild(el('span', 'par-no', String(item.index + 1)));
        var body = el('p');
        fill(body, item.text);
        block.appendChild(body);
        block.title = 'абзац ' + (item.index + 1) + ': щелчок делает его текущим';
        block.addEventListener('click', function () {
          session.paragraph = item.index;
          updateParagraphs();
        });
        text.appendChild(block);
      });
      panel.appendChild(text);
      if (essay.dictated) {
        var own = el('div', 'essay-own');
        own.appendChild(el('span', 'note', 'Надиктовано ' + essay.created + '.'));
        var edit = el('button', 'ghost small-button', '✎ Править');
        edit.type = 'button';
        edit.id = 'essay-edit';
        edit.addEventListener('click', function () { editEssay(essay); });
        own.appendChild(edit);
        var remove = el('button', 'ghost small-button', 'Удалить');
        remove.type = 'button';
        remove.id = 'essay-remove';
        remove.addEventListener('click', function () { removeEssay(essay); });
        own.appendChild(remove);
        panel.appendChild(own);
      } else {
        var source = el('p', 'note');
        source.appendChild(document.createTextNode('Источник: '));
        var link = el('a', '', essay.source.site || 'оригинал');
        link.href = essay.source.url || '#';
        link.target = '_blank';
        link.rel = 'noopener';
        source.appendChild(link);
        source.appendChild(document.createTextNode(essay.source.license ? ', ' + essay.source.license : ''));
        panel.appendChild(source);
      }
      shown = { essay: essay.id, marks: key };
      updateParagraphs(true);
    }

    function updateParagraphs(jump) {
      var text = $('essay-text');
      if (!text) { return; }
      var current = null;
      text.querySelectorAll('.par').forEach(function (block) {
        var index = Number(block.dataset.index);
        var here = index === session.paragraph;
        if (here && !block.classList.contains('is-current')) { jump = true; }
        block.classList.toggle('is-current', here);
        block.classList.toggle('is-reading', index === reading);
        if (here) { current = block; }
      });
      if (current && jump) {
        /* прокручивается только окно сочинения, а не вся страница */
        text.scrollTop = Math.max(0, current.offsetTop - text.offsetTop - text.clientHeight / 3);
      }
    }

    function render() {
      if (session.draft) { renderDictation(); } else if (session.essay) { renderEssay(); } else { renderList(); }
      updateCheatLocks();
    }

    /* --- диктовка ------------------------------------------------------------------ */

    function countWords(text) {
      try {
        return (text.match(/[\p{L}\d]+(?:-[\p{L}\d]+)*/gu) || []).length;
      } catch (e) {
        return text.split(/\s+/).filter(Boolean).length;
      }
    }

    /* Черновик: текст пишется под голос, но его можно править и руками. */
    function renderDictation() {
      var draft = session.draft;
      if (shown.essay !== '#draft') {
        panel.textContent = '';
        var head = el('div', 'block-head');
        head.appendChild(el('h2', '', draft.essay ? 'Правка диктовки' : 'Диктовка'));
        head.appendChild(el('span', 'tag tag-' + session.language, boot.languages[session.language].name));
        panel.appendChild(head);

        panel.appendChild(el('p', 'note', 'Говорите — каждая фраза дописывается в текст; править его можно и руками. ' +
          'Знаки называйте словами:'));
        var spoken = el('div', 'draft-marks');
        (boot.dictation.spoken[session.language] || []).forEach(function (pair) {
          var item = el('span', 'draft-pair', pair[0]);
          item.appendChild(el('b', '', pair[1]));
          spoken.appendChild(item);
        });
        panel.appendChild(spoken);

        var title = el('input', 'draft-title');
        title.type = 'text';
        title.id = 'draft-title';
        title.maxLength = boot.dictation.titleLimit;
        title.placeholder = 'Название — если не задать, им станут первые слова';
        title.autocomplete = 'off';
        title.addEventListener('input', function () {
          if (!session.draft) { return; }
          session.draft.title = title.value;
          saveDraft();
        });
        panel.appendChild(title);

        var area = el('textarea', 'draft-text');
        area.id = 'draft-text';
        area.rows = 12;
        area.maxLength = boot.dictation.limit;
        area.lang = boot.languages[session.language].tag;
        area.placeholder = 'Здесь появится надиктованный текст.';
        area.addEventListener('input', function () {
          if (!session.draft) { return; }
          session.draft.text = area.value;
          session.draft.undo = [];              /* текст правили руками: голосом последнюю фразу уже не стереть */
          saveDraft();
          updateDraft();
        });
        panel.appendChild(area);

        var row = el('div', 'draft-row');
        var check = el('label', 'check');
        check.title = 'Пауза в речи считается концом предложения. Если точка поставлена зря, начните следующую фразу ' +
          'со слова «' + (boot.dictation.spoken[session.language] || [['запятая']])[0][0] + '».';
        var box = el('input');
        box.type = 'checkbox';
        box.id = 'draft-period';
        box.addEventListener('change', function () {
          if (!session.draft) { return; }
          session.draft.period = box.checked;
          saveDraft();
        });
        check.appendChild(box);
        check.appendChild(document.createTextNode(' точка после каждой фразы'));
        row.appendChild(check);
        var stats = el('span', 'draft-stats');
        stats.id = 'draft-stats';
        row.appendChild(stats);
        panel.appendChild(row);

        var buttons = el('div', 'draft-buttons');
        var done = el('button', '', 'Закончить и сохранить');
        done.type = 'button';
        done.id = 'draft-done';
        done.addEventListener('click', function () { act('dictate_end'); });
        buttons.appendChild(done);
        var undo = el('button', 'ghost', 'Стереть последнюю фразу');
        undo.type = 'button';
        undo.id = 'draft-undo';
        undo.addEventListener('click', function () { act('dictate_undo'); });
        buttons.appendChild(undo);
        var drop = el('button', 'ghost', 'Бросить');
        drop.type = 'button';
        drop.id = 'draft-drop';
        drop.addEventListener('click', dropDraft);
        buttons.appendChild(drop);
        panel.appendChild(buttons);
        shown = { essay: '#draft', marks: '' };
      }
      var text = $('draft-text');
      if (text.value !== draft.text) {
        text.value = draft.text;
        text.scrollTop = text.scrollHeight;
      }
      if ($('draft-title').value !== draft.title && document.activeElement !== $('draft-title')) {
        $('draft-title').value = draft.title;
      }
      $('draft-period').checked = draft.period !== false;
      updateDraft();
    }

    function updateDraft() {
      var draft = session.draft;
      if (!draft || !$('draft-stats')) { return; }
      var words = countWords(draft.text);
      $('draft-stats').textContent = words + ' ' + plural(words, 'слово', 'слова', 'слов') + ' · ' +
        draft.text.length + ' из ' + String(boot.dictation.limit).replace(/\B(?=(\d{3})+$)/g, ' ') + ' знаков';
      $('draft-undo').disabled = !(draft.undo && draft.undo.length);
    }

    function dropDraft() {
      if (session.draft && session.draft.text.trim() && !global.confirm('Бросить диктовку? Текст не сохранится.')) { return; }
      session.draft = null;
      saveDraft();
      render();
      rest();
      note('Диктовка брошена, текст не сохранён.');
    }

    /* Надиктованное сочинение снова становится черновиком: его можно дописать голосом или поправить руками. */
    function editEssay(essay) {
      silence();
      session.draft = {
        text: essay.items.map(function (item) {
          return (item.section ? '# ' + item.section + '\n\n' : '') + item.text;
        }).join('\n\n'),
        title: essay.title, essay: essay.id, period: true, undo: []
      };
      session.essay = '';
      session.paragraph = 0;
      marks = [];
      saveDraft();
      render();
      rest();
      note('Сочинение «' + essay.title + '» открыто для правки: диктуйте дальше или правьте текст руками.');
    }

    function removeEssay(essay) {
      if (!global.confirm('Удалить надиктованное сочинение «' + essay.title + '»?')) { return; }
      silence();
      S.api('DELETE', '/api/dictations/' + encodeURIComponent(essay.id)).then(function (data) {
        if (data.error) {
          note('Сочинение не удалено: ' + data.error + '.', 'error');
          return;
        }
        boot.essays[data.language] = data.essays;
        delete essays[essay.id];
        if (session.essay === essay.id) {
          session.essay = '';
          session.paragraph = 0;
        }
        marks = [];
        render();
        rest();
        note('Сочинение «' + essay.title + '» удалено.');
      });
    }

    /* --- подсказка «что можно сказать» ------------------------------------------- */

    function renderCheat() {
      cheat.textContent = '';
      var group = '';
      (boot.cheatsheet[session.language] || []).forEach(function (operation) {
        if (operation.group !== group) {
          group = operation.group;
          cheat.appendChild(el('div', 'cheat-group', boot.groups[group] || group));
        }
        var row = el('div', 'cheat-row');
        row.dataset.essay = operation.needs_essay ? '1' : '';
        row.dataset.dictation = operation.dictation ? '1' : '';
        row.appendChild(el('span', 'cheat-title', operation.title + ':'));
        operation.phrases.forEach(function (phrase) {
          var chip = el('button', 'say', phrase);
          chip.type = 'button';
          chip.addEventListener('click', function () { sayPhrase(phrase); });
          row.appendChild(chip);
        });
        cheat.appendChild(row);
      });
      updateCheatLocks();
    }

    /* Приглушено то, что сейчас не сработает: операции, которым нужно открытое сочинение, — без
       него; операции диктовки — вне её, а все остальные — во время неё (тогда речь уходит в текст). */
    function updateCheatLocks() {
      cheat.querySelectorAll('.cheat-row').forEach(function (row) {
        row.classList.toggle('is-locked', (!!row.dataset.essay && !session.essay) ||
          !!row.dataset.dictation !== !!session.draft);
      });
    }

    function flashCheat() {
      cheat.classList.remove('is-flash');
      void cheat.offsetWidth;
      cheat.classList.add('is-flash');
    }

    /* Щелчок по фразе: без параметра она выполняется, с параметром —
       подставляется в строку ввода, чтобы параметр дописали. */
    function sayPhrase(phrase) {
      var slot = phrase.indexOf('‹');
      if (slot < 0) {
        submit(phrase, { source: 'click' });
        return;
      }
      var input = $('typed-text');
      input.value = phrase.slice(0, slot);
      input.focus();
    }

    /* --- настройки --------------------------------------------------------------- */

    function fillVoices() {
      Object.keys(boot.languages).forEach(function (code) {
        var box = $('voice-' + code);
        if (!box) { return; }
        var list = S.voice.voices(boot.languages[code].tag);
        var chosen = S.voice.choose(boot.languages[code].tag);
        box.textContent = '';
        list.forEach(function (voice) {
          var option = el('option', '', voice.name + (voice.localService ? '' : ' · сеть'));
          option.value = voice.voiceURI;
          option.selected = !!chosen && chosen.voiceURI === voice.voiceURI;
          box.appendChild(option);
        });
        if (!list.length) { box.appendChild(el('option', '', S.voice.supported ? 'голосов нет' : 'синтеза речи нет')); }
        box.disabled = !list.length;
      });
    }

    function bindSettings() {
      engineBox.value = prefs.engine;
      engineBox.addEventListener('change', function () {
        var again = listening;
        stopListening();
        prefs.engine = engineBox.value;
        savePrefs();
        checkEngine();
        if (again) { startListening(); }
      });

      var voiceOn = $('voice-on');
      voiceOn.checked = S.voice.prefs.enabled;
      voiceOn.addEventListener('change', function () {
        S.voice.prefs.enabled = voiceOn.checked;
        S.voice.save();
        if (!voiceOn.checked) { stopSpeaking(); }
      });

      Object.keys(boot.languages).forEach(function (code) {
        var box = $('voice-' + code);
        box.addEventListener('change', function () {
          S.voice.prefs.chosen[code] = box.value;
          S.voice.save();
        });
        $('voice-test-' + code).addEventListener('click', function () {
          S.say(SAMPLES[code], { fresh: true });
          S.voice.speak(SAMPLES[code], boot.languages[code].tag, {});
        });
      });
      fillVoices();
      S.voice.onvoices(fillVoices);

      var rate = $('voice-rate');
      rate.value = S.voice.prefs.rate;
      $('voice-rate-value').textContent = '×' + Number(rate.value).toFixed(1).replace('.', ',');
      rate.addEventListener('input', function () {
        S.voice.prefs.rate = Number(rate.value);
        S.voice.save();
        $('voice-rate-value').textContent = '×' + Number(rate.value).toFixed(1).replace('.', ',');
      });

      var duplex = $('duplex');
      duplex.checked = prefs.duplex;
      duplex.addEventListener('change', function () {
        prefs.duplex = duplex.checked;
        savePrefs();
      });

      var margin = $('vad-margin');
      margin.value = prefs.margin;
      $('vad-margin-value').textContent = prefs.margin + ' дБ';
      margin.addEventListener('input', function () {
        prefs.margin = Number(margin.value);
        $('vad-margin-value').textContent = prefs.margin + ' дБ';
        savePrefs();
        send({ type: 'config', margin: prefs.margin });
      });

      var pause = $('vad-pause');
      pause.value = prefs.pause;
      $('vad-pause-value').textContent = (prefs.pause / 1000).toFixed(1).replace('.', ',') + ' с';
      pause.addEventListener('input', function () {
        prefs.pause = Number(pause.value);
        $('vad-pause-value').textContent = (prefs.pause / 1000).toFixed(1).replace('.', ',') + ' с';
        savePrefs();
        send({ type: 'config', pause: prefs.pause });
      });
    }

    /* --- запуск --------------------------------------------------------------------- */

    listenButton.addEventListener('click', function () {
      if (listening) { silence(); stopListening(); setPhase('off'); } else { startListening(); }
    });
    stopButton.addEventListener('click', stopSpeaking);
    document.querySelectorAll('#language-switch button').forEach(function (button) {
      button.addEventListener('click', function () { chooseLanguage(button.dataset.language); });
    });
    $('typed').addEventListener('submit', function (event) {
      event.preventDefault();
      var input = $('typed-text');
      var text = input.value.trim();
      if (!text) { return; }
      input.value = '';
      submit(text, { source: 'keyboard' });
    });
    $('journal-clear').addEventListener('click', function () {
      journal.textContent = '';
      journal.appendChild(el('li', 'journal-empty', 'Журнал пуст.'));
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && phase === 'speaking') { stopSpeaking(); }
    });
    global.addEventListener('pagehide', function () {
      S.voice.cancel();
      if (mic) { mic.stop(); }
      if (channel) { channel.stop(); }
    });

    bindSettings();
    applyLanguage(session.language, null);
    render();
    setPhase('off');
    global.requestAnimationFrame(drawMeter);

    /* для проверок из консоли браузера и автоматических снимков */
    global.Sluhach.console = {
      submit: function (text) { submit(text, { source: 'keyboard' }); },
      act: act,
      state: function () { return { phase: phase, listening: listening, muted: muted, session: session }; },
      start: startListening,
      stop: stopListening
    };
  });
})(window);
