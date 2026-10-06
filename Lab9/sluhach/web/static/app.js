/* Общее для всех страниц «Слухача»: Пафнутий в углу, его облачко с репликами
 * и скрытое окно администратора с фразами-пасхалками.
 *
 * Пафнутий здесь не украшение, а индикатор: на пульте он показывает, что
 * делает система, — поднимает передние ноги, когда слышит речь, смотрит
 * вверх, пока она распознаётся, и шевелит ртом, пока звучит ответ. Сам ответ
 * появляется в его облачке.
 */

(function (global) {
  'use strict';

  var config = global.SLUHACH || {};

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

  /* Запрос к серверу с JSON в обе стороны; ошибка сервера приходит как {error}. */
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
      return { status: 0, error: 'сервер не отвечает' };
    });
  }

  /* --- реплики Пафнутия ------------------------------------------------------ */

  /* недавно сказанное: такие реплики повторяются, только если других не осталось */
  var said = [];
  var bubbleTimer = null;
  var spokenAt = 0;

  function hideBubble() {
    var companion = document.getElementById('companion');
    if (companion) { companion.classList.remove('speaking'); }
  }

  /* Пафнутий говорит из угла: реплика появляется в облачке под пауком. Если
     предыдущая прозвучала только что, новая дописывается к ней — иначе первую
     никто не успел бы прочесть. options.sticky — облачко не гаснет само: его
     уберёт hush(), когда отзвучит голос. */
  function say(text, options) {
    if (!text) { return; }
    said.push(text);
    if (said.length > 12) { said.shift(); }

    var companion = document.getElementById('companion');
    var bubble = document.getElementById('companion-bubble');
    if (!companion || !bubble) { return; }

    var now = Date.now();
    var line = element('p', '', text);
    if (companion.classList.contains('speaking') && now - spokenAt < 2500 && !(options && options.fresh)) {
      while (bubble.children.length > 1) { bubble.removeChild(bubble.firstChild); }
    } else {
      bubble.textContent = '';
    }
    bubble.appendChild(line);
    spokenAt = now;

    companion.classList.add('speaking');
    clearTimeout(bubbleTimer);
    if (!(options && options.sticky)) {
      bubbleTimer = setTimeout(hideBubble, 4000 + 45 * bubble.textContent.length);
    }
  }

  function hush(delay) {
    clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(hideBubble, delay === undefined ? 2200 : delay);
  }

  /* Реплика по поводу из набора, присланного страницей: {повод: [варианты]}.
     Поля вида {name} подставляются; вариант, которому поля не хватило, не
     выбирается. */
  function pick(lines, occasion, fields) {
    var variants = (lines && lines[occasion]) || [];
    var filled = variants.map(function (text) {
      var complete = true;
      var result = text.replace(/\{(\w+)\}/g, function (all, name) {
        if (fields && fields[name] !== undefined) { return fields[name]; }
        complete = false;
        return all;
      });
      return complete ? result : '';
    }).filter(Boolean);
    var fresh = filled.filter(function (text) { return said.indexOf(text) < 0; });
    var pool = fresh.length ? fresh : filled;
    return pool.length ? pool[Math.floor(Math.random() * pool.length)] : '';
  }

  /* --- Пафнутий в углу --------------------------------------------------------- */

  /* Куда и как смотрит паук в каждом состоянии. raise — передние ноги вверх. */
  var MOOD_POSE = {
    idle: { raise: 0, facing: 0 },
    sleeping: { raise: 0, facing: 0, look: { x: 0, y: 0.4 } },
    listening: { raise: 0, facing: -0.35 },
    hearing: { raise: 1, facing: -0.35, look: { x: -0.5, y: 0.5 } },
    thinking: { raise: 0, facing: 0.2, look: { x: 0.7, y: -0.9 } },
    speaking: { raise: 0.25, facing: -0.35 },
    happy: { raise: 1, facing: 0 },
    startled: { raise: 1, facing: 0 },
    dizzy: { raise: 0, facing: 0 }
  };

  var companion = {
    model: null,
    mood: function () {},
    away: function () {}
  };

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
      var want = MOOD_POSE[mood] || MOOD_POSE.idle;
      var target = want.look || pointer;
      look.x += (target.x - look.x) * 0.14;
      look.y += (target.y - look.y) * 0.14;
      raise += (want.raise - raise) * 0.18;
      facing += (want.facing - facing) * 0.12;
      model.set({
        mode: 'hang', sway: still ? 0 : t * 1.4, look: look, raise: raise, facing: facing,
        lean: still ? 0 : Math.sin(t * 1.6) * 0.9
      });
      if (mood === 'speaking') {
        /* рот открывается в ритме слогов: быстрая волна, перебитая медленной */
        model.talk(0.25 + 0.75 * Math.abs(Math.sin(t * 9.5)) * (0.55 + 0.45 * Math.sin(t * 2.7 + 1)));
      }
      if (now > nextBlink && mood !== 'sleeping') {
        model.blink();
        nextBlink = now + 2500 + Math.random() * 3500;
      }
      if (!still) { global.requestAnimationFrame(frame); }
    }
    global.requestAnimationFrame(frame);

    companion.mood = function (name) {
      if (!MOOD_POSE[name]) { name = 'idle'; }
      mood = name;
      model.mood(name);
      if (still) { global.requestAnimationFrame(frame); }
    };
    companion.away = function (value) { host.classList.toggle('is-away', !!value); };

    /* пять быстрых щелчков по пауку открывают тайник */
    var clicks = [];
    host.addEventListener('click', function () {
      var now = Date.now();
      clicks = clicks.filter(function (time) { return now - time < 2500; });
      clicks.push(now);
      if (clicks.length >= 5) {
        clicks = [];
        secret.open();
      }
    });

    /* вердикт или приветствие звучит само, без наведения на паука */
    var bubble = document.getElementById('companion-bubble');
    if (bubble && host.dataset.speaks) {
      var greeting = bubble.textContent.trim();
      setTimeout(function () { say(greeting); }, 300);
    }
  }

  /* --- тайник: фразы-пасхалки --------------------------------------------------- */

  var secret = {
    open: function () {}
  };

  function buildSecret() {
    var dialog = document.getElementById('secret');
    if (!dialog || typeof dialog.showModal !== 'function') { return; }
    var $ = function (id) { return document.getElementById(id); };
    var login = $('secret-login');
    var body = $('secret-body');
    var rows = $('secret-rows');
    var loginError = $('secret-login-error');
    var error = $('secret-error');
    var title = $('secret-title');

    /* Вошёл ли администратор: от этого зависит, что видно на странице — ссылка
       входа или пункт «Тайник» с кнопкой выхода. */
    function setAdmin(value) {
      document.body.classList.toggle('is-admin', !!value);
    }

    function showLogin(message) {
      setAdmin(false);
      login.hidden = false;
      body.hidden = true;
      title.textContent = title.dataset.login;
      loginError.textContent = message || '';
      $('secret-password').value = '';
      setTimeout(function () { ($('secret-name').value ? $('secret-password') : $('secret-name')).focus(); }, 50);
    }

    function row(egg) {
      var line = element('tr');
      var key = element('input');
      key.type = 'text';
      key.value = egg.key;
      key.maxLength = config.eggKeyLimit || 120;
      var answer = element('input');
      answer.type = 'text';
      answer.value = egg.answer;
      answer.maxLength = config.eggAnswerLimit || 400;
      var save = element('button', 'ghost small-button', 'Сохранить');
      save.type = 'button';
      save.addEventListener('click', function () {
        api('PUT', '/api/eggs/' + encodeURIComponent(egg.id), { key: key.value, answer: answer.value }).then(update);
      });
      var remove = element('button', 'ghost small-button', 'Удалить');
      remove.type = 'button';
      remove.addEventListener('click', function () {
        api('DELETE', '/api/eggs/' + encodeURIComponent(egg.id)).then(update);
      });
      var language = element('td');
      language.appendChild(element('span', 'tag tag-' + egg.language, egg.language === 'de' ? 'нем.' : 'рус.'));
      [key, answer].forEach(function (input) {
        var cell = element('td');
        cell.appendChild(input);
        line.appendChild(cell);
      });
      line.insertBefore(language, line.firstChild);
      var actions = element('td', 'actions');
      actions.appendChild(save);
      actions.appendChild(document.createTextNode(' '));
      actions.appendChild(remove);
      line.appendChild(actions);
      return line;
    }

    function showEggs(eggs) {
      setAdmin(true);
      login.hidden = true;
      body.hidden = false;
      title.textContent = title.dataset.open;
      rows.textContent = '';
      eggs.forEach(function (egg) { rows.appendChild(row(egg)); });
      $('secret-empty').hidden = eggs.length > 0;
      $('secret-table').hidden = eggs.length === 0;
    }

    /* ответ сервера на любую правку: новый список, ошибка или «войдите заново» */
    function update(data) {
      if (data.status === 401) { showLogin('Вход истёк — введите пароль ещё раз.'); return; }
      error.textContent = data.error ? 'Не сохранено: ' + data.error + '.' : '';
      if (data.eggs) { showEggs(data.eggs); }
    }

    function refresh() {
      api('GET', '/api/eggs').then(function (data) {
        if (data.status === 401) { showLogin(''); }
        else if (data.eggs) { error.textContent = ''; showEggs(data.eggs); }
        else { showLogin(data.error || ''); }
      });
    }

    $('secret-login-form').addEventListener('submit', function (event) {
      event.preventDefault();
      api('POST', '/api/admin/login', {
        login: $('secret-name').value, password: $('secret-password').value
      }).then(function (data) {
        if (data.eggs) { error.textContent = ''; showEggs(data.eggs); }
        else { showLogin(data.error ? 'Не пущу: ' + data.error + '.' : 'Не пущу.'); }
      });
    });

    $('secret-add').addEventListener('submit', function (event) {
      event.preventDefault();
      api('POST', '/api/eggs', { key: $('secret-key').value, answer: $('secret-answer').value }).then(function (data) {
        update(data);
        if (!data.error) {
          $('secret-key').value = '';
          $('secret-answer').value = '';
          $('secret-key').focus();
        }
      });
    });

    $('secret-probe-form').addEventListener('submit', function (event) {
      event.preventDefault();
      var result = $('secret-probe-result');
      api('POST', '/api/eggs/test', { text: $('secret-probe').value }).then(function (data) {
        if (data.status === 401) { showLogin('Вход истёк — введите пароль ещё раз.'); return; }
        if (data.error) { result.textContent = data.error; return; }
        result.textContent = data.match
          ? 'Сработает «' + data.match.key + '» (сходство ' + Math.round(data.score * 100) + ' %): «' + data.match.answer + '»'
          : 'Ни одна ключевая фраза не подходит: система повторит фразу или выполнит операцию.';
      });
    });

    /* выход: и из окна, и по кнопке внизу страницы */
    document.querySelectorAll('[data-admin-logout]').forEach(function (button) {
      button.addEventListener('click', function () {
        api('POST', '/api/admin/logout').then(function () {
          showLogin('');
          if (!dialog.contains(button) && dialog.open) { dialog.close(); }
        });
      });
    });
    $('secret-close').addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('close', function () {
      /* адрес /admin открывает окно; закрыли окно — метка из адреса убирается */
      if (global.location.hash === '#admin' && global.history && global.history.replaceState) {
        global.history.replaceState(null, '', global.location.pathname + global.location.search);
      }
    });

    secret.open = function () {
      if (dialog.open) { return; }
      /* до ответа сервера окно показывает то, что страница знает сама: вошедшему — заголовок
         тайника, остальным — вход. Ответ /api/eggs всё равно решает окончательно. */
      if (document.body.classList.contains('is-admin')) {
        login.hidden = true;
        body.hidden = true;
        title.textContent = title.dataset.open;
      } else {
        showLogin('');
      }
      dialog.showModal();
      refresh();
    };

    /* входы в окно: ссылки «Вход администратора» и «Тайник», адрес /admin, Ctrl+Alt+P */
    document.querySelectorAll('[data-admin-open]').forEach(function (link) {
      link.addEventListener('click', function (event) {
        event.preventDefault();
        secret.open();
      });
    });
    function byAddress() {
      if (global.location.hash === '#admin') { secret.open(); }
    }
    global.addEventListener('hashchange', byAddress);
    byAddress();
    document.addEventListener('keydown', function (event) {
      if (event.ctrlKey && event.altKey && !event.shiftKey && (event.code === 'KeyP')) {
        event.preventDefault();
        secret.open();
      }
    });
  }

  /* --- шапка ------------------------------------------------------------------ */

  function watchHeader() {
    /* меню ушло на вторую строку шапки — облачко паука не должно его закрывать */
    var brand = document.querySelector('header.top .brand');
    var nav = document.querySelector('header.top nav');
    function check() {
      if (brand && nav) { document.body.classList.toggle('header-wrapped', nav.offsetTop > brand.offsetTop + 10); }
    }
    check();
    global.addEventListener('resize', check);
  }

  global.Sluhach = {
    config: config, ready: ready, element: element, api: api,
    say: say, hush: hush, pick: pick, said: said,
    companion: companion, secret: secret
  };

  ready(function () {
    watchHeader();
    buildCompanion();
    buildSecret();
  });
})(window);
