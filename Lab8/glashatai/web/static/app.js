/* Общее для всех страниц «Глашатая»: запросы к серверу, настройки чтения,
 * всплывающие сообщения и Пафнутий в углу.
 *
 * Пафнутий здесь — индикатор: пока система читает, он шевелит ртом в такт
 * звуку (уровень приходит от проигрывателя), а реплики появляются в его
 * облачке.
 */

(function (global) {
  'use strict';

  var config = global.GLASHATAI || {};

  function ready(callback) {
    if (document.readyState !== 'loading') { callback(); }
    else { document.addEventListener('DOMContentLoaded', callback); }
  }

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  /* Запрос с JSON в обе стороны; ошибка сервера приходит как {error}. */
  function api(method, url, body) {
    var options = { method: method, credentials: 'same-origin', headers: {} };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    return fetch(url, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        data = data || {};
        data.status = response.status;
        if (!response.ok && !data.error) { data.error = 'сервер ответил ' + response.status; }
        return data;
      });
    }, function () {
      return { status: 0, error: 'сервер не отвечает — запущена ли система (python run.py)?' };
    });
  }

  /* --- настройки чтения: общие для всех страниц ------------------------------------- */

  var STORE = 'glashatai-reading';

  function loadPrefs(defaults) {
    var prefs = JSON.parse(JSON.stringify(defaults || {}));
    try {
      var saved = JSON.parse(global.localStorage.getItem(STORE) || '{}');
      ['settings', 'options'].forEach(function (part) {
        if (saved[part] && typeof saved[part] === 'object') {
          prefs[part] = prefs[part] || {};
          Object.keys(saved[part]).forEach(function (key) { prefs[part][key] = saved[part][key]; });
        }
      });
    } catch (e) { /* без хранилища — настройки по умолчанию */ }
    return prefs;
  }

  var saveTimer = null;
  /* Настройки хранятся в браузере и уходят на сервер: ими же читаются тексты из
     других программ и с чужих страниц. */
  function savePrefs(prefs) {
    try { global.localStorage.setItem(STORE, JSON.stringify(prefs)); } catch (e) { /* без хранилища */ }
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      api('POST', '/api/settings', { settings: prefs.settings, options: prefs.options });
    }, 600);
  }

  /* --- всплывающее сообщение -------------------------------------------------------- */

  var toastTimer = null;
  function toast(text, ms) {
    var node = document.getElementById('toast');
    if (!node) { return; }
    node.textContent = text;
    node.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.classList.remove('show'); }, ms || 2600);
  }

  /* --- Пафнутий в углу ------------------------------------------------------------- */

  var said = [];
  var bubbleTimer = null;

  function say(text, options) {
    if (!text) { return; }
    said.push(text);
    if (said.length > 12) { said.shift(); }
    var host = document.getElementById('companion');
    var bubble = document.getElementById('companion-bubble');
    if (!host || !bubble) { return; }
    bubble.textContent = text;
    host.classList.add('speaking');
    clearTimeout(bubbleTimer);
    if (!(options && options.sticky)) {
      bubbleTimer = setTimeout(function () { host.classList.remove('speaking'); }, 3500 + 45 * text.length);
    }
  }

  function hush(delay) {
    clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(function () {
      var host = document.getElementById('companion');
      if (host) { host.classList.remove('speaking'); }
    }, delay === undefined ? 1500 : delay);
  }

  var POSES = {
    idle: { raise: 0, facing: 0 },
    speaking: { raise: 0.25, facing: -0.35 },
    thinking: { raise: 0, facing: 0.2, look: { x: 0.7, y: -0.9 } },
    happy: { raise: 1, facing: 0 },
    sleeping: { raise: 0, facing: 0, look: { x: 0, y: 0.4 } }
  };

  /* уровень звука 0…1 — его сообщает проигрыватель, пока система читает */
  var voiceLevel = 0;
  var companion = { model: null, mood: function () {}, level: function (value) { voiceLevel = value; } };

  function buildCompanion() {
    var host = document.getElementById('companion');
    var figure = document.getElementById('companion-figure');
    if (!host || !figure || !global.Pafnuty) { return; }
    var model = global.Pafnuty.create({ mode: 'hang' });
    figure.appendChild(model.el);
    companion.model = model;
    var mood = 'idle';
    var pointer = { x: 0, y: 0.2 };
    var look = { x: 0, y: 0 };
    var raise = 0;
    var facing = 0;
    var nextBlink = 2000;
    var still = global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var started = performance.now();

    document.addEventListener('pointermove', function (event) {
      var box = figure.getBoundingClientRect();
      var dx = event.clientX - (box.left + box.width / 2);
      var dy = event.clientY - (box.top + box.height * 0.6);
      var length = Math.sqrt(dx * dx + dy * dy) || 1;
      var strength = Math.min(1, length / 160);
      pointer.x = dx / length * strength;
      pointer.y = dy / length * strength;
    });

    function frame(now) {
      var t = (now - started) / 1000;
      var want = POSES[mood] || POSES.idle;
      var target = want.look || pointer;
      look.x += (target.x - look.x) * 0.14;
      look.y += (target.y - look.y) * 0.14;
      raise += (want.raise - raise) * 0.18;
      facing += (want.facing - facing) * 0.12;
      model.set({ mode: 'hang', sway: still ? 0 : t * 1.4, look: look, raise: raise, facing: facing,
                  lean: still ? 0 : Math.sin(t * 1.6) * 0.9 });
      if (mood === 'speaking') { model.talk(Math.min(1, voiceLevel * 1.4)); }
      if (now > nextBlink && mood !== 'sleeping') {
        model.blink();
        nextBlink = now + 2500 + Math.random() * 3500;
      }
      if (!still) { global.requestAnimationFrame(frame); }
    }
    global.requestAnimationFrame(frame);

    companion.mood = function (name) {
      if (!POSES[name]) { name = 'idle'; }
      mood = name;
      model.mood(name);
      if (still) { global.requestAnimationFrame(frame); }
    };
    host.addEventListener('click', function () { say(host.querySelector('.companion-bubble').textContent); });
  }

  function watchHeader() {
    var brand = document.querySelector('header.top .brand');
    var nav = document.querySelector('header.top nav');
    function check() {
      if (brand && nav) { document.body.classList.toggle('header-wrapped', nav.offsetTop > brand.offsetTop + 10); }
    }
    check();
    global.addEventListener('resize', check);
  }

  global.Glashatai = {
    config: config, ready: ready, element: element, api: api, toast: toast,
    loadPrefs: loadPrefs, savePrefs: savePrefs, say: say, hush: hush, companion: companion
  };

  ready(function () {
    watchHeader();
    buildCompanion();
  });
})(window);
