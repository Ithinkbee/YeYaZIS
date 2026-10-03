/* Сапёр для «Изборника»: вместо мин на поле паучата, которых спрятал Пафнутий.
 *
 * Игра целиком живёт в браузере, как пасьянс «Паук» в «Арахне»: она ни на
 * что в системе не влияет, и держать её состояние на сервере незачем.
 *
 * Файл разделён надвое. Сверху — правила без DOM: раскладка, открытие
 * клеток, флажки. Они экспортируются через module.exports и проверяются
 * тестами в node (tests/sweeper_rules.test.js). Снизу — отрисовка и
 * управление.
 */

(function (global) {
  'use strict';

  /* --- правила ------------------------------------------------------------ */

  var LIMITS = { rows: [5, 30], cols: [5, 40] };

  /* Классические уровни сложности Windows. */
  var PRESETS = {
    novice: { rows: 9, cols: 9, spiders: 10 },
    amateur: { rows: 16, cols: 16, spiders: 40 },
    expert: { rows: 16, cols: 30, spiders: 99 }
  };

  function clamp(value, low, high) {
    value = Math.round(Number(value));
    if (!isFinite(value)) { return low; }
    return Math.max(low, Math.min(high, value));
  }

  /** Размеры в допустимых пределах; паучат хотя бы один и меньше, чем клеток. */
  function normalize(options) {
    var rows = clamp(options.rows, LIMITS.rows[0], LIMITS.rows[1]);
    var cols = clamp(options.cols, LIMITS.cols[0], LIMITS.cols[1]);
    var spiders = clamp(options.spiders, 1, rows * cols - 1);
    return { rows: rows, cols: cols, spiders: spiders };
  }

  function createGame(options) {
    var size = normalize(options);
    var cells = [];
    for (var i = 0; i < size.rows * size.cols; i++) {
      cells.push({ spider: false, open: false, flag: false, count: 0 });
    }
    return {
      rows: size.rows, cols: size.cols, spiders: size.spiders,
      cells: cells,
      laid: false,       /* паучата раскладываются при первом открытии */
      opened: 0,
      flags: 0,
      over: null,        /* null | 'win' | 'lose' */
      exploded: -1
    };
  }

  function neighbors(game, index) {
    var row = Math.floor(index / game.cols);
    var col = index % game.cols;
    var result = [];
    for (var dr = -1; dr <= 1; dr++) {
      for (var dc = -1; dc <= 1; dc++) {
        if (!dr && !dc) { continue; }
        var r = row + dr;
        var c = col + dc;
        if (r >= 0 && r < game.rows && c >= 0 && c < game.cols) { result.push(r * game.cols + c); }
      }
    }
    return result;
  }

  /**
   * Раскладывает паучат после первого хода. В открытой клетке их не бывает, а
   * если паучат не слишком много — и вокруг неё: первый ход открывает
   * область, а не одинокую цифру, с которой не за что зацепиться.
   */
  function lay(game, safe, random) {
    var forbidden = {};
    forbidden[safe] = true;
    if (game.cells.length - 9 >= game.spiders) {
      neighbors(game, safe).forEach(function (index) { forbidden[index] = true; });
    }
    var free = [];
    for (var i = 0; i < game.cells.length; i++) {
      if (!forbidden[i]) { free.push(i); }
    }
    /* частичное перемешивание Фишера — Йетса: нужны только первые spiders клеток */
    for (var k = 0; k < game.spiders; k++) {
      var j = k + Math.floor(random() * (free.length - k));
      var swap = free[k];
      free[k] = free[j];
      free[j] = swap;
      game.cells[free[k]].spider = true;
    }
    game.cells.forEach(function (cell, index) {
      cell.count = neighbors(game, index).filter(function (n) { return game.cells[n].spider; }).length;
    });
    game.laid = true;
  }

  /**
   * Открывает клетку. Пустая клетка (без паучат вокруг) открывает соседей,
   * и так по цепочке. Возвращает номера открытых клеток.
   */
  function open(game, index, random) {
    var cell = game.cells[index];
    if (game.over || !cell || cell.open || cell.flag) { return []; }
    if (!game.laid) { lay(game, index, random || Math.random); }
    if (cell.spider) {
      cell.open = true;
      game.over = 'lose';
      game.exploded = index;
      return [index];
    }
    var opened = [];
    var queue = [index];
    while (queue.length) {
      var current = queue.shift();
      var target = game.cells[current];
      if (target.open || target.flag || target.spider) { continue; }
      target.open = true;
      game.opened++;
      opened.push(current);
      if (target.count === 0) {
        neighbors(game, current).forEach(function (n) {
          if (!game.cells[n].open) { queue.push(n); }
        });
      }
    }
    if (game.opened === game.cells.length - game.spiders) {
      game.over = 'win';
      /* на выигранном поле все паучата помечены */
      game.cells.forEach(function (c) {
        if (c.spider && !c.flag) { c.flag = true; game.flags++; }
      });
    }
    return opened;
  }

  /** Ставит или снимает флажок на закрытой клетке. */
  function toggleFlag(game, index) {
    var cell = game.cells[index];
    if (game.over || !cell || cell.open) { return false; }
    cell.flag = !cell.flag;
    game.flags += cell.flag ? 1 : -1;
    return true;
  }

  /**
   * Щелчок по открытой цифре: если вокруг уже стоит столько флажков, сколько
   * паучат, открываются все остальные соседи. Ошибочный флажок здесь
   * проигрывает партию — как и в классическом сапёре.
   */
  function chord(game, index, random) {
    var cell = game.cells[index];
    if (game.over || !cell || !cell.open || !cell.count) { return []; }
    var around = neighbors(game, index);
    var flags = around.filter(function (n) { return game.cells[n].flag; }).length;
    if (flags !== cell.count) { return []; }
    var opened = [];
    around.forEach(function (n) {
      if (!game.cells[n].open && !game.cells[n].flag) {
        opened = opened.concat(open(game, n, random));
      }
    });
    return opened;
  }

  var rules = {
    LIMITS: LIMITS, PRESETS: PRESETS,
    normalize: normalize, createGame: createGame, neighbors: neighbors,
    lay: lay, open: open, toggleFlag: toggleFlag, chord: chord
  };

  /* Вне браузера файл подключается тестами: отрисовка тогда не нужна. */
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = rules;
    return;
  }
  global.SweeperRules = rules;

  /* --- отрисовка и управление ------------------------------------------- */

  var LONG_PRESS = 450;     /* мс: долгое касание ставит флажок */
  var STORAGE_KEY = 'izbornik-sweeper';

  function ready(callback) {
    if (document.readyState !== 'loading') { callback(); }
    else { document.addEventListener('DOMContentLoaded', callback); }
  }

  ready(function () {
    var board = document.getElementById('sweeper-board');
    if (!board) { return; }
    var wrap = document.getElementById('sweeper-wrap');
    var inputs = {
      rows: document.getElementById('sweeper-rows'),
      cols: document.getElementById('sweeper-cols'),
      spiders: document.getElementById('sweeper-spiders')
    };
    var leftBox = document.getElementById('sweeper-left');
    var clockBox = document.getElementById('sweeper-clock');
    var noteBox = document.getElementById('sweeper-note');
    var densityBox = document.getElementById('sweeper-density');
    var flagMode = document.getElementById('sweeper-flag-mode');
    var lines = JSON.parse(document.getElementById('sweeper-lines').textContent);

    var game = null;
    var elements = [];
    var startedAt = 0;
    var clockTimer = null;
    var pressTimer = null;
    var pressed = null;        /* {index, fired, x, y} — касание, которое может стать долгим */
    var longPress = { index: -1, at: 0 };

    function say(occasion) {
      if (global.Izbornik) { global.Izbornik.say(global.Izbornik.pick(lines, occasion)); }
    }

    function note(text, kind) {
      noteBox.textContent = text || '';
      noteBox.className = 'sweeper-note' + (kind ? ' is-' + kind : '');
    }

    function clock(seconds) {
      var s = Math.floor(seconds);
      return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
    }

    function stopClock() {
      clearInterval(clockTimer);
      clockTimer = null;
    }

    function tick() {
      clockBox.textContent = clock((Date.now() - startedAt) / 1000);
    }

    function readSettings() {
      return rules.normalize({
        rows: inputs.rows.value, cols: inputs.cols.value, spiders: inputs.spiders.value
      });
    }

    function showSettings(size) {
      inputs.rows.value = size.rows;
      inputs.cols.value = size.cols;
      inputs.spiders.value = size.spiders;
      inputs.spiders.max = size.rows * size.cols - 1;
      densityBox.textContent = Math.round(100 * size.spiders / (size.rows * size.cols)) + ' % клеток';
      document.querySelectorAll('[data-preset]').forEach(function (button) {
        var preset = rules.PRESETS[button.dataset.preset];
        button.classList.toggle('on', preset.rows === size.rows && preset.cols === size.cols &&
          preset.spiders === size.spiders);
      });
    }

    function start(size, greet) {
      stopClock();
      game = rules.createGame(size);
      showSettings(game);
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(size)); } catch (e) { /* не страшно */ }
      build();
      clockBox.textContent = '0:00';
      note('Первый ход безопасен: паучата разбегутся по полю, как только вы откроете клетку.');
      if (greet) { say('sweeper_start'); }
    }

    /* Размер клетки подбирается под ширину страницы: 30 столбцов профи должны
       поместиться без прокрутки. Из ширины вычитаются отступы поля (по 6 px)
       и зазоры между клетками (по 2 px) — как в style.css. */
    function fit() {
      if (!game) { return; }
      var width = wrap.clientWidth - 12 - 2 * (game.cols - 1);
      var cell = Math.max(20, Math.min(34, Math.floor(width / game.cols)));
      board.style.setProperty('--cell', cell + 'px');
    }

    function build() {
      board.innerHTML = '';
      board.style.setProperty('--cols', game.cols);
      board.classList.remove('is-over');
      elements = game.cells.map(function (cell, index) {
        var element = document.createElement('div');
        element.className = 'sw-cell';
        element.dataset.index = String(index);
        board.appendChild(element);
        return element;
      });
      fit();
      render();
    }

    function spiderIcon() {
      return '<svg class="sw-icon" viewBox="0 0 60 60" aria-hidden="true"><use href="#spider-glyph"></use></svg>';
    }

    function render() {
      game.cells.forEach(function (cell, index) {
        var element = elements[index];
        var classes = ['sw-cell'];
        var html = '';
        if (cell.open) {
          classes.push('is-open');
          if (cell.spider) {
            classes.push('is-spider');
            html = spiderIcon();
          } else if (cell.count) {
            classes.push('n' + cell.count);
            html = String(cell.count);
          }
        } else if (game.over === 'lose' && cell.spider && !cell.flag) {
          classes.push('is-open', 'is-spider');
          html = spiderIcon();
        } else if (cell.flag) {
          classes.push('is-flag');
          if (game.over === 'lose' && !cell.spider) { classes.push('is-wrong'); }
          html = '<svg class="sw-icon" viewBox="0 0 20 20" aria-hidden="true"><use href="#flag-glyph"></use></svg>';
        }
        if (index === game.exploded) { classes.push('is-exploded'); }
        var className = classes.join(' ');
        if (element.className !== className) { element.className = className; }
        if (element.innerHTML !== html) { element.innerHTML = html; }
      });
      leftBox.textContent = String(game.spiders - game.flags);
      board.classList.toggle('is-over', !!game.over);
    }

    function afterMove(opened) {
      if (opened.length && !clockTimer && !game.over) {
        startedAt = Date.now();
        clockTimer = setInterval(tick, 250);
      }
      render();
      if (!game.over) {
        if (opened.length) { note(''); }
        return;
      }
      if (!startedAt) { startedAt = Date.now(); }
      tick();
      stopClock();
      startedAt = 0;
      if (game.over === 'win') {
        note('Все паучата найдены за ' + clockBox.textContent + '. Пафнутий пересчитывает родню.', 'good');
        say('sweeper_win');
      } else {
        note('Паучонок проснулся. Остальные показаны; неверные флажки перечёркнуты.', 'bad');
        say('sweeper_lose');
      }
    }

    function primary(index) {
      var cell = game.cells[index];
      if (cell.open) { afterMove(rules.chord(game, index)); }
      else { afterMove(rules.open(game, index)); }
    }

    function flag(index) {
      if (game.cells[index].open) { afterMove(rules.chord(game, index)); return; }
      if (rules.toggleFlag(game, index)) { render(); }
    }

    function cellIndex(event) {
      var element = event.target.closest('.sw-cell');
      return element ? Number(element.dataset.index) : -1;
    }

    board.addEventListener('click', function (event) {
      var index = cellIndex(event);
      if (index < 0 || !game || game.over) { return; }
      if (pressed && pressed.fired) { pressed = null; return; }
      if (flagMode.checked) { flag(index); } else { primary(index); }
    });

    board.addEventListener('contextmenu', function (event) {
      event.preventDefault();
      var index = cellIndex(event);
      /* долгое касание в части браузеров вызывает ещё и contextmenu: флажок уже поставлен */
      if (longPress.index === index && Date.now() - longPress.at < 800) { return; }
      if (index >= 0 && game && !game.over) { flag(index); }
    });

    /* средняя кнопка — открыть соседей цифры */
    board.addEventListener('auxclick', function (event) {
      var index = cellIndex(event);
      if (event.button === 1 && index >= 0 && game && !game.over) { afterMove(rules.chord(game, index)); }
    });

    board.addEventListener('pointerdown', function (event) {
      pressed = null;
      clearTimeout(pressTimer);
      if (event.pointerType !== 'touch') { return; }
      var index = cellIndex(event);
      if (index < 0) { return; }
      pressed = { index: index, fired: false, x: event.clientX, y: event.clientY };
      pressTimer = setTimeout(function () {
        if (pressed && game && !game.over) {
          pressed.fired = true;
          longPress = { index: pressed.index, at: Date.now() };
          flag(pressed.index);
        }
      }, LONG_PRESS);
    });
    ['pointerup', 'pointercancel'].forEach(function (type) {
      board.addEventListener(type, function () { clearTimeout(pressTimer); });
    });
    board.addEventListener('pointermove', function (event) {
      if (pressed && !pressed.fired &&
          Math.abs(event.clientX - pressed.x) + Math.abs(event.clientY - pressed.y) > 12) {
        clearTimeout(pressTimer);
        pressed = null;
      }
    });

    document.getElementById('sweeper-new').addEventListener('click', function () {
      start(readSettings(), true);
    });
    document.querySelectorAll('[data-preset]').forEach(function (button) {
      button.addEventListener('click', function () {
        start(rules.PRESETS[button.dataset.preset], true);
      });
    });
    Object.keys(inputs).forEach(function (name) {
      inputs[name].addEventListener('change', function () { start(readSettings(), false); });
    });
    window.addEventListener('resize', fit);

    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY)); } catch (e) { saved = null; }
    start(saved && saved.rows ? rules.normalize(saved) : rules.PRESETS.novice, false);
  });
})(typeof window !== 'undefined' ? window : globalThis);
