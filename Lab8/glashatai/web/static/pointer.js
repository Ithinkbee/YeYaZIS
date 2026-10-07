/* «Глашатай, читай» — закладка для любой веб-страницы.
 *
 * Закладка добавляет этот сценарий на открытую страницу. Он рисует внизу
 * панель Пафнутия (в теневом DOM — стили страницы её не задевают),
 * подсвечивает абзац под указателем мыши и читает его по щелчку; если
 * мышью выделен фрагмент — читается он. Звук синтезирует «Глашатай» на этом
 * компьютере: страница просит его как обычный аудиофайл
 * (http://127.0.0.1:8083/api/say.wav?text=…). Длинный абзац делится на
 * куски по предложениям: первый кусок звучит, пока готовятся следующие.
 *
 * Сверху — деление на куски без DOM (проверяется тестами); снизу — панель.
 */

(function (global) {
  'use strict';

  /* --- правила -------------------------------------------------------------------- */

  var LIMIT = 320;
  /** точка после этого — не конец предложения: инициал, порядковое число, частое сокращение */
  var SHORT = /^(\S\.|\d{1,3}\.|ca\.|vgl\.|bzw\.|ggf\.|evtl\.|inkl\.|sog\.|Nr\.|Abb\.|Tab\.|Kap\.|Bd\.|Dr\.|Prof\.|S\.|f\.|ff\.)$/;

  /**
   * Текст -> куски не длиннее limit по границам предложений. Точка после
   * одиночной буквы («z.», «B.»), числа («19.») или частого сокращения
   * («vgl.», «Nr.») границей не считается.
   */
  function chunks(text, limit) {
    limit = limit || LIMIT;
    var clean = String(text || '').replace(/\s+/g, ' ').trim();
    if (!clean) { return []; }
    var sentences = [];
    var start = 0;
    var pattern = /[.!?…]["»“”)]*\s+(?=[A-ZÄÖÜ„"(\d])/g;
    var match;
    while ((match = pattern.exec(clean))) {
      var before = clean.slice(start, match.index + 1);
      var last = before.split(' ').pop();
      if (SHORT.test(last) && match[0][0] === '.') { continue; }
      sentences.push(clean.slice(start, match.index + match[0].length).trim());
      start = match.index + match[0].length;
    }
    if (start < clean.length) { sentences.push(clean.slice(start).trim()); }
    var result = [];
    var current = '';
    sentences.forEach(function (sentence) {
      while (sentence.length > limit) {
        var cut = sentence.lastIndexOf(', ', limit);
        if (cut < limit / 3) { cut = sentence.lastIndexOf(' ', limit); }
        if (cut < 1) { cut = limit; }
        if (current) { result.push(current); current = ''; }
        result.push(sentence.slice(0, cut + 1).trim());
        sentence = sentence.slice(cut + 1).trim();
      }
      if (current && (current + ' ' + sentence).length > limit) { result.push(current); current = ''; }
      current = current ? current + ' ' + sentence : sentence;
    });
    if (current) { result.push(current); }
    return result;
  }

  var rules = { LIMIT: LIMIT, chunks: chunks };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = rules;
    return;
  }

  /* --- панель на странице ---------------------------------------------------------------- */

  if (global.__glashataiPointer) { global.__glashataiPointer.show(); return; }

  var script = document.currentScript;
  var origin = script && script.src ? script.src.replace(/\/static\/pointer\.js.*$/, '') : 'http://127.0.0.1:8083';
  var BLOCKS = 'p, li, h1, h2, h3, h4, h5, h6, td, th, blockquote, dd, dt, figcaption, pre, summary, caption';

  var host = document.createElement('div');
  host.style.cssText = 'all: initial; position: fixed; right: 18px; bottom: 18px; z-index: 2147483647;';
  var shadow = host.attachShadow({ mode: 'open' });
  shadow.innerHTML = [
    '<style>',
    '.panel { font: 14px/1.4 "Segoe UI", Arial, sans-serif; color: #241d1a; background: #fff; border: 1px solid #e2d9cf;',
    '  border-radius: 14px; box-shadow: 0 12px 36px rgba(40, 20, 10, .25); padding: 10px 12px; width: 300px; }',
    '.head { display: flex; align-items: center; gap: 8px; }',
    '.spider { font-size: 26px; }',
    '.title { font-weight: 700; color: #9b2f2f; flex: 1; }',
    'button { font: inherit; font-size: 13px; border: 1px solid #9b2f2f; background: #fff; color: #9b2f2f; border-radius: 8px;',
    '  padding: 3px 10px; cursor: pointer; }',
    'button:hover { background: #f6e7e3; }',
    '.state { margin: 6px 0 0; color: #776c64; font-size: 13px; min-height: 1.4em; }',
    '.state.on { color: #9b2f2f; }',
    '.bar { height: 4px; background: #efe8e0; border-radius: 2px; margin-top: 6px; overflow: hidden; }',
    '.bar i { display: block; height: 100%; width: 0; background: linear-gradient(90deg, #9b2f2f, #b88a22); }',
    '</style>',
    '<div class="panel">',
    '  <div class="head"><span class="spider">🕷️</span><span class="title">Глашатай читает</span>',
    '    <button type="button" class="stop" title="Замолчать (Esc)">■</button>',
    '    <button type="button" class="close" title="Убрать панель">✕</button></div>',
    '  <div class="state">Наведите мышь на абзац и щёлкните. Выделенный фрагмент читается вместо абзаца.</div>',
    '  <div class="bar"><i></i></div>',
    '</div>'
  ].join('');
  document.documentElement.appendChild(host);
  var stateNode = shadow.querySelector('.state');
  var bar = shadow.querySelector('.bar i');

  var outline = document.createElement('div');
  outline.style.cssText = 'position: absolute; pointer-events: none; z-index: 2147483646; border-radius: 6px; ' +
    'box-shadow: 0 0 0 2px #b88a22; background: rgba(248, 239, 216, .35); transition: all .08s; display: none;';
  document.documentElement.appendChild(outline);

  var enabled = true;
  var hovered = null;
  var reading = null;
  var queue = [];
  var audio = null;
  var nextAudio = null;
  var token = 0;

  function setState(text, on) {
    stateNode.textContent = text;
    stateNode.className = 'state' + (on ? ' on' : '');
  }

  function place(node, color) {
    if (!node) { outline.style.display = 'none'; return; }
    var box = node.getBoundingClientRect();
    outline.style.display = 'block';
    outline.style.left = (box.left + global.scrollX - 3) + 'px';
    outline.style.top = (box.top + global.scrollY - 2) + 'px';
    outline.style.width = (box.width + 6) + 'px';
    outline.style.height = (box.height + 4) + 'px';
    outline.style.boxShadow = '0 0 0 2px ' + (color || '#b88a22');
  }

  function url(text) {
    return origin + '/api/say.wav?text=' + encodeURIComponent(text) + '&t=' + Date.now();
  }

  function stop(message) {
    token++;
    queue = [];
    [audio, nextAudio].forEach(function (item) { if (item) { item.pause(); item.removeAttribute('src'); } });
    audio = nextAudio = null;
    reading = null;
    bar.style.width = '0';
    place(hovered);
    setState(message || 'Готов. Наведите мышь на абзац и щёлкните.', false);
  }

  function prepare(text) {
    var item = new Audio();
    item.preload = 'auto';
    item.src = url(text);
    return item;
  }

  function read(text, node) {
    stop();
    var parts = chunks(text);
    if (!parts.length) { return; }
    var mine = ++token;
    var total = parts.length;
    reading = node;
    if (node) { place(node, '#9b2f2f'); }
    queue = parts.slice();
    function next() {
      if (mine !== token) { return; }
      if (!queue.length) { stop('Дочитано. Ещё абзац?'); return; }
      var text = queue.shift();
      audio = nextAudio || prepare(text);
      nextAudio = queue.length ? prepare(queue[0]) : null;
      setState('Синтезирую…', true);
      audio.onplaying = function () {
        if (mine === token) { setState('Читаю: «' + text.slice(0, 60) + (text.length > 60 ? '…' : '') + '»', true); }
      };
      audio.onended = function () {
        bar.style.width = (100 * (total - queue.length) / total) + '%';
        next();
      };
      audio.onerror = function () {
        if (mine !== token) { return; }
        stop('«Глашатай» не ответил: запущен ли он (python run.py)? Браузер мог запретить доступ к 127.0.0.1.');
      };
      var started = audio.play();
      if (started && started.catch) {
        started.catch(function (problem) {
          if (mine === token && problem && problem.name === 'NotAllowedError') {
            setState('Браузер не дал включить звук — щёлкните ещё раз.', false);
          }
        });
      }
    }
    next();
  }

  function blockAt(target) {
    if (!target || !target.closest || host.contains(target)) { return null; }
    var node = target.closest(BLOCKS);
    if (!node) {
      node = target.closest('div, section, article');
      if (node && node.children.length > 3) { return null; }
    }
    if (!node || !node.innerText || node.innerText.trim().length < 2) { return null; }
    return node;
  }

  function onMove(event) {
    if (!enabled || event.target === host) { return; }
    var node = blockAt(event.target);
    if (node !== hovered) {
      hovered = node;
      if (!reading) { place(node); }
    }
  }

  function onClick(event) {
    if (!enabled || event.composedPath().indexOf(host) >= 0) { return; }
    var selection = String(global.getSelection() || '').trim();
    var node = blockAt(event.target);
    if (!selection && !node) { return; }
    event.preventDefault();
    event.stopPropagation();
    read(selection || node.innerText, selection ? null : node);
  }

  function onKey(event) {
    if (event.key !== 'Escape') { return; }
    if (token && (audio || queue.length)) { stop(); } else { hide(); }
  }

  function hide() {
    stop();
    enabled = false;
    host.style.display = 'none';
    outline.style.display = 'none';
  }

  function show() {
    enabled = true;
    host.style.display = '';
    setState('Наведите мышь на абзац и щёлкните. Выделенный фрагмент читается вместо абзаца.', false);
  }

  shadow.querySelector('.stop').addEventListener('click', function () { stop(); });
  shadow.querySelector('.close').addEventListener('click', hide);
  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onClick, true);
  document.addEventListener('keydown', onKey, true);
  global.addEventListener('scroll', function () { place(reading || hovered, reading ? '#9b2f2f' : null); }, true);

  global.__glashataiPointer = { show: show, hide: hide, read: read, stop: stop, chunks: chunks };
})(typeof window !== 'undefined' ? window : globalThis);
