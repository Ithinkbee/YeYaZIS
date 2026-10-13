/* Труппа и декорации: кто где стоит и что проезжает мимо лифта.
 *
 * Расстановка делается «по времени», а не «по высоте». Для каждого паука
 * сначала решается, на какой секунде музыки он окажется в центре кадра, а
 * высота находится через путь лифта (Score.plan): где кабина будет в эту
 * секунду, там паук и висит. Поэтому при любых метках хора шахта заполнена
 * ровно: сдвинулась метка — труппа расставилась заново.
 *
 * Высота растёт вверх; x — от оси шахты: −640 — левая стена, 640 — правая.
 *
 *   подъём    сначала одна солистка едет рядом с кабиной, потом паучата
 *             встречаются всё чаще: на нитях, на полках у стен, в паутинах;
 *             этажи с табличками — лабораторные работы, по две на этаж, и
 *             у паучат под табличкой вещи этой работы
 *   зал       проём в стене: далеко в глубине Большой паук и ряды хора у его
 *             ног, ближе — балконы; Пафнутий и солистка висят перед кабиной
 *             (их ведёт сцена, здесь только роли)
 *   выход     последние этажи; провожающие машут, многие в шапочках
 *
 * В файле только данные и расчёты: он проверяется в node (tests/troupe.test.js).
 */

(function (global) {
  'use strict';

  var inNode = typeof module !== 'undefined' && module.exports;
  var Score = inNode ? require('./score.js') : global.Score;
  var Spider = inNode ? require('./spider.js') : global.Spider;

  var TAU = Math.PI * 2;
  var WALL = 640;               /* половина ширины шахты */
  var HALF = 450;               /* половина высоты кадра */
  var FAR = 0.25;               /* глубина зала: Большой паук смещается вчетверо медленнее стен */
  var THREAD = 1000;            /* нить уходит за верх кадра, пока паук виден */
  var SEED = 20261013;

  var COLOURS = [
    ['малиновый', 350, 58, 44], ['коралловый', 14, 70, 54], ['янтарный', 40, 78, 50], ['травяной', 95, 42, 40],
    ['бирюзовый', 176, 52, 36], ['небесный', 208, 55, 50], ['синий', 232, 48, 46], ['сиреневый', 282, 40, 56],
    ['розовый', 328, 58, 60], ['мятный', 152, 42, 52], ['песочный', 32, 38, 58], ['белый', 255, 22, 84]
  ];

  /* Кого в выводке сколько: паучат и крестовиков, как отец, больше всего. */
  var BROOD = [['baby', 26], ['cross', 20], ['jumper', 12], ['longlegs', 10], ['tarantula', 9], ['crab', 9], ['wasp', 7], ['widow', 7]];
  var TINY_BROOD = [['baby', 4], ['cross', 4], ['jumper', 2], ['crab', 2], ['widow', 1]];
  /* на этажах — без сенокосцев: под табличкой им тесно, а вещь в тонкой ноге не разглядеть */
  var FLOOR_BROOD = [['baby', 4], ['cross', 4], ['jumper', 2], ['tarantula', 1], ['wasp', 1], ['widow', 1], ['crab', 1]];

  var LABS_PER_FLOOR = 2;       /* работ на этаж */
  var FLOOR_UP = 340;           /* над перекрытием: паучата с вещами и таблички */
  var FLOOR_DOWN = 60;          /* под перекрытием: сама балка и тень */
  var FLOOR_STEP = 470;         /* ближе этого перекрытия друг к другу не ставятся */
  var SOLO_MIN = 2.5;           /* меньше этого солистка рядом с кабиной не едет, секунды */

  function pick(rng, weighted) {
    var total = 0;
    weighted.forEach(function (item) { total += item[1]; });
    var roll = rng() * total;
    for (var i = 0; i < weighted.length; i++) {
      roll -= weighted[i][1];
      if (roll < 0) { return weighted[i][0]; }
    }
    return weighted[weighted.length - 1][0];
  }

  /** Паучонок: вид, цвет и что на нём надето. */
  function child(rng, options) {
    options = options || {};
    var kind = options.kind || pick(rng, options.brood || BROOD);
    var colours;
    if (kind === 'widow') {
      colours = Spider.tones(265, 14, 17, '#e0343c');
    } else if (kind === 'wasp') {
      colours = Spider.tones(44, 86, 54, '#241a10');
    } else if (kind === 'tarantula') {
      var coat = [[24, 42, 34], [14, 60, 40], [265, 12, 26]][Math.floor(rng() * 3)];
      colours = Spider.tones(coat[0], coat[1], coat[2], '#e8792b');
    } else {
      var colour = COLOURS[Math.floor(rng() * COLOURS.length)];
      colours = Spider.tones(colour[1], colour[2], colour[3]);
    }
    var wear = [];
    var roll = rng();
    if (options.graduate && roll < 0.42) {
      wear.push('cap');
    } else if (!options.plain) {
      if (roll < 0.1) { wear.push('glasses'); }
      else if (roll < 0.17) { wear.push('hat'); }
      else if (roll < 0.24) { wear.push('headphones'); }
      else if (roll < 0.32) { wear.push('bow'); }
    }
    return { kind: kind, tones: colours, wear: wear, seed: Math.floor(rng() * 1e9) + 1 };
  }

  /**
   * Собирает труппу и декорации по расписанию plan и словам words
   * (из words берутся этажи). Одно и то же зерно даёт одну и ту же шахту.
   */
  function build(plan, words, seed) {
    var rng = Score.random(seed || SEED);
    var set = {
      beams: [],                /* перекрытия этажей с табличками */
      ledges: [],               /* полки у стен и балконы зала */
      webs: [],                 /* паутины */
      lamps: [],                /* лампы на стенах */
      girders: [],              /* балки, пролетающие перед самой кабиной */
      singers: [],              /* все, кто висит и стоит в шахте и на балконах зала */
      rows: [],                 /* дальний хор у ног Большого паука */
      giant: null, pafnuty: null, soloist: null,
      farewell: []              /* паучата на странице благодарности */
    };
    var taken = [];             /* занятые места: прямоугольники «x — высота» */

    function free(x0, x1, a0, a1) {
      for (var i = 0; i < taken.length; i++) {
        var box = taken[i];
        if (x0 < box.x1 && x1 > box.x0 && a0 < box.a1 && a1 > box.a0) { return false; }
      }
      return true;
    }
    function claim(x0, x1, a0, a1) { taken.push({ x0: x0, x1: x1, a0: a0, a1: a1 }); }

    function singer(spec, fields) {
      var one = {
        spec: spec, role: 'child', layer: 'shaft', mount: 'thread', scale: 1, x: 0, alt: 0,
        voice: 'high', from: 0,               /* с какой секунды поёт */
        delay: rng() * 0.09,                  /* каждый вступает чуть по-своему */
        gain: 0.8 + rng() * 0.35,
        phase: rng() * TAU,
        blink: 2.6 + rng() * 3.2,             /* как часто моргает, секунды */
        dreamy: rng() < 0.18,                 /* поёт, зажмурившись */
        wave: false
      };
      Object.keys(fields).forEach(function (key) { one[key] = fields[key]; });
      Spider.formOf(spec);
      set.singers.push(one);
      return one;
    }

    /* --- этажи ----------------------------------------------------------- */

    /* Лабораторные работы. На этаже их две: табличка слева и табличка справа,
       под каждой — трое паучат с вещами своей работы (props в words.json).
       По одной работе на этаж не выходит: если хор вступает рано, шести
       этажам до зала не хватает высоты, и они наезжают друг на друга. */
    var labs = (words && Array.isArray(words.floors) ? words.floors : []).filter(function (floor) {
      return floor && typeof floor === 'object';
    }).map(function (floor, index) {
      return {
        number: String(floor.number === undefined ? index + 1 : floor.number),
        name: String(floor.name || ''), about: String(floor.about || ''),
        props: (Array.isArray(floor.props) ? floor.props : []).filter(function (prop) { return typeof prop === 'string' && prop; })
      };
    });
    var storeys = [];
    for (var first = 0; first < labs.length; first += LABS_PER_FLOOR) { storeys.push(labs.slice(first, first + LABS_PER_FLOOR)); }

    /* Вступление рядом с кабиной едет солистка — этажи идут после неё. Чем
       раньше хор, тем короче её выход: этажам тоже нужно место. */
    var soloUntil = Score.clamp(plan.choir * 0.3, SOLO_MIN, 16);

    /* Где может стоять перекрытие: под залом — выше солистки и так, чтобы
       таблички не упёрлись в кромку зала; над залом — так, чтобы этаж проехал
       целиком до того, как кадр зальёт свет (rushed — хотя бы успел
       показаться). */
    var hall = plan.hall;
    var lowTop = hall.bottom - 190 - FLOOR_UP;
    var room = function (zone) { return zone[1] >= zone[0] ? 1 + Math.floor((zone[1] - zone[0]) / FLOOR_STEP) : 0; };
    var span = function (zone) { return Math.max(0, zone[1] - zone[0]) + FLOOR_STEP; };
    function zones(until, rushed) {
      var low = [plan.altitude(until + 1.6) + 320 + FLOOR_DOWN, lowTop];
      var high = [hall.top + 190 + FLOOR_DOWN, plan.altitude(plan.arrive - (rushed ? 2.6 : 4.5)) - 150];
      return { low: low, high: high, lowRoom: room(low), highRoom: room(high) };
    }

    var fit = zones(soloUntil, false);
    var roomy = fit.lowRoom + fit.highRoom >= storeys.length;
    if (!roomy) {
      /* Тесно. Сначала укорачивается выход солистки — ровно настолько, чтобы
         под залом встали все этажи, которым нет места над ним… */
      var needed = (storeys.length - fit.highRoom - 1) * FLOOR_STEP;
      soloUntil = Score.clamp(plan.when(lowTop - needed - 320 - FLOOR_DOWN) - 1.6, SOLO_MIN, soloUntil);
      fit = zones(soloUntil, false);
      /* …а если и этого мало, этаж ставится у самого выхода: он промелькнёт,
         зато не наедет на соседний */
      if (fit.lowRoom + fit.highRoom < storeys.length) { fit = zones(soloUntil, true); }
    }
    /* над залом — только те, кому не хватило места под ним… */
    var above = Math.min(fit.highRoom, Math.max(0, storeys.length - fit.lowRoom));
    if (roomy && fit.highRoom > 0) {
      /* …а если места вдоволь, этажи делятся по высоте; после зала лифт идёт
         быстрее, и читать таблички там труднее — туда этажей поменьше */
      var wish = Math.round(storeys.length * 0.6 * span(fit.high) / (span(fit.low) + 0.6 * span(fit.high)));
      var least = Math.max(0, storeys.length - fit.lowRoom);
      var most = Math.max(least, Math.min(fit.highRoom, storeys.length - (fit.lowRoom ? 1 : 0)));
      above = Score.clamp(wish, least, most);
    }
    var low = fit.low;
    var high = fit.high;

    /* Перекрытия в зоне: если просторно — через равные промежутки, если
       тесно — от края до края, чтобы между этажами осталось побольше стены. */
    function spread(zone, count) {
      var from = zone[0];
      var to = zone[1];
      if (to < from) { from = to = (from + to) / 2; }
      var places = [];
      for (var i = 0; i < count; i++) {
        places.push(count === 1 ? (from + to) / 2
          : (to - from) / count >= 900 ? from + (i + 0.5) * (to - from) / count
            : from + i * (to - from) / (count - 1));
      }
      return places;
    }

    spread(low, storeys.length - above).concat(spread(high, above)).forEach(function (alt, index) {
      var after = alt > hall.top;
      var beam = {
        alt: alt, index: index, after: after, labs: storeys[index],
        time: plan.when(alt + 140),             /* секунда, когда этаж в центре кадра */
        label: storeys[index].map(function (lab) { return lab.number; }).join('·')
      };
      set.beams.push(beam);
      claim(-WALL, WALL, alt - FLOOR_DOWN, alt + FLOOR_UP);
      set.lamps.push({ alt: alt + 240, x: -(WALL - 70) }, { alt: alt + 240, x: WALL - 70 });
      beam.labs.forEach(function (lab, place) {
        lab.x = beam.labs.length === 1 ? 0 : (place ? 1 : -1) * 245;
        /* вещь держат той ногой, что ближе к оси шахты; провожающие после
           зала этой ногой машут, а вещь перекладывают в другую */
        var hand = (lab.x > 0 ? -1 : 1) * (after ? -1 : 1);
        var group = [];
        var width = 0;
        for (var i = 0; i < 3; i++) {
          var spec = child(rng, { brood: FLOOR_BROOD, plain: true, graduate: after });
          var prop = lab.props.length ? lab.props[i % lab.props.length] : '';
          if (prop.indexOf('wear:') === 0) {
            if (Spider.WEAR[prop.slice(5)]) { spec.wear = [prop.slice(5)]; }
          } else if (prop) {
            spec.prop = prop;
          }
          var size = (1.12 + rng() * 0.2) / Math.pow(Spider.KINDS[spec.kind].legs, 0.6);
          var half = Spider.formOf(spec).width * size * 0.84;
          /* группа не шире своей таблички */
          if (group.length >= 2 && width + half * 2 > 452) { break; }
          group.push({ spec: spec, scale: size, half: half });
          width += half * 2;
        }
        var cursor = lab.x - width / 2;
        group.forEach(function (member) {
          cursor += member.half;
          singer(member.spec, {
            mount: 'feet', x: cursor, alt: alt, scale: member.scale, wave: after,
            lab: lab.number, hand: member.spec.prop ? hand : 0
          });
          cursor += member.half;
        });
      });
    });

    /* --- солистка ---------------------------------------------------------- */

    /* Первый голос. Пока лифт разгоняется, она поднимается по своей нити
       почти с той же скоростью и остаётся в кадре на всё вступление. */
    var soloSpec = { kind: 'baby', tones: Spider.tones(328, 58, 60), wear: ['bow'], seed: 7 };
    singer(soloSpec, {
      role: 'soloist', x: 190, alt: 190, scale: 1.9, dreamy: false, gain: 1.15, delay: 0,
      ride: { until: soloUntil, rate: 0.83 }, thread: THREAD
    });
    claim(-50, 430, -400, plan.altitude(soloUntil + 1.6) + 320);

    /* --- подъём и выход ------------------------------------------------------- */

    function hangOne(alt, side, options) {
      var spec = child(rng, options);
      var form = Spider.formOf(spec);
      var scale = (1.3 + rng() * 0.55) / Math.pow(Spider.KINDS[spec.kind].legs, 0.7);
      var half = form.width * scale * 0.82 + 10;
      var x = side * (110 + rng() * (WALL - 130 - half));
      var height = (34 * Spider.KINDS[spec.kind].legs - form.thread) * scale;
      if (Math.abs(x) + half > WALL - 12 || !free(x - half, x + half, alt - height - 16, alt + 36)) { return false; }
      claim(x - half, x + half, alt - height - 16, alt + 36);
      singer(spec, { x: x, alt: alt, scale: scale, wave: !!options.wave, thread: THREAD });
      return true;
    }

    function ledgeGroup(alt, side, count, options) {
      var specs = [];
      var width = 26;
      for (var i = 0; i < count; i++) {
        var spec = child(rng, options);
        var scale = (1.1 + rng() * 0.3) / Math.pow(Spider.KINDS[spec.kind].legs, 0.6);
        var half = Spider.formOf(spec).width * scale * 0.86;
        specs.push({ spec: spec, scale: scale, half: half });
        width += half * 2;
      }
      var floorAlt = alt - 80;
      var x0 = side > 0 ? WALL - width - 14 : -WALL;
      var x1 = side > 0 ? WALL : -WALL + width + 14;
      if (!free(x0, x1, floorAlt - 46, floorAlt + 215)) { return false; }
      claim(x0, x1, floorAlt - 46, floorAlt + 215);
      set.ledges.push({ alt: floorAlt, side: side, width: width + 14 });
      var cursor = WALL - 16;
      specs.forEach(function (item) {
        cursor -= item.half;
        singer(item.spec, { mount: 'feet', x: side * cursor, alt: floorAlt, scale: item.scale, wave: !!options.wave });
        cursor -= item.half;
      });
      return true;
    }

    function webGroup(alt, side, count, options) {
      var radius = 172 + rng() * 40;
      var x = side * (WALL - radius - 26);
      if (!free(x - radius, x + radius, alt - radius - 10, alt + radius + 10)) { return false; }
      claim(x - radius, x + radius, alt - radius - 10, alt + radius + 10);
      var spokes = [];
      var total = 11 + Math.floor(rng() * 4);
      for (var s = 0; s < total; s++) { spokes.push((s + (rng() - 0.5) * 0.5) / total * TAU); }
      var rings = [];
      for (var r = 0.16; r < 0.98; r += 0.1 + rng() * 0.05) { rings.push(r); }
      set.webs.push({ x: x, alt: alt, radius: radius, side: side, spokes: spokes, rings: rings });
      var turn = rng() * TAU;
      for (var i = 0; i < count; i++) {
        var spec = child(rng, options);
        var scale = (0.9 + rng() * 0.22) / Math.pow(Spider.KINDS[spec.kind].legs, 0.75);
        var away = count === 1 ? 0 : radius * (0.48 + rng() * 0.12);
        var angle = turn + i * TAU / count;
        singer(spec, {
          mount: 'web', x: x + Math.cos(angle) * away, alt: alt + Math.sin(angle) * away,
          scale: scale, wave: !!options.wave
        });
      }
      return true;
    }

    /* Отрезок шахты от секунды from до секунды to. gap — пауза между
       встречами в начале и в конце отрезка: хор по дороге густеет. */
    function ascent(from, to, options) {
      var t = from;
      for (var guard = 0; t < to && guard < 500; guard++) {
        var u = (t - from) / Math.max(1, to - from);
        var alt = plan.altitude(t);
        var crowd = options.crowd ? options.crowd(u) : u;
        for (var attempt = 0; attempt < 5; attempt++) {
          var side = rng() < 0.5 ? -1 : 1;
          var roll = rng();
          var threads = Score.mix(0.72, 0.3, crowd);
          var ledges = threads + Score.mix(0.22, 0.44, crowd);
          var placed = roll < threads ? hangOne(alt, side, options)
            : roll < ledges ? ledgeGroup(alt, side, 1 + Math.floor(rng() * (1.3 + crowd * 1.7)), options)
              : webGroup(alt, side, 1 + Math.floor(rng() * (1.4 + crowd * 1.6)), options);
          if (placed) { break; }
        }
        t += Score.mix(options.gap[0], options.gap[1], u) * (0.75 + rng() * 0.5);
      }
    }

    /* ни над нижней кромкой зала, ни под верхней никто не висит */
    claim(-WALL, WALL, hall.bottom - 190, hall.top + 190);
    ascent(Math.min(7, soloUntil * 0.6), plan.choir - 9, { gap: [3.1, 1.15] });
    ascent(plan.leave + 4.5, plan.arrive - 4.2, {
      gap: [1.5, 2.3], wave: true, graduate: true, crowd: function (u) { return 0.75 - u * 0.5; }
    });

    /* --- зал ------------------------------------------------------------------ */

    var cueAlt = plan.altitude(plan.choir);

    [-1, 1].forEach(function (side) {
      for (var alt = hall.bottom + 170 + (side > 0 ? 150 : 0); alt < hall.top - 180; alt += 300) {
        set.ledges.push({ alt: alt, side: side, width: 222, hall: true });
        set.lamps.push({ alt: alt + 205, x: side * (WALL - 16), hall: true });
        for (var i = 0; i < 2; i++) {
          var spec = child(rng, { brood: [['cross', 3], ['baby', 3], ['tarantula', 2], ['jumper', 2], ['crab', 1], ['widow', 1], ['wasp', 1]] });
          var scale = (0.95 + rng() * 0.15) / Math.pow(Spider.KINDS[spec.kind].legs, 0.6);
          singer(spec, {
            layer: 'hall', mount: 'feet', x: side * (WALL - 66 - i * 98), alt: alt, scale: scale,
            voice: spec.kind === 'tarantula' ? 'low' : rng() < 0.5 ? 'mid' : 'high', from: plan.choir
          });
        }
      }
    });

    /* Большой паук. В момент вступления хора его глаза — в верхней трети
       кадра; брюшко, зубцы короны и ноги в кадр не помещаются. */
    var giantTones = Spider.tones(258, 24, 37, '#ece5f8');
    giantTones.leg = 'hsl(258 30% 20%)';
    set.giant = {
      spec: { kind: 'cross', tones: giantTones, wear: ['regalia'], seed: 3 },
      role: 'giant', scale: 16, x: 0, alt: cueAlt + (HALF - 326) / FAR,
      voice: 'low', from: plan.choir, phase: 0.4, blink: 6.5, gain: 1.1, delay: 0
    };
    Spider.formOf(set.giant.spec);

    /* Дальний хор: гирлянды у ног Большого паука, на его глубине. Рядом с
       ним паучата — с его зрачок: так и видно, какой он большой. Три ряда во
       всю ширину и два «крыла» выше, по бокам от его головы. */
    [[604, 0], [672, 0], [740, 0], [536, 356], [468, 404]].forEach(function (row, number) {
      var line = { alt: cueAlt + (HALF - row[0]) / FAR, singers: [] };
      var shift = number % 2 ? 29 : 0;
      for (var x = -609 + shift; x <= 612; x += 58) {
        if (Math.abs(x) < row[1]) { continue; }
        var spec = child(rng, { brood: TINY_BROOD, plain: true });
        line.singers.push({
          spec: spec, x: x + (rng() - 0.5) * 8, scale: 0.36 + rng() * 0.07,
          /* гирлянда провисает к середине */
          drop: 16 * (1 - (x / WALL) * (x / WALL)),
          voice: rng() < 0.6 ? 'mid' : 'high', from: plan.choir,
          delay: rng() * 0.12, gain: 0.75 + rng() * 0.4, phase: rng() * TAU, blink: 2.5 + rng() * 3
        });
        Spider.formOf(spec);
      }
      line.wing = row[1];
      set.rows.push(line);
    });

    /* Пафнутий — в бабочке и с палочкой; солистка — напротив. Оба висят перед
       кабиной по сторонам от Большого паука и не заслоняют ему рот; когда
       они появляются и исчезают — решает сцена. */
    set.pafnuty = {
      spec: { kind: 'cross', tones: Spider.PAFNUTY, wear: ['bowtie'], seed: 1 },
      role: 'pafnuty', scale: 2.7, x: -306, y: 418, voice: 'mid', from: plan.choir, phase: 0, blink: 4.1, gain: 1, delay: 0
    };
    set.soloist = {
      spec: { kind: soloSpec.kind, tones: soloSpec.tones, wear: soloSpec.wear, seed: soloSpec.seed },
      role: 'soloist', scale: 1.55, x: 366, y: 462, voice: 'high', from: 0, phase: 1.9, blink: 3.3, gain: 1.15, delay: 0
    };
    Spider.formOf(set.pafnuty.spec);
    Spider.formOf(set.soloist.spec);

    /* --- мелочи ------------------------------------------------------------------ */

    /* нить крепится к ближайшему перекрытию над пауком, а не уходит сквозь него */
    var ceilings = set.beams.map(function (beam) { return beam.alt - 44; }).concat([hall.bottom]);
    set.singers.forEach(function (one) {
      if (one.mount !== 'thread') { return; }
      /* у солистки, которая едет рядом с кабиной, считается место, где она остановится */
      var rest = one.ride ? one.alt + one.ride.rate * plan.altitude(one.ride.until) : one.alt;
      one.top = rest + one.thread;          /* высота, на которой нить закреплена */
      ceilings.forEach(function (ceiling) {
        if (ceiling > rest + 30 && ceiling < one.top) { one.top = ceiling; }
      });
    });

    /* лампы между этажами: шахта не должна надолго темнеть */
    var lit = set.lamps.map(function (lamp) { return lamp.alt; });
    for (var lampAlt = 420, lampSide = 1; lampAlt < plan.top - 300; lampAlt += 560, lampSide = -lampSide) {
      var near = lit.some(function (alt) { return Math.abs(alt - lampAlt) < 330; });
      var inHall = lampAlt > hall.bottom - 120 && lampAlt < hall.top + 120;
      if (!near && !inHall) { set.lamps.push({ alt: lampAlt, x: lampSide * (WALL - 16) }); }
    }

    /* балки перед самой кабиной: пролетают быстро и дают почувствовать скорость */
    var quiet = function (t) { return t > plan.choir - 9 && t < plan.leave + 3.5; };
    for (var time = 9.5; time < plan.arrive - 5; time += 8 + rng() * 5) {
      if (!quiet(time)) { set.girders.push({ alt: plan.altitude(time), tilt: (rng() - 0.5) * 0.05 }); }
    }

    /* провожающие на странице благодарности: девять разных, каждый своего цвета */
    var used = {};
    for (var k = 0; set.farewell.length < 9 && k < 80; k++) {
      var guest = child(rng, { brood: [['baby', 4], ['cross', 3], ['jumper', 2], ['tarantula', 1], ['crab', 1], ['wasp', 1], ['widow', 1]], graduate: true });
      var key = guest.kind + guest.tones.body;
      if (used[key]) { continue; }
      used[key] = true;
      Spider.formOf(guest);
      set.farewell.push({ spec: guest, scale: 0.86 + rng() * 0.3, phase: rng() * TAU, blink: 2.6 + rng() * 3, gain: 0.85 + rng() * 0.3, delay: rng() * 0.08 });
    }

    set.singers.sort(function (a, b) { return a.alt - b.alt; });
    set.count = set.singers.length + set.rows.reduce(function (sum, row) { return sum + row.singers.length; }, 0);
    return set;
  }

  var api = { WALL: WALL, HALF: HALF, FAR: FAR, SEED: SEED, COLOURS: COLOURS, BROOD: BROOD, child: child, build: build };

  if (inNode) { module.exports = api; }
  global.Troupe = api;
})(typeof window !== 'undefined' ? window : globalThis);
