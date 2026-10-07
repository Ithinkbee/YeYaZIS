/* Пафнутий: модель паука для «Глашатая».
 *
 * Модель перенесена из «Слухача» и дополнена для «Моего говорящего
 * Пафнутия»: брови (сердится, грустит), грустный рот, крем на мордочке,
 * шесть вещей гардероба и подъём любой из восьми ног — паук поджимает ту
 * ногу, в которую ткнули.
 *
 * В прошлых работах паук был двумя кружками с восемью чёрточками. Здесь у
 * него брюшко с крестом, как у крестовика, головогрудь с двумя большими и
 * двумя малыми глазами, рот, педипальпы и восемь ног из двух сегментов с
 * коленом. Ноги не нарисованы заранее: у каждой задана точка крепления и
 * длины сегментов, а колено вычисляется по положению стопы (обратная
 * кинематика двух звеньев). Поэтому одна и та же модель висит на нити в углу
 * страницы, шагает по карте, растопыривает ноги в прыжке и поджимает их в
 * воде — меняются только точки, куда ставятся стопы.
 *
 * Файл разделён надвое, как игры прошлых работ: сверху — геометрия без DOM,
 * она экспортируется через module.exports и проверяется в node
 * (tests/pafnuty_model.test.js); снизу — построение и обновление SVG.
 */

(function (global) {
  'use strict';

  /* --- геометрия ---------------------------------------------------------- */

  var VIEW = 120;               /* модель вписана в квадрат 120 × 120 */
  var CENTER = 60;              /* ось симметрии */
  var GROUND = 96;              /* на этой высоте стоят стопы */

  /* Ноги правой стороны, от передней к задней; левые — их отражение.
     anchor — крепление к головогруди, femur и tibia — длины сегментов,
     stand, hang, air, swim — где стопа стоя, вися на нити, в прыжке и в воде;
     up — куда передняя нога поднимается, когда паук прислушивается.
     Чем дальше нога от головы, тем она короче: стоя ноги ложатся вложенными
     дугами, расходятся веером и не пересекаются. */
  var RIGHT_LEGS = [
    { anchor: [74, 62], femur: 26, tibia: 40, stand: [116, GROUND], hang: [110, 90], air: [118, 30], swim: [114, 46], up: [116, 36] },
    { anchor: [77, 67], femur: 21, tibia: 32, stand: [104, GROUND], hang: [101, 98], air: [124, 60], swim: [118, 66] },
    { anchor: [77, 73], femur: 16, tibia: 25, stand: [92, GROUND], hang: [91, 102], air: [112, 94], swim: [108, 88] },
    { anchor: [74, 78], femur: 11, tibia: 18, stand: [80, GROUND], hang: [80, 102], air: [92, 104], swim: [90, 100] }
  ];

  /* Походка: ноги ходят двумя четвёрками, как у настоящих пауков, — пока
     одна четвёрка стоит, другая переносится. STANCE — доля шага на опоре. */
  var STANCE = 0.6;
  var STRIDE = 13;              /* размах шага стопы */
  var LIFT = 9;                 /* на сколько стопа поднимается при переносе */

  function legs() {
    var all = [];
    RIGHT_LEGS.forEach(function (leg, index) {
      [1, -1].forEach(function (side) {
        var mirror = function (point) { return [CENTER + side * (point[0] - CENTER), point[1]]; };
        all.push({
          index: index, side: side, femur: leg.femur, tibia: leg.tibia,
          anchor: mirror(leg.anchor), stand: mirror(leg.stand), hang: mirror(leg.hang),
          air: mirror(leg.air), swim: mirror(leg.swim), up: leg.up ? mirror(leg.up) : null,
          /* соседние ноги одной стороны и парные ноги разных сторон — в противофазе */
          phase: ((index + (side > 0 ? 0 : 1)) % 2) * 0.5 + index * 0.04
        });
      });
    });
    return all;
  }

  var LEGS = legs();

  /**
   * Колено ноги из двух сегментов: крепление (ax, ay), стопа (fx, fy).
   * Решений два — колено по одну или по другую сторону от прямой «крепление —
   * стопа». Обычно выбирается верхнее: нога встаёт дугой. У ноги, поднятой
   * вверх (raised), колено, наоборот, отводится в сторону — иначе оно ушло бы
   * за брюшко, и нога казалась бы прямой палкой. Если до стопы не дотянуться,
   * нога вытягивается в прямую, и стопа возвращается на её конец.
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

  /**
   * Смещение стопы в цикле шага: phase — фаза ноги от 0 до 1. На опоре стопа
   * едет назад относительно тела (тело идёт вперёд, стопа стоит на земле), в
   * переносе — поднимается и летит вперёд.
   */
  function gait(phase) {
    phase = phase - Math.floor(phase);
    if (phase < STANCE) {
      return { dx: STRIDE * (0.5 - phase / STANCE), dy: 0, grounded: true };
    }
    var swing = (phase - STANCE) / (1 - STANCE);
    return { dx: STRIDE * (swing - 0.5), dy: -LIFT * Math.sin(Math.PI * swing), grounded: false };
  }

  function mix(a, b, t) { return a + (b - a) * t; }

  /**
   * Поза: где у каждой ноги колено и стопа.
   *
   * options:
   *   mode    — 'hang' (на нити), 'stand' (на земле), 'swim' (в воде)
   *   walk    — фаза шага; число растёт, пока паук идёт
   *   moving  — 0…1: насколько выражена походка (0 — стоит)
   *   air     — 0…1: насколько ноги растопырены в прыжке
   *   raise   — 0…1: насколько подняты передние ноги (паук прислушивается)
   *   facing  — −1…1: куда повёрнута голова (ноги крепятся к ней)
   *   lean    — сдвиг тела по вертикали (приседание перед прыжком, качание)
   *   sway    — качание висящих ног, радианы
   *   ground  — функция: смещение от оси → высота земли под стопой
   *             относительно GROUND (для неровной карты)
   *   lift    — массив из восьми чисел 0…1: насколько поджата каждая нога
   *             (порядок — как в LEGS)
   */
  function pose(options) {
    options = options || {};
    var mode = options.mode || 'hang';
    var air = Math.max(0, Math.min(1, options.air || 0));
    var raise = Math.max(0, Math.min(1, options.raise || 0));
    var moving = Math.max(0, Math.min(1, options.moving || 0));
    var facing = Math.max(-1, Math.min(1, options.facing || 0));
    var lean = options.lean || 0;
    var sway = options.sway || 0;
    var walk = options.walk || 0;
    var headShift = facing * 5;
    var lift = options.lift || [];
    var result = [];

    LEGS.forEach(function (leg, number) {
      var ax = leg.anchor[0] + headShift;
      var ay = leg.anchor[1] + lean;
      var rest = mode === 'stand' ? leg.stand : mode === 'swim' ? leg.swim : leg.hang;
      var fx = rest[0];
      var fy = rest[1];
      var grounded = mode === 'stand';

      if (mode === 'stand') {
        var step = gait(walk * (facing < 0 ? -1 : 1) + leg.phase);
        fx += step.dx * moving;
        fy += step.dy * moving;
        grounded = step.grounded || moving < 0.5;
        if (options.ground) {
          /* стопа ищет землю под собой; над обрывом нога просто свисает */
          var drop = options.ground(fx - CENTER);
          fy += Math.max(-26, Math.min(16, drop));
        }
      } else {
        /* висящие и плывущие ноги качаются вместе с телом */
        fx += Math.sin(sway + leg.index * 0.9) * 2.2 * leg.side;
        fy += Math.cos(sway * 1.3 + leg.index * 1.7) * 1.6 + lean;
      }
      if (raise > 0 && leg.up) {
        fx = mix(fx, leg.up[0] + headShift, raise);
        fy = mix(fy, leg.up[1] + lean, raise);
        grounded = false;
      }
      if (air > 0) {
        fx = mix(fx, leg.air[0] + headShift, air);
        fy = mix(fy, leg.air[1] + lean, air);
        grounded = grounded && air < 0.5;
      }

      var tuck = Math.max(0, Math.min(1, lift[number] || 0));
      if (tuck > 0) {
        /* поджатая нога: стопа подтягивается вверх и к телу */
        fx = mix(fx, ax + leg.side * leg.femur * 0.75, tuck);
        fy = mix(fy, ay - leg.tibia * 0.55, tuck);
        grounded = false;
      }

      /* передняя нога, поднятая выше крепления, сгибается коленом в сторону */
      var raised = (leg.index === 0 && Math.max(air, raise) > 0.5) || tuck > 0.5;
      var solved = solveLeg(ax, ay, fx, fy, leg.femur, leg.tibia, leg.side, raised);
      result.push({
        index: leg.index, side: leg.side, grounded: grounded,
        ax: ax, ay: ay, kx: solved.kx, ky: solved.ky, fx: solved.fx, fy: solved.fy
      });
    });
    return result;
  }

  var geometry = {
    VIEW: VIEW, CENTER: CENTER, GROUND: GROUND, LEGS: LEGS, STANCE: STANCE, STRIDE: STRIDE, LIFT: LIFT,
    solveLeg: solveLeg, gait: gait, pose: pose
  };

  /* Вне браузера файл подключается тестами: рисунок тогда не нужен. */
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = geometry;
    return;
  }

  /* --- рисунок ------------------------------------------------------------ */

  var SVG = 'http://www.w3.org/2000/svg';
  var counter = 0;              /* у каждого экземпляра свои идентификаторы градиентов */

  function node(tag, attributes, parent) {
    var element = document.createElementNS(SVG, tag);
    Object.keys(attributes || {}).forEach(function (name) { element.setAttribute(name, attributes[name]); });
    if (parent) { parent.appendChild(element); }
    return element;
  }

  function round(value) { return Math.round(value * 100) / 100; }

  /* Выражения глаз, рта и бровей. eyes: open | wide | happy | closed | dizzy;
     mouth: smile | talk | oh | flat | sad; brows: angry | sad. */
  var MOODS = {
    idle: { eyes: 'open', mouth: 'smile' },
    listening: { eyes: 'open', mouth: 'flat' },
    hearing: { eyes: 'wide', mouth: 'oh' },
    thinking: { eyes: 'open', mouth: 'flat' },
    speaking: { eyes: 'open', mouth: 'talk' },
    startled: { eyes: 'wide', mouth: 'oh' },
    happy: { eyes: 'happy', mouth: 'smile' },
    dizzy: { eyes: 'dizzy', mouth: 'flat' },
    sleeping: { eyes: 'closed', mouth: 'flat' },
    angry: { eyes: 'open', mouth: 'flat', brows: 'angry' },
    sad: { eyes: 'open', mouth: 'sad', brows: 'sad' },
    disgusted: { eyes: 'closed', mouth: 'sad', brows: 'angry' },
    sleepy: { eyes: 'closed', mouth: 'oh' },
    chewing: { eyes: 'happy', mouth: 'talk' },
    laughing: { eyes: 'happy', mouth: 'talk' }
  };

  /**
   * Строит паука.
   *
   * options.mode — 'hang' или 'stand': от него зависит рамка рисунка (висящему
   * нужна нить над головой). Возвращает объект с методами:
   *   set(params)  — поза (см. pose) и взгляд: look {x, y} от −1 до 1
   *   mood(name)   — выражение: idle, listening, hearing, thinking, speaking,
   *                  startled, happy, dizzy, sleeping
   *   talk(amount) — насколько открыт рот, 0…1 (для режима speaking)
   *   blink()      — моргнуть
   */
  function create(options) {
    options = options || {};
    var mode = options.mode || 'hang';
    var id = 'pf' + (++counter);
    var view = mode === 'hang' ? '0 -34 120 142' : '0 14 120 90';
    var svg = node('svg', { viewBox: view, 'class': 'pafnuty pafnuty-' + mode, 'aria-hidden': 'true' });

    var defs = node('defs', {}, svg);
    var abdomenFill = node('radialGradient', { id: id + 'a', cx: '38%', cy: '30%', r: '75%' }, defs);
    node('stop', { offset: '0', style: 'stop-color: var(--pf-light)' }, abdomenFill);
    node('stop', { offset: '0.55', style: 'stop-color: var(--pf-body)' }, abdomenFill);
    node('stop', { offset: '1', style: 'stop-color: var(--pf-dark)' }, abdomenFill);
    var headFill = node('radialGradient', { id: id + 'h', cx: '40%', cy: '28%', r: '80%' }, defs);
    node('stop', { offset: '0', style: 'stop-color: var(--pf-light)' }, headFill);
    node('stop', { offset: '0.7', style: 'stop-color: var(--pf-body)' }, headFill);
    node('stop', { offset: '1', style: 'stop-color: var(--pf-dark)' }, headFill);

    var thread = mode === 'hang'
      ? node('line', { x1: CENTER, y1: -34, x2: CENTER, y2: 22, 'class': 'pf-thread' }, svg) : null;
    var all = node('g', { 'class': 'pf-all' }, svg);

    /* ноги рисуются первыми — тело их перекрывает */
    var legLayer = node('g', { 'class': 'pf-legs' }, all);
    var legNodes = LEGS.map(function () {
      var group = node('g', { 'class': 'pf-leg' }, legLayer);
      return {
        tibia: node('path', { 'class': 'pf-tibia' }, group),
        femur: node('path', { 'class': 'pf-femur' }, group),
        knee: node('circle', { r: 2.5, 'class': 'pf-knee' }, group),
        foot: node('circle', { r: 2.1, 'class': 'pf-foot' }, group)
      };
    });

    var abdomen = node('g', { 'class': 'pf-abdomen' }, all);
    node('ellipse', { cx: CENTER, cy: 44, rx: 27, ry: 25, fill: 'url(#' + id + 'a)' }, abdomen);
    /* крест крестовика: три пятна по вертикали и два по бокам */
    [[60, 29, 2.6], [60, 38, 3.4], [60, 48, 2.6], [50.5, 38, 2.5], [69.5, 38, 2.5]].forEach(function (spot) {
      node('ellipse', { cx: spot[0], cy: spot[1], rx: spot[2], ry: spot[2] * 1.12, 'class': 'pf-cross' }, abdomen);
    });
    node('path', { d: 'M40 33 Q45 24 55 22', 'class': 'pf-shine' }, abdomen);

    var head = node('g', { 'class': 'pf-head' }, all);
    /* педипальпы — короткие «усики» у рта */
    node('path', { d: 'M52 84 q-2 5 1 8', 'class': 'pf-palp' }, head);
    node('path', { d: 'M68 84 q2 5 -1 8', 'class': 'pf-palp' }, head);
    node('ellipse', { cx: CENTER, cy: 70, rx: 19, ry: 17, fill: 'url(#' + id + 'h)' }, head);
    node('ellipse', { cx: 45.5, cy: 76, rx: 3.6, ry: 2.3, 'class': 'pf-cheek' }, head);
    node('ellipse', { cx: 74.5, cy: 76, rx: 3.6, ry: 2.3, 'class': 'pf-cheek' }, head);

    var face = node('g', { 'class': 'pf-face' }, head);
    var smallEyes = [[45, 61.5], [75, 61.5]].map(function (at) {
      var group = node('g', { 'class': 'pf-eye-small' }, face);
      node('circle', { cx: at[0], cy: at[1], r: 2.4, 'class': 'pf-pupil' }, group);
      node('circle', { cx: at[0] - 0.7, cy: at[1] - 0.8, r: 0.8, 'class': 'pf-glint' }, group);
      return group;
    });
    var eyes = [[52.5, 68], [67.5, 68]].map(function (at) {
      var group = node('g', { 'class': 'pf-eye' }, face);
      group.style.transformOrigin = at[0] + 'px ' + at[1] + 'px';
      var open = node('g', { 'class': 'pf-eye-open' }, group);
      node('circle', { cx: at[0], cy: at[1], r: 6.3, 'class': 'pf-white' }, open);
      var pupil = node('g', { 'class': 'pf-pupil-group' }, open);
      node('circle', { cx: at[0], cy: at[1], r: 3.2, 'class': 'pf-pupil' }, pupil);
      node('circle', { cx: at[0] - 1.1, cy: at[1] - 1.3, r: 1.15, 'class': 'pf-glint' }, pupil);
      /* довольные глаза — дужки, головокружение — крестики */
      node('path', {
        d: 'M' + (at[0] - 5) + ' ' + (at[1] + 1.5) + ' Q' + at[0] + ' ' + (at[1] - 6) + ' ' + (at[0] + 5) + ' ' + (at[1] + 1.5),
        'class': 'pf-eye-happy'
      }, group);
      node('path', {
        d: 'M' + (at[0] - 4) + ' ' + (at[1] - 4) + ' l8 8 M' + (at[0] + 4) + ' ' + (at[1] - 4) + ' l-8 8',
        'class': 'pf-eye-dizzy'
      }, group);
      node('path', {
        d: 'M' + (at[0] - 5.5) + ' ' + at[1] + ' Q' + at[0] + ' ' + (at[1] + 3.5) + ' ' + (at[0] + 5.5) + ' ' + at[1],
        'class': 'pf-eye-closed'
      }, group);
      return { group: group, pupil: pupil };
    });
    /* брови: сердитые сходятся к переносице, грустные — домиком */
    var brows = node('g', { 'class': 'pf-brows' }, face);
    var browLeft = node('path', { 'class': 'pf-brow' }, brows);
    var browRight = node('path', { 'class': 'pf-brow' }, brows);
    var smile = node('path', { d: 'M54.5 78.5 Q60 83.5 65.5 78.5', 'class': 'pf-mouth pf-mouth-smile' }, face);
    node('path', { d: 'M55 81.5 Q60 77.2 65 81.5', 'class': 'pf-mouth pf-mouth-sad' }, face);
    var flat = node('path', { d: 'M56 80 Q60 81 64 80', 'class': 'pf-mouth pf-mouth-flat' }, face);
    var open = node('ellipse', { cx: CENTER, cy: 80.5, rx: 3.4, ry: 2.4, 'class': 'pf-mouth-open' }, face);

    /* крем от торта: клякса на мордочке */
    var cream = node('g', { 'class': 'pf-cream' }, head);
    node('path', { d: 'M44 66 q4 -9 10 -4 q4 -7 10 -1 q6 -6 9 2 q5 2 2 8 q3 6 -4 7 q-4 6 -10 2 q-6 5 -10 -1 q-8 1 -7 -6 q-5 -3 0 -7z' }, cream);
    node('ellipse', { cx: 52, cy: 84, rx: 2.2, ry: 3.4 }, cream);
    node('ellipse', { cx: 67, cy: 86, rx: 1.8, ry: 2.8 }, cream);

    /* гардероб: вещи рисуются в группе головы и двигаются вместе с ней */
    var wear = {};
    function item(name, parts) {
      var group = node('g', { 'class': 'pf-acc pf-acc-' + name }, head);
      parts.forEach(function (part) { node(part[0], part[1], group); });
      wear[name] = group;
    }
    item('hat', [
      ['ellipse', { cx: 60, cy: 54.5, rx: 17, ry: 3.6, fill: '#1f1a24' }],
      ['rect', { x: 49, y: 33, width: 22, height: 21, rx: 2, fill: '#2a2330' }],
      ['rect', { x: 49, y: 47, width: 22, height: 4.2, fill: '#9b2f2f' }]
    ]);
    item('glasses', [
      ['circle', { cx: 52.5, cy: 68, r: 7.6, fill: 'rgba(200,230,255,.18)', stroke: '#2a211d', 'stroke-width': 1.6 }],
      ['circle', { cx: 67.5, cy: 68, r: 7.6, fill: 'rgba(200,230,255,.18)', stroke: '#2a211d', 'stroke-width': 1.6 }],
      ['path', { d: 'M59.9 67.2 Q60 65.6 60.1 67.2', stroke: '#2a211d', 'stroke-width': 1.6, fill: 'none' }],
      ['path', { d: 'M44.9 66.5 L41 64.5 M75.1 66.5 L79 64.5', stroke: '#2a211d', 'stroke-width': 1.4 }]
    ]);
    item('bowtie', [
      ['path', { d: 'M60 88 L51 83.5 L51 92.5 Z M60 88 L69 83.5 L69 92.5 Z', fill: '#b88a22', stroke: '#7a5a14', 'stroke-width': .8 }],
      ['circle', { cx: 60, cy: 88, r: 2.2, fill: '#7a5a14' }]
    ]);
    item('headphones', [
      ['path', { d: 'M42 70 Q42 49 60 49 Q78 49 78 70', stroke: '#2a211d', 'stroke-width': 3, fill: 'none' }],
      ['rect', { x: 37.5, y: 65, width: 7, height: 12, rx: 3, fill: '#9b2f2f' }],
      ['rect', { x: 75.5, y: 65, width: 7, height: 12, rx: 3, fill: '#9b2f2f' }]
    ]);
    item('crown', [
      ['path', { d: 'M48 56 L48 45 L53.5 50 L60 41 L66.5 50 L72 45 L72 56 Z', fill: '#e2b94a', stroke: '#9c7419', 'stroke-width': 1 }],
      ['circle', { cx: 60, cy: 51, r: 1.8, fill: '#9b2f2f' }]
    ]);
    item('cap', [
      ['path', { d: 'M44 50 L60 43 L76 50 L60 57 Z', fill: '#1f1a24' }],
      ['path', { d: 'M51 53 L51 58 Q60 62 69 58 L69 53', fill: '#2a2330' }],
      ['path', { d: 'M74 50.5 L76 61', stroke: '#e2b94a', 'stroke-width': 1.2 }],
      ['circle', { cx: 76, cy: 62, r: 1.5, fill: '#e2b94a' }]
    ]);

    var current = { mode: mode };
    var moodName = '';
    var lastJoints = [];

    function draw() {
      var joints = pose(current);
      lastJoints = joints;
      joints.forEach(function (joint, i) {
        var view = legNodes[i];
        view.femur.setAttribute('d', 'M' + round(joint.ax) + ' ' + round(joint.ay) + 'L' + round(joint.kx) + ' ' + round(joint.ky));
        view.tibia.setAttribute('d', 'M' + round(joint.kx) + ' ' + round(joint.ky) + 'L' + round(joint.fx) + ' ' + round(joint.fy));
        view.knee.setAttribute('cx', round(joint.kx));
        view.knee.setAttribute('cy', round(joint.ky));
        view.foot.setAttribute('cx', round(joint.fx));
        view.foot.setAttribute('cy', round(joint.fy));
      });
      var facing = Math.max(-1, Math.min(1, current.facing || 0));
      var lean = current.lean || 0;
      /* голова смотрит вперёд, брюшко отстаёт — получается вид в три четверти */
      head.setAttribute('transform', 'translate(' + round(facing * 5) + ' ' + round(lean) + ')');
      abdomen.setAttribute('transform', 'translate(' + round(-facing * 4) + ' ' + round(lean * 0.6) + ')');
      var look = current.look || { x: 0, y: 0 };
      var lx = Math.max(-1, Math.min(1, (look.x || 0) + facing * 0.7)) * 2.3;
      var ly = Math.max(-1, Math.min(1, look.y || 0)) * 2.1;
      eyes.forEach(function (eye) { eye.pupil.setAttribute('transform', 'translate(' + round(lx) + ' ' + round(ly) + ')'); });
      smallEyes.forEach(function (eye) { eye.setAttribute('transform', 'translate(' + round(lx * 0.25) + ' ' + round(ly * 0.25) + ')'); });
      if (thread) { thread.setAttribute('y2', round(22 + lean * 0.6)); }
    }

    var api = {
      el: svg,
      set: function (params) {
        Object.keys(params || {}).forEach(function (key) { current[key] = params[key]; });
        draw();
        return api;
      },
      mood: function (name) {
        if (!MOODS[name] || name === moodName) { return api; }
        moodName = name;
        svg.setAttribute('data-eyes', MOODS[name].eyes);
        svg.setAttribute('data-mouth', MOODS[name].mouth);
        svg.setAttribute('data-mood', name);
        var browKind = MOODS[name].brows || '';
        svg.setAttribute('data-brows', browKind);
        if (browKind === 'angry') {
          browLeft.setAttribute('d', 'M45.5 58.5 L57 62.5');
          browRight.setAttribute('d', 'M74.5 58.5 L63 62.5');
        } else if (browKind === 'sad') {
          browLeft.setAttribute('d', 'M46 61.5 L57 58');
          browRight.setAttribute('d', 'M74 61.5 L63 58');
        }
        return api;
      },
      talk: function (amount) {
        amount = Math.max(0, Math.min(1, amount));
        open.setAttribute('ry', round(0.8 + 2.9 * amount));
        open.setAttribute('rx', round(3.6 - 0.7 * amount));
        return api;
      },
      blink: function () {
        svg.classList.add('pf-blink');
        setTimeout(function () { svg.classList.remove('pf-blink'); }, 140);
        return api;
      },
      moodName: function () { return moodName; },
      /* суставы ног последней позы — по ним страница узнаёт, в какую ногу ткнули */
      joints: function () { return lastJoints; },
      wear: function (name, on) {
        if (wear[name]) { wear[name].classList.toggle('on', !!on); }
        return api;
      },
      cream: function (on) { svg.classList.toggle('pf-creamed', !!on); return api; },
      angry: function (on) { svg.classList.toggle('pf-angry', !!on); return api; }
    };
    void smile;
    void cream;
    void flat;
    api.mood(options.mood || 'idle');
    api.set({});
    return api;
  }

  global.Pafnuty = { create: create, geometry: geometry, MOODS: MOODS };
})(typeof window !== 'undefined' ? window : globalThis);
