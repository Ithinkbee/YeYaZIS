/* Проверка расстановки труппы вне браузера.
 *
 * Расстановка лежит в poklon/web/static/troupe.js. Запускается из pytest
 * (tests/test_scripts.py), а вручную так:
 *
 *     node tests/troupe.test.js
 *
 * Проверяется то, что обещано в ролике: этажи — это лабораторные, по две на
 * этаж, и у паучат под табличкой вещи своей работы; паучата разных видов и
 * цветов, никто не висит в стене и друг на друге; в зале стоит Пафнутий в
 * бабочке, а Большой паук в кадр не помещается. И то, что расстановка одна и
 * та же при каждом показе и перестраивается под метки — в том числе когда
 * хор вступает рано и этажам тесно.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const root = path.join(__dirname, '..');
const Score = require(path.join(root, 'poklon', 'web', 'static', 'score.js'));
const Spider = require(path.join(root, 'poklon', 'web', 'static', 'spider.js'));
const Troupe = require(path.join(root, 'poklon', 'web', 'static', 'troupe.js'));
const words = JSON.parse(fs.readFileSync(path.join(root, 'data', 'words.json'), 'utf8'));

let failures = 0;
let checks = 0;

function check(name, condition, detail) {
  checks++;
  if (condition) { return; }
  failures++;
  console.log('  ОШИБКА: ' + name + (detail !== undefined ? ' — ' + detail : ''));
}

function section(title) { console.log('\n' + title); }

const STAGE_WIDTH = 1600;
const STAGE_HEIGHT = 900;
const plan = Score.plan(154, { choir: 70, leave: 118 });
const set = Troupe.build(plan, words);
const screen = (alt, t, depth) => Troupe.HALF - (alt - plan.altitude(t)) * (depth || 1);

section('Этажи — лабораторные работы');
{
  const labs = set.beams.reduce((all, beam) => all.concat(beam.labs), []);
  check('на этаже по две работы', set.beams.length === Math.ceil(words.floors.length / 2) && set.beams.every((beam) => beam.labs.length === 2),
    set.beams.length);
  check('работы все и по порядку — из words.json', labs.map((lab) => lab.number).join() === words.floors.map((floor) => floor.number).join() &&
    labs[0].name === words.floors[0].name && labs[5].about === words.floors[5].about);
  check('таблички на этаже — слева и справа', set.beams.every((beam) => beam.labs[0].x < -200 && beam.labs[1].x > 200));
  check('таблички не выходят за стены и не наезжают друг на друга', labs.every((lab) => Math.abs(lab.x) + 226 < Troupe.WALL && Math.abs(lab.x) > 226));
  check('на табло кабины — оба номера', set.beams[0].label === '1·2' && set.beams[2].label === '8·9', set.beams[0].label);
  check('этажи идут снизу вверх и не наезжают друг на друга', set.beams.every((beam, i) => i === 0 || beam.alt >= set.beams[i - 1].alt + 470));
  check('первый этаж — после вступления солистки', set.beams[0].time > 16, set.beams[0].time);
  check('часть этажей — до зала, часть — после', set.beams[0].time < plan.choir && set.beams[set.beams.length - 1].time > plan.leave &&
    !set.beams[0].after && set.beams[set.beams.length - 1].after);
  check('в зале этажей нет', set.beams.every((beam) => beam.alt + 340 < plan.hall.bottom - 100 || beam.alt - 60 > plan.hall.top + 100));
  check('этаж в центре кадра — на своей секунде', set.beams.every((beam) => Math.abs(plan.altitude(beam.time) - beam.alt - 140) < 1));
  check('у каждого этажа — свет', set.beams.every((beam) => set.lamps.filter((lamp) => Math.abs(lamp.alt - beam.alt - 240) < 1).length === 2));
  const none = Troupe.build(plan, { floors: [] });
  check('без этажей ролик тоже собирается', none.beams.length === 0 && none.singers.length > 20);
  const odd = Troupe.build(plan, { floors: [null, 'строка', { name: 'Без номера' }] });
  check('испорченные этажи пропускаются', odd.beams.length === 1 && odd.beams[0].labs.length === 1 && odd.beams[0].labs[0].number === '1');
  check('одинокая табличка висит посередине', odd.beams[0].labs[0].x === 0 && odd.beams[0].label === '1');
  const five = Troupe.build(plan, { floors: words.floors.slice(0, 5) });
  check('нечётное число работ: последняя — одна на этаже', five.beams.length === 3 && five.beams[2].labs.length === 1 && five.beams[1].labs.length === 2);
}

section('Вещи лабораторных');
{
  const onFloors = set.singers.filter((one) => one.lab);
  const groups = words.floors.map((floor) => onFloors.filter((one) => one.lab === floor.number).sort((a, b) => a.x - b.x));
  const signOf = (number) => set.beams.reduce((all, beam) => all.concat(beam.labs), []).filter((lab) => lab.number === number)[0];
  check('под каждой табличкой стоят двое-трое', groups.every((group) => group.length >= 2 && group.length <= 3), groups.map((group) => group.length).join());
  check('группа не шире своей таблички', groups.every((group, i) => group.every((one) => Math.abs(one.x - signOf(words.floors[i].number).x) < 226)));
  check('группа стоит на своём перекрытии', groups.every((group, i) => group.every((one) =>
    one.mount === 'feet' && set.beams.some((beam) => beam.alt === one.alt && beam.labs.some((lab) => lab.number === words.floors[i].number)))));
  /* слева направо — в том порядке, в каком вещи записаны: «EN», «→», «DE» читаются как фраза */
  check('вещи — из words.json, слева направо', groups.every((group, i) => group.every((one, place) => {
    const prop = words.floors[i].props[place % words.floors[i].props.length];
    return prop.indexOf('wear:') === 0 ? one.spec.wear.join() === prop.slice(5) && !one.spec.prop : one.spec.prop === prop;
  })));
  const used = words.floors.reduce((all, floor) => all.concat(floor.props), []);
  check('у каждой работы свои вещи', words.floors.every((floor) => floor.props.length >= 2) && new Set(words.floors.map((floor) => floor.props.join())).size === words.floors.length);
  check('каждая вещь из words.json нарисована', used.every((prop) => prop.indexOf('wear:') === 0
    ? typeof Spider.WEAR[prop.slice(5)] === 'function' : typeof Spider.HOLD[prop.split(':')[0]] === 'function'), used.join());
  const holders = onFloors.filter((one) => one.spec.prop);
  check('вещь держат поднятой ногой', holders.length >= 14 && holders.every((one) => one.hand === 1 || one.hand === -1), holders.length);
  check('до зала — ногой, что ближе к оси шахты', holders.filter((one) => !one.wave).every((one) => one.hand === (signOf(one.lab).x > 0 ? -1 : 1)));
  check('после зала ближней ногой машут, а вещь — в другой', holders.filter((one) => one.wave).length >= 2 &&
    holders.filter((one) => one.wave).every((one) => one.hand === (signOf(one.lab).x > 0 ? 1 : -1)));
  check('кто в наушниках — ничего не держит', onFloors.filter((one) => one.spec.wear.indexOf('headphones') >= 0).every((one) => !one.hand && !one.spec.prop));
  check('остальным паукам вещей не выдают', set.singers.filter((one) => !one.lab).every((one) => !one.hand && !one.spec.prop));
  const strange = Troupe.build(plan, { floors: [{ name: 'Без вещей' }, { name: 'С чужими', props: ['нет такой', 5, null, 'wear:нет такого'] }] });
  check('работа без вещей и с неизвестными вещами не ломает сборку', strange.beams.length === 1 && strange.singers.filter((one) => one.lab).length >= 4);
}

section('Ранний хор');
{
  /* запись на 86 секунд, хор с 36-й: до зала всего полминуты, после — десять секунд */
  const early = Score.plan(85.81, { choir: 36.1, leave: 77.81 });
  const tight = Troupe.build(early, words);
  const solo = tight.singers.filter((one) => one.role === 'soloist')[0];
  check('все этажи — до зала', tight.beams.length === 3 && tight.beams.every((beam) => !beam.after && beam.time < early.choir - 6),
    tight.beams.map((beam) => beam.time.toFixed(1)).join());
  check('этажи не наезжают друг на друга', tight.beams.every((beam, i) => i === 0 || beam.alt >= tight.beams[i - 1].alt + 470),
    tight.beams.map((beam) => Math.round(beam.alt)).join());
  check('таблички не упираются в кромку зала', tight.beams[2].alt + 340 <= early.hall.bottom - 189);
  check('солистка уходит раньше, чем в длинной записи', solo.ride.until >= 2.5 && solo.ride.until < 12, solo.ride.until);
  check('первый этаж — выше солистки', tight.beams[0].alt - 60 >= early.altitude(solo.ride.until + 1.6) + 319);
  check('вещи выданы всем работам', words.floors.every((floor) => tight.singers.some((one) => one.lab === floor.number && (one.spec.prop || one.spec.wear.length))));

  /* метку хора двигают: этажи должны оставаться целыми в разумных пределах */
  [34, 31, 28, 26, 24].forEach((choir) => {
    const moved = Troupe.build(Score.plan(85.81, { choir: choir, leave: 77.81 }), words);
    const steps = moved.beams.slice(1).map((beam, i) => Math.round(beam.alt - moved.beams[i].alt));
    check('хор на ' + choir + '-й секунде: этажи не наезжают', moved.beams.length === 3 && steps.every((step) => step >= 470), steps.join());
  });
  const rushed = Troupe.build(Score.plan(85.81, { choir: 22, leave: 77.81 }), words);
  check('совсем рано: лишний этаж уходит за зал, а не наезжает', rushed.beams.filter((beam) => beam.after).length === 1 &&
    rushed.beams[1].alt >= rushed.beams[0].alt + 470);
}

section('Паучата');
{
  const shaft = set.singers.filter((one) => one.layer === 'shaft');
  check('в шахте есть кому петь', shaft.length >= 40, shaft.length);
  const inside = set.singers.every((one) => {
    const form = Spider.formOf(one.spec);
    return Math.abs(one.x) + Math.min(form.width, 40) * one.scale * 0.5 <= Troupe.WALL;
  });
  check('никто не висит в стене', inside);
  check('видов не меньше шести', new Set(set.singers.map((one) => one.spec.kind)).size >= 6, new Set(set.singers.map((one) => one.spec.kind)).size);
  check('цветов не меньше десяти', new Set(set.singers.map((one) => one.spec.tones.body)).size >= 10);
  check('кто-то висит, кто-то стоит, кто-то сидит в паутине', ['thread', 'feet', 'web'].every((mount) => set.singers.some((one) => one.mount === mount)));
  check('в проёме зала из шахты никто не висит', shaft.every((one) => one.alt < plan.hall.bottom - 150 || one.alt > plan.hall.top + 150));
  check('нить закреплена выше паука', set.singers.filter((one) => one.mount === 'thread').every((one) => one.top > one.alt + 30));
  check('нить не проходит сквозь перекрытие', set.singers.filter((one) => one.mount === 'thread' && !one.ride).every((one) =>
    set.beams.every((beam) => !(beam.alt - 44 > one.alt + 30 && beam.alt - 44 < one.top - 0.5))));

  /* висящие не налезают друг на друга: между точками опоры есть место */
  const hanging = shaft.filter((one) => one.mount === 'thread' && !one.ride);
  let apart = true;
  hanging.forEach((a, i) => hanging.slice(i + 1).forEach((b) => {
    if (Math.abs(a.x - b.x) < 60 && Math.abs(a.alt - b.alt) < 80) { apart = false; }
  }));
  check('висящие не налезают друг на друга', apart);

  const early = shaft.filter((one) => one.alt < plan.altitude(25)).length;
  const late = shaft.filter((one) => one.alt > plan.altitude(45) && one.alt < plan.altitude(65)).length;
  check('к залу хор густеет', late > early, early + ' → ' + late);
  const farewell = shaft.filter((one) => one.alt > plan.hall.top);
  check('после зала все машут вслед', farewell.length >= 5 && farewell.every((one) => one.wave), farewell.length);
  check('до зала не машет никто', shaft.filter((one) => one.alt < plan.hall.bottom).every((one) => !one.wave));
  check('у выхода многие в шапочках', farewell.filter((one) => one.spec.wear.indexOf('cap') >= 0).length >= 2);
}

section('Солистка');
{
  const solo = set.singers.filter((one) => one.role === 'soloist');
  check('солистка одна', solo.length === 1);
  const one = solo[0];
  const at = (t) => screen(one.alt + one.ride.rate * plan.altitude(Math.min(t, one.ride.until)), t);
  check('в начале она в кадре', at(0) > 100 && at(0) < 500, at(0));
  check('и остаётся в нём всё вступление', at(8) > 100 && at(8) < 800 && at(15) < 860, at(8) + ', ' + at(15));
  check('потом лифт её обгоняет', at(one.ride.until + 3) > STAGE_HEIGHT + 100, at(one.ride.until + 3));
  check('в зале она снова рядом — с тем же бантом', set.soloist.spec.kind === one.spec.kind && set.soloist.spec.wear.indexOf('bow') >= 0 &&
    set.soloist.spec.tones.body === one.spec.tones.body);
}

section('Зал');
{
  const chief = set.pafnuty;
  check('Пафнутий в бабочке', chief.spec.wear.join() === 'bowtie');
  check('Пафнутий — крестовик, фиолетовый', chief.spec.kind === 'cross' && chief.spec.tones === Spider.PAFNUTY);
  check('Пафнутий крупнее любого из детей', set.singers.every((one) => one.scale < chief.scale));
  check('Пафнутий в кадре', Math.abs(chief.x) < 600 && chief.y > 100 && chief.y < 700);

  const giant = set.giant;
  const form = Spider.formOf(giant.spec);
  check('Большой паук не помещается в кадр по ширине', form.width * 2 * giant.scale > STAGE_WIDTH, form.width * 2 * giant.scale);
  check('и по высоте', (form.ground - form.thread) * giant.scale > STAGE_HEIGHT, (form.ground - form.thread) * giant.scale);
  check('он в короне', giant.spec.wear.join() === 'regalia');
  check('он поёт басом', giant.voice === 'low' && giant.from === plan.choir);
  const eyesAt = (t) => screen(giant.alt, t, Troupe.FAR) + form.eyeY * giant.scale;
  check('на вступлении хора его глаза в кадре', eyesAt(plan.choir) > 150 && eyesAt(plan.choir) < 450, eyesAt(plan.choir));
  check('и остаются в кадре весь хор', eyesAt(plan.leave) > 150 && eyesAt(plan.leave) < 600, eyesAt(plan.leave));
  check('рот тоже виден весь хор', eyesAt(plan.leave) + (form.mouthY - form.eyeY) * giant.scale < 700);
  check('зубцы короны — за кадром', screen(giant.alt, plan.choir, Troupe.FAR) - 23 * giant.scale < 0);
  check('Пафнутий и солистка не заслоняют его рот', Math.abs(chief.x) > 200 && Math.abs(set.soloist.x) > 200);

  const tiny = set.rows.reduce((all, row) => all.concat(row.singers), []);
  check('дальний хор большой', tiny.length >= 60, tiny.length);
  check('рядом с Большим пауком они — с его глаз', tiny.every((one) => one.scale * 20 < giant.scale));
  check('ряды на вступлении в кадре', set.rows.every((row) => {
    const y = screen(row.alt, plan.choir, Troupe.FAR);
    return y > 400 && y < 820;
  }));
  check('дальний хор молчит до вступления', tiny.every((one) => one.from === plan.choir));

  const boxes = set.singers.filter((one) => one.layer === 'hall');
  check('на балконах поют', boxes.length >= 8 && boxes.every((one) => one.from === plan.choir && Math.abs(one.x) > 400), boxes.length);
  check('балконы — внутри проёма', set.ledges.filter((ledge) => ledge.hall).every((ledge) => ledge.alt > plan.hall.bottom && ledge.alt < plan.hall.top));
  check('в труппе все сосчитаны', set.count === set.singers.length + tiny.length, set.count);
}

section('Провожающие');
{
  check('их девять', set.farewell.length === 9);
  check('все разные', new Set(set.farewell.map((guest) => guest.spec.kind + guest.spec.tones.body)).size === 9);
}

section('Повторяемость и метки');
{
  const picture = (troupe) => JSON.stringify(troupe.singers.map((one) => [one.spec.kind, one.spec.tones.body, Math.round(one.x), Math.round(one.alt), one.mount]));
  check('та же запись — та же шахта', picture(Troupe.build(plan, words)) === picture(set));
  check('другое зерно — другая', picture(Troupe.build(plan, words, 99)) !== picture(set));

  const moved = Score.plan(154, { choir: 55, leave: 100 });
  const other = Troupe.build(moved, words);
  check('сдвинулись метки — сдвинулся зал', Math.abs(other.giant.alt - set.giant.alt) > 1000);
  check('этажи остались все', other.beams.length === set.beams.length);
  check('и никто не оказался в проёме', other.singers.filter((one) => one.layer === 'shaft').every((one) =>
    one.alt < moved.hall.bottom - 150 || one.alt > moved.hall.top + 150));

  const short = Troupe.build(Score.plan(45, { choir: 18, leave: 33 }), words);
  check('короткая запись: ролик собирается', short.singers.length > 10 && short.giant && short.beams.length === 3 &&
    short.beams.every((beam) => isFinite(beam.alt) && isFinite(beam.time)));
  const tail = Troupe.build(Score.plan(120, { choir: 60, leave: 119 }), words);
  check('хор до конца записи: ролик собирается', tail.singers.length > 20 && tail.beams.every((beam) => isFinite(beam.alt)));
}

console.log('\nпроверок: ' + checks + ', ошибок: ' + failures);
process.exit(failures ? 1 : 0);
