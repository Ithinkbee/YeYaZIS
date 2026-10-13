/* Паук: Пафнутий и его дети.
 *
 * Модель перенесена из лабораторных («Слухач», «Глашатай»): брюшко с крестом,
 * головогрудь с двумя большими и двумя малыми глазами, рот, педипальпы и
 * восемь ног из двух сегментов. Ноги по-прежнему не нарисованы заранее: у
 * каждой задана точка крепления и длины сегментов, а колено вычисляется по
 * положению стопы (обратная кинематика двух звеньев).
 *
 * Отличий два. Во-первых, рисунок теперь на canvas, а не в SVG: в ролике
 * десятки пауков сразу, и все они в каждом кадре двигаются. Во-вторых, у
 * Пафнутия появились дети разных видов. Вид — это пропорции той же модели:
 * у птицееда ноги толстые и мохнатые, у сенокосца тело с горошину и ноги
 * вдвое длиннее, у скакуна огромные глаза, у чёрной вдовы красные песочные
 * часы на брюшке. Цвет задаётся отдельно от вида.
 *
 * Начало координат модели — центр головогруди; единица — та же, что в
 * лабораторных (паук вписан в квадрат 120 × 120).
 *
 * Сверху — геометрия без рисунка: она экспортируется через module.exports и
 * проверяется в node (tests/spider.test.js). Снизу — рисунок.
 */

(function (global) {
  'use strict';

  var TAU = Math.PI * 2;

  /* --- геометрия ---------------------------------------------------------- */

  /* Ноги правой стороны, от передней к задней; левые — их отражение.
     anchor — крепление к головогруди, femur и tibia — длины сегментов;
     stand, hang, splay — где стопа у стоящего, у висящего на нити и у
     сидящего в паутине; up — куда поднимается передняя нога, когда паук
     машет или дирижирует. */
  var BASE_LEGS = [
    { anchor: [14, -8], femur: 26, tibia: 40, stand: [56, 26], hang: [50, 20], splay: [58, -40], up: [56, -34] },
    { anchor: [17, -3], femur: 21, tibia: 32, stand: [44, 26], hang: [41, 28], splay: [64, -10] },
    { anchor: [17, 3], femur: 16, tibia: 25, stand: [32, 26], hang: [31, 32], splay: [52, 24] },
    { anchor: [14, 8], femur: 11, tibia: 18, stand: [20, 26], hang: [20, 32], splay: [32, 34] }
  ];

  /* Виды. head и abdomen — полуоси головогруди и брюшка; legs — длина ног
     относительно крестовика, thick — их толщина, spread — насколько шире
     расставлены стопы; eye — радиус большого глаза; pattern — рисунок на
     брюшке; fuzz — мохнатый; bands — полосатые ноги. */
  var KINDS = {
    cross: { title: 'крестовик', head: [19, 17], abdomen: [27, 25], legs: 1, thick: 1, eye: 6.3, pattern: 'cross' },
    baby: { title: 'паучонок', head: [21, 19], abdomen: [20, 18], legs: 0.8, thick: 1.05, eye: 7.6, pattern: 'dots' },
    tarantula: { title: 'птицеед', head: [22, 19], abdomen: [28, 25], legs: 0.9, thick: 1.75, eye: 5.8, pattern: 'none', fuzz: true, bands: true },
    longlegs: { title: 'сенокосец', head: [13.5, 12.5], abdomen: [13, 11], legs: 1.7, thick: 0.5, eye: 4.7, pattern: 'none' },
    jumper: { title: 'скакун', head: [23, 20], abdomen: [19, 17], legs: 0.8, thick: 1.3, eye: 8.4, pattern: 'peacock', sideEye: 3.5 },
    widow: { title: 'чёрная вдова', head: [15, 14], abdomen: [29, 28], legs: 1.1, thick: 0.8, eye: 5.3, pattern: 'hourglass' },
    wasp: { title: 'аргиопа', head: [17, 15.5], abdomen: [21, 29], legs: 1.15, thick: 0.85, eye: 5.8, pattern: 'stripes', bands: true },
    crab: { title: 'бокоход', head: [20, 15.5], abdomen: [31, 20], legs: 1, thick: 1.1, spread: 1.22, eye: 5.8, pattern: 'dots' }
  };

  /**
   * Форма паука данного вида: размеры тела и восемь ног с точками, куда
   * ставятся стопы в каждой позе.
   */
  function shape(name) {
    var kind = KINDS[name] || KINDS.cross;
    var hx = kind.head[0] / 19;
    var hy = kind.head[1] / 17;
    var reach = kind.legs;
    var wide = kind.spread || 1;
    /* длинноногий стоит выше: земля под ним дальше от головы */
    var ground = 26 * Math.pow(reach, 1.1);
    var abdomenY = -(0.55 * kind.head[1] + 0.667 * kind.abdomen[1]);
    var legs = [];
    BASE_LEGS.forEach(function (leg, index) {
      [1, -1].forEach(function (side) {
        var at = function (point) { return [side * point[0] * reach * wide, point[1] * reach]; };
        legs.push({
          index: index, side: side, femur: leg.femur * reach, tibia: leg.tibia * reach,
          anchor: [side * leg.anchor[0] * hx, leg.anchor[1] * hy],
          stand: [side * leg.stand[0] * reach * wide, ground],
          hang: at(leg.hang), splay: at(leg.splay), up: leg.up ? at(leg.up) : null
        });
      });
    });
    var eyeX = Math.max(7.5 * hx, kind.eye + 0.9);     /* большие глаза не должны слипаться */
    return {
      kind: name, title: kind.title, hx: hx, hy: hy, legs: legs, thick: kind.thick, ground: ground,
      head: { rx: kind.head[0], ry: kind.head[1] },
      abdomen: { rx: kind.abdomen[0], ry: kind.abdomen[1], y: abdomenY },
      thread: abdomenY - kind.abdomen[1] + 3,          /* здесь к брюшку крепится нить */
      eye: kind.eye, eyeX: eyeX, eyeY: -2 * hy,
      sideEye: kind.sideEye || 2.4 * Math.min(hx, hy),
      mouthY: 10.5 * hy,
      pattern: kind.pattern, fuzz: !!kind.fuzz, bands: !!kind.bands,
      width: Math.max(kind.abdomen[0], 56 * reach * wide),   /* половина ширины вместе с ногами */
      rest: {}
    };
  }

  /**
   * Колено ноги из двух сегментов: крепление (ax, ay), стопа (fx, fy).
   * Решений два — колено по одну или по другую сторону от прямой «крепление —
   * стопа». Обычно выбирается верхнее: нога встаёт дугой. У ноги, поднятой
   * вверх (raised), колено отводится в сторону — иначе оно ушло бы за
   * брюшко. Если до стопы не дотянуться, нога вытягивается в прямую, и стопа
   * возвращается на её конец.
   */
  function solveLeg(ax, ay, fx, fy, femur, tibia, side, raised) {
    var dx = fx - ax;
    var dy = fy - ay;
    var distance = Math.sqrt(dx * dx + dy * dy) || 1e-6;
    var reach = femur + tibia - 0.01;
    var fold = Math.abs(femur - tibia) + 0.01;
    var clamped = Math.max(fold, Math.min(reach, distance));
    if (clamped !== distance) {
      fx = ax + dx / distance * clamped;
      fy = ay + dy / distance * clamped;
      dx = fx - ax;
      dy = fy - ay;
      distance = clamped;
    }
    /* проекция колена на прямую и его высота над ней — по теореме косинусов */
    var along = (femur * femur - tibia * tibia + distance * distance) / (2 * distance);
    var height = Math.sqrt(Math.max(0, femur * femur - along * along));
    var ux = dx / distance;
    var uy = dy / distance;
    var px = ax + ux * along;
    var py = ay + uy * along;
    var first = { x: px - uy * height, y: py + ux * height };
    var second = { x: px + uy * height, y: py - ux * height };
    var weight = raised ? 0.3 : 1;
    var outer = function (knee) { return side * knee.x - weight * knee.y; };
    var knee = outer(first) >= outer(second) ? first : second;
    return { kx: knee.x, ky: knee.y, fx: fx, fy: fy };
  }

  function mix(a, b, t) { return a + (b - a) * t; }
  function clamp(value, low, high) { return value < low ? low : value > high ? high : value; }

  /**
   * Поза: где у каждой ноги колено и стопа.
   *
   * state:
   *   mode        — 'hang' (на нити), 'stand' (на опоре), 'splay' (в паутине)
   *   lean        — сдвиг тела по вертикали: стоящий приседает над стопами
   *   sway        — качание свободных ног, радианы
   *   raiseLeft,
   *   raiseRight  — 0…1: насколько поднята передняя нога
   *   wave        — фаза взмаха поднятой ноги, радианы
   *   hand        — какой передней ногой паук держит вещь: 1 — правой,
   *                 −1 — левой; эта нога не машет
   */
  function pose(form, state) {
    state = state || {};
    var mode = state.mode || 'hang';
    var lean = state.lean || 0;
    var sway = state.sway || 0;
    var wave = state.wave || 0;
    return form.legs.map(function (leg) {
      var ax = leg.anchor[0];
      var ay = leg.anchor[1] + lean;
      var rest = mode === 'stand' ? leg.stand : mode === 'splay' ? leg.splay : leg.hang;
      var fx = rest[0];
      var fy = rest[1];
      if (mode !== 'stand') {
        /* свободные ноги качаются вместе с телом */
        fx += Math.sin(sway + leg.index * 0.9) * 2.2 * leg.side;
        fy += Math.cos(sway * 1.3 + leg.index * 1.7) * 1.6 + lean;
      }
      var up = leg.up ? clamp((leg.side > 0 ? state.raiseRight : state.raiseLeft) || 0, 0, 1) : 0;
      if (up > 0) {
        /* нога, которая держит вещь, поднята ровно; свободная — машет */
        var swing = state.hand === leg.side ? 0 : wave;
        fx = mix(fx, leg.up[0] + Math.sin(swing) * 9 * leg.side, up);
        fy = mix(fy, leg.up[1] + lean + Math.cos(swing * 2) * 3, up);
      }
      var solved = solveLeg(ax, ay, fx, fy, leg.femur, leg.tibia, leg.side, up > 0.5);
      return { index: leg.index, side: leg.side, ax: ax, ay: ay, kx: solved.kx, ky: solved.ky, fx: solved.fx, fy: solved.fy };
    });
  }

  /* Сдвиг модели, при котором в начало координат попадает точка опоры:
     'thread' — место, где крепится нить, 'feet' — земля под стопами. */
  function anchorOffset(form, anchor) {
    return anchor === 'thread' ? form.thread : anchor === 'feet' ? form.ground : 0;
  }

  /* --- цвета ------------------------------------------------------------------ */

  /** Тона паука по одному цвету: тело, тень, блик, ноги; mark — рисунок на брюшке. */
  function tones(hue, saturation, lightness, mark) {
    var hsl = function (s, l) { return 'hsl(' + hue + ' ' + Math.round(s) + '% ' + Math.round(l) + '%)'; };
    return {
      body: hsl(saturation, lightness),
      dark: hsl(saturation, lightness * 0.56),
      light: hsl(saturation * 0.85, Math.min(90, lightness + 24)),
      leg: hsl(saturation * 0.8, lightness * 0.45),
      mark: mark || '#f6f0ff'
    };
  }

  /* Пафнутий остаётся фиолетовым, как во всех лабораторных. */
  var PAFNUTY = { body: '#5b3d8a', dark: '#33205a', light: '#9479cc', leg: '#2f1f4d', mark: '#f6f0ff' };

  var geometry = {
    KINDS: KINDS, BASE_LEGS: BASE_LEGS, PAFNUTY: PAFNUTY,
    shape: shape, solveLeg: solveLeg, pose: pose, anchorOffset: anchorOffset, tones: tones
  };

  /* --- рисунок ---------------------------------------------------------------- */

  var INK = '#1d1528';
  var ZERO = { x: 0, y: 0 };

  function formOf(spec) { return spec.form || (spec.form = shape(spec.kind)); }

  /* Градиенты привязаны к холсту, на котором созданы; у паука они одни на
     весь ролик. */
  function paints(ctx, spec) {
    if (spec.paint && spec.paint.ctx === ctx) { return spec.paint; }
    var form = formOf(spec);
    var a = form.abdomen;
    var ax = -0.24 * a.rx;
    var ay = a.y - 0.4 * a.ry;
    var abdomen = ctx.createRadialGradient(ax, ay, 0, ax, ay, 1.5 * Math.max(a.rx, a.ry));
    abdomen.addColorStop(0, spec.tones.light);
    abdomen.addColorStop(0.55, spec.tones.body);
    abdomen.addColorStop(1, spec.tones.dark);
    var hx = -0.2 * form.head.rx;
    var hy = -0.44 * form.head.ry;
    var head = ctx.createRadialGradient(hx, hy, 0, hx, hy, 1.6 * Math.max(form.head.rx, form.head.ry));
    head.addColorStop(0, spec.tones.light);
    head.addColorStop(0.7, spec.tones.body);
    head.addColorStop(1, spec.tones.dark);
    spec.paint = { ctx: ctx, abdomen: abdomen, head: head };
    return spec.paint;
  }

  function oval(ctx, x, y, rx, ry) {
    ctx.beginPath();
    ctx.ellipse(x, y, rx, ry, 0, 0, TAU);
  }

  /* Мелкие случайные детали паука (шерсть, пятна) — по его собственному зерну. */
  function details(spec) {
    if (spec.details) { return spec.details; }
    var form = formOf(spec);
    var state = (spec.seed || 1) >>> 0;
    var next = function () {
      state = (state * 1664525 + 1013904223) >>> 0;
      return state / 4294967296;
    };
    var hairs = [];
    if (form.fuzz) {
      [[0, form.abdomen.y, form.abdomen.rx, form.abdomen.ry, 30], [0, 0, form.head.rx, form.head.ry, 22]].forEach(function (body) {
        for (var i = 0; i < body[4]; i++) {
          var angle = (i + next() * 0.7) / body[4] * TAU;
          var long = 2.2 + next() * 2.4;
          hairs.push([body[0] + Math.cos(angle) * body[2], body[1] + Math.sin(angle) * body[3],
            Math.cos(angle) * long, Math.sin(angle) * long]);
        }
      });
    }
    var dots = [];
    for (var d = 0; d < 6; d++) {
      var turn = next() * TAU;
      var far = 0.2 + next() * 0.5;
      dots.push([Math.cos(turn) * far * form.abdomen.rx, form.abdomen.y + Math.sin(turn) * far * form.abdomen.ry, 1.6 + next() * 2]);
    }
    spec.details = { hairs: hairs, dots: dots };
    return spec.details;
  }

  function drawPattern(ctx, spec, form) {
    var a = form.abdomen;
    var kx = a.rx / 27;
    var ky = a.ry / 25;
    ctx.fillStyle = spec.tones.mark;
    if (form.pattern === 'cross') {
      /* крест крестовика: три пятна по вертикали и два по бокам */
      ctx.globalAlpha *= 0.93;
      [[0, -15, 2.6], [0, -6, 3.4], [0, 4, 2.6], [-9.5, -6, 2.5], [9.5, -6, 2.5]].forEach(function (spot) {
        oval(ctx, spot[0] * kx, a.y + spot[1] * ky, spot[2] * kx, spot[2] * 1.12 * ky);
        ctx.fill();
      });
      ctx.globalAlpha /= 0.93;
    } else if (form.pattern === 'hourglass') {
      ctx.beginPath();
      ctx.moveTo(-6 * kx, a.y - 9 * ky); ctx.lineTo(6 * kx, a.y - 9 * ky); ctx.lineTo(0, a.y);
      ctx.lineTo(6 * kx, a.y + 9 * ky); ctx.lineTo(-6 * kx, a.y + 9 * ky); ctx.lineTo(0, a.y);
      ctx.closePath();
      ctx.fill();
    } else if (form.pattern === 'stripes') {
      /* полосы огибают брюшко: каждая — сплюснутый овал во всю его ширину */
      for (var j = 0; j < 4; j++) {
        var y = (-0.56 + j * 0.37) * a.ry;
        var half = a.rx * Math.sqrt(Math.max(0, 1 - (y / a.ry) * (y / a.ry))) * 0.96;
        oval(ctx, 0, a.y + y, half, a.ry * 0.085);
        ctx.fill();
      }
    } else if (form.pattern === 'dots') {
      ctx.globalAlpha *= 0.85;
      details(spec).dots.forEach(function (dot) {
        oval(ctx, dot[0], dot[1], dot[2], dot[2]);
        ctx.fill();
      });
      ctx.globalAlpha /= 0.85;
    } else if (form.pattern === 'peacock') {
      ctx.lineWidth = 2.2;
      ['#2bd4c4', '#f2c230', '#e0457b'].forEach(function (colour, ring) {
        ctx.strokeStyle = colour;
        oval(ctx, 0, a.y - a.ry * 0.08, a.rx * (0.72 - ring * 0.22), a.ry * (0.66 - ring * 0.2));
        ctx.stroke();
      });
      oval(ctx, 0, a.y - a.ry * 0.08, a.rx * 0.11, a.ry * 0.11);
      ctx.fill();
    }
  }

  function drawEyes(ctx, form, state) {
    var look = state.look || ZERO;
    var mode = (state.blink || 0) > 0.6 && state.eyes !== 'happy' ? 'closed' : state.eyes || 'open';
    var r = form.eye;
    ctx.lineWidth = 2.1;
    ctx.strokeStyle = INK;
    for (var side = -1; side <= 1; side += 2) {
      var x = side * form.eyeX;
      var y = form.eyeY;
      if (mode === 'happy') {
        /* довольные глаза — дужки вверх */
        ctx.beginPath();
        ctx.moveTo(x - r * 0.8, y + r * 0.24);
        ctx.quadraticCurveTo(x, y - r * 0.95, x + r * 0.8, y + r * 0.24);
        ctx.stroke();
      } else if (mode === 'closed') {
        ctx.beginPath();
        ctx.moveTo(x - r * 0.87, y);
        ctx.quadraticCurveTo(x, y + r * 0.55, x + r * 0.87, y);
        ctx.stroke();
      } else {
        var grow = mode === 'wide' ? 1.14 : 1;
        ctx.fillStyle = '#fff';
        ctx.strokeStyle = 'rgba(20, 10, 40, .25)';
        ctx.lineWidth = 0.7;
        oval(ctx, x, y, r * grow, r * grow);
        ctx.fill();
        ctx.stroke();
        var px = x + clamp(look.x || 0, -1, 1) * r * 0.37;
        var py = y + clamp(look.y || 0, -1, 1) * r * 0.33;
        var pupil = r * (mode === 'wide' ? 0.4 : 0.51);
        ctx.fillStyle = INK;
        oval(ctx, px, py, pupil, pupil);
        ctx.fill();
        ctx.fillStyle = '#fff';
        oval(ctx, px - pupil * 0.34, py - pupil * 0.4, pupil * 0.36, pupil * 0.36);
        ctx.fill();
        ctx.lineWidth = 2.1;
        ctx.strokeStyle = INK;
      }
    }
  }

  function drawMouth(ctx, form, state) {
    var open = clamp(state.mouth || 0, 0, 1);
    var y = form.mouthY;
    if (open < 0.08) {
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      if (state.eyes === 'closed') {
        ctx.moveTo(-4 * form.hx, y - 0.5 * form.hy);
        ctx.quadraticCurveTo(0, y + 0.5 * form.hy, 4 * form.hx, y - 0.5 * form.hy);
      } else {
        ctx.moveTo(-5.5 * form.hx, y - 2 * form.hy);
        ctx.quadraticCurveTo(0, y + 3 * form.hy, 5.5 * form.hx, y - 2 * form.hy);
      }
      ctx.stroke();
      return;
    }
    /* поющий рот: чем громче, тем круглее */
    var rx = (3.7 - 0.5 * open) * form.hx;
    var ry = (0.9 + 3.9 * open) * form.hy;
    ctx.fillStyle = '#3a1526';
    ctx.strokeStyle = INK;
    ctx.lineWidth = 0.9;
    oval(ctx, 0, y + ry * 0.12, rx, ry);
    ctx.fill();
    ctx.stroke();
    if (open > 0.4) {
      ctx.fillStyle = '#d8627c';
      oval(ctx, 0, y + ry * 0.58, rx * 0.6, ry * 0.36);
      ctx.fill();
    }
  }

  /* Гардероб из «Моего говорящего Пафнутия». Вещи рисуются в координатах
     головы крестовика; у других видов они растягиваются вместе с головой. */
  var WEAR = {
    bowtie: function (ctx) {
      ctx.fillStyle = '#c9992b';
      ctx.strokeStyle = '#7a5a14';
      ctx.lineWidth = 0.9;
      ctx.beginPath();
      ctx.moveTo(0, 18); ctx.lineTo(-11, 12.5); ctx.lineTo(-11, 23.5); ctx.closePath();
      ctx.moveTo(0, 18); ctx.lineTo(11, 12.5); ctx.lineTo(11, 23.5); ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#7a5a14';
      oval(ctx, 0, 18, 2.6, 2.6);
      ctx.fill();
    },
    hat: function (ctx) {
      ctx.fillStyle = '#1f1a24';
      oval(ctx, 0, -15.5, 17, 3.6);
      ctx.fill();
      ctx.fillStyle = '#2a2330';
      ctx.fillRect(-11, -37, 22, 21);
      ctx.fillStyle = '#9b2f2f';
      ctx.fillRect(-11, -23, 22, 4.2);
    },
    glasses: function (ctx, form) {
      var x = form.eyeX / form.hx;
      var y = form.eyeY / form.hy;
      var r = form.eye / Math.min(form.hx, form.hy) + 1.3;
      ctx.fillStyle = 'rgba(200, 230, 255, .18)';
      ctx.strokeStyle = '#2a211d';
      ctx.lineWidth = 1.6;
      [-1, 1].forEach(function (side) {
        oval(ctx, side * x, y, r, r);
        ctx.fill();
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(side * (x + r), y - 1.5);
        ctx.lineTo(side * (x + r + 4), y - 3.5);
        ctx.stroke();
      });
    },
    headphones: function (ctx) {
      ctx.strokeStyle = '#2a211d';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(-18, 0);
      ctx.quadraticCurveTo(-18, -21, 0, -21);
      ctx.quadraticCurveTo(18, -21, 18, 0);
      ctx.stroke();
      ctx.fillStyle = '#9b2f2f';
      ctx.beginPath();
      ctx.roundRect(-22.5, -5, 7, 12, 3);
      ctx.roundRect(15.5, -5, 7, 12, 3);
      ctx.fill();
    },
    crown: function (ctx) {
      ctx.fillStyle = '#e2b94a';
      ctx.strokeStyle = '#9c7419';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(-12, -14); ctx.lineTo(-12, -25); ctx.lineTo(-6.5, -20); ctx.lineTo(0, -29);
      ctx.lineTo(6.5, -20); ctx.lineTo(12, -25); ctx.lineTo(12, -14);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#9b2f2f';
      oval(ctx, 0, -19, 1.8, 1.8);
      ctx.fill();
    },
    /* корона Большого паука: приземистая, в пять зубцов. Зубцы в кадр не
       попадают — видны обод с камнями и низ зубцов */
    regalia: function (ctx) {
      ctx.fillStyle = '#e2b94a';
      ctx.strokeStyle = '#9c7419';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(-14.5, -12.5); ctx.lineTo(-14.5, -23); ctx.lineTo(-10.8, -17.6); ctx.lineTo(-7.2, -23);
      ctx.lineTo(-3.6, -17.6); ctx.lineTo(0, -24.5); ctx.lineTo(3.6, -17.6); ctx.lineTo(7.2, -23);
      ctx.lineTo(10.8, -17.6); ctx.lineTo(14.5, -23); ctx.lineTo(14.5, -12.5);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#c4942a';
      ctx.fillRect(-14.5, -15.4, 29, 2.9);
      [[0, '#9b2f2f'], [-8.2, '#2f6f9b'], [8.2, '#2f6f9b']].forEach(function (stone) {
        ctx.fillStyle = stone[1];
        oval(ctx, stone[0], -13.95, 1.15, 1.15);
        ctx.fill();
      });
    },
    /* академическая шапочка: её носят те, кто провожает у самого выхода */
    cap: function (ctx) {
      ctx.fillStyle = '#2a2330';
      ctx.beginPath();
      ctx.moveTo(-9, -17); ctx.lineTo(-9, -12); ctx.quadraticCurveTo(0, -8, 9, -12); ctx.lineTo(9, -17);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = '#1f1a24';
      ctx.beginPath();
      ctx.moveTo(-16, -20); ctx.lineTo(0, -27); ctx.lineTo(16, -20); ctx.lineTo(0, -13);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = '#e2b94a';
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(14, -19.5); ctx.lineTo(16, -9);
      ctx.stroke();
      ctx.fillStyle = '#e2b94a';
      oval(ctx, 16, -8, 1.5, 1.5);
      ctx.fill();
    },
    bow: function (ctx) {
      ctx.fillStyle = '#ff7fa8';
      ctx.strokeStyle = '#c94a76';
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(-9, -15); ctx.quadraticCurveTo(-19, -24, -18, -12); ctx.quadraticCurveTo(-14, -11, -9, -15);
      ctx.moveTo(-9, -15); ctx.quadraticCurveTo(-3, -25, 0, -15); ctx.quadraticCurveTo(-4, -12, -9, -15);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#c94a76';
      oval(ctx, -9, -15, 2, 2);
      ctx.fill();
    }
  };

  /* Лист бумаги со строчками: документ, свиток, реферат. */
  function paper(ctx, x, y, width, height, lines) {
    ctx.fillStyle = '#fbf7ee';
    ctx.strokeStyle = '#b3a792';
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    ctx.rect(x, y, width, height);
    ctx.fill();
    ctx.stroke();
    ctx.lineCap = 'butt';
    for (var i = 0; i < lines; i++) {
      var at = y + 3.4 + i * (height - 6) / Math.max(1, lines - 1 + 0.4);
      /* первая строка — заголовок, последняя короче остальных */
      ctx.strokeStyle = i === 0 ? '#9b2f2f' : '#8d8377';
      ctx.lineWidth = i === 0 ? 1.5 : 1;
      ctx.beginPath();
      ctx.moveTo(x + 2.4, at);
      ctx.lineTo(x + width - (i === 0 ? 6 : i === lines - 1 ? 7.5 : 2.4), at);
      ctx.stroke();
    }
    ctx.lineCap = 'round';
  }

  /* Вещи лабораторных работ: их держат паучата на этажах. Начало координат —
     стопа поднятой ноги; x растёт от тела наружу (у левой ноги рисунок
     отражается — кроме табличек: надпись должна читаться).

       lens      лупа                  — поиск
       page      документ              — то, что ищут и что читают вслух
       card:XX   табличка с надписью   — языки: RU ? DE, EN → DE
       scroll    длинный свиток        — исходный текст
       scissors  ножницы               — из него отбирают главное
       note      короткая записка      — реферат
       horn      рог глашатая          — синтез речи
       mic       микрофон              — распознавание речи

     Наушники — не здесь, а в гардеробе: они надеты, а не в ноге. */
  var PROP_SIZE = 1.45;         /* вещи нарисованы мелко, а разглядеть их нужно из зала */
  var HOLD = {
    lens: function (ctx, side) {
      ctx.scale(side, 1);
      ctx.strokeStyle = '#6b4a2a';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(5, -8);
      ctx.stroke();
      ctx.fillStyle = 'rgba(196, 230, 255, .42)';
      ctx.strokeStyle = '#2f2937';
      ctx.lineWidth = 2.6;
      oval(ctx, 11, -17.5, 10, 10);
      ctx.fill();
      ctx.stroke();
      ctx.strokeStyle = 'rgba(255, 255, 255, .85)';
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.arc(11, -17.5, 6.3, Math.PI * 1.05, Math.PI * 1.5);
      ctx.stroke();
    },
    page: function (ctx, side) {
      ctx.scale(side, 1);
      ctx.rotate(0.14);
      paper(ctx, -6, -27, 18, 24, 6);
    },
    card: function (ctx, side, text) {
      ctx.strokeStyle = '#6b4a2a';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(0, -9);
      ctx.stroke();
      ctx.font = '700 11px "Segoe UI", Arial, sans-serif';
      var width = Math.max(20, ctx.measureText(text).width + 9);
      ctx.fillStyle = '#f5eedd';
      ctx.strokeStyle = '#9b2f2f';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.roundRect(-width / 2, -25, width, 16, 3);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#241d1a';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(text, 0, -16.6);
    },
    scroll: function (ctx, side) {
      ctx.scale(side, 1);
      ctx.rotate(0.1);
      paper(ctx, -5, -33, 15, 30, 9);
      /* валики сверху и снизу */
      ctx.fillStyle = '#d6c49a';
      ctx.strokeStyle = '#a8946a';
      ctx.lineWidth = 0.7;
      ctx.beginPath();
      ctx.roundRect(-7, -35.5, 19, 4, 2);
      ctx.roundRect(-7, -5, 19, 4, 2);
      ctx.fill();
      ctx.stroke();
    },
    scissors: function (ctx, side) {
      ctx.scale(side, 1);
      ctx.strokeStyle = '#c3c7d2';
      ctx.lineWidth = 2.4;
      ctx.beginPath();
      ctx.moveTo(1, -8); ctx.lineTo(10, -28);
      ctx.moveTo(9, -8); ctx.lineTo(0, -28);
      ctx.stroke();
      ctx.fillStyle = '#6d7180';
      oval(ctx, 5, -17, 1.4, 1.4);
      ctx.fill();
      ctx.strokeStyle = '#9b2f2f';
      ctx.lineWidth = 2.2;
      oval(ctx, 0.5, -4.5, 3.4, 3.8);
      ctx.stroke();
      oval(ctx, 9.5, -4.5, 3.4, 3.8);
      ctx.stroke();
    },
    note: function (ctx, side) {
      ctx.scale(side, 1);
      ctx.rotate(-0.08);
      paper(ctx, -5, -18, 16, 14, 3);
    },
    horn: function (ctx, side, text, state) {
      ctx.scale(side, 1);
      ctx.rotate(0.3);
      ctx.fillStyle = '#e2b94a';
      ctx.strokeStyle = '#9c7419';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(-1.5, -1); ctx.lineTo(1.5, -1); ctx.lineTo(4, -17);
      ctx.quadraticCurveTo(6, -24, 12, -27);
      ctx.lineTo(-12, -27);
      ctx.quadraticCurveTo(-6, -24, -4, -17);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#c4942a';
      oval(ctx, 0, -27, 12, 3);
      ctx.fill();
      ctx.stroke();
      /* вымпел */
      ctx.fillStyle = '#9b2f2f';
      ctx.beginPath();
      ctx.moveTo(3.4, -13); ctx.lineTo(12.5, -13.5); ctx.lineTo(10, -9.5); ctx.lineTo(12.5, -5.5); ctx.lineTo(2.2, -6);
      ctx.closePath();
      ctx.fill();
      /* звук идёт, пока паук поёт */
      var loud = clamp(state.mouth || 0, 0, 1);
      if (loud > 0.1) {
        ctx.strokeStyle = 'rgba(255, 236, 190, ' + (0.3 + 0.6 * loud).toFixed(2) + ')';
        ctx.lineWidth = 1.5;
        for (var ring = 0; ring < 3; ring++) {
          ctx.beginPath();
          ctx.arc(0, -29, 7 + ring * 5, Math.PI * 1.22, Math.PI * 1.78);
          ctx.stroke();
        }
      }
    },
    mic: function (ctx, side) {
      ctx.scale(side, 1);
      ctx.rotate(0.2);
      ctx.strokeStyle = '#2a2433';
      ctx.lineWidth = 3.4;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(0, -13);
      ctx.stroke();
      ctx.fillStyle = '#9d98a8';
      ctx.lineWidth = 1.2;
      oval(ctx, 0, -18.5, 5.6, 6.4);
      ctx.fill();
      ctx.stroke();
      ctx.strokeStyle = 'rgba(42, 36, 51, .55)';
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(-5.4, -18.5); ctx.lineTo(5.4, -18.5);
      ctx.moveTo(-4.5, -21.6); ctx.lineTo(4.5, -21.6);
      ctx.moveTo(-4.5, -15.4); ctx.lineTo(4.5, -15.4);
      ctx.moveTo(0, -24.8); ctx.lineTo(0, -12.2);
      ctx.stroke();
      ctx.fillStyle = '#b88a22';
      ctx.fillRect(-2.7, -13.4, 5.4, 2.2);
    }
  };

  /* «card:RU» — вещь card с надписью RU; у остальных вещей надписи нет. */
  function propOf(spec) {
    if (!spec.propParts) {
      var name = String(spec.prop);
      var cut = name.indexOf(':');
      spec.propParts = cut < 0 ? [name, ''] : [name.slice(0, cut), name.slice(cut + 1)];
    }
    return spec.propParts;
  }

  function drawProp(ctx, spec, joint, state) {
    var parts = propOf(spec);
    if (!HOLD[parts[0]]) { return; }
    ctx.save();
    ctx.translate(joint.fx, joint.fy);
    ctx.scale(PROP_SIZE, PROP_SIZE);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    HOLD[parts[0]](ctx, joint.side, parts[1], state);
    ctx.restore();
  }

  /**
   * Рисует паука в его собственных координатах (начало — центр головогруди).
   *
   * spec  — кто это: kind (вид), tones (тона), wear (что надето), prop (что
   *         держит: 'lens', 'card:RU' — см. HOLD), seed
   * state — что он делает: поза (см. pose) и лицо:
   *   mouth — насколько открыт рот, 0…1
   *   look  — взгляд {x, y} от −1 до 1
   *   eyes  — 'open' | 'wide' | 'happy' | 'closed'
   *   blink — 0…1: моргает
   *   baton — дирижёрская палочка в правой передней ноге
   *   hand  — какой ногой держит вещь (см. pose); без этого вещь не рисуется
   */
  function draw(ctx, spec, state) {
    state = state || {};
    var form = formOf(spec);
    var colours = spec.tones;
    var paint = paints(ctx, spec);
    var joints = pose(form, state);
    var thick = form.thick;
    var lean = state.lean || 0;
    var i, joint;

    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    /* ноги рисуются первыми — тело их перекрывает */
    ctx.strokeStyle = colours.leg;
    ctx.lineWidth = 3.2 * thick;
    ctx.beginPath();
    for (i = 0; i < joints.length; i++) {
      joint = joints[i];
      ctx.moveTo(joint.kx, joint.ky);
      ctx.lineTo(joint.fx, joint.fy);
    }
    ctx.stroke();
    ctx.lineWidth = 4.6 * thick;
    ctx.beginPath();
    for (i = 0; i < joints.length; i++) {
      joint = joints[i];
      ctx.moveTo(joint.ax, joint.ay);
      ctx.lineTo(joint.kx, joint.ky);
    }
    ctx.stroke();
    if (form.bands) {
      ctx.strokeStyle = colours.mark;
      ctx.lineWidth = 3.2 * thick;
      ctx.lineCap = 'butt';
      ctx.beginPath();
      for (i = 0; i < joints.length; i++) {
        joint = joints[i];
        ctx.moveTo(mix(joint.kx, joint.fx, 0.3), mix(joint.ky, joint.fy, 0.3));
        ctx.lineTo(mix(joint.kx, joint.fx, 0.55), mix(joint.ky, joint.fy, 0.55));
      }
      ctx.stroke();
      ctx.lineCap = 'round';
    }
    ctx.fillStyle = colours.body;
    ctx.strokeStyle = colours.leg;
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    for (i = 0; i < joints.length; i++) {
      joint = joints[i];
      ctx.moveTo(joint.kx + 2.5 * thick, joint.ky);
      ctx.arc(joint.kx, joint.ky, 2.5 * thick, 0, TAU);
    }
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = colours.leg;
    ctx.beginPath();
    for (i = 0; i < joints.length; i++) {
      joint = joints[i];
      ctx.moveTo(joint.fx + 2.1 * thick, joint.fy);
      ctx.arc(joint.fx, joint.fy, 2.1 * thick, 0, TAU);
    }
    ctx.fill();

    if (state.baton) {
      /* палочка продолжает правую переднюю ногу */
      joint = joints[0];
      var bx = joint.fx - joint.kx;
      var by = joint.fy - joint.ky;
      var bl = Math.sqrt(bx * bx + by * by) || 1;
      ctx.strokeStyle = '#fbf6ea';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(joint.fx, joint.fy);
      ctx.lineTo(joint.fx + bx / bl * 20 + 4, joint.fy + by / bl * 20 - 7);
      ctx.stroke();
    }

    /* брюшко */
    var a = form.abdomen;
    ctx.save();
    ctx.translate(0, lean * 0.6);
    if (form.fuzz) {
      ctx.strokeStyle = colours.body;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      details(spec).hairs.forEach(function (hair) {
        ctx.moveTo(hair[0], hair[1]);
        ctx.lineTo(hair[0] + hair[2], hair[1] + hair[3]);
      });
      ctx.stroke();
    }
    ctx.fillStyle = paint.abdomen;
    oval(ctx, 0, a.y, a.rx, a.ry);
    ctx.fill();
    drawPattern(ctx, spec, form);
    ctx.strokeStyle = 'rgba(255, 255, 255, .32)';
    ctx.lineWidth = 2.6;
    ctx.beginPath();
    ctx.moveTo(-20 * a.rx / 27, a.y - 11 * a.ry / 25);
    ctx.quadraticCurveTo(-15 * a.rx / 27, a.y - 20 * a.ry / 25, -5 * a.rx / 27, a.y - 22 * a.ry / 25);
    ctx.stroke();
    ctx.restore();

    /* головогрудь */
    ctx.save();
    ctx.translate(0, lean);
    ctx.strokeStyle = colours.leg;
    ctx.lineWidth = 3.6 * Math.min(1.3, thick);
    ctx.beginPath();
    ctx.moveTo(-8 * form.hx, 14 * form.hy);
    ctx.quadraticCurveTo(-10 * form.hx, 19 * form.hy, -7 * form.hx, 22 * form.hy);
    ctx.moveTo(8 * form.hx, 14 * form.hy);
    ctx.quadraticCurveTo(10 * form.hx, 19 * form.hy, 7 * form.hx, 22 * form.hy);
    ctx.stroke();
    ctx.fillStyle = paint.head;
    oval(ctx, 0, 0, form.head.rx, form.head.ry);
    ctx.fill();
    ctx.fillStyle = 'rgba(255, 157, 181, .5)';
    oval(ctx, -14.5 * form.hx, 6 * form.hy, 3.6 * form.hx, 2.3 * form.hy);
    ctx.fill();
    oval(ctx, 14.5 * form.hx, 6 * form.hy, 3.6 * form.hx, 2.3 * form.hy);
    ctx.fill();
    var look = state.look || ZERO;
    for (var side = -1; side <= 1; side += 2) {
      var sx = side * 15 * form.hx + (look.x || 0) * 0.6;
      var sy = -8.5 * form.hy + (look.y || 0) * 0.5;
      ctx.fillStyle = INK;
      oval(ctx, sx, sy, form.sideEye, form.sideEye);
      ctx.fill();
      ctx.fillStyle = '#fff';
      oval(ctx, sx - form.sideEye * 0.3, sy - form.sideEye * 0.33, form.sideEye * 0.33, form.sideEye * 0.33);
      ctx.fill();
    }
    drawEyes(ctx, form, state);
    drawMouth(ctx, form, state);
    if (spec.wear && spec.wear.length) {
      ctx.scale(form.hx, form.hy);
      for (i = 0; i < spec.wear.length; i++) {
        if (WEAR[spec.wear[i]]) { WEAR[spec.wear[i]](ctx, form); }
      }
    }
    ctx.restore();

    /* вещь — поверх всего: её держат перед собой */
    if (spec.prop && state.hand) { drawProp(ctx, spec, joints[state.hand > 0 ? 0 : 1], state); }
  }

  /**
   * Тот же паук издалека: без градиентов, колен и рисунка на брюшке, ноги —
   * в одной заранее посчитанной позе. В дальнем хоре таких десятки, и каждый
   * размером с ноготь — подробности там не видны, а считать их дорого.
   */
  function drawTiny(ctx, spec, state) {
    state = state || {};
    var form = formOf(spec);
    var mode = state.mode || 'stand';
    var joints = form.rest[mode] || (form.rest[mode] = pose(form, { mode: mode }));
    var lean = state.lean || 0;
    var a = form.abdomen;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = spec.tones.leg;
    ctx.lineWidth = 4.2 * form.thick;
    ctx.beginPath();
    for (var i = 0; i < joints.length; i++) {
      ctx.moveTo(joints[i].ax, joints[i].ay + lean);
      ctx.lineTo(joints[i].kx, joints[i].ky + lean * 0.5);
      ctx.lineTo(joints[i].fx, joints[i].fy);
    }
    ctx.stroke();
    ctx.fillStyle = spec.tones.body;
    oval(ctx, 0, a.y + lean * 0.6, a.rx, a.ry);
    ctx.fill();
    ctx.fillStyle = spec.tones.light;
    oval(ctx, -a.rx * 0.3, a.y - a.ry * 0.35 + lean * 0.6, a.rx * 0.34, a.ry * 0.3);
    ctx.fill();
    ctx.fillStyle = spec.tones.body;
    oval(ctx, 0, lean, form.head.rx, form.head.ry);
    ctx.fill();
    var look = state.look || ZERO;
    for (var side = -1; side <= 1; side += 2) {
      var x = side * form.eyeX;
      var y = form.eyeY + lean;
      ctx.fillStyle = '#fff';
      oval(ctx, x, y, form.eye, form.eye);
      ctx.fill();
      ctx.fillStyle = INK;
      oval(ctx, x + (look.x || 0) * form.eye * 0.35, y + (look.y || 0) * form.eye * 0.3, form.eye * 0.55, form.eye * 0.55);
      ctx.fill();
    }
    var open = clamp(state.mouth || 0, 0, 1);
    if (open > 0.12) {
      ctx.fillStyle = '#3a1526';
      oval(ctx, 0, form.mouthY + lean, 3.6 * form.hx, (1 + 4 * open) * form.hy);
      ctx.fill();
    }
  }

  /**
   * Ставит паука на сцену: (x, y) — точка опоры (anchor: 'thread' — конец
   * нити, 'feet' — земля под стопами, 'centre' — центр головогруди), scale —
   * размер, state.tilt — наклон вокруг точки опоры (висящий качается).
   */
  function place(ctx, x, y, scale, anchor, spec, state, tiny) {
    var form = formOf(spec);
    ctx.save();
    ctx.translate(x, y);
    if (state && state.tilt) { ctx.rotate(state.tilt); }
    ctx.scale(scale, scale);
    ctx.translate(0, -anchorOffset(form, anchor));
    (tiny ? drawTiny : draw)(ctx, spec, state);
    ctx.restore();
  }

  /** Где на сцене окажутся большие глаза паука: по ним в темноте видны блики. */
  function eyes(x, y, scale, anchor, spec) {
    var form = formOf(spec);
    var dy = (form.eyeY - anchorOffset(form, anchor)) * scale;
    return { left: x - form.eyeX * scale, right: x + form.eyeX * scale, y: y + dy, r: form.eye * scale };
  }

  var api = {
    KINDS: KINDS, PAFNUTY: PAFNUTY, WEAR: WEAR, HOLD: HOLD, geometry: geometry,
    shape: shape, solveLeg: solveLeg, pose: pose, anchorOffset: anchorOffset, tones: tones, formOf: formOf,
    draw: draw, drawTiny: drawTiny, place: place, eyes: eyes
  };

  if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
  global.Spider = api;
})(typeof window !== 'undefined' ? window : globalThis);
