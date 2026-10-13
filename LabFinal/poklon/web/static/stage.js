/* Сцена: рисует кадр ролика для секунды t.
 *
 * Кадр — функция времени и больше ничего: в сцене нет состояния, которое
 * копится от кадра к кадру. Поэтому ролик можно ставить на паузу, мотать
 * вперёд и назад и снимать любой кадр — он всегда выйдет одинаковым.
 *
 * Сцена — 1600 × 900 единиц; x отсчитывается от оси шахты (−800…800), y —
 * сверху вниз. Высота h попадает на экран в y = 450 − (h − высота кабины)·p,
 * где p — глубина слоя: стены шахты — 1, Большой паук в глубине зала — 0,25,
 * балки перед самой кабиной — 2,3.
 *
 * Слои снизу вверх: глубина зала → Большой паук и дальний хор → стена шахты
 * с проёмом зала → перекрытия, паутины, полки → пауки → колонны → Пафнутий
 * → свет → блики, лучи, пыль → балки переднего плана → кабина лифта.
 *
 * Свет сделан отдельным маленьким холстом: на нём тёмный фон и светлые
 * пятна ламп, и он умножается на готовую картинку. Так в шахте темно между
 * лампами, а в зале свет включается разом — на вступлении хора.
 */

(function (global) {
  'use strict';

  var Score = global.Score;
  var Spider = global.Spider;
  var Troupe = global.Troupe;

  var W = 1600;
  var H = 900;
  var HALF = Troupe.HALF;
  var WALL = Troupe.WALL;
  var FAR = Troupe.FAR;
  var TAU = Math.PI * 2;
  var TILE = 1200;              /* высота куска стены, который повторяется */
  var NEAR = 2.3;               /* глубина балок переднего плана */
  var LIGHT_SCALE = 4;          /* холст света вчетверо мельче сцены */

  var clamp = Score.clamp;
  var mix = Score.mix;
  var ease = Score.ease;

  function easeOutBack(t) {
    t = clamp(t, 0, 1) - 1;
    return 1 + t * t * (2.2 * t + 1.2);
  }

  /* Псевдослучайное число по номеру: для мелочей, которым не нужен общий генератор. */
  function hash(n) {
    var x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
    return x - Math.floor(x);
  }

  function sheet(width, height) {
    var canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(width));
    canvas.height = Math.max(1, Math.round(height));
    return canvas;
  }

  /* --- фактуры ---------------------------------------------------------------- */

  /* Задняя стена шахты: бетонные плиты, направляющие лифта, кабели. Кусок
     высотой TILE стыкуется сам с собой. Цвета — «при полном свете»: темноту
     добавляет холст света. */
  function wallTexture(k) {
    var canvas = sheet(WALL * 2 * k, TILE * k);
    var g = canvas.getContext('2d');
    var rng = Score.random(11);
    g.scale(k, k);
    g.fillStyle = '#6f6889';
    g.fillRect(0, 0, WALL * 2, TILE);
    for (var row = 0; row < 6; row++) {
      for (var col = -1; col < 5; col++) {
        var x = col * 320 + (row % 2 ? 160 : 0);
        var y = row * 200;
        g.fillStyle = 'hsl(' + (252 + rng() * 10) + ' ' + (13 + rng() * 4) + '% ' + (52 + rng() * 9) + '%)';
        g.fillRect(x + 2, y + 2, 316, 196);
        g.fillStyle = 'rgba(255, 255, 255, .13)';
        g.fillRect(x + 2, y + 2, 316, 3);
        g.fillRect(x + 2, y + 2, 3, 196);
        g.fillStyle = 'rgba(20, 14, 40, .3)';
        g.fillRect(x + 2, y + 194, 316, 4);
        g.fillRect(x + 315, y + 2, 3, 196);
        g.fillStyle = 'rgba(30, 24, 50, .55)';
        [[16, 16], [304, 16], [16, 184], [304, 184]].forEach(function (bolt) {
          g.beginPath();
          g.arc(x + bolt[0], y + bolt[1], 4, 0, TAU);
          g.fill();
        });
      }
    }
    /* потёки */
    for (var s = 0; s < 16; s++) {
      var sx = rng() * WALL * 2;
      var sy = 40 + rng() * (TILE - 420);
      var long = 120 + rng() * 240;
      var stain = g.createLinearGradient(0, sy, 0, sy + long);
      stain.addColorStop(0, 'rgba(30, 22, 52, .26)');
      stain.addColorStop(1, 'rgba(30, 22, 52, 0)');
      g.fillStyle = stain;
      g.fillRect(sx, sy, 8 + rng() * 22, long);
    }
    /* направляющие, по которым ходит противовес */
    [WALL - 255, WALL + 255].forEach(function (rail) {
      g.fillStyle = '#373246';
      g.fillRect(rail - 9, 0, 18, TILE);
      g.fillStyle = 'rgba(255, 255, 255, .16)';
      g.fillRect(rail - 9, 0, 4, TILE);
      g.fillStyle = '#2a2637';
      for (var bracket = 50; bracket < TILE; bracket += 200) { g.fillRect(rail - 20, bracket, 40, 12); }
    });
    /* кабели */
    [[WALL - 480, '#2b2634', 5], [WALL - 469, '#3b2a2a', 4], [WALL - 459, '#2b2634', 3], [WALL + 470, '#2b2634', 4]].forEach(function (cable) {
      g.fillStyle = cable[1];
      g.fillRect(cable[0], 0, cable[2], TILE);
    });
    g.fillStyle = '#4a4458';
    for (var clampY = 110; clampY < TILE; clampY += 300) { g.fillRect(WALL - 486, clampY, 36, 9); }
    return canvas;
  }

  /* Левая колонна (правая — её отражение). */
  function pillarTexture(k) {
    var width = W / 2 - WALL;
    var canvas = sheet(width * k, TILE * k);
    var g = canvas.getContext('2d');
    g.scale(k, k);
    var steel = g.createLinearGradient(0, 0, width, 0);
    steel.addColorStop(0, '#2c2838');
    steel.addColorStop(0.55, '#4b4560');
    steel.addColorStop(0.9, '#3a3549');
    steel.addColorStop(1, '#1f1c29');
    g.fillStyle = steel;
    g.fillRect(0, 0, width, TILE);
    g.fillStyle = 'rgba(255, 255, 255, .1)';
    g.fillRect(width * 0.5, 0, 3, TILE);
    /* труба с муфтами */
    g.fillStyle = '#8c5a44';
    g.fillRect(34, 0, 16, TILE);
    g.fillStyle = 'rgba(255, 220, 190, .28)';
    g.fillRect(37, 0, 4, TILE);
    g.fillStyle = '#5f3c2e';
    for (var joint = 90; joint < TILE; joint += 400) { g.fillRect(30, joint, 24, 14); }
    g.fillStyle = 'rgba(20, 16, 30, .7)';
    for (var rivet = 25; rivet < TILE; rivet += 50) {
      g.beginPath();
      g.arc(width - 16, rivet, 3.4, 0, TAU);
      g.arc(96, rivet, 3.4, 0, TAU);
      g.fill();
    }
    return canvas;
  }

  /* Табличка этажа — в цветах лабораторных: кремовая страница, бордовый
     знак с золотой чертой, название и чем занималась работа. */
  function signSprite(lab, k) {
    var width = 452;
    var height = 164;
    var canvas = sheet(width * k, height * k);
    var g = canvas.getContext('2d');
    g.scale(k, k);
    g.fillStyle = '#2a2433';
    g.beginPath();
    g.roundRect(0, 0, width, height, 12);
    g.fill();
    g.fillStyle = '#f5eedd';
    g.beginPath();
    g.roundRect(5, 5, width - 10, height - 10, 8);
    g.fill();
    g.strokeStyle = '#b88a22';
    g.lineWidth = 2;
    g.beginPath();
    g.roundRect(11, 11, width - 22, height - 22, 5);
    g.stroke();
    /* знак с номером — как буква в шапке каждой лабораторной */
    var mark = g.createLinearGradient(24, 30, 128, 134);
    mark.addColorStop(0, '#9b2f2f');
    mark.addColorStop(1, '#772222');
    g.fillStyle = mark;
    g.beginPath();
    g.roundRect(26, 30, 104, 104, 12);
    g.fill();
    g.fillStyle = '#b88a22';
    g.fillRect(26, 124, 104, 6);
    g.fillStyle = '#fff';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    var size = 74;
    g.font = '700 ' + size + 'px "Segoe UI", Arial, sans-serif';
    while (size > 30 && g.measureText(lab.number).width > 86) {
      size -= 4;
      g.font = '700 ' + size + 'px "Segoe UI", Arial, sans-serif';
    }
    g.fillText(lab.number, 78, 78);
    g.textAlign = 'left';
    g.textBaseline = 'alphabetic';
    g.fillStyle = '#9b2f2f';
    g.font = '600 15px "Segoe UI", Arial, sans-serif';
    g.fillText('ЛАБОРАТОРНАЯ РАБОТА', 150, 50);
    g.fillStyle = '#241d1a';
    size = 38;
    g.font = '700 ' + size + 'px "Segoe UI", Arial, sans-serif';
    while (size > 18 && g.measureText(lab.name).width > 280) {
      size -= 2;
      g.font = '700 ' + size + 'px "Segoe UI", Arial, sans-serif';
    }
    g.fillText(lab.name, 150, 92);
    g.fillStyle = '#776c64';
    size = 21;
    g.font = size + 'px "Segoe UI", Arial, sans-serif';
    while (size > 12 && g.measureText(lab.about).width > 280) {
      size -= 1;
      g.font = size + 'px "Segoe UI", Arial, sans-serif';
    }
    g.fillText(lab.about, 150, 124);
    return { canvas: canvas, width: width, height: height, k: k };
  }

  /* --- сцена ------------------------------------------------------------------- */

  function Stage(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.light = sheet(W / LIGHT_SCALE, H / LIGHT_SCALE);
    this.lightCtx = this.light.getContext('2d');
    this.k = 1;
    this.wall = null;
    this.pillar = null;
    this.resize(W, H);
  }

  /** Подгоняет холст под размер сцены на экране (в пикселях CSS). */
  Stage.prototype.resize = function (width) {
    var ratio = Math.min(global.devicePixelRatio || 1, 2);
    var k = clamp(width * ratio, 320, 2560) / W;
    var pixels = Math.round(W * k);
    if (this.canvas.width === pixels && this.wall) { return; }
    this.canvas.width = pixels;
    this.canvas.height = Math.round(H * k);
    this.k = pixels / W;
    this.wall = null;           /* фактуры рисуются заново под новый размер */
    this.pillar = null;
  };

  /** Рисует кадр: show — расписание, труппа, признаки музыки; t — секунда. */
  Stage.prototype.render = function (show, t) {
    var ctx = this.ctx;
    var k = this.k;
    ctx.setTransform(k, 0, 0, k, W / 2 * k, 0);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
    if (t < show.plan.arrive) {
      this.shaft(show, t);
      /* у самого выхода кадр заливает свет */
      var white = ease((t - (show.plan.arrive - 2.4)) / 2.4);
      if (white > 0) {
        ctx.fillStyle = 'rgba(255, 252, 244, ' + white.toFixed(3) + ')';
        ctx.fillRect(-W / 2, 0, W, H);
      }
    } else {
      this.surface(show, t - show.plan.arrive);
    }
  };

  /* Насколько открыт рот певца: его полоса спектра в эту секунду. */
  function voiceOf(show, one, t) {
    if (t < one.from) { return 0; }
    var level = Score.sample(show.features[one.voice], t - one.delay) * one.gain;
    level = clamp((level - 0.12) / 0.72, 0, 1);
    /* у каждого своё лёгкое дрожание — рты не двигаются как один */
    return level * (0.84 + 0.16 * Math.sin(t * 9 + one.phase * 5));
  }

  function blinkOf(one, t) {
    var cycle = (t + one.phase * 3) / one.blink;
    return cycle - Math.floor(cycle) < 0.13 / one.blink ? 1 : 0;
  }

  /* Все смотрят на кабину: пока лифт проезжает мимо, глаза его провожают. */
  function lookAt(x, y) {
    return { x: clamp(-x / 430, -1, 1), y: clamp((HALF - y) / 330, -1, 1) };
  }

  function perform(show, one, t, x, y) {
    var voice = voiceOf(show, one, t);
    var state = {
      mouth: voice, look: lookAt(x, y), blink: blinkOf(one, t),
      eyes: one.dreamy && voice > 0.3 ? 'happy' : 'open'
    };
    if (one.mount === 'thread') {
      state.mode = 'hang';
      state.sway = t * 1.3 + one.phase;
      state.tilt = Math.sin(t * 0.9 + one.phase) * 0.06;
      state.lean = -voice * 1.2;
    } else if (one.mount === 'web') {
      state.mode = 'splay';
      state.sway = t * 0.8 + one.phase;
    } else {
      state.mode = 'stand';
      state.lean = Math.sin(t * 2 + one.phase) * 0.9 - voice * 2.2;
    }
    if (one.hand) {
      /* вещь своей лабораторной паук держит на виду и чуть покачивает */
      state.hand = one.hand;
      state[one.hand > 0 ? 'raiseRight' : 'raiseLeft'] = 0.8 + 0.05 * Math.sin(t * 1.3 + one.phase);
    }
    if (one.wave) {
      /* провожающие машут той ногой, что ближе к кабине, — или той, что свободна */
      var free = one.hand ? -one.hand : x > 0 ? -1 : 1;
      state[free > 0 ? 'raiseRight' : 'raiseLeft'] = 0.8 + 0.2 * Math.sin(t * 0.7 + one.phase);
      state.wave = t * 6.5 + one.phase;
    }
    return state;
  }

  function hallLight(plan, t) {
    if (t < plan.choir - 0.1) { return 0; }
    return ease((t - plan.choir + 0.1) / 0.45) * (1 - 0.55 * ease((t - plan.leave - 0.5) / 5));
  }

  Stage.prototype.shaft = function (show, t) {
    var ctx = this.ctx;
    var plan = show.plan;
    var set = show.troupe;
    var k = this.k;
    var cam = plan.altitude(t);
    var speed = plan.speed(t);
    var lights = [];
    var glows = [];
    var hall = plan.hall;
    var hallTop = HALF - (hall.top - cam);
    var hallBottom = HALF - (hall.bottom - cam);
    var hallSeen = hallBottom > 0 && hallTop < H;
    var openTop = Math.max(0, hallTop);             /* видимая часть проёма зала */
    var openBottom = Math.min(H, hallBottom);
    var lit = hallLight(plan, t);
    /* насколько кадр занят залом: от этого зависит общий свет */
    var inHall = hallSeen ? ease(hallBottom / 700) * (1 - ease(hallTop / 900)) : 0;
    var leaving = t > plan.leave ? ease((t - plan.leave - 3) / Math.max(1, plan.arrive - plan.leave - 3)) : 0;
    var i, one, x, y, state;

    if (!this.wall) { this.wall = wallTexture(k); }
    if (!this.pillar) { this.pillar = pillarTexture(k); }

    ctx.fillStyle = '#0b0a12';
    ctx.fillRect(-W / 2, 0, W, H);

    /* --- зал: глубина, Большой паук, дальний хор --- */
    if (hallSeen) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(-WALL, openTop, WALL * 2, openBottom - openTop);
      ctx.clip();
      var deep = ctx.createLinearGradient(0, 0, 0, H);
      deep.addColorStop(0, '#4b4592');
      deep.addColorStop(1, '#252150');
      ctx.fillStyle = deep;
      ctx.fillRect(-WALL, 0, WALL * 2, H);

      var giant = set.giant;
      var giantY = HALF - (giant.alt - cam) * FAR;
      /* за спиной Большого паука — его паутина: кольца теряются в темноте */
      ctx.strokeStyle = 'rgba(214, 208, 255, .09)';
      ctx.lineWidth = 2;
      var hub = giantY - 330;
      for (var ring = 1; ring <= 9; ring++) {
        ctx.beginPath();
        for (var corner = 0; corner <= 16; corner++) {
          var turn = corner / 16 * TAU;
          var radius = ring * 150 * (1 + 0.05 * Math.sin(corner * 2.4 + ring));
          ctx.lineTo(Math.cos(turn) * radius, hub + Math.sin(turn) * radius);
        }
        ctx.stroke();
      }
      ctx.beginPath();
      for (var spoke = 0; spoke < 16; spoke++) {
        ctx.moveTo(0, hub);
        ctx.lineTo(Math.cos(spoke / 16 * TAU) * 1500, hub + Math.sin(spoke / 16 * TAU) * 1500);
      }
      ctx.stroke();
      /* огоньки в глубине зала загораются вместе со светом */
      if (lit > 0) {
        for (var spark = 0; spark < 46; spark++) {
          var sx = (hash(spark) - 0.5) * WALL * 2;
          var sy = ((hash(spark + 50) * 1400 + cam * 0.12) % 1400) - 250;
          var twinkle = 0.35 + 0.3 * Math.sin(t * (1 + hash(spark + 9) * 2) + spark);
          ctx.fillStyle = 'rgba(255, 224, 170, ' + (twinkle * lit).toFixed(3) + ')';
          ctx.beginPath();
          ctx.arc(sx, sy, 2 + hash(spark + 3) * 3, 0, TAU);
          ctx.fill();
        }
      }

      /* свет из-за спины Большого паука: по нему читаются брюшко и ноги */
      var back = ctx.createRadialGradient(0, giantY - 120, 60, 0, giantY - 120, 980);
      back.addColorStop(0, 'rgba(186, 176, 255, .62)');
      back.addColorStop(0.55, 'rgba(130, 120, 228, .3)');
      back.addColorStop(1, 'rgba(120, 110, 220, 0)');
      ctx.fillStyle = back;
      ctx.fillRect(-WALL, 0, WALL * 2, H);

      var bass = voiceOf(show, giant, t);
      var awake = t >= plan.choir - 0.35;
      Spider.place(ctx, giant.x, giantY, giant.scale, 'centre', giant.spec, {
        mode: 'stand', mouth: bass,
        look: { x: Math.sin(t * 0.31) * 0.35, y: 0.55 + Math.sin(t * 0.2) * 0.2 },
        eyes: !awake ? 'closed' : t < plan.choir + 0.7 ? 'wide' : 'open',
        blink: blinkOf(giant, t),
        lean: Math.sin(t * 1.1) * 0.25 - bass * 0.5
      });
      /* дымка: Большой паук далеко */
      ctx.fillStyle = 'rgba(40, 34, 78, .26)';
      ctx.fillRect(-WALL, 0, WALL * 2, H);
      var giantEyes = Spider.eyes(giant.x, giantY, giant.scale, 'centre', giant.spec);
      if (awake && lit < 1) {
        glows.push({ x: giantEyes.left, y: giantEyes.y, r: giantEyes.r * 1.5, c: [255, 250, 235], a: 0.8 * (1 - lit), deep: true });
        glows.push({ x: giantEyes.right, y: giantEyes.y, r: giantEyes.r * 1.5, c: [255, 250, 235], a: 0.8 * (1 - lit), deep: true });
      }

      for (var r = set.rows.length - 1; r >= 0; r--) {
        var row = set.rows[r];
        var rowY = HALF - (row.alt - cam) * FAR;
        if (rowY < -60 || rowY > H + 60) { continue; }
        /* гирлянда, на которой стоит ряд */
        ctx.strokeStyle = 'rgba(232, 226, 250, .55)';
        ctx.lineWidth = 1.6;
        [-1, 1].forEach(function (side) {
          if (row.wing && side < 0) {
            ctx.beginPath();
            ctx.moveTo(-WALL, rowY - 10);
            ctx.quadraticCurveTo(-(WALL + row.wing) / 2, rowY + 14, -row.wing + 20, rowY + 4);
            ctx.stroke();
          } else if (row.wing) {
            ctx.beginPath();
            ctx.moveTo(WALL, rowY - 10);
            ctx.quadraticCurveTo((WALL + row.wing) / 2, rowY + 14, row.wing - 20, rowY + 4);
            ctx.stroke();
          } else if (side < 0) {
            ctx.beginPath();
            ctx.moveTo(-WALL, rowY);
            ctx.quadraticCurveTo(0, rowY + 32, WALL, rowY);
            ctx.stroke();
          }
        });
        for (i = 0; i < row.singers.length; i++) {
          one = row.singers[i];
          y = rowY + one.drop;
          var note = voiceOf(show, one, t);
          Spider.place(ctx, one.x, y, one.scale, 'feet', one.spec, {
            mode: 'stand', mouth: note, look: lookAt(one.x, y), lean: Math.sin(t * 2.2 + one.phase) * 1.4 - note * 3
          }, true);
          if (lit < 1 && blinkOf(one, t) === 0) {
            var pair = Spider.eyes(one.x, y, one.scale, 'feet', one.spec);
            glows.push({ x: pair.left, y: pair.y, r: pair.r * 2.2, c: [255, 246, 220], a: 0.75 * (1 - lit), deep: true });
            glows.push({ x: pair.right, y: pair.y, r: pair.r * 2.2, c: [255, 246, 220], a: 0.75 * (1 - lit), deep: true });
          }
        }
      }
      ctx.restore();

      lights.push({ x: 0, y: giantEyes.y + 60, r: 700, c: [214, 214, 255], i: 0.72 * lit });
      lights.push({ x: -380, y: 690, r: 520, c: [255, 226, 180], i: 0.5 * lit });
      lights.push({ x: 380, y: 690, r: 520, c: [255, 226, 180], i: 0.5 * lit });
    }

    /* --- стена шахты с проёмом зала --- */
    ctx.save();
    if (hallSeen) {
      ctx.beginPath();
      if (hallTop > 0) { ctx.rect(-WALL, 0, WALL * 2, hallTop); }
      if (hallBottom < H) { ctx.rect(-WALL, hallBottom, WALL * 2, H - hallBottom); }
      ctx.clip();
    }
    if (!hallSeen || hallTop > 0 || hallBottom < H) {
      var first = Math.floor((cam - HALF) / TILE);
      var last = Math.floor((cam + HALF) / TILE);
      for (var tile = first; tile <= last; tile++) {
        ctx.drawImage(this.wall, -WALL, HALF - ((tile + 1) * TILE - cam), WALL * 2, TILE + 0.6);
      }
      /* дно шахты: ниже нулевой отметки — приямок */
      var pit = HALF - (-330 - cam);
      if (pit < H) {
        ctx.fillStyle = '#211e2c';
        ctx.fillRect(-WALL, pit, WALL * 2, H - pit);
        ctx.fillStyle = '#b88a22';
        ctx.fillRect(-WALL, pit, WALL * 2, 6);
      }
    }
    ctx.restore();
    if (hallSeen) {
      /* кромки проёма: балка и тень от неё внутрь зала */
      [[hallBottom, -1], [hallTop, 1]].forEach(function (edge) {
        var at = edge[0];
        if (at < -80 || at > H + 80) { return; }
        var shade = ctx.createLinearGradient(0, at, 0, at + edge[1] * 120);
        shade.addColorStop(0, 'rgba(8, 6, 16, .7)');
        shade.addColorStop(1, 'rgba(8, 6, 16, 0)');
        ctx.fillStyle = shade;
        ctx.fillRect(-WALL, Math.min(at, at + edge[1] * 120), WALL * 2, 120);
        drawGirder(ctx, at - (edge[1] > 0 ? 50 : 0), 50);
      });
    }

    /* --- перекрытия этажей и таблички --- */
    for (i = 0; i < set.beams.length; i++) {
      var beam = set.beams[i];
      y = HALF - (beam.alt - cam);
      if (y < -60 || y > H + 360) { continue; }
      /* таблички висят над головами: под каждой стоят паучата её работы */
      for (var place = 0; place < beam.labs.length; place++) {
        var lab = beam.labs[place];
        if (!lab.sprite || lab.sprite.k !== k) { lab.sprite = signSprite(lab, k); }
        var sign = lab.sprite;
        ctx.fillStyle = 'rgba(10, 8, 20, .35)';
        ctx.fillRect(lab.x - sign.width / 2 + 8, y - sign.height - 140, sign.width, sign.height);
        ctx.drawImage(sign.canvas, lab.x - sign.width / 2, y - sign.height - 150, sign.width, sign.height);
      }
      drawGirder(ctx, y, 44);
    }

    /* --- паутины --- */
    for (i = 0; i < set.webs.length; i++) {
      var web = set.webs[i];
      y = HALF - (web.alt - cam);
      if (y < -web.radius - 40 || y > H + web.radius + 40) { continue; }
      drawWeb(ctx, web, y);
    }

    /* --- полки и балконы --- */
    for (i = 0; i < set.ledges.length; i++) {
      var ledge = set.ledges[i];
      y = HALF - (ledge.alt - cam);
      if (y < -40 || y > H + 90) { continue; }
      drawLedge(ctx, ledge, y);
    }

    /* --- пауки --- */
    for (i = 0; i < set.singers.length; i++) {
      one = set.singers[i];
      var alt = one.ride ? one.alt + one.ride.rate * plan.altitude(Math.min(t, one.ride.until)) : one.alt;
      y = HALF - (alt - cam);
      if (y < -260 || y > H + 320) { continue; }
      x = one.x;
      state = perform(show, one, t, x, y);
      if (one.mount === 'thread') {
        var swing = Math.sin(state.tilt) * 320;
        ctx.strokeStyle = 'rgba(232, 228, 248, .7)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(x, HALF - (one.top - cam));
        ctx.lineTo(x + swing, y);
        ctx.stroke();
        x += swing;
      }
      Spider.place(ctx, x, y, one.scale, one.mount === 'thread' ? 'thread' : one.mount === 'feet' ? 'feet' : 'centre', one.spec, state);
      if (one.role === 'soloist') {
        /* первый голос в луче: на вступлении светится только она */
        lights.push({ x: x, y: y + 90, r: 300, c: [255, 240, 248], i: 0.55 });
      }
      if (one.layer === 'hall' && lit < 1 && !state.blink) {
        var spot = Spider.eyes(x, y, one.scale, 'feet', one.spec);
        glows.push({ x: spot.left, y: spot.y, r: spot.r * 1.7, c: [255, 246, 220], a: 0.7 * (1 - lit) * inHall });
        glows.push({ x: spot.right, y: spot.y, r: spot.r * 1.7, c: [255, 246, 220], a: 0.7 * (1 - lit) * inHall });
      }
    }

    /* --- колонны по краям --- */
    var firstTile = Math.floor((cam - HALF) / TILE);
    var lastTile = Math.floor((cam + HALF) / TILE);
    for (var p = firstTile; p <= lastTile; p++) {
      var py = HALF - ((p + 1) * TILE - cam);
      ctx.drawImage(this.pillar, -W / 2, py, W / 2 - WALL, TILE + 0.6);
      ctx.save();
      ctx.scale(-1, 1);
      ctx.drawImage(this.pillar, -W / 2, py, W / 2 - WALL, TILE + 0.6);
      ctx.restore();
    }

    /* --- лампы --- */
    for (i = 0; i < set.lamps.length; i++) {
      var lamp = set.lamps[i];
      y = HALF - (lamp.alt - cam);
      if (y < -400 || y > H + 400) { continue; }
      var power = (lamp.hall ? 0.2 + 0.8 * lit : 1) * (0.93 + 0.07 * Math.sin(t * 13 + i * 2.1));
      ctx.fillStyle = '#2a2535';
      ctx.fillRect(lamp.x - 15, y - 9, 30, 12);
      ctx.fillStyle = 'rgb(255, ' + Math.round(200 + 30 * power) + ', ' + Math.round(140 + 60 * power) + ')';
      ctx.beginPath();
      ctx.arc(lamp.x, y + 9, 10, 0, TAU);
      ctx.fill();
      lights.push({ x: lamp.x, y: y + 20, r: 380, c: [255, 200, 128], i: 0.82 * power });
      glows.push({ x: lamp.x, y: y + 9, r: 54, c: [255, 212, 150], a: 0.75 * power });
    }

    /* --- Пафнутий и солистка перед кабиной --- */
    if (t > plan.choir - 3) {
      this.pinned(show, set.soloist, t, cam, lit, lights);
      this.pinned(show, set.pafnuty, t, cam, lit, lights);
    }

    /* --- свет --- */
    var flicker = t < -0.2 ? (hash(Math.floor(t * 14)) > 0.4 ? 0.5 + 0.3 * ease((t + plan.lead) / plan.lead) : 0.16) : 1;
    lights.push({ x: 0, y: 26, r: 780, c: [255, 238, 206], i: 0.8 * flicker * (1 - 0.62 * inHall * (1 - lit)) });
    if (leaving > 0) {
      lights.push({ x: 0, y: -260, r: 900 + 900 * leaving, c: [255, 247, 228], i: Math.min(1, leaving * 1.25) });
    }
    var shade = [82, 74, 114];
    var dark = [15, 13, 26];
    var bright = [140, 130, 172];
    var day = [232, 222, 204];
    var ambient = [0, 0, 0];
    for (i = 0; i < 3; i++) {
      ambient[i] = mix(mix(shade[i], mix(dark[i], bright[i], lit), inHall), day[i], leaving * leaving);
    }
    this.lighting(lights, ambient);

    /* --- блики, лучи, пыль: всё, что светится само --- */
    ctx.globalCompositeOperation = 'lighter';
    /* Блики рисуются после света, поверх готового кадра, — и сами за стену
       не прячутся. Глаза тех, кто в глубине зала (deep), видны только в его
       проёме: иначе они светились бы сквозь стену шахты. */
    for (var pass = 0; pass < 2; pass++) {
      if (pass) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(-WALL, openTop, WALL * 2, Math.max(0, openBottom - openTop));
        ctx.clip();
      }
      for (i = 0; i < glows.length; i++) {
        var glow = glows[i];
        if (glow.a <= 0.01 || !!glow.deep !== !!pass) { continue; }
        var halo = ctx.createRadialGradient(glow.x, glow.y, 0, glow.x, glow.y, glow.r);
        halo.addColorStop(0, 'rgba(' + glow.c.join(',') + ',' + glow.a.toFixed(3) + ')');
        halo.addColorStop(1, 'rgba(' + glow.c.join(',') + ',0)');
        ctx.fillStyle = halo;
        ctx.fillRect(glow.x - glow.r, glow.y - glow.r, glow.r * 2, glow.r * 2);
      }
      if (pass) { ctx.restore(); }
    }
    if (lit > 0.02 && hallSeen) {
      /* прожекторы: два держат дирижёра, два бродят по хору */
      var paf = set.pafnuty;
      [[-600, paf.x, paf.y + 130, 190, 0.2], [80, paf.x, paf.y + 130, 190, 0.14],
        [-300, -330 + Math.sin(t * 0.43) * 250, 700, 190, 0.1], [300, 330 + Math.sin(t * 0.37 + 2) * 250, 700, 190, 0.1]
      ].forEach(function (beamOf) {
        var from = beamOf[0];
        var cone = ctx.createLinearGradient(from, -20, beamOf[1], beamOf[2]);
        cone.addColorStop(0, 'rgba(255, 240, 205, ' + (beamOf[4] * lit).toFixed(3) + ')');
        cone.addColorStop(1, 'rgba(255, 240, 205, 0)');
        ctx.fillStyle = cone;
        ctx.beginPath();
        ctx.moveTo(from - 14, -20);
        ctx.lineTo(from + 14, -20);
        ctx.lineTo(beamOf[1] + beamOf[3], beamOf[2] + 60);
        ctx.lineTo(beamOf[1] - beamOf[3], beamOf[2] + 60);
        ctx.closePath();
        ctx.fill();
      });
    }
    if (leaving > 0) {
      /* лучи сверху: выход близко */
      for (var ray = 0; ray < 5; ray++) {
        var rx = -520 + ray * 260 + Math.sin(t * 0.3 + ray) * 40;
        var rays = ctx.createLinearGradient(0, 0, 0, 760);
        rays.addColorStop(0, 'rgba(255, 246, 220, ' + (0.2 * leaving).toFixed(3) + ')');
        rays.addColorStop(1, 'rgba(255, 246, 220, 0)');
        ctx.fillStyle = rays;
        ctx.beginPath();
        ctx.moveTo(rx - 50, 0);
        ctx.lineTo(rx + 50, 0);
        ctx.lineTo(rx + 190, 760);
        ctx.lineTo(rx - 150, 760);
        ctx.closePath();
        ctx.fill();
      }
    }
    for (var mote = 0; mote < 54; mote++) {
      var depth = 0.4 + hash(mote + 200) * 1.5;
      var mx = (hash(mote) - 0.5) * 1500 + Math.sin(t * 0.3 + mote) * 18;
      var my = (hash(mote + 100) * H + cam * depth * 0.6 + t * 7) % H;
      ctx.fillStyle = 'rgba(255, 240, 214, ' + (0.07 + 0.2 * hash(mote + 300) * (0.5 + 0.5 * Math.max(lit, leaving))).toFixed(3) + ')';
      ctx.beginPath();
      ctx.arc(mx, my, 0.9 + depth, 0, TAU);
      ctx.fill();
    }
    /* вспышка на вступлении хора */
    var since = t - plan.choir;
    if (since > -0.05 && since < 1.2) {
      ctx.fillStyle = 'rgba(255, 244, 222, ' + (0.42 * Math.exp(-Math.max(0, since) / 0.28)).toFixed(3) + ')';
      ctx.fillRect(-W / 2, 0, W, H);
    }
    ctx.globalCompositeOperation = 'source-over';

    /* --- балки переднего плана --- */
    for (i = 0; i < set.girders.length; i++) {
      y = HALF - (set.girders[i].alt - cam) * NEAR;
      if (y < -160 || y > H + 160) { continue; }
      ctx.save();
      ctx.translate(0, y);
      ctx.rotate(set.girders[i].tilt);
      ctx.fillStyle = 'rgba(13, 11, 20, .93)';
      ctx.fillRect(-W / 2 - 40, -32, W + 80, 64);
      ctx.fillStyle = 'rgba(255, 236, 200, .08)';
      ctx.fillRect(-W / 2 - 40, -32, W + 80, 6);
      ctx.fillStyle = '#1c1926';
      for (var bolt = -760; bolt <= 760; bolt += 95) {
        ctx.beginPath();
        ctx.arc(bolt, 0, 6, 0, TAU);
        ctx.fill();
      }
      ctx.restore();
    }

    this.cabin(show, t, cam, speed);
  };

  /* Холст света: тёмный фон, на нём светлые пятна; умножается на кадр. */
  Stage.prototype.lighting = function (lights, ambient) {
    var g = this.lightCtx;
    var ctx = this.ctx;
    g.globalCompositeOperation = 'source-over';
    g.fillStyle = 'rgb(' + ambient.map(Math.round).join(',') + ')';
    g.fillRect(0, 0, this.light.width, this.light.height);
    g.globalCompositeOperation = 'lighter';
    for (var i = 0; i < lights.length; i++) {
      var light = lights[i];
      if (light.i <= 0.01) { continue; }
      var x = (light.x + W / 2) / LIGHT_SCALE;
      var y = light.y / LIGHT_SCALE;
      var r = light.r / LIGHT_SCALE;
      var colour = light.c.join(',');
      var pool = g.createRadialGradient(x, y, 0, x, y, r);
      pool.addColorStop(0, 'rgba(' + colour + ',' + Math.min(1, light.i).toFixed(3) + ')');
      pool.addColorStop(0.5, 'rgba(' + colour + ',' + (Math.min(1, light.i) * 0.42).toFixed(3) + ')');
      pool.addColorStop(1, 'rgba(' + colour + ',0)');
      g.fillStyle = pool;
      g.fillRect(x - r, y - r, r * 2, r * 2);
    }
    ctx.globalCompositeOperation = 'multiply';
    ctx.drawImage(this.light, -W / 2, 0, W, H);
    ctx.globalCompositeOperation = 'source-over';
  };

  /* Пафнутий и солистка висят перед кабиной: спускаются на нитях перед
     самым вступлением хора, весь хор остаются в кадре, а когда кабина уходит
     вверх — остаются на своей высоте и машут вслед. */
  Stage.prototype.pinned = function (show, one, t, cam, lit, lights) {
    var ctx = this.ctx;
    var plan = show.plan;
    var chief = one.role === 'pafnuty';
    var from = plan.choir - (chief ? 2.7 : 1.9);
    var until = plan.choir + (chief ? -0.35 : 0.3);
    if (t < from) { return; }
    var y = mix(-380, one.y, easeOutBack((t - from) / (until - from)));
    var gone = t > plan.leave;
    if (gone) { y += cam - plan.altitude(plan.leave); }
    if (y > H + 420) { return; }
    var voice = voiceOf(show, one, t);
    var tilt = Math.sin(t * 0.8 + one.phase) * 0.045;
    var x = one.x + Math.sin(tilt) * 420;
    var state = {
      mode: 'hang', mouth: voice, look: lookAt(x, y + 60), blink: blinkOf(one, t), tilt: tilt,
      sway: t * 1.2 + one.phase, lean: -voice * 1.1, eyes: 'open'
    };
    if (chief) {
      if (gone) {
        state.raiseLeft = 1;
        state.wave = t * 6.5;
        state.eyes = 'happy';
      } else if (t >= plan.choir - 0.2) {
        /* дирижирует: ноги ходят вразнобой, размах — по громкости */
        var loud = 0.45 + 0.55 * Score.sample(show.features.loud, t);
        state.raiseRight = clamp(0.5 + 0.5 * Math.sin(t * 3.9) * loud, 0, 1);
        state.raiseLeft = clamp(0.5 + 0.5 * Math.sin(t * 3.9 + 2.6) * loud, 0, 1);
        state.baton = true;
      }
    } else {
      state.eyes = voice > 0.55 ? 'happy' : 'open';
      if (gone) {
        state.raiseRight = 1;
        state.wave = t * 6.5 + 1;
      }
    }
    /* когда паук уходит за нижний край кадра, его нить тает, а не обрывается */
    ctx.strokeStyle = 'rgba(236, 232, 250, ' + (0.8 * clamp(1 - (y - H) / 400, 0, 1)).toFixed(3) + ')';
    ctx.lineWidth = chief ? 2 : 1.5;
    ctx.beginPath();
    ctx.moveTo(one.x, Math.min(-10, y - 1400));
    ctx.lineTo(x, y);
    ctx.stroke();
    Spider.place(ctx, x, y, one.scale, 'thread', one.spec, state);
    lights.push({ x: x, y: y + (chief ? 90 : 60), r: chief ? 330 : 240, c: [255, 232, 186], i: chief ? 0.35 + 0.6 * lit : 0.25 + 0.5 * lit });
  };

  /* Балка двутаврового сечения во всю ширину шахты; y — её верх. */
  function drawGirder(ctx, y, height) {
    ctx.fillStyle = '#26222f';
    ctx.fillRect(-WALL, y, WALL * 2, height);
    ctx.fillStyle = '#3d384b';
    ctx.fillRect(-WALL, y, WALL * 2, 9);
    ctx.fillRect(-WALL, y + height - 9, WALL * 2, 9);
    ctx.fillStyle = 'rgba(255, 255, 255, .12)';
    ctx.fillRect(-WALL, y, WALL * 2, 2);
    ctx.fillStyle = 'rgba(10, 8, 18, .6)';
    ctx.beginPath();
    for (var rivet = -WALL + 30; rivet < WALL; rivet += 76) {
      ctx.moveTo(rivet + 3.5, y + height / 2);
      ctx.arc(rivet, y + height / 2, 3.5, 0, TAU);
    }
    ctx.fill();
    /* тень под балкой */
    var under = ctx.createLinearGradient(0, y + height, 0, y + height + 26);
    under.addColorStop(0, 'rgba(8, 6, 16, .45)');
    under.addColorStop(1, 'rgba(8, 6, 16, 0)');
    ctx.fillStyle = under;
    ctx.fillRect(-WALL, y + height, WALL * 2, 26);
  }

  function drawLedge(ctx, ledge, y) {
    var x0 = ledge.side > 0 ? WALL - ledge.width : -WALL;
    var wallX = ledge.side * WALL;
    var edge = ledge.side * (WALL - ledge.width);
    if (ledge.hall) {
      /* балкон зала — театральная ложа: бархат и золотой кант */
      ctx.fillStyle = '#7d2531';
      ctx.beginPath();
      ctx.moveTo(wallX, y + 6);
      ctx.lineTo(edge, y + 6);
      ctx.quadraticCurveTo(edge + ledge.side * 30, y + 62, wallX, y + 78);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = '#d6a93c';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(edge, y + 14);
      ctx.quadraticCurveTo(edge + ledge.side * 30, y + 60, wallX, y + 72);
      ctx.stroke();
      ctx.fillStyle = '#d6a93c';
      ctx.fillRect(x0 - 4, y - 2, ledge.width + 8, 10);
      ctx.fillStyle = 'rgba(255, 255, 255, .3)';
      ctx.fillRect(x0 - 4, y - 2, ledge.width + 8, 2.5);
      return;
    }
    /* подкос */
    ctx.fillStyle = '#2a2634';
    ctx.beginPath();
    ctx.moveTo(wallX, y + 12);
    ctx.lineTo(wallX - ledge.side * Math.min(96, ledge.width * 0.6), y + 12);
    ctx.lineTo(wallX, y + 70);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = '#3a3548';
    ctx.fillRect(x0, y, ledge.width, 14);
    ctx.fillStyle = 'rgba(255, 255, 255, .16)';
    ctx.fillRect(x0, y, ledge.width, 2.5);
    /* под полкой — клочок паутины */
    ctx.strokeStyle = 'rgba(232, 228, 248, .3)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (var strand = 1; strand <= 3; strand++) {
      ctx.moveTo(edge, y + 14);
      ctx.quadraticCurveTo(edge + ledge.side * strand * 14, y + 14 + strand * 9, edge + ledge.side * strand * 30, y + 14);
    }
    ctx.stroke();
  }

  function drawWeb(ctx, web, y) {
    var x = web.x;
    var r = web.radius;
    var i;
    ctx.strokeStyle = 'rgba(236, 232, 250, .46)';
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    /* растяжки к стене и в стороны: на них паутина висит */
    ctx.moveTo(x, y); ctx.lineTo(web.side * WALL, y - r * 1.25);
    ctx.moveTo(x, y); ctx.lineTo(web.side * WALL, y + r * 1.2);
    ctx.moveTo(x, y); ctx.lineTo(x - web.side * r * 1.5, y - r * 1.5);
    ctx.moveTo(x, y); ctx.lineTo(x - web.side * r * 1.4, y + r * 1.45);
    for (i = 0; i < web.spokes.length; i++) {
      ctx.moveTo(x, y);
      ctx.lineTo(x + Math.cos(web.spokes[i]) * r, y + Math.sin(web.spokes[i]) * r);
    }
    ctx.stroke();
    ctx.strokeStyle = 'rgba(236, 232, 250, .34)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (var ring = 0; ring < web.rings.length; ring++) {
      var radius = web.rings[ring] * r;
      for (i = 0; i <= web.spokes.length; i++) {
        var angle = web.spokes[i % web.spokes.length];
        var px = x + Math.cos(angle) * radius;
        var py = y + Math.sin(angle) * radius;
        if (i === 0) {
          ctx.moveTo(px, py);
        } else {
          /* нить между спицами провисает к центру */
          var before = web.spokes[i - 1];
          var middle = (before + angle + (i === web.spokes.length ? TAU : 0)) / 2;
          ctx.quadraticCurveTo(x + Math.cos(middle) * radius * 0.9, y + Math.sin(middle) * radius * 0.9, px, py);
        }
      }
    }
    ctx.stroke();
  }

  /* Кабина: рама, лампа, перила и пол. Мы смотрим из неё, поэтому она
     неподвижна — только дрожит на ходу. */
  Stage.prototype.cabin = function (show, t, cam, speed) {
    var ctx = this.ctx;
    var plan = show.plan;
    var shake = Math.min(1, speed / 150);
    ctx.save();
    ctx.translate(Math.sin(t * 31) * 0.7 * shake, (Math.sin(t * 23.7) * 0.9 + Math.sin(t * 9.1) * 0.6) * shake);

    ctx.fillStyle = '#17141f';
    ctx.fillRect(-W / 2 - 4, -8, W + 8, 30);                  /* верхняя рама */
    ctx.fillRect(-W / 2 - 4, 0, 30, H);                       /* угловые стойки */
    ctx.fillRect(W / 2 - 26, 0, 30, H);
    ctx.fillStyle = 'rgba(255, 240, 210, .09)';
    ctx.fillRect(-W / 2 + 21, 22, 3, H);
    ctx.fillRect(W / 2 - 24, 22, 3, H);
    ctx.fillRect(-W / 2, 20, W, 2);

    /* лампа */
    ctx.fillStyle = '#24202e';
    ctx.beginPath();
    ctx.moveTo(-56, 22); ctx.lineTo(56, 22); ctx.lineTo(40, 36); ctx.lineTo(-40, 36);
    ctx.closePath();
    ctx.fill();
    var on = t < -0.2 ? (hash(Math.floor(t * 14)) > 0.4 ? 0.8 : 0.25) : 1;
    ctx.fillStyle = 'rgba(255, 238, 200, ' + on + ')';
    ctx.fillRect(-36, 36, 72, 5);
    ctx.globalCompositeOperation = 'lighter';
    var bulb = ctx.createRadialGradient(0, 40, 0, 0, 40, 130);
    bulb.addColorStop(0, 'rgba(255, 232, 190, ' + (0.34 * on) + ')');
    bulb.addColorStop(1, 'rgba(255, 232, 190, 0)');
    ctx.fillStyle = bulb;
    ctx.fillRect(-130, 22, 260, 150);
    ctx.globalCompositeOperation = 'source-over';

    /* табло: какой этаж проехали */
    var label = '';
    for (var i = 0; i < show.troupe.beams.length; i++) {
      if (cam > show.troupe.beams[i].alt - 200) { label = show.troupe.beams[i].label; }
    }
    if (t > plan.dusk + 2 && t < plan.leave + 2) { label = '♪'; }
    if (t > plan.arrive - 7) { label = 'ВЫХОД'; }
    ctx.fillStyle = '#07060b';
    ctx.beginPath();
    ctx.roundRect(556, -2, 188, 22, 4);
    ctx.fill();
    ctx.fillStyle = speed > 2 || Math.sin(t * 5) > 0 ? '#ffb347' : '#6b4a1c';
    ctx.font = '700 16px Consolas, "Courier New", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText((speed > 2 ? '▲ ' : '■ ') + label, 650, 10);

    /* перила и пол */
    ctx.fillStyle = '#1b1824';
    ctx.fillRect(-W / 2, 812, W, 11);
    ctx.fillStyle = 'rgba(255, 240, 210, .14)';
    ctx.fillRect(-W / 2, 812, W, 2.5);
    ctx.fillStyle = '#1b1824';
    for (var post = -686; post <= 686; post += 196) { ctx.fillRect(post - 4, 823, 8, 40); }
    ctx.fillStyle = '#14121b';
    ctx.fillRect(-W / 2 - 4, 860, W + 8, H - 856);
    /* предупредительная полоса по краю пола */
    ctx.save();
    ctx.beginPath();
    ctx.rect(-W / 2, 860, W, 8);
    ctx.clip();
    ctx.fillStyle = '#b88a22';
    ctx.fillRect(-W / 2, 860, W, 8);
    ctx.fillStyle = '#17141f';
    ctx.beginPath();
    for (var stripe = -W / 2 - 20; stripe < W / 2 + 20; stripe += 36) {
      ctx.moveTo(stripe, 868); ctx.lineTo(stripe + 12, 860); ctx.lineTo(stripe + 30, 860); ctx.lineTo(stripe + 18, 868);
      ctx.closePath();
    }
    ctx.fill();
    ctx.restore();
    ctx.restore();

    /* тени по углам кадра */
    var corners = ctx.createRadialGradient(0, HALF, 420, 0, HALF, 1000);
    corners.addColorStop(0, 'rgba(6, 4, 12, 0)');
    corners.addColorStop(1, 'rgba(6, 4, 12, .62)');
    ctx.fillStyle = corners;
    ctx.fillRect(-W / 2, 0, W, H);
  };

  /* Поверхность: страница лабораторных — кремовый фон, в правом верхнем углу
     на нити висит Пафнутий, как висел в каждой работе. Вдоль нижнего края
     один за другим появляются провожающие. Слова пишет страница (show.js). */
  Stage.prototype.surface = function (show, since) {
    var ctx = this.ctx;
    var plan = show.plan;
    var set = show.troupe;
    var t = plan.arrive + since;
    ctx.fillStyle = '#f7f4ef';
    ctx.fillRect(-W / 2, 0, W, H);
    var warm = ctx.createRadialGradient(-200, 300, 80, -200, 300, 1300);
    warm.addColorStop(0, 'rgba(255, 255, 255, .9)');
    warm.addColorStop(1, 'rgba(246, 231, 227, .55)');
    ctx.fillStyle = warm;
    ctx.fillRect(-W / 2, 0, W, H);

    /* паутина в левом верхнем углу */
    ctx.strokeStyle = 'rgba(119, 108, 100, .2)';
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    for (var spoke = 0; spoke <= 6; spoke++) {
      var angle = spoke / 6 * Math.PI / 2;
      ctx.moveTo(-W / 2, 0);
      ctx.lineTo(-W / 2 + Math.cos(angle) * 330, Math.sin(angle) * 330);
    }
    for (var ring = 1; ring <= 5; ring++) {
      for (var arc = 0; arc < 6; arc++) {
        var a0 = arc / 6 * Math.PI / 2;
        var a1 = (arc + 1) / 6 * Math.PI / 2;
        var radius = ring * 62;
        ctx.moveTo(-W / 2 + Math.cos(a0) * radius, Math.sin(a0) * radius);
        ctx.quadraticCurveTo(-W / 2 + Math.cos((a0 + a1) / 2) * radius * 0.88, Math.sin((a0 + a1) / 2) * radius * 0.88,
          -W / 2 + Math.cos(a1) * radius, Math.sin(a1) * radius);
      }
    }
    ctx.stroke();

    /* провожающие */
    var guests = set.farewell;
    for (var i = 0; i < guests.length; i++) {
      var guest = guests[i];
      /* сначала выходят крайние, потом те, что ближе к середине */
      var order = Math.min(i, guests.length - 1 - i) * 2 + (i > guests.length / 2 ? 1 : 0);
      var up = easeOutBack((since - 2.4 - order * 0.34) / 0.7);
      if (up <= 0) { continue; }
      var x = -W / 2 + W * (i + 0.5) / guests.length;
      var y = H - 12 + (1 - up) * 240;
      var voice = Score.sample(show.features.high, t - guest.delay) * guest.gain;
      voice = clamp((voice - 0.12) / 0.72, 0, 1);
      var state = {
        mode: 'stand', mouth: voice, look: { x: clamp(-x / 600, -1, 1), y: -0.5 }, blink: blinkOf(guest, t),
        lean: Math.sin(t * 2 + guest.phase) * 1 - voice * 2,
        eyes: voice < 0.1 && Math.sin(t * 0.4 + guest.phase) > 0.6 ? 'happy' : 'open',
        wave: t * 6.5 + guest.phase
      };
      state[i % 2 ? 'raiseLeft' : 'raiseRight'] = 0.75 + 0.25 * Math.sin(t * 0.8 + guest.phase);
      Spider.place(ctx, x, y, guest.scale, 'feet', guest.spec, state);
    }

    /* Пафнутий спускается на своё обычное место */
    var chief = set.pafnuty;
    var down = easeOutBack((since - 0.9) / 1.5);
    var tilt = Math.sin(t * 0.8) * 0.05;
    var px = 600 + Math.sin(tilt) * 300;
    var py = mix(-330, 150, down);
    var talk = since > 3 ? Math.max(0, Math.sin(since * 9)) * (Math.sin(since * 1.26) > 0.2 ? 0.55 : 0) : 0;
    ctx.strokeStyle = '#a79fb8';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(600, -10);
    ctx.lineTo(px, py);
    ctx.stroke();
    Spider.place(ctx, px, py, 2, 'thread', chief.spec, {
      mode: 'hang', tilt: tilt, sway: t * 1.2, mouth: talk, blink: blinkOf(chief, t),
      look: { x: -0.7, y: 0.35 }, eyes: since > 9 && Math.sin(since * 0.5) > 0.75 ? 'happy' : 'open',
      raiseLeft: since > 2.6 ? 0.85 + 0.15 * Math.sin(t) : 0, wave: t * 6
    });

    /* свет, с которым лифт вышел наружу, гаснет не сразу */
    var white = 1 - ease(since / 1.4);
    if (white > 0) {
      ctx.fillStyle = 'rgba(255, 252, 244, ' + white.toFixed(3) + ')';
      ctx.fillRect(-W / 2, 0, W, H);
    }
  };

  global.Stage = Stage;
  Stage.W = W;
  Stage.H = H;
})(window);
