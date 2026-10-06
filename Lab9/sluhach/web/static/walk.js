/* Прогулка с Пафнутием для «Слухача».
 *
 * Паук идёт по карте слева направо и слушается голоса: пока слышит голос —
 * идёт, а от громкого звука подпрыгивает от неожиданности, и тем выше, чем
 * громче. Молчание — стоит. Карта — лужайки, ступени, овраги и протоки с
 * водой: через воду нужно перепрыгнуть, из оврага — выпрыгнуть. Слов игра
 * не распознаёт, ей нужна только громкость, поэтому язык неважен. Механика
 * взята у игр, управляемых голосом («Yasuhati», «Scream Go Hero»).
 *
 * Файл разделён надвое, как игры прошлых работ: сверху — правила без DOM
 * (карта, физика, перевод громкости в управление), они экспортируются через
 * module.exports и проверяются в node (tests/walk_rules.test.js); снизу —
 * отрисовка и управление.
 */

(function (global) {
  'use strict';

  /* --- правила ------------------------------------------------------------ */

  var WALK_SPEED = 115;       /* скорость шага, единиц карты в секунду */
  var AIR_SPEED = 170;        /* скорость в полёте, пока звучит голос */
  var AIR_DRAG = 3.2;         /* без голоса полёт вперёд затухает: доля скорости, теряемая за секунду */
  var GRAVITY = 1500;
  var JUMP_MIN = 430;         /* начальная скорость прыжка на пороге громкости: высота 62 */
  var JUMP_MAX = 690;         /* и при самом громком звуке: высота 159 */
  /* Между громким звуком и прыжком проходит мгновение испуга: за это время
     звук успевает дорасти до полной громкости, и прыжок получается таким,
     каким был крик, а не таким, каким был его первый миг. */
  var STARTLE = 0.07;
  var QUIET = 0.25;           /* уровень голоса, с которого паук идёт (шкала 0…1) */
  var LOUD = 0.62;            /* уровень, с которого он прыгает */
  /* Неожиданность бывает один раз: чтобы прыгнуть снова, голос должен стихнуть
     ниже этой доли порога. Иначе непрерывный крик превратился бы в скачку, и
     паук прыгал бы в воду сразу после приземления. */
  var REARM = 0.85;
  var VOICE_HOLD = 0.18;      /* голос «звучит» ещё столько секунд после звука: паузы между слогами — не тишина */
  var FOOT = 14;              /* половина расстановки ног: на краю паук стоит, пока хоть одна нога на земле */
  var STEP_UP = 10;           /* ступеньку такой высоты он одолевает шагом */
  var START_HEIGHT = 80;      /* высота земли в начале карты */
  var RAVINE_DEPTH = 50;      /* глубина оврага: шагом не выйти, прыжком — легко */
  var WATER_LEVEL = 18;       /* высота поверхности воды */
  var SINK = 14;              /* утонул, когда ушёл под воду на столько */
  var RESPAWN = 1.5;          /* секунд от всплеска до возвращения на метку */
  var START_X = 70;

  /* Карты. Запись — слова через пробел:
       G260  земля длиной 260        W70   вода шириной 70
       R80   овраг длиной 80         U24   дальше земля выше на 24
       D24   дальше земля ниже на 24 C     метка возвращения
       F     финиш
     Проходимость каждой карты проверяется тестом: по ней идёт «игрок»,
     который кричит ровно настолько, насколько нужно. */
  var LEVELS = [
    {
      id: 'meadow', name: 'Лужайка', text: 'три лужи, ступенька и овраг — привыкнуть к голосу',
      spec: 'G300 W55 G230 U22 G200 D22 G170 C R75 G210 W70 G190 W60 G260 F G220'
    },
    {
      id: 'ravines', name: 'Овраги', text: 'ступени вверх и вниз, овраги и вода пошире',
      spec: 'G260 W70 G150 R80 G140 U26 G160 W85 G170 C U26 G150 D52 G120 R95 G130 W100 G180 C ' +
        'W75 G110 W75 G150 U24 G170 R70 G150 W105 G260 F G220'
    },
    {
      id: 'water', name: 'Большая вода', text: 'островки и широкие протоки — тут нужен громкий голос',
      spec: 'G240 W90 G110 W95 G100 W110 G170 C U28 G130 W120 G120 D28 G95 W100 G95 W125 G170 C ' +
        'R90 G120 U30 G110 W135 G130 W110 G100 D30 G95 W140 G270 F G220'
    }
  ];

  /** Разбирает запись карты в отрезки земли, метки и финиш. */
  function buildLevel(spec) {
    var segments = [];
    var checkpoints = [];
    var x = 0;
    var height = START_HEIGHT;
    var finish = null;
    String(spec).trim().split(/\s+/).forEach(function (word) {
      var kind = word.charAt(0);
      var value = Number(word.slice(1));
      if (kind === 'G' || kind === 'R') {
        if (!(value > 0)) { throw new Error('у отрезка «' + word + '» нет длины'); }
        var top = kind === 'R' ? height - RAVINE_DEPTH : height;
        /* дно оврага должно остаться над водой, иначе овраг от протоки не отличить */
        if (top < WATER_LEVEL + 8) { throw new Error('овраг опустился до воды: ' + word); }
        var last = segments[segments.length - 1];
        if (last && last.x1 === x && last.top === top && !!last.ravine === (kind === 'R')) {
          last.x1 = x + value;
        } else {
          segments.push({ x0: x, x1: x + value, top: top, ravine: kind === 'R' });
        }
        x += value;
      } else if (kind === 'W') {
        if (!(value > 0)) { throw new Error('у воды «' + word + '» нет ширины'); }
        x += value;
      } else if (kind === 'U' || kind === 'D') {
        height += (kind === 'U' ? 1 : -1) * value;
        if (height < WATER_LEVEL + 20) { throw new Error('земля опустилась до воды: ' + word); }
      } else if (kind === 'C') {
        checkpoints.push(x);
      } else if (kind === 'F') {
        finish = x;
      } else {
        throw new Error('непонятное слово в записи карты: ' + word);
      }
    });
    if (finish === null) { throw new Error('на карте нет финиша'); }
    return { segments: segments, checkpoints: checkpoints, finish: finish, length: x, spec: spec };
  }

  /** Отрезок земли под точкой x или null над водой. */
  function segmentAt(level, x) {
    var segments = level.segments;
    var low = 0;
    var high = segments.length - 1;
    while (low <= high) {
      var middle = (low + high) >> 1;
      var segment = segments[middle];
      if (x < segment.x0) { high = middle - 1; }
      else if (x >= segment.x1) { low = middle + 1; }
      else { return segment; }
    }
    return null;
  }

  /** Высота земли под точкой x; над водой — минус бесконечность. */
  function groundAt(level, x) {
    var segment = segmentAt(level, x);
    return segment ? segment.top : -Infinity;
  }

  /** Земля, на которую паук опирается: самая высокая под расстановкой ног, но не стена выше него. */
  function support(level, x, y) {
    var best = -Infinity;
    [x - FOOT, x, x + FOOT].forEach(function (point) {
      var top = groundAt(level, point);
      if (top <= y + STEP_UP + 1e-6 && top > best) { best = top; }
    });
    return best;
  }

  function jumpSpeed(power) {
    return JUMP_MIN + (JUMP_MAX - JUMP_MIN) * Math.max(0, Math.min(1, power));
  }

  function jumpHeight(power) {
    var speed = jumpSpeed(power);
    return speed * speed / (2 * GRAVITY);
  }

  /** Длина прыжка по ровному месту, если голос звучит весь полёт. */
  function jumpLength(power) {
    return AIR_SPEED * 2 * jumpSpeed(power) / GRAVITY;
  }

  function createRun(level) {
    return {
      level: level,
      x: START_X, y: groundAt(level, START_X), vx: 0, vy: 0,
      grounded: true,
      startle: -1,              /* секунд до прыжка; −1 — паук не напуган */
      peak: 0,                  /* самый громкий звук за время испуга */
      armed: true,              /* можно ли испугать снова */
      hold: 0,                  /* сколько ещё «звучит» голос */
      checkpoint: -1,           /* номер последней метки; −1 — начало карты */
      respawn: 0,               /* секунд до возвращения на метку */
      inRavine: false,
      wall: null,               /* стена, в которую паук упёрся (о ней уже сказано) */
      time: 0, falls: 0, jumps: 0, silent: 0,
      over: null                /* null | 'win' */
    };
  }

  /** Где паук появляется после падения в воду: у последней метки, на ровном месте перед ней. */
  function respawnPoint(state) {
    var level = state.level;
    if (state.checkpoint < 0) { return { x: START_X, y: groundAt(level, START_X) }; }
    var flag = level.checkpoints[state.checkpoint];
    var spots = [flag - FOOT - 6, flag + FOOT + 6];
    /* метка может стоять на краю оврага или воды: тогда паук встаёт с той стороны, где земля */
    var solid = spots.filter(function (x) { var segment = segmentAt(level, x); return segment && !segment.ravine; });
    var x = solid.length ? solid[0] : spots.filter(function (point) { return segmentAt(level, point); })[0];
    if (x === undefined) { x = START_X; }
    return { x: x, y: groundAt(level, x) };
  }

  /**
   * Прогулка на dt секунд вперёд. voice — уровень голоса от 0 до 1.
   * Возвращает события для отрисовки и реплик.
   */
  function step(state, dt, voice) {
    var events = [];
    var level = state.level;
    if (state.over) { return events; }

    if (state.respawn > 0) {
      state.respawn -= dt;
      state.y -= 26 * dt;                         /* тонет */
      if (state.respawn <= 0) {
        var point = respawnPoint(state);
        state.x = point.x;
        state.y = point.y;
        state.vx = state.vy = 0;
        state.grounded = true;
        state.startle = -1;
        state.armed = false;                      /* не прыгать от того же крика, с которым падал */
        state.hold = 0;
        state.inRavine = false;
        state.wall = null;
        events.push({ type: 'respawn' });
      }
      return events;
    }

    state.time += dt;
    voice = Math.max(0, Math.min(1, voice || 0));
    if (voice >= QUIET) { state.hold = VOICE_HOLD; state.silent = 0; }
    else { state.hold = Math.max(0, state.hold - dt); state.silent += dt; }
    var voiced = state.hold > 0;
    if (voice < LOUD * REARM) { state.armed = true; }

    /* испуг и прыжок */
    if (state.grounded && state.startle < 0 && voice >= LOUD && state.armed) {
      state.startle = STARTLE;
      state.peak = voice;
      state.armed = false;
      events.push({ type: 'startle' });
    }
    if (state.startle >= 0) {
      state.peak = Math.max(state.peak, voice);
      state.startle -= dt;
      if (state.startle <= 0) {
        state.startle = -1;
        if (state.grounded) {
          var power = (state.peak - LOUD) / (1 - LOUD);
          state.vy = jumpSpeed(power);
          state.grounded = false;
          state.jumps++;
          events.push({ type: 'jump', power: Math.max(0, Math.min(1, power)) });
        }
      }
    }

    /* движение вперёд */
    if (state.grounded) {
      state.vx = voiced ? WALK_SPEED : 0;
    } else if (voiced) {
      state.vx += (AIR_SPEED - state.vx) * Math.min(1, 10 * dt);
    } else {
      state.vx *= Math.exp(-AIR_DRAG * dt);
    }
    var next = state.x + state.vx * dt;
    var ahead = segmentAt(level, next + FOOT);
    if (ahead && ahead.top > state.y + STEP_UP + 1e-6 && ahead.x0 > state.x - FOOT) {
      /* впереди стена выше ног: дальше её края не пройти */
      next = Math.max(state.x, Math.min(next, ahead.x0 - FOOT - 0.01));
      if (state.grounded && voiced && state.wall !== ahead.x0) {
        state.wall = ahead.x0;
        events.push({ type: 'wall' });
      }
    }
    state.x = next;

    /* опора и падение */
    var under = support(level, state.x, state.y);
    if (state.grounded) {
      if (under < state.y - STEP_UP) {
        state.grounded = false;                   /* шагнул с края */
        state.vy = 0;
      } else if (under > -Infinity) {
        state.y = under;                          /* ступенька вверх или вниз */
      }
    }
    if (!state.grounded) {
      state.vy -= GRAVITY * dt;
      var fall = state.y + state.vy * dt;
      if (state.vy <= 0 && under > -Infinity && fall <= under) {
        state.y = under;
        state.grounded = true;
        events.push({ type: 'land', speed: -state.vy });
        state.vy = 0;
      } else {
        state.y = fall;
      }
      if (!state.grounded && state.y < WATER_LEVEL - SINK && groundAt(level, state.x) === -Infinity) {
        state.respawn = RESPAWN;
        state.falls++;
        state.vx = state.vy = 0;
        state.startle = -1;
        events.push({ type: 'splash' });
        return events;
      }
    }

    if (state.grounded) {
      var here = segmentAt(level, state.x);
      var inRavine = !!(here && here.ravine && Math.abs(state.y - here.top) < 1);
      if (inRavine !== state.inRavine) {
        state.inRavine = inRavine;
        events.push({ type: inRavine ? 'ravine' : 'ravine_out' });
      }
      while (state.checkpoint + 1 < level.checkpoints.length && state.x >= level.checkpoints[state.checkpoint + 1]) {
        state.checkpoint++;
        events.push({ type: 'checkpoint', index: state.checkpoint });
      }
      if (state.x >= level.finish) {
        state.over = 'win';
        state.vx = 0;
        events.push({ type: 'finish', stars: stars(state) });
      }
    }
    return events;
  }

  /** Оценка прогулки: три звезды — ни разу не искупался, две — не больше двух раз. */
  function stars(state) {
    return state.falls === 0 ? 3 : state.falls <= 2 ? 2 : 1;
  }

  /* --- голос --------------------------------------------------------------- */

  var QUIET_MARGIN = 12;      /* без замера голоса: идти — на столько дБ громче шума комнаты */
  var LOUD_MARGIN = 16;       /* и прыгать — ещё на столько громче */
  var LOUD_RANGE = 10;        /* от порога прыжка до самого сильного прыжка, дБ */
  var LOUD_TOP = -5;          /* громче микрофон не передаёт, звук обрезается: самый сильный прыжок — не выше */
  var VOICE_GAP = 6;          /* голос — то, что на столько дБ громче шума комнаты */
  var VOICE_SHARE = 0.12;     /* при настройке голос должен занять хотя бы такую долю времени */
  var VOICE_REACH = 14;       /* идти — от звуков не более чем на столько дБ тише спокойного голоса */
  var VOICE_HEADROOM = 9;     /* прыгать — от голоса на столько дБ громче спокойного */

  /** Шум комнаты по замерам громкости в тишине, дБ: медиана — случайный стук её не сдвинет. */
  function noiseOf(values) {
    if (!values.length) { return null; }
    var sorted = values.slice().sort(function (a, b) { return a - b; });
    return sorted[Math.floor(sorted.length / 2)];
  }

  /**
   * Спокойный голос игрока, дБ, по замерам громкости с того мига, как он
   * заговорил.
   *
   * В счёт идут только замеры заметно громче шума. Берётся не самый громкий
   * звук и не средний, а уровень, громче которого пятая часть звуков, —
   * ударные гласные: по ним и судят о громкости речи. Если голос занял меньше
   * VOICE_SHARE времени, его не было (null): кашель и стук — не голос.
   */
  function voiceOf(values, noiseDb) {
    var heard = values.filter(function (value) { return value > noiseDb + VOICE_GAP; })
      .sort(function (a, b) { return a - b; });
    if (heard.length < Math.max(5, values.length * VOICE_SHARE)) { return null; }
    return heard[Math.floor(heard.length * 0.8)];
  }

  /**
   * Пороги: с какой громкости идти и с какой прыгать.
   *
   * По одному шуму комнаты пороги можно только угадать: в тихой комнате
   * порог прыжка вышел бы ниже обычной речи, и паук скакал бы от каждого
   * слова. Поэтому, если известен спокойный голос игрока (voiceDb), пороги
   * ставятся по нему: «идти» — посередине между шумом и голосом, но не дальше
   * VOICE_REACH от голоса (иначе паук пошёл бы от вздоха), «прыгать» — на
   * VOICE_HEADROOM громче голоса. Без голоса — по шуму, с запасом.
   */
  function calibrate(noiseDb, voiceDb) {
    var quiet;
    var loud;
    if (typeof voiceDb === 'number' && voiceDb > noiseDb + VOICE_GAP) {
      quiet = Math.max((noiseDb + voiceDb) / 2, voiceDb - VOICE_REACH);
      quiet = Math.max(-60, Math.min(-20, quiet));
      loud = Math.max(quiet + 8, Math.min(LOUD_TOP - 5, voiceDb + VOICE_HEADROOM));
      return { noise: noiseDb, voice: voiceDb, quiet: quiet, loud: loud };
    }
    quiet = Math.max(-52, Math.min(-24, noiseDb + QUIET_MARGIN));
    loud = Math.max(quiet + 8, Math.min(-8, quiet + LOUD_MARGIN));
    return { noise: noiseDb, quiet: quiet, loud: loud };
  }

  /**
   * Уровень голоса 0…1 по громкости в дБ: порог «идти» попадает в QUIET,
   * порог «прыгать» — в LOUD, единица — на LOUD_RANGE дБ выше него, но не
   * выше LOUD_TOP: при высоком пороге до самого сильного прыжка иначе было
   * бы не докричаться.
   */
  function levelFromDb(db, calibration) {
    var quiet = calibration.quiet;
    var loud = Math.max(quiet + 1, calibration.loud);
    if (db < quiet) {
      return QUIET * Math.max(0, Math.min(1, (db - (quiet - QUIET_MARGIN)) / QUIET_MARGIN));
    }
    if (db < loud) {
      return QUIET + (LOUD - QUIET) * (db - quiet) / (loud - quiet);
    }
    var top = Math.max(loud + 3, Math.min(loud + LOUD_RANGE, LOUD_TOP));
    return LOUD + (1 - LOUD) * Math.min(1, (db - loud) / (top - loud));
  }

  /* --- случайная карта ------------------------------------------------------ */

  function seeded(seed) {
    var state = seed >>> 0;
    return function () {
      state += 0x6D2B79F5;
      var t = state;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /**
   * Случайная карта по зерну. difficulty 0…1 растягивает воду и укорачивает
   * островки. Вода никогда не шире, чем берёт прыжок средней силы, а за ней
   * всегда есть место приземлиться — поэтому любая такая карта проходима.
   */
  function generate(seed, difficulty) {
    var random = seeded(seed);
    difficulty = Math.max(0, Math.min(1, difficulty === undefined ? 0.5 : difficulty));
    var between = function (low, high) { return Math.round(low + (high - low) * random()); };
    var words = ['G280'];
    var raised = 0;
    var obstacles = 9 + Math.round(5 * difficulty);
    for (var i = 0; i < obstacles; i++) {
      var roll = random();
      if (roll < 0.5) {
        words.push('W' + between(55, 85 + 45 * difficulty));
      } else if (roll < 0.75) {
        words.push('R' + between(65, 95));
      } else if (raised === 0) {
        raised = between(20, 30);
        words.push('U' + raised);
      } else {
        words.push('D' + raised);
        raised = 0;
      }
      words.push('G' + between(150 - 45 * difficulty, 230 - 60 * difficulty));
      if (i === Math.floor(obstacles / 3) || i === Math.floor(2 * obstacles / 3)) { words.push('C'); }
    }
    words.push('G120', 'F', 'G220');
    return words.join(' ');
  }

  var rules = {
    WALK_SPEED: WALK_SPEED, AIR_SPEED: AIR_SPEED, GRAVITY: GRAVITY, JUMP_MIN: JUMP_MIN, JUMP_MAX: JUMP_MAX,
    STARTLE: STARTLE, QUIET: QUIET, LOUD: LOUD, REARM: REARM, VOICE_HOLD: VOICE_HOLD, FOOT: FOOT, STEP_UP: STEP_UP,
    START_HEIGHT: START_HEIGHT, RAVINE_DEPTH: RAVINE_DEPTH, WATER_LEVEL: WATER_LEVEL, SINK: SINK, RESPAWN: RESPAWN,
    START_X: START_X, LEVELS: LEVELS, QUIET_MARGIN: QUIET_MARGIN, LOUD_MARGIN: LOUD_MARGIN, LOUD_RANGE: LOUD_RANGE,
    LOUD_TOP: LOUD_TOP, VOICE_GAP: VOICE_GAP, VOICE_SHARE: VOICE_SHARE, VOICE_REACH: VOICE_REACH,
    VOICE_HEADROOM: VOICE_HEADROOM,
    buildLevel: buildLevel, segmentAt: segmentAt, groundAt: groundAt, support: support,
    jumpSpeed: jumpSpeed, jumpHeight: jumpHeight, jumpLength: jumpLength,
    createRun: createRun, respawnPoint: respawnPoint, step: step, stars: stars,
    noiseOf: noiseOf, voiceOf: voiceOf, calibrate: calibrate, levelFromDb: levelFromDb,
    seeded: seeded, generate: generate
  };

  /* Вне браузера файл подключается тестами: отрисовка тогда не нужна. */
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = rules;
    return;
  }
  global.WalkRules = rules;

  /* --- отрисовка и управление ------------------------------------------- */

  var S = global.Sluhach;
  var STEP = 1 / 120;           /* шаг расчёта, с: прыжок короткий, шаг должен быть мелким */
  var VIEW_W = 960;             /* размер сцены в единицах карты */
  var VIEW_H = 420;
  var BASE_Y = 330;             /* на этой высоте экрана лежит нулевая высота карты */
  var HERO_AT = 0.3;            /* паук держится на трети ширины сцены */
  var HERO_SIZE = 86;           /* ширина рисунка паука на сцене */
  var MODEL = 120;              /* ширина модели паука в её собственных единицах */
  var TALK_PAUSE = 4500;        /* реплики о рядовых событиях — не чаще раза в 4,5 с */
  var STORE = 'sluhach-walk';
  var METER_LOW = -70;
  var METER_HIGH = 0;
  var KEY_QUIET = 0.4;          /* уровень «голоса» при управлении с клавиатуры */
  var KEY_LOUD = 0.86;
  var NOISE_TIME = 1500;        /* настройка голоса, мс: столько паук слушает тишину, */
  var VOICE_WAIT = 8000;        /* столько ждёт, пока игрок заговорит, */
  var VOICE_TIME = 2500;        /* и столько слушает его спокойный голос */
  var WEAK_VOICE = -50;         /* голос тише этого, дБ, — микрофону не хватает усиления */

  function screenY(height) { return BASE_Y - height; }

  function clock(seconds) {
    var whole = Math.floor(seconds);
    var tenth = Math.floor((seconds - whole) * 10);
    return Math.floor(whole / 60) + ':' + ('0' + (whole % 60)).slice(-2) + ',' + tenth;
  }

  /* устойчивое «случайное» число по координате — трава и цветы не мигают между кадрами */
  function noise(value) {
    var x = Math.sin(value * 127.1) * 43758.5453;
    return x - Math.floor(x);
  }

  S.ready(function () {
    var root = document.getElementById('walk');
    if (!root || !global.Pafnuty) { return; }

    var $ = function (id) { return document.getElementById(id); };
    var el = S.element;
    var lines = JSON.parse($('walk-lines').textContent);
    var intro = $('walk-intro');
    var play = $('walk-play');
    var stage = $('stage');
    var back = $('stage-back');
    var front = $('stage-front');
    var heroBox = $('hero');
    var bubble = $('hero-bubble');
    var result = $('stage-result');
    var hint = $('stage-hint');
    var stageMeter = $('stage-meter');
    var voiceMeter = $('voice-meter');
    var micButton = $('mic-toggle');
    var micNote = $('mic-note');
    var voiceState = $('voice-state');
    var quietBox = $('quiet-threshold');
    var loudBox = $('loud-threshold');
    var pauseButton = $('walk-pause');

    var hero = global.Pafnuty.create({ mode: 'stand' });
    hero.el.style.width = HERO_SIZE + 'px';
    hero.el.style.left = (-HERO_SIZE / 2) + 'px';
    /* стопы модели (высота GROUND) должны стоять в точке героя */
    hero.el.style.top = (-(global.Pafnuty.geometry.GROUND - 14) * HERO_SIZE / MODEL) + 'px';
    heroBox.appendChild(hero.el);

    /* --- сохранённое: пороги голоса и лучшие прогулки ---------------------- */

    var saved = { quiet: null, loud: null, best: {} };
    try {
      var stored = JSON.parse(global.localStorage.getItem(STORE) || '{}');
      if (typeof stored.quiet === 'number' && typeof stored.loud === 'number') {
        saved.quiet = stored.quiet;
        saved.loud = stored.loud;
      }
      if (stored.best && typeof stored.best === 'object') { saved.best = stored.best; }
    } catch (e) { /* ничего не сохранялось */ }

    function persist() {
      try { global.localStorage.setItem(STORE, JSON.stringify(saved)); } catch (e) { /* без хранилища */ }
    }

    /* --- голос --------------------------------------------------------------- */

    var mic = null;
    var micDb = S.micRules.SILENCE_DB;       /* последний уровень с микрофона, дБ */
    var smoothDb = METER_LOW;
    var calibration = rules.calibrate(-60);
    if (saved.quiet !== null) { calibration = { noise: saved.quiet - rules.QUIET_MARGIN, quiet: saved.quiet, loud: saved.loud }; }
    var listening = null;                    /* идёт настройка голоса: {kind: 'noise' | 'voice', until, values, …} */
    var keys = { quiet: false, loud: false };

    function showThresholds() {
      var scale = function (db) { return 100 * (1 - S.micRules.scale(db, METER_LOW, METER_HIGH)); };
      [voiceMeter, stageMeter].forEach(function (meter) {
        meter.style.setProperty('--quiet-top', scale(calibration.quiet) + '%');
        meter.style.setProperty('--loud-top', scale(calibration.loud) + '%');
      });
      quietBox.value = Math.round(calibration.quiet);
      loudBox.value = Math.round(calibration.loud);
      $('quiet-value').textContent = String(Math.round(calibration.quiet)).replace('-', '−') + ' дБ';
      $('loud-value').textContent = String(Math.round(calibration.loud)).replace('-', '−') + ' дБ';
    }

    function setThresholds(quiet, loud, keep) {
      quiet = Math.max(-60, Math.min(-12, quiet));
      loud = Math.max(quiet + 4, Math.min(-3, loud));
      calibration = { noise: calibration.noise, quiet: quiet, loud: loud };
      if (keep) {
        saved.quiet = quiet;
        saved.loud = loud;
        persist();
      }
      showThresholds();
    }

    /* Уровень голоса 0…1 в эту минуту: микрофон или клавиши. */
    function voiceLevel() {
      var level = mic && mic.active && !listening ? rules.levelFromDb(micDb, calibration) : 0;
      if (keys.loud) { level = Math.max(level, KEY_LOUD); }
      else if (keys.quiet) { level = Math.max(level, KEY_QUIET); }
      return level;
    }

    function startMic() {
      if (mic) { return; }
      micButton.disabled = true;
      micNote.textContent = 'Запрашиваю микрофон…';
      /* обработка сигнала браузером выключена: она выравнивает громкость, а игре нужна именно она */
      mic = new S.Mic({ pcm: false, processing: false, onLevel: function (db) { micDb = db; } });
      mic.start().then(function () {
        micButton.disabled = false;
        micButton.textContent = 'Выключить микрофон';
        $('mic-listen').disabled = false;
        if (saved.quiet === null) {
          measureNoise();
        } else {
          micNote.textContent = 'Микрофон включён, пороги взяты с прошлого раза. Скажите что-нибудь — проверим.';
        }
      }, function (problem) {
        mic = null;
        micButton.disabled = false;
        micNote.textContent = 'Не получилось: ' + (problem && problem.name ? S.Mic.describe(problem)
          : String((problem && problem.message) || problem)) + '. Можно гулять и с клавиатуры.';
      });
    }

    function stopMic() {
      if (!mic) { return; }
      mic.stop();
      mic = null;
      micDb = S.micRules.SILENCE_DB;
      listening = null;
      micButton.textContent = 'Включить микрофон';
      $('mic-listen').disabled = true;
      micNote.textContent = 'Микрофон выключен. Без него паук слушается клавиш: → — идти, пробел — прыгать.';
    }

    function decibels(value) {
      return String(Math.round(value)).replace('-', '−') + ' дБ';
    }

    /* Настройка в два шага: сначала тишина — это шум комнаты, потом спокойный
       голос игрока; паук ждёт, пока тот заговорит. Пороги ставятся в конце
       второго шага. */
    function measureNoise() {
      if (!mic) { return; }
      listening = { kind: 'noise', until: performance.now() + NOISE_TIME, values: [] };
      micNote.textContent = 'Шаг 1 из 2. Тише… слушаю комнату.';
      say('walk_listen', true);
    }

    function finishNoise() {
      var noiseDb = rules.noiseOf(listening.values);
      /* ни одного замера громче цифрового нуля: либо микрофон глушит тишину сам, либо он выключен */
      var mute = noiseDb === null;
      if (mute) { noiseDb = S.micRules.SILENCE_DB; }
      listening = { kind: 'voice', until: performance.now() + VOICE_WAIT, values: [], noise: noiseDb, mute: mute, heard: false };
      micNote.textContent = 'Шаг 2 из 2. ' + (mute ? 'В тишине микрофон молчит совсем. ' : 'Шум комнаты — ' + decibels(noiseDb) + '. ') +
        'Теперь скажите что-нибудь вполголоса — тем голосом, которым будете вести паука.';
      say('walk_voice', true);
    }

    /* Очередной замер громкости, пока идёт настройка. */
    function hearSetup(now) {
      if (listening.kind === 'noise') {
        /* цифровой ноль — не шум комнаты: микрофон ещё не прислал ни одного замера */
        if (micDb > S.micRules.SILENCE_DB) { listening.values.push(micDb); }
        if (now >= listening.until) { finishNoise(); }
        return;
      }
      if (!listening.heard && micDb > listening.noise + rules.VOICE_GAP) {
        /* игрок заговорил: с этого мига голос слушается VOICE_TIME, сколько бы он ни собирался до того */
        listening.heard = true;
        listening.until = now + VOICE_TIME;
      }
      if (listening.heard) { listening.values.push(micDb); }
      if (now >= listening.until) { finishVoice(); }
    }

    function finishVoice() {
      var noiseDb = listening.noise;
      var mute = listening.mute;
      var voiceDb = rules.voiceOf(listening.values, noiseDb);
      listening = null;
      if (voiceDb === null && mute) {
        micNote.textContent = 'С микрофона не пришло ни звука: проверьте, не выключен ли он в системе, и нажмите ' +
          '«Настроить заново». Пороги остались прежними.';
        say('walk_unheard', true);
        return;
      }
      calibration = rules.calibrate(noiseDb, voiceDb);
      setThresholds(calibration.quiet, calibration.loud, true);
      if (voiceDb === null) {
        micNote.textContent = 'Голоса не услышал, поэтому пороги поставлены наугад — по одному шуму комнаты (' +
          decibels(noiseDb) + '). Нажмите «Настроить заново» и скажите что-нибудь или поправьте пороги ползунками.';
        say('walk_unheard', true);
        return;
      }
      var advice = ' Проверьте голосом; пороги можно поправить ползунками.';
      if (voiceDb < WEAK_VOICE) {
        advice = ' Голос доходит очень тихим: если паук слушается плохо, прибавьте усиление микрофона в системе ' +
          'или сядьте к нему ближе и настройте заново.';
      } else if (calibration.loud < voiceDb + rules.VOICE_HEADROOM - 1) {
        advice = ' Голос доходит очень громким, запаса до крика почти нет: убавьте усиление микрофона в системе ' +
          'или отодвиньтесь от него и настройте заново.';
      }
      micNote.textContent = 'Готово. ' + (mute ? '' : 'Шум комнаты — ' + decibels(noiseDb) + ', ') +
        (mute ? 'Ваш' : 'ваш') + ' спокойный голос — ' + decibels(voiceDb) + ': от такого паук идёт, а от голоса громче ' +
        decibels(calibration.loud) + ' — прыгает.' + advice;
      say('walk_ready', true);
    }

    /* --- реплики ------------------------------------------------------------- */

    var lastTalk = 0;
    var bubbleTimer = null;

    function say(occasion, important) {
      var now = Date.now();
      if (!important && now - lastTalk < TALK_PAUSE) { return; }
      var text = S.pick(lines, occasion);
      if (!text) { return; }
      lastTalk = now;
      if (play.hidden) {
        S.say(text);                         /* на странице выбора говорит паук из угла */
        return;
      }
      S.said.push(text);
      if (S.said.length > 12) { S.said.shift(); }
      bubble.textContent = text;
      bubble.classList.add('show');
      clearTimeout(bubbleTimer);
      bubbleTimer = setTimeout(function () { bubble.classList.remove('show'); }, 2600 + 40 * text.length);
    }

    /* --- сцена ----------------------------------------------------------------- */

    var level = null;
    var meta = null;                /* {id, name}: какая карта идёт */
    var run = null;
    var running = false;
    var paused = false;
    var frameId = 0;
    var lastFrame = 0;
    var backlog = 0;
    var camera = 0;
    var walkPhase = 0;
    var moving = 0;
    var air = 0;
    var squash = 0;                 /* приседание после приземления */
    var mood = 'idle';
    var moodUntil = 0;
    var particles = [];
    var remarks = {};
    var scale = 1;

    function resize() {
      var width = stage.clientWidth || VIEW_W;
      scale = width / VIEW_W;
      var ratio = Math.min(2, global.devicePixelRatio || 1);
      [back, front].forEach(function (canvas) {
        canvas.width = Math.round(VIEW_W * scale * ratio);
        canvas.height = Math.round(VIEW_H * scale * ratio);
        canvas.getContext('2d').setTransform(scale * ratio, 0, 0, scale * ratio, 0, 0);
      });
    }

    function burst(kind, x, y, count) {
      for (var i = 0; i < count; i++) {
        var angle = kind === 'water' ? -Math.PI / 2 + (Math.random() - 0.5) * 1.5 : Math.PI + Math.random() * Math.PI;
        var speed = kind === 'water' ? 130 + Math.random() * 190 : 20 + Math.random() * 50;
        particles.push({
          kind: kind, x: x + (Math.random() - 0.5) * 22, y: y,
          vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
          life: kind === 'water' ? 0.9 : 0.45, age: 0, size: kind === 'water' ? 2 + Math.random() * 3 : 3 + Math.random() * 3
        });
      }
    }

    function drawSky(ctx, time) {
      var sky = ctx.createLinearGradient(0, 0, 0, VIEW_H);
      sky.addColorStop(0, '#bfe0f8');
      sky.addColorStop(0.7, '#e9f5fd');
      sky.addColorStop(1, '#f4f9f2');
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, VIEW_W, VIEW_H);
      ctx.fillStyle = 'rgba(255, 246, 204, .9)';
      ctx.beginPath();
      ctx.arc(VIEW_W - 130, 74, 34, 0, Math.PI * 2);
      ctx.fill();
      /* облака плывут сами и чуть отстают от карты */
      ctx.fillStyle = 'rgba(255, 255, 255, .85)';
      for (var i = 0; i < 6; i++) {
        var x = ((i * 290 + 80 - camera * 0.12 - time * 5) % (VIEW_W + 300) + VIEW_W + 300) % (VIEW_W + 300) - 150;
        var y = 44 + noise(i + 3) * 90;
        var size = 0.7 + noise(i + 11) * 0.7;
        [[0, 0, 46, 15], [-26, 5, 28, 12], [28, 6, 30, 11]].forEach(function (puff) {
          ctx.beginPath();
          ctx.ellipse(x + puff[0] * size, y + puff[1] * size, puff[2] * size, puff[3] * size, 0, 0, Math.PI * 2);
          ctx.fill();
        });
      }
    }

    function drawHills(ctx, parallax, baseline, height, color, shift) {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(0, VIEW_H);
      for (var x = 0; x <= VIEW_W; x += 12) {
        var world = x + camera * parallax + shift;
        var y = baseline - height * (0.55 + 0.3 * Math.sin(world * 0.006) + 0.15 * Math.sin(world * 0.017 + 1.3));
        ctx.lineTo(x, y);
      }
      ctx.lineTo(VIEW_W, VIEW_H);
      ctx.closePath();
      ctx.fill();
    }

    function drawGround(ctx) {
      level.segments.forEach(function (segment, index) {
        var x0 = segment.x0 - camera;
        var x1 = segment.x1 - camera;
        if (x1 < -20 || x0 > VIEW_W + 20) { return; }
        var top = screenY(segment.top);
        var soil = ctx.createLinearGradient(0, top, 0, VIEW_H);
        soil.addColorStop(0, segment.ravine ? '#96724c' : '#b08757');
        soil.addColorStop(1, segment.ravine ? '#6f5235' : '#84623f');
        ctx.fillStyle = soil;
        ctx.fillRect(x0, top, x1 - x0, VIEW_H - top);
        /* открытый обрыв — в тени: видно, где край */
        [[level.segments[index - 1], x0, 1], [level.segments[index + 1], x1, -1]].forEach(function (side) {
          var neighbour = side[0];
          var touching = neighbour && (side[2] > 0 ? neighbour.x1 === segment.x0 : neighbour.x0 === segment.x1);
          var bottom = touching ? screenY(neighbour.top) : VIEW_H;
          if (bottom <= top + 2) { return; }
          var shade = ctx.createLinearGradient(side[1], 0, side[1] + side[2] * 14, 0);
          shade.addColorStop(0, 'rgba(40, 25, 10, .30)');
          shade.addColorStop(1, 'rgba(40, 25, 10, 0)');
          ctx.fillStyle = shade;
          ctx.fillRect(Math.min(side[1], side[1] + side[2] * 14), top + 9, 14, bottom - top - 9);
        });
        /* камешки в земле */
        ctx.fillStyle = 'rgba(60, 40, 20, .16)';
        for (var s = Math.floor(segment.x0 / 46); s * 46 < segment.x1; s++) {
          var sx = s * 46 + noise(s) * 30 - camera;
          if (sx > x0 + 6 && sx < x1 - 6) {
            ctx.beginPath();
            ctx.ellipse(sx, top + 30 + noise(s + 7) * (VIEW_H - top - 40), 5 + noise(s + 2) * 5, 3 + noise(s + 4) * 3, 0, 0, Math.PI * 2);
            ctx.fill();
          }
        }
        /* дёрн */
        ctx.fillStyle = segment.ravine ? '#5f8f4a' : '#74b356';
        ctx.beginPath();
        ctx.roundRect(x0 - 3, top - 4, x1 - x0 + 6, 15, 6);
        ctx.fill();
        ctx.fillStyle = segment.ravine ? '#4c7a3b' : '#5c9a45';
        ctx.fillRect(x0 - 1, top + 7, x1 - x0 + 2, 4);
        /* травинки и цветы */
        for (var g = Math.floor(segment.x0 / 23); g * 23 < segment.x1; g++) {
          var gx = g * 23 + noise(g + 31) * 16;
          if (gx < segment.x0 + 8 || gx > segment.x1 - 8) { continue; }
          var screen = gx - camera;
          ctx.strokeStyle = '#4f8c3c';
          ctx.lineWidth = 1.6;
          ctx.beginPath();
          ctx.moveTo(screen, top - 3);
          ctx.lineTo(screen - 3, top - 10 - noise(g) * 5);
          ctx.moveTo(screen, top - 3);
          ctx.lineTo(screen + 3, top - 9 - noise(g + 5) * 5);
          ctx.stroke();
          if (noise(g + 77) > 0.82 && !segment.ravine) {
            ctx.fillStyle = noise(g + 5) > 0.5 ? '#f6d04a' : '#f3f1ff';
            ctx.beginPath();
            ctx.arc(screen + 6, top - 9, 2.6, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      });
    }

    function drawFlag(ctx, x, reached) {
      var screen = x - camera;
      if (screen < -40 || screen > VIEW_W + 40) { return; }
      var top = screenY(rules.groundAt(level, x));
      ctx.strokeStyle = '#6b5a4a';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(screen, top);
      ctx.lineTo(screen, top - 54);
      ctx.stroke();
      ctx.fillStyle = reached ? '#5b3d8a' : '#c9c1d6';
      ctx.beginPath();
      ctx.moveTo(screen + 1, top - 54);
      ctx.lineTo(screen + 30, top - 45);
      ctx.lineTo(screen + 1, top - 34);
      ctx.closePath();
      ctx.fill();
    }

    function drawFinish(ctx, time) {
      var screen = level.finish - camera;
      if (screen < -80 || screen > VIEW_W + 80) { return; }
      var top = screenY(rules.groundAt(level, level.finish));
      ctx.strokeStyle = '#6b5a4a';
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.moveTo(screen - 34, top);
      ctx.lineTo(screen - 34, top - 118);
      ctx.moveTo(screen + 34, top);
      ctx.lineTo(screen + 34, top - 118);
      ctx.stroke();
      /* финишная паутина между столбами */
      ctx.strokeStyle = 'rgba(120, 110, 140, .75)';
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      for (var i = 0; i <= 4; i++) {
        ctx.moveTo(screen - 34, top - 58 - i * 14);
        ctx.quadraticCurveTo(screen, top - 50 - i * 14 + Math.sin(time * 2 + i) * 1.5, screen + 34, top - 58 - i * 14);
      }
      for (var j = -2; j <= 2; j++) {
        ctx.moveTo(screen + j * 14, top - 112);
        ctx.lineTo(screen + j * 14, top - 52);
      }
      ctx.stroke();
      ctx.fillStyle = '#5b3d8a';
      ctx.beginPath();
      ctx.roundRect(screen - 40, top - 140, 80, 24, 6);
      ctx.fill();
      ctx.fillStyle = '#fff';
      ctx.font = '700 14px "Segoe UI", sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('ФИНИШ', screen, top - 127);
    }

    function drawShadow(ctx) {
      if (!run || run.respawn > 0) { return; }
      var under = rules.support(level, run.x, run.y);
      if (under === -Infinity) { return; }
      var height = run.y - under;
      var size = Math.max(0.35, 1 - height / 220);
      ctx.fillStyle = 'rgba(30, 20, 50, ' + (0.22 * size) + ')';
      ctx.beginPath();
      ctx.ellipse(run.x - camera, screenY(under) + 3, 30 * size, 6 * size, 0, 0, Math.PI * 2);
      ctx.fill();
    }

    /* Вода рисуется поверх паука: упав, он уходит под неё. */
    function drawWater(ctx, time) {
      var surface = screenY(rules.WATER_LEVEL);
      var gaps = [];
      var previous = 0;
      level.segments.forEach(function (segment) {
        if (segment.x0 > previous) { gaps.push([previous, segment.x0]); }
        previous = segment.x1;
      });
      gaps.forEach(function (gap) {
        var x0 = gap[0] - camera;
        var x1 = gap[1] - camera;
        if (x1 < 0 || x0 > VIEW_W) { return; }
        var water = ctx.createLinearGradient(0, surface, 0, VIEW_H);
        water.addColorStop(0, 'rgba(86, 164, 226, .82)');
        water.addColorStop(1, 'rgba(38, 96, 168, .95)');
        ctx.fillStyle = water;
        ctx.beginPath();
        ctx.moveTo(x0, VIEW_H);
        for (var x = x0; x <= x1 + 4; x += 6) {
          var px = Math.min(x, x1);
          ctx.lineTo(px, surface + Math.sin((px + camera) * 0.05 + time * 2.4) * 2.6 + Math.sin((px + camera) * 0.12 - time * 1.5) * 1.3);
        }
        ctx.lineTo(x1, VIEW_H);
        ctx.closePath();
        ctx.fill();
        /* блики */
        ctx.strokeStyle = 'rgba(255, 255, 255, .5)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        for (var w = Math.ceil((gap[0] + 8) / 34); w * 34 < gap[1] - 14; w++) {
          var wx = w * 34 + Math.sin(time * 1.2 + w) * 5 - camera;
          var wy = surface + 12 + noise(w) * 34;
          ctx.moveTo(wx, wy);
          ctx.lineTo(wx + 11, wy);
        }
        ctx.stroke();
      });
    }

    function drawParticles(ctx, kind) {
      particles.forEach(function (particle) {
        if (particle.kind !== kind) { return; }
        var fade = 1 - particle.age / particle.life;
        ctx.fillStyle = kind === 'water' ? 'rgba(120, 190, 240, ' + fade + ')' : 'rgba(150, 120, 90, ' + (0.6 * fade) + ')';
        ctx.beginPath();
        ctx.arc(particle.x - camera, particle.y, particle.size * (kind === 'water' ? 1 : 1 + particle.age * 2), 0, Math.PI * 2);
        ctx.fill();
      });
    }

    function placeHero(time) {
      var x = (run.x - camera) * scale;
      var y = screenY(run.y) * scale;
      /* в воде паук покачивается, после приземления приседает */
      var bob = run.respawn > 0 ? Math.sin(time * 9) * 2 : 0;
      heroBox.style.transform = 'translate(' + x.toFixed(2) + 'px, ' + (y + bob).toFixed(2) + 'px) scale(' + scale.toFixed(4) + ')';
      var unit = HERO_SIZE / MODEL;           /* единиц карты в единице модели */
      hero.set({
        mode: run.respawn > 0 ? 'swim' : 'stand',
        walk: walkPhase, moving: moving, air: air, facing: 1,
        lean: (run.startle >= 0 ? 6 : 0) + squash * 7 - air * 3,
        sway: time * 7,
        look: { x: 0.5, y: run.grounded ? 0.15 : (run.vy > 0 ? -0.7 : 0.6) },
        /* стопы ищут землю: на краю и на ступеньке ноги стоят на разной высоте */
        ground: run.grounded ? function (offset) {
          var top = rules.groundAt(level, run.x + offset * unit);
          return top === -Infinity ? 14 : (run.y - top) / unit;
        } : null
      });
      var now = performance.now();
      var wanted = now < moodUntil ? mood : (run.respawn > 0 ? 'dizzy' : run.over ? 'happy'
        : (!run.grounded && run.vy > 0) || run.startle >= 0 ? 'startled' : 'idle');
      hero.mood(wanted);
      bubble.style.left = Math.max(120, Math.min(stage.clientWidth - 120, x)) + 'px';
      bubble.style.top = Math.max(46, y - 74 * scale) + 'px';
    }

    function draw(time) {
      var ctx = back.getContext('2d');
      drawSky(ctx, time);
      drawHills(ctx, 0.2, 300, 150, '#cfe3d2', 400);
      drawHills(ctx, 0.4, 330, 120, '#b4d2ae', 90);
      drawGround(ctx);
      level.checkpoints.forEach(function (x, index) { drawFlag(ctx, x, run.checkpoint >= index); });
      drawFinish(ctx, time);
      drawShadow(ctx);
      drawParticles(ctx, 'dust');
      var over = front.getContext('2d');
      over.clearRect(0, 0, VIEW_W, VIEW_H);
      drawWater(over, time);
      drawParticles(over, 'water');
      placeHero(time);
    }

    function drawHud() {
      $('hud-time').textContent = clock(run.time);
      $('hud-falls').textContent = run.falls;
      $('hud-progress').style.width = Math.max(0, Math.min(100, 100 * (run.x - rules.START_X) / (level.finish - rules.START_X))) + '%';
    }

    function drawMeters() {
      smoothDb += (Math.max(METER_LOW, mic && mic.active ? micDb : METER_LOW) - smoothDb) * 0.4;
      var level01 = voiceLevel();
      var shown = mic && mic.active ? 100 * S.micRules.scale(smoothDb, METER_LOW, METER_HIGH)
        /* без микрофона шкала показывает уровень, заданный клавишами */
        : 100 * S.micRules.scale(level01 >= rules.LOUD ? calibration.loud + 4 : level01 >= rules.QUIET ? calibration.quiet + 3 : METER_LOW,
          METER_LOW, METER_HIGH);
      $('voice-meter-fill').style.height = shown + '%';
      $('stage-meter-fill').style.height = shown + '%';
      var state = level01 >= rules.LOUD ? 'loud' : level01 >= rules.QUIET ? 'quiet' : 'silent';
      voiceState.className = 'voice-state is-' + state;
      voiceState.textContent = listening ? (listening.kind === 'noise' ? 'слушаю тишину…'
        : listening.heard ? 'слышу голос — продолжайте…' : 'жду ваш голос…')
        : state === 'loud' ? 'громко — прыжок!'
        : state === 'quiet' ? 'тихо — иду' : (mic && mic.active ? 'тишина — стою' : 'микрофон выключен');
    }

    /* --- ход игры ---------------------------------------------------------------- */

    function handle(events) {
      events.forEach(function (event) {
        if (event.type === 'jump') {
          if (Math.random() < 0.45 || !remarks.jump) { remarks.jump = true; say('walk_jump'); }
        } else if (event.type === 'land') {
          squash = Math.min(1, event.speed / 620);
          burst('dust', run.x, screenY(run.y) - 2, 5);
        } else if (event.type === 'splash') {
          burst('water', run.x, screenY(rules.WATER_LEVEL), 22);
          say('walk_water', true);
        } else if (event.type === 'respawn') {
          hint.textContent = run.checkpoint >= 0 ? 'С метки — ещё раз.' : 'С начала — ещё раз.';
        } else if (event.type === 'ravine') {
          say('walk_ravine', true);
        } else if (event.type === 'ravine_out') {
          say('walk_ravine_out');
        } else if (event.type === 'wall') {
          if (!run.inRavine) { say('walk_wall'); }
        } else if (event.type === 'checkpoint') {
          say('walk_checkpoint', true);
        } else if (event.type === 'finish') {
          finish(event.stars);
        }
      });
    }

    function frame(now) {
      if (!running) { frameId = 0; return; }
      var dt = Math.min(0.1, (now - lastFrame) / 1000);
      lastFrame = now;
      var time = now / 1000;

      if (listening) { hearSetup(now); }

      if (level && run) {
        if (!paused) {
          var voice = voiceLevel();
          backlog += dt;
          var before = run.x;
          while (backlog >= STEP) {
            handle(rules.step(run, STEP, voice));
            backlog -= STEP;
          }
          /* шаг ног привязан к пройденному пути: стопа на опоре не скользит */
          if (run.grounded) { walkPhase += (run.x - before) / (global.Pafnuty.geometry.STRIDE * HERO_SIZE / MODEL / 0.6); }
          moving += ((run.grounded && run.vx > 1 ? 1 : 0) - moving) * Math.min(1, 14 * dt);
          air += ((run.grounded ? 0 : 1) - air) * Math.min(1, 16 * dt);
          squash = Math.max(0, squash - 5 * dt);
          particles = particles.filter(function (particle) {
            particle.age += dt;
            particle.x += particle.vx * dt;
            particle.y += particle.vy * dt;
            if (particle.kind === 'water') { particle.vy += 620 * dt; }
            return particle.age < particle.life;
          });
          if (!run.over && run.silent > 7 && run.respawn <= 0 && !remarks.silent) {
            remarks.silent = true;
            say('walk_silent', true);
          }
          if (run.silent < 1) { remarks.silent = false; }
          /* камера догоняет паука плавно и не выходит за края карты */
          var target = Math.max(0, Math.min(level.length - VIEW_W, run.x - VIEW_W * HERO_AT));
          camera += (target - camera) * Math.min(1, 6 * dt);
          drawHud();
        }
        draw(time);
      }
      drawMeters();
      frameId = global.requestAnimationFrame(frame);
    }

    function ensureLoop() {
      running = true;
      if (!frameId) {
        lastFrame = performance.now();
        frameId = global.requestAnimationFrame(frame);
      }
    }

    function setPaused(value) {
      if (!run || run.over) { return; }
      paused = value;
      pauseButton.textContent = paused ? 'Продолжить' : 'Пауза';
      hint.textContent = paused ? 'Пауза. Паук ждёт.' : hintText();
      if (paused) { say('walk_pause', true); }
    }

    function hintText() {
      return mic && mic.active ? 'Тихий голос — идти, громкий — прыгать. Молчание — стоять.'
        : 'Микрофон выключен: → — идти, пробел — прыгать.';
    }

    function begin(choice) {
      meta = choice;
      level = rules.buildLevel(choice.spec);
      run = rules.createRun(level);
      camera = 0;
      walkPhase = 0;
      moving = air = squash = 0;
      particles = [];
      remarks = {};
      paused = false;
      backlog = 0;
      lastTalk = 0;
      intro.hidden = true;
      play.hidden = false;
      result.hidden = true;
      pauseButton.disabled = false;
      pauseButton.textContent = 'Пауза';
      $('hud-name').textContent = choice.name;
      $('hud-best').textContent = saved.best[choice.id] ? clock(saved.best[choice.id].time) : '—';
      hint.textContent = hintText();
      S.companion.away(true);                 /* паук из угла ушёл гулять */
      resize();
      drawHud();
      ensureLoop();
      say('walk_start', true);
      play.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function finish(earned) {
      pauseButton.disabled = true;
      var best = saved.best[meta.id];
      var record = !best || earned > best.stars || (earned === best.stars && run.time < best.time);
      if (record && !meta.random) {
        saved.best[meta.id] = { stars: earned, time: Math.round(run.time * 10) / 10 };
        persist();
      }
      $('result-stars').innerHTML = '';
      for (var i = 1; i <= 3; i++) { $('result-stars').appendChild(el('span', i <= earned ? 'on' : '', '★')); }
      $('result-title').textContent = earned === 3 ? 'Дошёл, не замочив лап!' : 'Финиш!';
      $('result-text').textContent = 'Прогулка заняла ' + clock(run.time) + ', прыжков — ' + run.jumps +
        ', купаний — ' + run.falls + '.' + (record && best && !meta.random ? ' Это лучше прежнего.' : '');
      result.hidden = false;
      hint.textContent = '';
      say('walk_finish_' + earned, true);
      buildLevels();
    }

    function leave() {
      play.hidden = true;
      intro.hidden = false;
      run = null;
      level = null;
      bubble.classList.remove('show');
      S.companion.away(false);
      buildLevels();
    }

    /* --- выбор карты ------------------------------------------------------------ */

    function buildLevels() {
      var box = $('walk-levels');
      box.textContent = '';
      rules.LEVELS.forEach(function (item, index) {
        var button = el('button', 'walk-level');
        button.type = 'button';
        button.appendChild(el('b', '', (index + 1) + '. ' + item.name));
        var best = saved.best[item.id];
        var mark = el('i', '', best ? '★★★'.slice(0, best.stars) + '☆☆☆'.slice(0, 3 - best.stars) : '☆☆☆');
        mark.appendChild(el('em', '', best ? clock(best.time) : 'не пройдена'));
        button.appendChild(mark);
        button.appendChild(el('span', '', item.text));
        button.addEventListener('click', function () { begin(item); });
        box.appendChild(button);
      });
      var random = el('button', 'walk-level');
      random.type = 'button';
      random.appendChild(el('b', '', 'Случайная карта'));
      random.appendChild(el('i', '', '?'));
      random.appendChild(el('span', '', 'каждый раз новая; проходима всегда, но в рекорды не идёт'));
      random.addEventListener('click', function () {
        var seed = Math.floor(Math.random() * 1e9);
        begin({ id: 'random', name: 'Случайная карта № ' + (seed % 1000), spec: rules.generate(seed, 0.5), random: true });
      });
      box.appendChild(random);
    }

    /* --- управление -------------------------------------------------------------- */

    micButton.addEventListener('click', function () { if (mic) { stopMic(); } else { startMic(); } });
    $('mic-listen').addEventListener('click', measureNoise);
    quietBox.addEventListener('input', function () { setThresholds(Number(quietBox.value), calibration.loud, true); });
    loudBox.addEventListener('input', function () {
      setThresholds(Math.min(calibration.quiet, Number(loudBox.value) - 4), Number(loudBox.value), true);
    });
    pauseButton.addEventListener('click', function () { setPaused(!paused); });
    $('walk-restart').addEventListener('click', function () { if (meta) { begin(meta); } });
    $('walk-leave').addEventListener('click', leave);
    $('result-again').addEventListener('click', function () { if (meta) { begin(meta); } });
    $('result-leave').addEventListener('click', leave);
    $('result-next').addEventListener('click', function () {
      var index = rules.LEVELS.findIndex(function (item) { return meta && item.id === meta.id; });
      begin(rules.LEVELS[(index + 1) % rules.LEVELS.length]);
    });

    function key(event, down) {
      if (event.target && /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) { return; }
      var code = event.code;
      if (code === 'ArrowRight' || code === 'KeyD') { keys.quiet = down; }
      else if (code === 'Space' || code === 'ArrowUp' || code === 'KeyW') { keys.loud = down; }
      else if (code === 'KeyP' && down && !play.hidden) { setPaused(!paused); }
      else { return; }
      if (!play.hidden) { event.preventDefault(); }
    }
    document.addEventListener('keydown', function (event) { key(event, true); });
    document.addEventListener('keyup', function (event) { key(event, false); });
    global.addEventListener('blur', function () { keys.quiet = keys.loud = false; });
    global.addEventListener('resize', function () { if (!play.hidden) { resize(); } });
    document.addEventListener('visibilitychange', function () {
      if (document.hidden && run && !run.over && !paused) { setPaused(true); }
    });
    global.addEventListener('pagehide', function () { if (mic) { mic.stop(); } });

    showThresholds();
    buildLevels();
    ensureLoop();

    /* для проверок из консоли браузера и автоматических снимков */
    global.Sluhach.walk = {
      begin: function (index) { begin(rules.LEVELS[index || 0]); },
      state: function () { return run; },
      keys: keys,
      leave: leave
    };
  });
})(typeof window !== 'undefined' ? window : globalThis);
