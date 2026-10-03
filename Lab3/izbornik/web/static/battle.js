/* Бой с Пафнутием для «Изборника».
 *
 * Вверху — дорожка между Изборником игрока (слева) и паутиной Пафнутия
 * (справа), внизу — поле букв со спрятанными ключевыми словами реферата.
 * Найденное слово выходит из Изборника воином и идёт к паутине; из паутины
 * каждые десять секунд выходит паук и идёт к Изборнику. Встретившись, слово и
 * паук дерутся; дошедший до чужой базы бьёт по ней. За побеждённых пауков
 * игрок получает монеты и покупает на них улучшения своих слов.
 *
 * Бой идёт в браузере: сервер только выдаёт поля букв (/api/battle/grid).
 * Файл разделён надвое, как пасьянс «Паук» в «Арахне»: сверху — правила без
 * DOM, они экспортируются через module.exports и проверяются тестами в node
 * (tests/battle_rules.test.js); снизу — отрисовка и управление.
 */

(function (global) {
  'use strict';

  /* --- правила ------------------------------------------------------------ */

  var LANE = 1000;            /* длина дорожки в условных единицах */
  var BASE_FRONT = 80;        /* передний край Изборника */
  var WEB_FRONT = 920;        /* передний край паутины */
  var MELEE = 16;             /* дистанция ближнего боя */
  var BASE_HP = 600;          /* прочность Изборника и паутины */
  /* По базам бьют в треть силы: иначе толпа воинов у паутины решала бы бой за
     секунды и схватки посреди дорожки ничего бы не значили. */
  var SIEGE = 0.3;
  var SPIDER_INTERVAL = 10;   /* секунд между пауками */
  var FIRST_SPIDER = 5;       /* первый паук — через пять секунд после начала */
  /* Каждый следующий паук на 7 % крепче и злее. Числа подобраны прогоном
     боёв: игрок, находящий слово раз в 8 секунд, почти всегда побеждает за
     полторы минуты, раз в 10 секунд — примерно в половине боёв, раз в 12 —
     редко. */
  var GROWTH = 0.07;
  var BOSS_AT = 0.35;         /* Пафнутий выходит сам, когда от паутины остаётся 35 % */
  var WORD_SPEED = 55;        /* слово проходит дорожку секунд за пятнадцать */
  var POISON_SLOW = 0.8;      /* под ядом пауза между ударами длиннее на 80 % */
  var WEB_SLOW = 0.5;         /* опутанное паутиной слово идёт вдвое медленнее */
  var REPAIR = 120;           /* починка возвращает Изборнику столько прочности */

  /* Виды пауков. hp и damage растут с номером паука (GROWTH), остальное
     постоянно; period — пауза между ударами, reach — дальность удара. */
  var SPIDERS = {
    brown: { name: 'бурый паук', hp: 80, damage: 10, speed: 40, period: 1.0, reach: MELEE, coins: 5,
      note: 'обычный: кусает, пока не победят' },
    green: { name: 'зелёный паук', hp: 70, damage: 7, speed: 40, period: 1.0, reach: MELEE, coins: 7, poison: 5,
      note: 'ядовитый: укушенное слово пять секунд бьёт медленнее' },
    red: { name: 'красный паук', hp: 70, damage: 6, speed: 42, period: 1.0, reach: MELEE, coins: 7, burn: 4, burnDps: 4,
      note: 'огненный: поджигает слово, и оно четыре секунды теряет прочность' },
    white: { name: 'белый паук', hp: 50, damage: 6, speed: 35, period: 1.4, reach: 170, coins: 8, web: 2.5,
      note: 'стреляет паутиной издалека; опутанное слово идёт вдвое медленнее' },
    yellow: { name: 'жёлтый паук', hp: 45, damage: 8, speed: 85, period: 0.8, reach: MELEE, coins: 4,
      note: 'быстрый: добегает до Изборника вдвое скорее' },
    black: { name: 'чёрный паук', hp: 260, damage: 18, speed: 28, period: 1.4, reach: 18, coins: 15,
      note: 'крупный: медленный, но крепкий и больно бьёт' },
    boss: { name: 'Пафнутий', hp: 800, damage: 25, speed: 24, period: 1.5, reach: 20, coins: 40, boss: true,
      note: 'выходит сам, когда от паутины остаётся треть' }
  };
  /* Первые пауки выходят по порядку — так каждый вид появляется отдельно и
     его можно разглядеть; дальше — случайно по весам. */
  var INTRO = ['brown', 'brown', 'green', 'brown', 'red', 'yellow', 'white', 'brown', 'black'];
  var MIX = [['brown', 30], ['green', 15], ['red', 15], ['white', 14], ['yellow', 14], ['black', 12]];

  /* Улучшения слов. Действуют на все слова, в том числе уже вышедшие. */
  var UPGRADES = {
    damage: { name: 'Острое перо', text: 'урон слов +20 %', costs: [15, 30, 50, 75, 105] },
    hp: { name: 'Кожаный переплёт', text: 'прочность слов +20 %', costs: [15, 30, 50, 75, 105] },
    speed: { name: 'Скоропись', text: 'слова ходят и бьют на 12 % быстрее', costs: [25, 50, 80] },
    antidote: { name: 'Противоядие', text: 'яд, огонь и паутина слабее на 30 %', costs: [20, 40, 65] },
    repair: { name: 'Починка переплёта', text: 'Изборнику +' + REPAIR + ' прочности', costs: [25], repeat: true }
  };
  var UPGRADE_ORDER = ['damage', 'hp', 'speed', 'antidote', 'repair'];

  /** Воин-слово: чем длиннее слово, тем он крепче и сильнее. */
  function wordStats(length) {
    return { hp: 30 + 12 * length, damage: 4 + 1.5 * length };
  }

  function createBattle(random) {
    return {
      time: 0,
      nextId: 1,
      units: [],
      base: { hp: BASE_HP, max: BASE_HP },     /* Изборник */
      web: { hp: BASE_HP, max: BASE_HP },      /* паутина Пафнутия */
      spiderTimer: FIRST_SPIDER,
      spawned: 0,
      seen: {},
      boss: false,
      coins: 0,
      earned: 0,
      spent: 0,
      levels: { damage: 0, hp: 0, speed: 0, antidote: 0 },
      words: 0,
      letters: 0,
      longest: '',
      killed: 0,
      lost: 0,
      over: null,                               /* null | 'win' | 'lose' */
      random: random || Math.random
    };
  }

  function hpMultiplier(state) { return 1 + 0.2 * state.levels.hp; }
  function damageMultiplier(state) { return 1 + 0.2 * state.levels.damage; }
  function speedMultiplier(state) { return 1 + 0.12 * state.levels.speed; }
  function resistance(state) { return 1 - 0.3 * state.levels.antidote; }

  function spiderKind(number, random) {
    if (number <= INTRO.length) { return INTRO[number - 1]; }
    var total = MIX.reduce(function (sum, item) { return sum + item[1]; }, 0);
    var roll = random() * total;
    for (var i = 0; i < MIX.length; i++) {
      roll -= MIX[i][1];
      if (roll < 0) { return MIX[i][0]; }
    }
    return 'brown';
  }

  /** Найденное слово выходит на дорожку. */
  function sendWord(state, text, events) {
    var length = text.length;
    var stats = wordStats(length);
    var unit = {
      id: state.nextId++, side: 'word', kind: 'word', text: text,
      x: BASE_FRONT, baseHp: stats.hp, hp: stats.hp * hpMultiplier(state), maxHp: stats.hp * hpMultiplier(state),
      baseDamage: stats.damage, speed: WORD_SPEED, period: 1, reach: MELEE, cooldown: 0,
      poison: 0, burn: 0, burnDps: 0, web: 0, moving: true
    };
    state.units.push(unit);
    state.words++;
    state.letters += length;
    if (length > state.longest.length) { state.longest = text; }
    if (events) { events.push({ type: 'spawn', unit: unit }); }
    return unit;
  }

  /** Паук выходит из паутины; kind не задан — по расписанию. */
  function spawnSpider(state, kind, events) {
    if (kind !== 'boss') { state.spawned++; }
    kind = kind || spiderKind(state.spawned, state.random);
    var type = SPIDERS[kind];
    var growth = type.boss ? 1 : 1 + GROWTH * (state.spawned - 1);
    var unit = {
      id: state.nextId++, side: 'spider', kind: kind,
      x: WEB_FRONT, hp: type.hp * growth, maxHp: type.hp * growth, damage: type.damage * growth,
      speed: type.speed, period: type.period, reach: type.reach, cooldown: 0,
      coins: type.coins, growth: growth, moving: true
    };
    var first = !state.seen[kind];
    state.seen[kind] = true;
    state.units.push(unit);
    if (events) { events.push({ type: 'spawn', unit: unit, first: first }); }
    return unit;
  }

  /** Цена следующего уровня улучшения; null — улучшать больше некуда. */
  function price(state, key) {
    var upgrade = UPGRADES[key];
    if (!upgrade) { return null; }
    if (upgrade.repeat) { return upgrade.costs[0]; }
    var level = state.levels[key];
    return level < upgrade.costs.length ? upgrade.costs[level] : null;
  }

  function canBuy(state, key) {
    var cost = price(state, key);
    if (state.over || cost === null || state.coins < cost) { return false; }
    return key !== 'repair' || state.base.hp < state.base.max;
  }

  function buy(state, key) {
    if (!canBuy(state, key)) { return false; }
    var cost = price(state, key);
    state.coins -= cost;
    state.spent += cost;
    if (key === 'repair') {
      state.base.hp = Math.min(state.base.max, state.base.hp + REPAIR);
      return true;
    }
    var before = hpMultiplier(state);
    state.levels[key]++;
    if (key === 'hp') {
      /* прибавка прочности достаётся и словам, которые уже в бою */
      var after = hpMultiplier(state);
      state.units.forEach(function (unit) {
        if (unit.side !== 'word') { return; }
        unit.maxHp = unit.baseHp * after;
        unit.hp += unit.baseHp * (after - before);
      });
    }
    return true;
  }

  /** Ближайший к бойцу живой враг впереди. Пройти сквозь врага нельзя,
      поэтому для слова это паук с наименьшей координатой, для паука —
      слово с наибольшей. */
  function frontEnemy(state, unit) {
    var best = null;
    state.units.forEach(function (other) {
      if (other.side === unit.side || other.hp <= 0) { return; }
      if (!best || (unit.side === 'word' ? other.x < best.x : other.x > best.x)) { best = other; }
    });
    return best;
  }

  /** Бой на dt секунд вперёд. Возвращает события для отрисовки. */
  function step(state, dt) {
    var events = [];
    if (state.over) { return events; }
    state.time += dt;

    state.spiderTimer -= dt;
    while (state.spiderTimer <= 0) {
      spawnSpider(state, null, events);
      state.spiderTimer += SPIDER_INTERVAL;
    }
    if (!state.boss && state.web.hp < state.web.max * BOSS_AT) {
      state.boss = true;
      spawnSpider(state, 'boss', events);
    }

    var resist = resistance(state);
    state.units.forEach(function (unit) {
      if (unit.hp <= 0) { return; }
      var speed = unit.speed;
      var period = unit.period;
      var damage = unit.damage;
      if (unit.side === 'word') {
        unit.poison = Math.max(0, unit.poison - dt);
        unit.web = Math.max(0, unit.web - dt);
        if (unit.burn > 0) {
          unit.hp -= unit.burnDps * Math.min(dt, unit.burn);
          unit.burn = Math.max(0, unit.burn - dt);
          if (unit.hp <= 0) { return; }
        }
        damage = unit.baseDamage * damageMultiplier(state);
        speed = WORD_SPEED * speedMultiplier(state) * (unit.web > 0 ? 1 - WEB_SLOW * resist : 1);
        period = unit.period / speedMultiplier(state) * (unit.poison > 0 ? 1 + POISON_SLOW * resist : 1);
      }
      unit.cooldown = Math.max(0, unit.cooldown - dt);

      var enemy = frontEnemy(state, unit);
      var forward = unit.side === 'word' ? 1 : -1;
      var toEnemy = enemy ? (enemy.x - unit.x) * forward : Infinity;
      var toBase = unit.side === 'word' ? WEB_FRONT - unit.x : unit.x - BASE_FRONT;
      var target = null;
      /* допуск: подойдя вплотную, боец мог бы бесконечно «подходить» на
         исчезающе малое расстояние из-за погрешности округления */
      if (toEnemy <= unit.reach + 1e-6) { target = enemy; }
      else if (toBase <= unit.reach + 1e-6) { target = unit.side === 'word' ? 'web' : 'base'; }

      unit.moving = !target;
      if (!target) {
        /* подходит на расстояние удара, но не ближе ближнего боя: сквозь
           врага не проходят и на базу не залезают */
        var room = Math.min(toEnemy, toBase) - MELEE;
        unit.x += forward * Math.max(0, Math.min(speed * dt, room));
        return;
      }
      if (unit.cooldown > 0) { return; }
      unit.cooldown = period;

      if (target === 'web' || target === 'base') {
        var building = state[target];
        var blow = damage * SIEGE;
        building.hp = Math.max(0, building.hp - blow);
        events.push({ type: 'siege', unit: unit, target: target, damage: blow });
        return;
      }
      target.hp -= damage;
      events.push({ type: unit.reach > 2 * MELEE ? 'shot' : 'hit', unit: unit, target: target, damage: damage });
      if (unit.side === 'spider') {
        var type = SPIDERS[unit.kind];
        if (type.poison) { target.poison = type.poison; }
        if (type.burn) {
          target.burn = type.burn;
          target.burnDps = type.burnDps * unit.growth * resist;
        }
        if (type.web) { target.web = type.web; }
      }
    });

    state.units = state.units.filter(function (unit) {
      if (unit.hp > 0) { return true; }
      if (unit.side === 'spider') {
        state.coins += unit.coins;
        state.earned += unit.coins;
        state.killed++;
      } else {
        state.lost++;
      }
      events.push({ type: 'death', unit: unit });
      return false;
    });

    if (state.web.hp <= 0) { state.over = 'win'; }
    else if (state.base.hp <= 0) { state.over = 'lose'; }
    if (state.over) { events.push({ type: 'over', result: state.over }); }
    return events;
  }

  /* --- поле букв ------------------------------------------------------------ */

  /**
   * Выделение по прямой от клетки start до клетки end. Слова читаются только
   * слева направо и сверху вниз, но тянуть мышь можно и в обратную сторону —
   * клетки всё равно возвращаются по порядку чтения. Наискосок выделение
   * прилипает к ближайшему направлению.
   */
  function selectLine(start, end) {
    var cells = [];
    var i;
    if (Math.abs(end.col - start.col) >= Math.abs(end.row - start.row)) {
      for (i = Math.min(start.col, end.col); i <= Math.max(start.col, end.col); i++) {
        cells.push({ row: start.row, col: i });
      }
    } else {
      for (i = Math.min(start.row, end.row); i <= Math.max(start.row, end.row); i++) {
        cells.push({ row: i, col: start.col });
      }
    }
    return cells;
  }

  function wordCells(word) {
    var cells = [];
    for (var i = 0; i < word.letters.length; i++) {
      cells.push(word.dir === 'right'
        ? { row: word.row, col: word.col + i }
        : { row: word.row + i, col: word.col });
    }
    return cells;
  }

  /** Номер ещё не найденного слова, которое точно занимает выделенные клетки, или −1. */
  function matchWord(words, found, cells) {
    for (var w = 0; w < words.length; w++) {
      if (found[w]) { continue; }
      var target = wordCells(words[w]);
      if (target.length !== cells.length) { continue; }
      var same = target.every(function (cell, i) {
        return cell.row === cells[i].row && cell.col === cells[i].col;
      });
      if (same) { return w; }
    }
    return -1;
  }

  var rules = {
    LANE: LANE, BASE_FRONT: BASE_FRONT, WEB_FRONT: WEB_FRONT, MELEE: MELEE, BASE_HP: BASE_HP,
    SIEGE: SIEGE, SPIDER_INTERVAL: SPIDER_INTERVAL, FIRST_SPIDER: FIRST_SPIDER, GROWTH: GROWTH,
    BOSS_AT: BOSS_AT, REPAIR: REPAIR, POISON_SLOW: POISON_SLOW, WEB_SLOW: WEB_SLOW,
    SPIDERS: SPIDERS, INTRO: INTRO, UPGRADES: UPGRADES, UPGRADE_ORDER: UPGRADE_ORDER,
    wordStats: wordStats, createBattle: createBattle, spiderKind: spiderKind,
    sendWord: sendWord, spawnSpider: spawnSpider, price: price, canBuy: canBuy, buy: buy,
    step: step, selectLine: selectLine, wordCells: wordCells, matchWord: matchWord
  };

  /* Вне браузера файл подключается тестами: отрисовка тогда не нужна. */
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = rules;
    return;
  }
  global.BattleRules = rules;

  /* --- отрисовка и управление ------------------------------------------- */

  var STEP = 1 / 30;          /* шаг расчёта, с */
  var TALK_PAUSE = 5000;      /* реплики о рядовых событиях — не чаще раза в 5 с */
  var FOUND_PAUSE = 450;      /* найденное слово исчезает с поля за это время */

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

  function clock(seconds) {
    var s = Math.floor(seconds);
    return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
  }

  ready(function () {
    var root = document.getElementById('battle');
    if (!root) { return; }

    var $ = function (id) { return document.getElementById(id); };
    var intro = $('battle-intro');
    var arena = $('battle-arena');
    var startButton = $('battle-start');
    var startNote = $('battle-start-note');
    var languageBox = $('battle-language');
    var lane = $('lane');
    var unitsLayer = $('lane-units');
    var toast = $('lane-toast');
    var result = $('battle-result');
    var lettersBox = $('letters');
    var cover = $('letters-cover');
    var wordsBox = $('battle-words');
    var sourceBox = $('battle-source');
    var shopBox = $('battle-shop');
    var pauseButton = $('battle-pause');
    var surrenderButton = $('battle-surrender');
    var statsBox = $('battle-stats');
    var webPafnuty = $('web-pafnuty');
    var hud = {
      baseBar: $('hud-base-bar'), baseHp: $('hud-base-hp'),
      webBar: $('hud-web-bar'), webHp: $('hud-web-hp'),
      clock: $('hud-clock'), next: $('hud-next'), coins: $('hud-coins')
    };
    var lines = JSON.parse($('battle-lines').textContent);

    var state = null;
    var views = {};              /* id бойца -> {el, bar} */
    var grid = null;             /* текущее поле букв с сервера */
    var found = [];
    var cells = [];              /* [row][col] -> элемент клетки */
    var gone = [];               /* [row][col] -> буква стёрта */
    var played = [];             /* документы, из рефератов которых уже были поля */
    var upcoming = null;         /* следующее поле, запрошенное заранее */
    var selection = null;
    var paused = false;
    var running = false;
    var frameId = 0;
    var lastFrame = 0;
    var backlog = 0;
    var lastTalk = 0;
    var remarks = {};            /* разовые реплики: паутина рвётся, Изборник гибнет */
    var shopSignature = '';
    var language = 'ru';

    /* --- Пафнутий ---------------------------------------------------------- */

    function talk(occasion, fields, important) {
      var now = Date.now();
      if (!important && now - lastTalk < TALK_PAUSE) { return; }
      if (!global.Izbornik) { return; }
      var text = global.Izbornik.pick(lines, occasion, fields);
      if (!text) { return; }
      lastTalk = now;
      global.Izbornik.say(text);
    }

    function announce(text) {
      toast.textContent = text;
      toast.classList.remove('show');
      void toast.offsetWidth;                 /* перезапуск анимации */
      toast.classList.add('show');
    }

    /* --- легенда и лавка ---------------------------------------------------- */

    function spiderIcon(kind) {
      var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 60 60');
      svg.setAttribute('class', 'spider-icon spider-' + kind);
      var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
      use.setAttribute('href', '#spider-glyph');
      svg.appendChild(use);
      return svg;
    }

    function buildLegend() {
      var legend = $('spider-legend');
      Object.keys(rules.SPIDERS).forEach(function (kind) {
        var type = rules.SPIDERS[kind];
        var item = element('li');
        item.appendChild(spiderIcon(kind));
        var text = element('span');
        text.appendChild(element('b', '', type.name[0].toUpperCase() + type.name.slice(1)));
        text.appendChild(document.createTextNode(' — ' + type.note + '. За победу — ' + type.coins + ' мон.'));
        item.appendChild(text);
        legend.appendChild(item);
      });
    }

    function buildShop() {
      shopBox.innerHTML = '';
      rules.UPGRADE_ORDER.forEach(function (key) {
        var upgrade = rules.UPGRADES[key];
        var button = element('button', 'shop-item');
        button.type = 'button';
        button.dataset.upgrade = key;
        button.appendChild(element('b', 'shop-name', upgrade.name));
        button.appendChild(element('span', 'shop-text', upgrade.text));
        button.appendChild(element('span', 'shop-level'));
        button.appendChild(element('span', 'shop-price'));
        button.addEventListener('click', function () {
          if (!state || paused) { return; }
          if (rules.buy(state, key)) {
            if (key !== 'repair' && Math.random() < 0.5) { talk('battle_shop'); }
            refreshShop(true);
            drawHud();
          }
        });
        shopBox.appendChild(button);
      });
    }

    function refreshShop(force) {
      if (!state) { return; }
      var signature = state.coins + '|' + JSON.stringify(state.levels) + '|' + Math.round(state.base.hp) +
        '|' + paused + '|' + !!state.over;
      if (!force && signature === shopSignature) { return; }
      shopSignature = signature;
      shopBox.querySelectorAll('.shop-item').forEach(function (button) {
        var key = button.dataset.upgrade;
        var upgrade = rules.UPGRADES[key];
        var cost = rules.price(state, key);
        var level = upgrade.repeat ? '' : Array.apply(null, Array(upgrade.costs.length)).map(function (_, i) {
          return i < state.levels[key] ? '●' : '○';
        }).join('');
        button.querySelector('.shop-level').textContent = level;
        button.querySelector('.shop-price').textContent = cost === null ? 'всё' : cost + ' мон.';
        button.disabled = paused || !rules.canBuy(state, key);
        button.classList.toggle('is-max', cost === null);
      });
    }

    /* --- бойцы на дорожке --------------------------------------------------- */

    function createView(unit) {
      var node = element('div', 'unit unit-' + unit.side + (unit.side === 'spider' ? ' unit-' + unit.kind : ''));
      node.style.setProperty('--row', String(unit.id % 4));
      var hp = element('div', 'unit-hp');
      var bar = element('i');
      hp.appendChild(bar);
      node.appendChild(hp);
      if (unit.side === 'word') {
        node.appendChild(element('span', 'unit-body', unit.text.toUpperCase()));
        node.title = unit.text;
      } else {
        var body = spiderIcon(unit.kind);
        body.setAttribute('class', 'unit-body spider-icon spider-' + unit.kind);
        node.appendChild(body);
        node.title = rules.SPIDERS[unit.kind].name;
      }
      unitsLayer.appendChild(node);
      views[unit.id] = { el: node, bar: bar };
      placeView(unit);
    }

    function placeView(unit) {
      var view = views[unit.id];
      if (!view) { return; }
      view.el.style.left = (100 * unit.x / rules.LANE) + '%';
      view.bar.style.width = Math.max(0, 100 * unit.hp / unit.maxHp) + '%';
      var list = view.el.classList;
      list.toggle('is-moving', !!unit.moving);
      if (unit.side === 'word') {
        list.toggle('is-poisoned', unit.poison > 0);
        list.toggle('is-burning', unit.burn > 0);
        list.toggle('is-webbed', unit.web > 0);
      }
    }

    function flash(unit, className) {
      var view = unit && views[unit.id];
      if (!view) { return; }
      view.el.classList.remove(className);
      void view.el.offsetWidth;
      view.el.classList.add(className);
    }

    function flashBase(target) {
      var node = lane.querySelector(target === 'web' ? '.base-web' : '.base-book');
      node.classList.remove('is-hit');
      void node.offsetWidth;
      node.classList.add('is-hit');
    }

    function shoot(from, to) {
      var shot = element('div', 'web-shot');
      shot.style.left = (100 * from.x / rules.LANE) + '%';
      shot.style.setProperty('--row', String(from.id % 4));
      unitsLayer.appendChild(shot);
      void shot.offsetWidth;
      shot.style.left = (100 * to.x / rules.LANE) + '%';
      setTimeout(function () { shot.remove(); }, 320);
    }

    function removeView(unit) {
      var view = views[unit.id];
      if (!view) { return; }
      delete views[unit.id];
      view.el.classList.add('is-dead');
      if (unit.side === 'spider') {
        var coin = element('div', 'coin-pop', '+' + unit.coins);
        coin.style.left = (100 * unit.x / rules.LANE) + '%';
        unitsLayer.appendChild(coin);
        setTimeout(function () { coin.remove(); }, 1100);
      }
      setTimeout(function () { view.el.remove(); }, 480);
    }

    function clearLane() {
      Object.keys(views).forEach(function (id) { views[id].el.remove(); });
      views = {};
      unitsLayer.innerHTML = '';
    }

    /* --- ход боя ------------------------------------------------------------ */

    function handle(events) {
      events.forEach(function (event) {
        var unit = event.unit;
        if (event.type === 'spawn') {
          createView(unit);
          if (unit.side === 'spider' && unit.kind === 'boss') {
            if (webPafnuty) { webPafnuty.classList.add('is-away'); }
            announce('Пафнутий выходит сам! У него ' + Math.round(unit.hp) + ' прочности.');
            talk('battle_boss', null, true);
          } else if (unit.side === 'spider' && event.first && unit.kind !== 'brown') {
            var type = rules.SPIDERS[unit.kind];
            announce('Новый паук: ' + type.name + ' — ' + type.note + '.');
            talk('battle_new_spider', { spider: type.name }, true);
          }
        } else if (event.type === 'hit') {
          flash(unit, 'is-striking');
          flash(event.target, 'is-hurt');
        } else if (event.type === 'shot') {
          shoot(unit, event.target);
          flash(event.target, 'is-hurt');
        } else if (event.type === 'siege') {
          flash(unit, 'is-striking');
          flashBase(event.target);
          siegeRemark(event.target);
        } else if (event.type === 'death') {
          removeView(unit);
          if (unit.kind === 'boss') { talk('battle_boss_down', null, true); }
          else if (Math.random() < 0.35) {
            talk(unit.side === 'spider' ? 'battle_spider_down' : 'battle_word_down');
          }
        } else if (event.type === 'over') {
          finish(event.result);
        }
      });
    }

    function siegeRemark(target) {
      var building = state[target];
      var low = building.hp < building.max * 0.3;
      var key = target + (low ? '-low' : '');
      if (remarks[key]) { return; }
      remarks[key] = true;
      if (target === 'web') { talk(low ? 'battle_web_low' : 'battle_web_hit', null, low); }
      else { talk(low ? 'battle_base_low' : 'battle_base_hit', null, low); }
    }

    function drawHud() {
      hud.baseBar.style.width = (100 * state.base.hp / state.base.max) + '%';
      hud.webBar.style.width = (100 * state.web.hp / state.web.max) + '%';
      hud.baseHp.textContent = Math.ceil(state.base.hp);
      hud.webHp.textContent = Math.ceil(state.web.hp);
      hud.clock.textContent = clock(state.time);
      hud.next.textContent = Math.ceil(state.spiderTimer);
      hud.coins.textContent = state.coins;
      statsBox.textContent = 'Слов в бою: ' + state.words + ' · пауков побеждено: ' + state.killed +
        ' · слов потеряно: ' + state.lost;
    }

    function draw() {
      state.units.forEach(placeView);
      drawHud();
      refreshShop(false);
    }

    function frame(now) {
      if (!running) { frameId = 0; return; }
      var dt = Math.min(0.25, (now - lastFrame) / 1000);
      lastFrame = now;
      if (!paused) {
        backlog += dt;
        while (backlog >= STEP && running) {
          handle(rules.step(state, STEP));
          backlog -= STEP;
        }
        if (state) { draw(); }
      }
      if (running) { frameId = requestAnimationFrame(frame); }
    }

    function setPaused(value) {
      if (!running) { return; }
      paused = value;
      cover.hidden = !paused;
      pauseButton.textContent = paused ? 'Продолжить' : 'Пауза';
      arena.classList.toggle('is-paused', paused);
      selection = null;
      clearSelection();
      refreshShop(true);
      if (paused) { talk('battle_pause', null, true); }
    }

    function finish(outcome) {
      running = false;
      paused = false;
      cover.hidden = true;
      pauseButton.textContent = 'Пауза';
      pauseButton.disabled = true;
      surrenderButton.disabled = true;
      toast.classList.remove('show');
      clearSelection();
      arena.classList.add('is-over');
      refreshShop(true);
      draw();
      $('battle-result-title').textContent = outcome === 'win'
        ? 'Победа! Паутина Пафнутия порвана.'
        : 'Поражение: пауки добрались до Изборника.';
      $('battle-result-text').textContent = 'Бой длился ' + clock(state.time) + '. Слов в бою: ' + state.words +
        (state.longest ? ' (самое длинное — «' + state.longest + '»)' : '') + ', пауков побеждено: ' + state.killed +
        ', монет заработано: ' + state.earned + '.';
      result.className = 'battle-result is-' + outcome;
      result.hidden = false;
      talk(outcome === 'win' ? 'battle_win' : 'battle_lose', null, true);
    }

    /* --- поле букв -------------------------------------------------------- */

    function fetchGrid() {
      var url = '/api/battle/grid?language=' + encodeURIComponent(language) +
        '&exclude=' + encodeURIComponent(played.join(','));
      return fetch(url).then(function (response) { return response.json(); }).then(function (data) {
        if (!data || data.error) { throw new Error((data && data.error) || 'нет ответа'); }
        return data;
      });
    }

    function prefetch() {
      upcoming = fetchGrid();
      upcoming.catch(function () { upcoming = null; });
    }

    function loadGrid(data) {
      grid = data;
      found = data.words.map(function () { return false; });
      played.push(data.doc_id);
      if (played.length > 6) { played.shift(); }
      lettersBox.style.setProperty('--cols', String(data.cols));
      lettersBox.innerHTML = '';
      cells = [];
      gone = [];
      for (var r = 0; r < data.rows; r++) {
        cells.push([]);
        gone.push([]);
        for (var c = 0; c < data.cols; c++) {
          var cell = element('div', 'letter', data.letters[r][c]);
          lettersBox.appendChild(cell);
          cells[r].push(cell);
          gone[r].push(false);
        }
      }
      wordsBox.innerHTML = '';
      data.words.forEach(function (word, index) {
        var item = element('li', 'word-chip', word.text);
        item.dataset.index = String(index);
        item.title = 'ключевое слово № ' + word.rank + ' реферата · ' + word.letters.length + ' букв';
        wordsBox.appendChild(item);
      });
      sourceBox.innerHTML = '';
      sourceBox.appendChild(document.createTextNode('Ключевые слова реферата документа '));
      var link = element('a', '', '«' + data.title + '»');
      link.href = data.link;
      link.target = '_blank';
      sourceBox.appendChild(link);
      prefetch();
    }

    function nextGrid() {
      lettersBox.classList.add('is-shuffling');
      var alphabet = [];
      grid.letters.forEach(function (row) { alphabet = alphabet.concat(row.split('')); });
      var spins = 0;
      var spin = setInterval(function () {
        cells.forEach(function (row) {
          row.forEach(function (cell) {
            cell.textContent = alphabet[Math.floor(Math.random() * alphabet.length)];
            cell.classList.remove('is-gone');
          });
        });
        if (++spins >= 7) { clearInterval(spin); }
      }, 70);
      var request = upcoming || fetchGrid();
      upcoming = null;
      request.then(function (data) {
        setTimeout(function () {
          clearInterval(spin);
          lettersBox.classList.remove('is-shuffling');
          if (!running) { return; }
          loadGrid(data);
          if (Math.random() < 0.6) { talk('battle_grid'); }
        }, 500);
      }, function () {
        clearInterval(spin);
        sourceBox.textContent = 'Сервер не прислал новое поле — пробую ещё раз…';
        setTimeout(function () { if (running) { nextGrid(); } }, 2000);
      });
    }

    function cellAt(event) {
      var box = lettersBox.getBoundingClientRect();
      if (!grid || !box.width) { return null; }
      var col = Math.floor((event.clientX - box.left) / (box.width / grid.cols));
      var row = Math.floor((event.clientY - box.top) / (box.height / grid.rows));
      return {
        row: Math.max(0, Math.min(grid.rows - 1, row)),
        col: Math.max(0, Math.min(grid.cols - 1, col))
      };
    }

    function clearSelection() {
      lettersBox.querySelectorAll('.is-selected').forEach(function (cell) {
        cell.classList.remove('is-selected');
      });
    }

    function showSelection() {
      clearSelection();
      if (!selection) { return; }
      rules.selectLine(selection.start, selection.end).forEach(function (cell) {
        cells[cell.row][cell.col].classList.add('is-selected');
      });
    }

    function releaseSelection() {
      if (!selection) { return; }
      var chosen = rules.selectLine(selection.start, selection.end);
      selection = null;
      clearSelection();
      if (!running || paused || chosen.length < 2) { return; }
      var index = rules.matchWord(grid.words, found, chosen);
      if (index < 0) {
        chosen.forEach(function (cell) { flashCell(cells[cell.row][cell.col], 'is-miss'); });
        return;
      }
      found[index] = true;
      var word = grid.words[index];
      chosen.forEach(function (cell) {
        gone[cell.row][cell.col] = true;
        cells[cell.row][cell.col].classList.add('is-found');
      });
      setTimeout(function () {
        chosen.forEach(function (cell) {
          var node = cells[cell.row][cell.col];
          node.classList.remove('is-found');
          node.classList.add('is-gone');
        });
      }, FOUND_PAUSE);
      wordsBox.querySelector('[data-index="' + index + '"]').classList.add('is-found');
      var unit = rules.sendWord(state, word.text);
      createView(unit);
      talk(word.letters.length >= 8 ? 'battle_long_word' : 'battle_word', { word: word.text },
        word.letters.length >= 8);
      if (found.every(Boolean)) { setTimeout(nextGrid, FOUND_PAUSE + 150); }
    }

    function flashCell(node, className) {
      node.classList.remove(className);
      void node.offsetWidth;
      node.classList.add(className);
    }

    lettersBox.addEventListener('pointerdown', function (event) {
      if (!running || paused || !grid || event.button > 0) { return; }
      var cell = cellAt(event);
      if (!cell || gone[cell.row][cell.col]) { return; }
      event.preventDefault();
      try { lettersBox.setPointerCapture(event.pointerId); } catch (e) { /* уже не нажато */ }
      selection = { start: cell, end: cell };
      showSelection();
    });
    lettersBox.addEventListener('pointermove', function (event) {
      if (!selection) { return; }
      var cell = cellAt(event);
      if (!cell || (cell.row === selection.end.row && cell.col === selection.end.col)) { return; }
      selection.end = cell;
      showSelection();
    });
    lettersBox.addEventListener('pointerup', releaseSelection);
    lettersBox.addEventListener('pointercancel', function () {
      selection = null;
      clearSelection();
    });

    /* --- начало и конец ----------------------------------------------------- */

    function begin() {
      language = languageBox.value;
      startButton.disabled = true;
      startNote.textContent = 'Пафнутий расставляет паучат…';
      played = [];
      upcoming = null;
      fetchGrid().then(function (data) {
        startButton.disabled = false;
        startNote.textContent = '';
        state = rules.createBattle();
        remarks = {};
        clearLane();
        if (webPafnuty) { webPafnuty.classList.remove('is-away'); }
        intro.hidden = true;
        arena.hidden = false;
        result.hidden = true;
        arena.classList.remove('is-over', 'is-paused');
        cover.hidden = true;
        paused = false;
        pauseButton.textContent = 'Пауза';
        pauseButton.disabled = false;
        surrenderButton.disabled = false;
        loadGrid(data);
        refreshShop(true);
        drawHud();
        running = true;
        backlog = 0;
        lastFrame = performance.now();
        lastTalk = 0;
        talk('battle_start', null, true);
        if (!frameId) { frameId = requestAnimationFrame(frame); }
        arena.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, function (problem) {
        startButton.disabled = false;
        startNote.textContent = 'Не удалось получить поле букв: ' + problem.message;
      });
    }

    startButton.addEventListener('click', begin);
    $('battle-again').addEventListener('click', begin);
    $('battle-rules').addEventListener('click', function () {
      running = false;
      arena.hidden = true;
      intro.hidden = false;
      clearLane();
    });
    pauseButton.addEventListener('click', function () { setPaused(!paused); });
    surrenderButton.addEventListener('click', function () {
      if (!running) { return; }
      state.over = 'lose';
      state.base.hp = 0;
      finish('lose');
    });
    document.addEventListener('visibilitychange', function () {
      if (document.hidden && running && !paused) { setPaused(true); }
    });

    buildLegend();
    buildShop();
  });
})(typeof window !== 'undefined' ? window : globalThis);
