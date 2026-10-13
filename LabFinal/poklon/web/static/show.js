/* Показ: загрузка, музыка, часы ролика, клавиши и репетиция.
 *
 * Порядок такой. Страница спрашивает у сервера запись, слова и метки
 * (/api/show). Запись разбирается браузером целиком и прослушивается
 * (Score.analysis) — пока идёт счёт, кнопка вызова лифта неактивна. Потом по
 * меткам строятся расписание и труппа, и ролик ждёт нажатия: без него
 * браузер не даст включить звук.
 *
 * Часы ролика — часы звука. Секунда t — это место в записи, которое сейчас
 * слышно; сцена рисует кадр для t. Поэтому рты и свет не расходятся с
 * музыкой, даже если вкладка подтормаживает. Без записи часы обычные.
 *
 * Клавиши: пробел — пауза, F — во весь экран, R — репетиция, ← → — перемотка
 * на пять секунд (с Shift — на одну), M — без звука, Home — сначала,
 * Esc — к кнопке вызова. На репетиции 1 и 2 ставят метки хора.
 *
 * Для проверок страница понимает ключи адреса: ?t=95 — показать кадр 95-й
 * секунды и стоять; ?auto=1 — начать без нажатия; ?rehearsal=1 — открыть
 * репетицию.
 */

(function () {
  'use strict';

  var LEAD = Score.LEAD;
  var SILENT_LENGTH = 150;      /* столько идёт ролик без записи, секунды */
  var TAIL = 16;                /* сколько секунд после выхода видно на ленте репетиции */

  var params = new URLSearchParams(location.search);
  var el = function (id) { return document.getElementById(id); };
  var stageBox = el('stage');
  var stage = new Stage(el('scene'));

  var show = {
    plan: null, troupe: null, features: null, words: {},
    track: null,                /* { name, duration } или null — ролик в тишине */
    buffer: null,               /* разобранная запись */
    cues: null,                 /* действующие метки: { choir, leave } */
    found: null,                /* метки, найденные по громкости */
    origin: 'guess'             /* откуда метки: found | guess | saved | hand */
  };
  var clock = { playing: false, t: -LEAD, origin: 0, audio: false, ctx: null, gain: null, source: null, muted: false };
  var mode = 'loading';         /* loading — идёт счёт, ready — ждём нажатия, running — ролик идёт */
  var rehearsing = false;
  var still = params.has('t');

  /* --- мелочи ------------------------------------------------------------------- */

  function stamp(seconds) {
    var sign = seconds < 0 ? '−' : '';
    seconds = Math.abs(seconds);
    var whole = Math.floor(seconds);
    return sign + Math.floor(whole / 60) + ':' + String(whole % 60).padStart(2, '0');
  }

  function status(html, bad) {
    el('call-status').innerHTML = html;
    el('call-status').classList.toggle('bad', !!bad);
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"]/g, function (sign) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[sign];
    });
  }

  /* --- слова -------------------------------------------------------------------- */

  function fillWords() {
    var words = show.words;
    document.title = '«' + (words.title || 'Поклон') + '» — прощальный ролик';
    el('call-title').textContent = words.title || 'Поклон';
    el('call-sub').textContent = words.subtitle || '';
    el('call-course').textContent = words.course || '';
    el('thanks-app').textContent = words.title || 'Поклон';
    el('thanks-course').textContent = words.course || '';
    el('thanks-title').textContent = words.thanks || 'Спасибо!';
    el('thanks-to').textContent = words.to || '';

    /* строки прощания появляются по одной; подпись — после последней */
    var lines = el('thanks-lines');
    lines.textContent = '';
    var at = 4.2;
    (words.lines || []).forEach(function (line) {
      var p = document.createElement('p');
      p.textContent = line;
      p.setAttribute('data-at', at.toFixed(1));
      lines.appendChild(p);
      at += 2.4;
    });
    var sign = el('thanks-sign');
    sign.setAttribute('data-at', at.toFixed(1));
    var names = (words.signature || []).map(escapeHtml).join(', ');
    var rest = [words.group, words.place].filter(Boolean).map(escapeHtml).join(' · ');
    sign.innerHTML = (names ? '<b>' + names + '</b>' : '') + (names && rest ? '<br>' : '') + rest;
    el('credits').setAttribute('data-at', (at + 1.6).toFixed(1));
    el('again').setAttribute('data-at', (at + 4).toFixed(1));
  }

  function fillCredits() {
    var words = show.words;
    var html = '';
    var cast = (words.credits || []).filter(function (row) { return Array.isArray(row) && row.length >= 2; });
    if (cast.length) {
      html += '<h3>В ролях</h3>';
      cast.forEach(function (row) {
        var who = String(row[1]).replace('{count}', show.troupe ? show.troupe.count : '');
        html += '<p>' + escapeHtml(row[0]) + ' — <b>' + escapeHtml(who) + '</b></p>';
      });
    }
    var floors = (words.floors || []).filter(function (floor) { return floor && floor.name; });
    if (floors.length) {
      html += '<h3>Лабораторные</h3>';
      floors.forEach(function (floor) {
        html += '<p><b>' + escapeHtml(floor.number) + '</b> · ' + escapeHtml(floor.name) + '</p>';
      });
    }
    if (words.music && show.track) {
      html += '<h3>Музыка</h3><p>' + escapeHtml(words.music) + '</p>';
    }
    el('credits').innerHTML = html;
  }

  /* --- расписание и труппа ---------------------------------------------------------- */

  function rebuild() {
    var duration = show.track ? show.track.duration : SILENT_LENGTH;
    show.plan = Score.plan(duration, show.cues);
    show.cues = { choir: show.plan.choir, leave: show.plan.leave };
    if (!show.track) { show.features = Score.silent(duration, show.cues); }
    var seed = parseInt(params.get('seed'), 10);
    show.troupe = Troupe.build(show.plan, show.words, seed > 0 ? seed : undefined);
    fillCredits();
    drawTape();
  }

  function useSilence() {
    show.track = null;
    show.buffer = null;
    show.found = null;
    show.cues = Score.guess(SILENT_LENGTH);
    show.origin = 'guess';
    rebuild();
  }

  /* --- запись ---------------------------------------------------------------------- */

  function audioContext() {
    if (!clock.ctx) {
      var Context = window.AudioContext || window.webkitAudioContext;
      if (!Context) { throw new Error('браузер не умеет разбирать звук'); }
      clock.ctx = new Context();
      clock.gain = clock.ctx.createGain();
      clock.gain.connect(clock.ctx.destination);
    }
    return clock.ctx;
  }

  function decode(bytes) {
    var ctx = audioContext();
    return new Promise(function (resolve, reject) {
      var promise = ctx.decodeAudioData(bytes, resolve, reject);
      if (promise && promise.catch) { promise.catch(reject); }
    }).catch(function () {
      throw new Error('браузер не смог разобрать запись');
    });
  }

  /* Прослушивание: по частям, чтобы страница не замирала. */
  function listen(buffer) {
    var channels = [];
    for (var c = 0; c < buffer.numberOfChannels; c++) { channels.push(buffer.getChannelData(c)); }
    var job = Score.analysis(channels, buffer.sampleRate);
    return new Promise(function (resolve) {
      (function step() {
        var share = job.run(240);
        status('Пафнутий слушает запись… ' + Math.round(share * 100) + '%');
        if (share < 1) { setTimeout(step, 0); } else { resolve(job.finish()); }
      })();
    });
  }

  function useTrack(bytes, name, saved) {
    status('Пафнутий разбирает запись…');
    return decode(bytes).then(function (buffer) {
      return listen(buffer).then(function (features) {
        show.buffer = buffer;
        show.features = features;
        show.track = { name: name, duration: buffer.duration };
        show.found = Score.detectCues(features, buffer.duration);
        if (saved && Math.abs(saved.duration - buffer.duration) < 1.5) {
          show.cues = { choir: saved.choir, leave: saved.leave };
          show.origin = 'saved';
        } else {
          show.cues = { choir: show.found.choir, leave: show.found.leave };
          show.origin = show.found.found ? 'found' : 'guess';
        }
        rebuild();
      });
    });
  }

  function announce() {
    if (!show.track) {
      status('Музыка не найдена: положите запись в папку <b>music</b> или перетащите её прямо сюда.<br>' +
        'Подняться можно и в тишине.');
      return;
    }
    var about = {
      found: 'хор найден по громкости',
      saved: 'метки хора — с репетиции',
      hand: 'метки хора поставлены вручную',
      guess: 'хор по громкости не выделился — метки поставлены на глаз, поправьте их на репетиции (R)'
    }[show.origin];
    status('♪ <b>' + escapeHtml(show.track.name) + '</b> · ' + stamp(show.track.duration) +
      '<br>' + about + ': ' + stamp(show.cues.choir) + ' – ' + stamp(show.cues.leave));
  }

  function ready() {
    mode = 'ready';
    el('call-button').disabled = false;
    announce();
    if (still) {
      /* проверочный кадр: без кнопки и без музыки */
      document.body.classList.add('still');
      mode = 'running';
      el('call').hidden = true;
      clock.t = Score.clamp(parseFloat(params.get('t')) || 0, -LEAD, show.plan.end);
    } else if (params.has('auto')) {
      begin();
    }
    if (params.has('rehearsal')) { toggleRehearsal(true); }
  }

  function boot() {
    layout();
    useSilence();
    requestAnimationFrame(frame);
    fetch('/api/show').then(function (response) { return response.json(); }).then(function (info) {
      show.words = info.words || {};
      fillWords();
      rebuild();
      if (!info.track) { return null; }
      return fetch(info.track.url).then(function (response) {
        if (!response.ok) { throw new Error('сервер не отдал запись'); }
        return response.arrayBuffer();
      }).then(function (bytes) { return useTrack(bytes, info.track.name, info.cues); });
    }).then(ready, function (error) {
      useSilence();
      ready();
      status('С записью не вышло: ' + escapeHtml(error.message) + '. Ролик пойдёт в тишине.', true);
    });
  }

  /* --- часы ------------------------------------------------------------------------- */

  function now() {
    if (!clock.playing) { return clock.t; }
    return clock.audio ? clock.ctx.currentTime - clock.origin : performance.now() / 1000 - clock.origin;
  }

  function silence() {
    if (!clock.source) { return; }
    try { clock.source.stop(); } catch (error) { /* ещё не началась или уже кончилась */ }
    clock.source.disconnect();
    clock.source = null;
  }

  /* Запускает ролик с секунды t. Запись ставится с этого же места; до первой
     ноты (t < 0) её начало откладывается. */
  function play(t) {
    silence();
    clock.t = t;
    clock.playing = true;
    var ctx = clock.ctx;
    if (show.buffer && ctx && ctx.state === 'running') {
      /* звук доходит до колонок с задержкой: кадр должен показывать то, что уже слышно */
      var latency = ctx.outputLatency || ctx.baseLatency || 0;
      var when = ctx.currentTime + 0.08;
      clock.audio = true;
      clock.origin = when - t + latency;
      if (t < show.buffer.duration) {
        clock.source = ctx.createBufferSource();
        clock.source.buffer = show.buffer;
        clock.source.connect(clock.gain);
        clock.source.start(when + Math.max(0, -t), Math.max(0, t));
      }
    } else {
      clock.audio = false;
      clock.origin = performance.now() / 1000 - t;
    }
  }

  function pause() {
    if (!clock.playing) { return; }
    clock.t = now();
    clock.playing = false;
    silence();
  }

  function seek(t) {
    t = Score.clamp(t, -LEAD, show.plan.end);
    if (clock.playing) { play(t); } else { clock.t = t; }
  }

  /* Звук включается только после нажатия; если браузер всё же не дал — ролик
     пойдёт по обычным часам, без музыки. */
  function wake() {
    var ctx = clock.ctx;
    if (!ctx || !show.buffer || ctx.state === 'running') { return Promise.resolve(); }
    return Promise.race([
      ctx.resume().catch(function () {}),
      new Promise(function (resolve) { setTimeout(resolve, 1500); })
    ]);
  }

  /* Экран с кнопкой вызова уходит. Он остаётся в разметке (гаснет плавно),
     поэтому выключается целиком: иначе кнопка, на которой остался фокус,
     ловила бы пробел и запускала ролик заново. */
  function dismissCall() {
    el('call').classList.add('gone');
    el('call').inert = true;
  }

  function begin() {
    if (mode !== 'ready') { return; }
    mode = 'running';
    dismissCall();
    wake().then(function () { play(-LEAD); });
  }

  function backToCall() {
    pause();
    clock.t = -LEAD;
    mode = 'ready';
    el('call').classList.remove('gone');
    el('call').inert = false;
    toggleRehearsal(false);
  }

  function togglePause() {
    if (mode === 'ready') { begin(); return; }
    if (mode !== 'running') { return; }
    if (clock.playing) { pause(); } else { wake().then(function () { play(clock.t); }); }
  }

  /* --- кадр --------------------------------------------------------------------------- */

  var lastBubble = -1;

  function overlays(t) {
    var plan = show.plan;
    var since = t - plan.arrive;
    var thanks = el('thanks');
    thanks.hidden = since < 0.2;
    if (!thanks.hidden) {
      var timed = thanks.querySelectorAll('[data-at]');
      for (var i = 0; i < timed.length; i++) {
        timed[i].classList.toggle('on', since >= parseFloat(timed[i].getAttribute('data-at')));
      }
      /* реплики Пафнутия сменяются каждые пять секунд */
      var bubbles = show.words.bubbles || [];
      var turn = Math.floor((since - 3.2) / 5);
      var bubble = el('bubble');
      if (turn >= 0 && bubbles.length) {
        if (turn !== lastBubble) {
          bubble.textContent = bubbles[turn % bubbles.length];
          lastBubble = turn;
        }
        bubble.classList.toggle('on', (since - 3.2) % 5 < 4.3);
      } else {
        bubble.classList.remove('on');
        lastBubble = -1;
      }
    }
    el('pause').hidden = !(mode === 'running' && !clock.playing && !rehearsing && !still);
    if (rehearsing) { tick(t); }
  }

  function frame() {
    requestAnimationFrame(frame);
    if (!show.plan) { return; }
    /* после выхода часы идут и дальше: слова остаются на экране, Пафнутий качается на нити */
    var t = now();
    stage.render(show, t);
    overlays(t);
  }

  function layout() {
    var width = stageBox.clientWidth;
    stageBox.style.fontSize = (width / 100) + 'px';
    stage.resize(width);
    drawTape();
  }

  /* --- репетиция ------------------------------------------------------------------------ */

  var tape = el('reh-canvas');
  var dragging = null;

  function tapeLength() { return show.plan.arrive + TAIL; }

  /* Лента времени: громкость записи, действия ролика и две метки хора. */
  function drawTape() {
    if (!rehearsing || !show.plan) { return; }
    var box = tape.parentNode;
    var ratio = Math.min(window.devicePixelRatio || 1, 2);
    var width = Math.max(100, box.clientWidth);
    var height = Math.max(30, box.clientHeight);
    tape.width = Math.round(width * ratio);
    tape.height = Math.round(height * ratio);
    var g = tape.getContext('2d');
    g.setTransform(ratio, 0, 0, ratio, 0, 0);
    var plan = show.plan;
    var total = tapeLength();
    var px = function (seconds) { return seconds / total * width; };

    [[0, plan.choir, '#1d1a2c', 'подъём'], [plan.choir, plan.leave, '#3a2c16', 'большой хор'],
      [plan.leave, plan.arrive, '#1d1a2c', 'выход'], [plan.arrive, total, '#3b352b', 'спасибо']].forEach(function (part) {
      g.fillStyle = part[2];
      g.fillRect(px(part[0]), 0, px(part[1]) - px(part[0]), height);
      g.fillStyle = 'rgba(233, 226, 210, .5)';
      g.font = '11px "Segoe UI", sans-serif';
      g.textBaseline = 'top';
      g.fillText(part[3], px(part[0]) + 6, 4);
    });

    var features = show.features;
    if (features) {
      var draw = function (series, colour, scale) {
        g.fillStyle = colour;
        g.beginPath();
        g.moveTo(0, height);
        for (var x = 0; x <= width; x++) {
          var from = Math.floor(x / width * total * Score.RATE);
          var to = Math.max(from + 1, Math.floor((x + 1) / width * total * Score.RATE));
          var top = 0;
          for (var i = from; i < to && i < series.length; i++) { if (series[i] > top) { top = series[i]; } }
          g.lineTo(x, height - Math.min(1, top) * (height - 16) * scale);
        }
        g.lineTo(width, height);
        g.closePath();
        g.fill();
      };
      draw(features.level, 'rgba(233, 226, 210, .5)', 1);
      draw(features.low, 'rgba(255, 179, 71, .5)', 0.5);
    }

    g.fillStyle = 'rgba(255, 255, 255, .18)';
    show.troupe.beams.forEach(function (beam) { g.fillRect(px(beam.time), height - 10, 1, 10); });

    [[plan.choir, 'хор'], [plan.leave, 'конец хора']].forEach(function (mark) {
      g.fillStyle = '#ffcf6b';
      g.fillRect(px(mark[0]) - 1, 0, 2, height);
      g.beginPath();
      g.moveTo(px(mark[0]) - 7, 0); g.lineTo(px(mark[0]) + 7, 0); g.lineTo(px(mark[0]), 10);
      g.closePath();
      g.fill();
      /* подпись метки — на тёмной плашке: под ней может быть громкость */
      var caption = mark[1] + ' ' + stamp(mark[0]);
      g.font = '600 11px "Segoe UI", sans-serif';
      g.textBaseline = 'bottom';
      g.fillStyle = 'rgba(12, 10, 20, .88)';
      g.fillRect(px(mark[0]) + 2, height - 18, g.measureText(caption).width + 9, 16);
      g.fillStyle = '#ffcf6b';
      g.fillText(caption, px(mark[0]) + 6, height - 4);
    });
    describeCues();
  }

  function describeCues(extra) {
    var text = {
      found: 'Метки найдены по громкости записи.',
      guess: show.track ? 'Громкая часть не выделилась — метки поставлены на глаз.' : 'Записи нет: метки условные.',
      saved: 'Метки сохранены на прошлой репетиции.',
      hand: 'Метки поставлены вручную — не забудьте сохранить.'
    }[show.origin];
    el('reh-note').textContent = (extra ? extra + ' ' : '') + text +
      ' Метку можно перетащить по ленте или поставить клавишами 1 и 2 в текущем месте.';
  }

  function tick(t) {
    el('reh-cursor').style.left = Score.clamp(t / tapeLength(), 0, 1) * 100 + '%';
    el('reh-time').textContent = stamp(t) + ' / ' + stamp(show.plan.duration);
    el('reh-play').textContent = clock.playing ? '⏸' : '⏵';
    el('reh-act').textContent = {
      wait: 'лифт стоит', rise: 'подъём', hall: 'большой хор', leave: 'выход', surface: 'спасибо'
    }[Score.act(show.plan, t)];
  }

  function toggleRehearsal(open) {
    rehearsing = open === undefined ? !rehearsing : open;
    el('rehearsal').hidden = !rehearsing;
    if (!rehearsing) { return; }
    if (mode === 'ready') {
      mode = 'running';
      dismissCall();
      clock.t = 0;
    }
    drawTape();
  }

  function setCue(name, seconds) {
    var cues = { choir: show.cues.choir, leave: show.cues.leave };
    cues[name] = seconds;
    /* метки не могут поменяться местами: вторая отодвигается */
    if (name === 'choir' && cues.leave < cues.choir + 12) { cues.leave = cues.choir + 12; }
    if (name === 'leave' && cues.choir > cues.leave - 12) { cues.choir = cues.leave - 12; }
    show.cues = cues;
    show.origin = 'hand';
    rebuild();
  }

  function tapeSeconds(event) {
    var box = tape.getBoundingClientRect();
    return Score.clamp((event.clientX - box.left) / box.width, 0, 1) * tapeLength();
  }

  tape.parentNode.addEventListener('pointerdown', function (event) {
    var seconds = tapeSeconds(event);
    var reach = 9 / tape.getBoundingClientRect().width * tapeLength();
    dragging = Math.abs(seconds - show.plan.choir) < reach ? 'choir'
      : Math.abs(seconds - show.plan.leave) < reach ? 'leave' : 'seek';
    tape.parentNode.setPointerCapture(event.pointerId);
    if (dragging === 'seek') { seek(seconds); }
  });
  tape.parentNode.addEventListener('pointermove', function (event) {
    if (!dragging) { return; }
    if (dragging === 'seek') { seek(tapeSeconds(event)); } else { setCue(dragging, tapeSeconds(event)); }
  });
  ['pointerup', 'pointercancel'].forEach(function (name) {
    tape.parentNode.addEventListener(name, function () { dragging = null; });
  });

  el('reh-play').addEventListener('click', togglePause);
  el('reh-close').addEventListener('click', function () { toggleRehearsal(false); });
  el('reh-choir').addEventListener('click', function () { setCue('choir', now()); });
  el('reh-leave').addEventListener('click', function () { setCue('leave', now()); });
  el('reh-auto').addEventListener('click', function () {
    if (show.found) {
      show.cues = { choir: show.found.choir, leave: show.found.leave };
      show.origin = show.found.found ? 'found' : 'guess';
    } else {
      show.cues = Score.guess(SILENT_LENGTH);
      show.origin = 'guess';
    }
    rebuild();
    fetch('/api/cues', { method: 'DELETE' }).catch(function () {});
  });
  el('reh-save').addEventListener('click', function () {
    if (!show.track) {
      describeCues('Без записи сохранять нечего.');
      return;
    }
    fetch('/api/cues', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        track: show.track.name, duration: show.track.duration, choir: show.cues.choir, leave: show.cues.leave
      })
    }).then(function (response) { return response.json(); }).then(function (answer) {
      if (!answer.ok) { throw new Error(answer.error); }
      show.origin = 'saved';
      describeCues('Сохранено.');
    }).catch(function (error) {
      describeCues('Сохранить не удалось: ' + error.message + '.');
    });
  });

  /* --- запись, перетащенная на страницу ------------------------------------------------------ */

  var dragDepth = 0;

  function hasFiles(event) {
    return event.dataTransfer && Array.prototype.indexOf.call(event.dataTransfer.types || [], 'Files') >= 0;
  }

  window.addEventListener('dragenter', function (event) {
    if (!hasFiles(event)) { return; }
    event.preventDefault();
    dragDepth++;
    el('drop').hidden = false;
  });
  window.addEventListener('dragover', function (event) { if (hasFiles(event)) { event.preventDefault(); } });
  window.addEventListener('dragleave', function (event) {
    if (!hasFiles(event)) { return; }
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) { el('drop').hidden = true; }
  });
  window.addEventListener('drop', function (event) {
    if (!hasFiles(event)) { return; }
    event.preventDefault();
    dragDepth = 0;
    el('drop').hidden = true;
    var file = event.dataTransfer.files[0];
    if (!file) { return; }
    backToCall();
    mode = 'loading';
    el('call-button').disabled = true;
    file.arrayBuffer().then(function (bytes) {
      var copy = bytes.slice(0);          /* разбор забирает буфер себе, а запись ещё сохранять */
      return useTrack(bytes, file.name, null).then(function () {
        /* сохраняем в папку с музыкой: в следующий раз запись уже будет на месте */
        return fetch('/api/track?name=' + encodeURIComponent(file.name), { method: 'POST', body: copy })
          .then(function (response) { return response.json(); })
          .catch(function () { return { ok: false }; });
      });
    }).then(function (answer) {
      mode = 'ready';
      el('call-button').disabled = false;
      announce();
      if (answer && answer.ok && answer.playing && answer.playing !== answer.name) {
        el('call-status').innerHTML += '<br>В папке music есть и другая запись — при следующем запуске сыграет <b>' +
          escapeHtml(answer.playing) + '</b>.';
      }
    }, function (error) {
      /* файл не подошёл: всё остаётся как было до него */
      mode = 'ready';
      el('call-button').disabled = false;
      status('«' + escapeHtml(file.name) + '»: ' + escapeHtml(error.message) + '. Подойдут mp3, m4a, ogg, flac, wav.<br>' +
        (show.track ? 'Осталась прежняя запись: <b>' + escapeHtml(show.track.name) + '</b>.' : 'Пока ролик идёт в тишине.'), true);
    });
  });

  /* --- кнопки и клавиши ------------------------------------------------------------------------ */

  el('call-button').addEventListener('click', function () { begin(); });
  el('again').addEventListener('click', function () {
    wake().then(function () { play(-LEAD); });
  });

  function fullscreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else if (document.documentElement.requestFullscreen) {
      document.documentElement.requestFullscreen().catch(function () {});
    }
  }

  window.addEventListener('keydown', function (event) {
    if (event.ctrlKey || event.altKey || event.metaKey) { return; }
    var key = event.code;
    if (key === 'Space' || key === 'Enter') {
      /* кнопка, выбранная клавишей Tab, сама отзовётся на пробел */
      if (event.target && event.target.tagName === 'BUTTON') { return; }
      event.preventDefault();
      togglePause();
    } else if (key === 'KeyF') {
      fullscreen();
    } else if (key === 'KeyR') {
      if (mode !== 'loading') { toggleRehearsal(); }
    } else if (key === 'KeyM') {
      clock.muted = !clock.muted;
      if (clock.gain) { clock.gain.gain.value = clock.muted ? 0 : 1; }
    } else if (key === 'ArrowLeft' || key === 'ArrowRight') {
      if (mode === 'running') {
        event.preventDefault();
        seek(now() + (key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? 1 : 5));
      }
    } else if (key === 'Home') {
      if (mode === 'running') { seek(-LEAD); }
    } else if (key === 'Escape') {
      if (mode === 'running' && !document.fullscreenElement) { backToCall(); }
    } else if (key === 'Digit1' || key === 'Digit2') {
      if (rehearsing) { setCue(key === 'Digit1' ? 'choir' : 'leave', now()); }
    }
  });

  /* После щелчка фокус на кнопке не остаётся: пробел — это всегда пауза, а
     не повторное нажатие последней кнопки. */
  document.addEventListener('click', function (event) {
    var button = event.target.closest && event.target.closest('button');
    if (button) { button.blur(); }
  });

  /* во время показа указатель мыши прячется */
  var idleTimer = 0;
  window.addEventListener('mousemove', function () {
    document.body.classList.remove('idle');
    clearTimeout(idleTimer);
    idleTimer = setTimeout(function () {
      if (mode === 'running' && clock.playing && !rehearsing) { document.body.classList.add('idle'); }
    }, 2500);
  });

  window.addEventListener('resize', layout);

  /* для проверок и сценариев tools/ */
  window.Poklon = {
    show: show, clock: clock, now: now, seek: seek, begin: begin, pause: pause, togglePause: togglePause,
    toggleRehearsal: toggleRehearsal, setCue: setCue, mode: function () { return mode; }
  };

  boot();
})();
