/* Тир Пафнутия: правила без отрисовки.
 *
 * Пафнутий стоит на вершине Вавилонской башни, а на него волнами идут
 * английские слова переведённого текста. Попадание паутиной переводит слово
 * на немецкий — и слово побеждено. План волн (какие слова, в какой волне,
 * кто мини-босс) строит сервер (dragoman/game.py); здесь — как бой идёт:
 * скорость и урон противников, уровни сложности, расписание появления слов,
 * запас паутины, раскрытие перевода у мини-босса, попадание снаряда.
 *
 * Файл подключается и браузером (window.ShooterRules), и тестами в node
 * (tests/shooter_rules.test.js) — поэтому в нём нет ни DOM, ни three.js.
 */

(function (global) {
  'use strict';

  var ARENA_RADIUS = 30;          /* радиус площадки на вершине башни, м */
  var GATES = 6;                  /* ворота в парапете, через которые входят слова */

  var PLAYER = {
    hp: 100,
    speed: 7.5,                   /* м/с */
    dashSpeed: 24,
    dashTime: 0.18,
    dashCooldown: 1.5,
    jump: 8.5,
    gravity: 24,
    radius: 0.9,
    ammo: 14,                     /* запас паутины */
    ammoRegen: 4.2,               /* нитей в секунду */
    shotSpeed: 46,
    shotCooldown: 0.15,
    netCooldown: 14,              /* ловчая сеть: перезарядка, с */
    netRadius: 6.5,
    netBossDamage: 5
  };

  /* Противники. hp у мини-босса задаёт план (длина слова + номер волны). */
  var KINDS = {
    swarm: { speed: 6.0, damage: 4, melee: 1.5, period: 0.8, scale: 0.72, height: 0.78,
      name: 'мелочь', note: 'служебные слова: маленькие, быстрые, бегут стайкой' },
    walker: { speed: 3.5, damage: 8, melee: 1.7, period: 1.0, scale: 1.0, height: 1.0,
      name: 'слово', note: 'существительные, прилагательные, наречия: идут и кусают' },
    gunner: { speed: 2.4, damage: 6, shootRange: 18, keep: 11, period: 2.3, scale: 1.0, height: 1.0,
      shotSpeed: 15, name: 'слово с пушкой', note: 'глаголы: держатся поодаль и стреляют буквами' },
    boss: { speed: 2.1, damage: 14, melee: 2.6, shootRange: 22, keep: 6, period: 1.3, scale: 2.1, height: 2.1,
      shotSpeed: 17, volley: 3, volleyPeriod: 3.4,
      name: 'мини-босс', note: 'самое длинное слово волны: держит много попаданий и стреляет очередями' }
  };

  var DIFFICULTY = {
    easy: { label: 'лёгкий', speed: 0.8, damage: 0.55, spawn: 1.4, maxAlive: 9, bossHp: 0.75 },
    normal: { label: 'обычный', speed: 1.0, damage: 1.0, spawn: 1.0, maxAlive: 13, bossHp: 1.0 },
    hard: { label: 'трудный', speed: 1.2, damage: 1.35, spawn: 0.75, maxAlive: 18, bossHp: 1.3 }
  };

  var SPAWN_INTERVAL = 1.05;      /* с между появлениями при обычной сложности */
  var WAVE_INTRO = 3.0;           /* с объявления волны */
  var WAVE_BREAK = 4.0;           /* с передышки после мини-босса */
  var WAVE_HEAL = 25;             /* прочность, которую Пафнутий восстанавливает между волнами */
  var FLY_HEAL = 20;              /* муха лечит */
  var FLY_CHANCE = 0.08;

  /** Генератор случайных чисел с зерном: одинаковое расписание для одного плана. */
  function seeded(seed) {
    var state = (seed >>> 0) || 1;
    return function () {
      state += 0x6D2B79F5;
      var t = state;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /**
   * Расписание появления противников волны: [{enemy, t, gate}]. Мелочь
   * приходит стайками по три-четыре из одних ворот, остальные — по одному,
   * ворота чередуются. Время — с начала волны.
   */
  function spawnSchedule(enemies, difficulty, seed) {
    var level = DIFFICULTY[difficulty] || DIFFICULTY.normal;
    var random = seeded(seed || 1);
    var interval = SPAWN_INTERVAL * level.spawn;
    var result = [];
    var t = 0.5;
    var gate = Math.floor(random() * GATES);
    var i = 0;
    while (i < enemies.length) {
      var enemy = enemies[i];
      if (enemy.kind === 'swarm') {
        var pack = 0;
        while (i < enemies.length && enemies[i].kind === 'swarm' && pack < 4) {
          result.push({ enemy: enemies[i], t: t + pack * 0.22, gate: gate });
          i++;
          pack++;
        }
        t += interval * 1.4;
      } else {
        result.push({ enemy: enemy, t: t, gate: gate });
        i++;
        t += interval * (0.75 + random() * 0.5);
      }
      gate = (gate + 1 + Math.floor(random() * (GATES - 1))) % GATES;
    }
    return result;
  }

  /** Перестановка: мелочь собирается в стайки, иначе стайка из одного слова. */
  function groupSwarms(enemies) {
    var swarms = enemies.filter(function (e) { return e.kind === 'swarm'; });
    var others = enemies.filter(function (e) { return e.kind !== 'swarm'; });
    var result = [];
    var s = 0;
    var o = 0;
    while (s < swarms.length || o < others.length) {
      for (var k = 0; k < 3 && s < swarms.length; k++) { result.push(swarms[s++]); }
      for (var m = 0; m < 2 && o < others.length; m++) { result.push(others[o++]); }
    }
    return result;
  }

  /** Прочность мини-босса с учётом сложности. */
  function bossHp(planHp, difficulty) {
    var level = DIFFICULTY[difficulty] || DIFFICULTY.normal;
    return Math.max(4, Math.round(planHp * level.bossHp));
  }

  /**
   * Перевод мини-босса раскрывается по мере попаданий: сколько прочности
   * снято, столько долей немецкого слова видно. «Implementation» с половиной
   * прочности — «Implemen·······».
   */
  function bossReveal(german, hp, maxHp) {
    var letters = Array.from(german);
    var done = maxHp > 0 ? 1 - Math.max(0, hp) / maxHp : 1;
    var shown = Math.round(letters.length * done);
    if (hp <= 0) { shown = letters.length; }
    return letters.slice(0, shown).join('') + letters.slice(shown).map(function (ch) {
      return ch === ' ' ? ' ' : '·';
    }).join('');
  }

  function damage(kind, difficulty) {
    var level = DIFFICULTY[difficulty] || DIFFICULTY.normal;
    return KINDS[kind].damage * level.damage;
  }

  function speed(kind, difficulty) {
    var level = DIFFICULTY[difficulty] || DIFFICULTY.normal;
    return KINDS[kind].speed * level.speed;
  }

  /** Запас паутины через dt секунд. */
  function regenAmmo(ammo, dt) {
    return Math.min(PLAYER.ammo, ammo + PLAYER.ammoRegen * dt);
  }

  /** Точка остаётся внутри площадки (с учётом радиуса тела). */
  function clampToArena(x, z, radius) {
    var limit = ARENA_RADIUS - (radius || 0);
    var d = Math.sqrt(x * x + z * z);
    if (d <= limit) { return [x, z]; }
    return [x / d * limit, z / d * limit];
  }

  /** Положение ворот: на окружности парапета, равномерно. */
  function gatePosition(gate) {
    var angle = (gate / GATES) * Math.PI * 2 + Math.PI / GATES;
    return [Math.cos(angle) * (ARENA_RADIUS - 1.5), Math.sin(angle) * (ARENA_RADIUS - 1.5)];
  }

  /**
   * Попал ли снаряд, пролетевший за кадр из p0 в p1 (радиус r), в противника
   * — вертикальный цилиндр с центром c, радиусом и полувысотой. Отрезок
   * проверяется целиком, иначе быстрый снаряд пролетал бы сквозь мелкое слово.
   */
  function segmentHitsCylinder(p0, p1, r, c, radius, halfHeight) {
    var dx = p1[0] - p0[0];
    var dz = p1[2] - p0[2];
    var fx = p0[0] - c[0];
    var fz = p0[2] - c[2];
    var a = dx * dx + dz * dz;
    var t = a > 1e-9 ? -(fx * dx + fz * dz) / a : 0;
    t = Math.max(0, Math.min(1, t));
    var px = p0[0] + dx * t - c[0];
    var pz = p0[2] + dz * t - c[2];
    var py = p0[1] + (p1[1] - p0[1]) * t - c[1];
    return px * px + pz * pz <= (radius + r) * (radius + r) && Math.abs(py) <= halfHeight + r;
  }

  /** Оценка боя: звёзды за точность и оставшуюся прочность. */
  function stars(result) {
    var accuracy = result.shots ? result.hits / result.shots : 0;
    var score = 1;
    if (result.won) { score++; }
    if (result.won && (accuracy >= 0.5 || result.hp >= 50)) { score++; }
    return score;
  }

  /** Сколько слов текста переведено: доля вхождений, а не разных слов. */
  function progress(defeated, words) {
    var total = 0;
    var done = 0;
    words.forEach(function (w) {
      total += w.count;
      if (defeated[w.en.toLowerCase()]) { done += w.count; }
    });
    return total ? done / total : 0;
  }

  var rules = {
    ARENA_RADIUS: ARENA_RADIUS, GATES: GATES, PLAYER: PLAYER, KINDS: KINDS, DIFFICULTY: DIFFICULTY,
    SPAWN_INTERVAL: SPAWN_INTERVAL, WAVE_INTRO: WAVE_INTRO, WAVE_BREAK: WAVE_BREAK, WAVE_HEAL: WAVE_HEAL,
    FLY_HEAL: FLY_HEAL, FLY_CHANCE: FLY_CHANCE,
    seeded: seeded, spawnSchedule: spawnSchedule, groupSwarms: groupSwarms, bossHp: bossHp,
    bossReveal: bossReveal, damage: damage, speed: speed, regenAmmo: regenAmmo, clampToArena: clampToArena,
    gatePosition: gatePosition, segmentHitsCylinder: segmentHitsCylinder, stars: stars, progress: progress
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = rules;
  } else {
    global.ShooterRules = rules;
  }
})(typeof window !== 'undefined' ? window : globalThis);
