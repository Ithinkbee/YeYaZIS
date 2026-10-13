/* Проверка партитуры вне браузера: спектр, поиск хора, путь лифта.
 *
 * Расчёты лежат в poklon/web/static/score.js и экспортируются через
 * module.exports — ради этой проверки. Запускается из pytest
 * (tests/test_scripts.py), а вручную так:
 *
 *     node tests/score.test.js
 *
 * Настоящей записи здесь нет: звук составляется из синусов так, как устроена
 * песня, — тихий высокий голос, потом громкая часть с басом, потом снова
 * тихо. Проверяется, что громкая часть находится там, где она есть, что
 * полосы спектра различают бас и верх и что лифт едет только вверх.
 */

'use strict';

const path = require('path');
const Score = require(path.join(__dirname, '..', 'poklon', 'web', 'static', 'score.js'));

let failures = 0;
let checks = 0;

function check(name, condition, detail) {
  checks++;
  if (condition) { return; }
  failures++;
  console.log('  ОШИБКА: ' + name + (detail !== undefined ? ' — ' + detail : ''));
}

function section(title) { console.log('\n' + title); }

const RATE = 22050;

/* Звук из трёх частей: [0, choir) — тихий тон 1320 Гц, [choir, leave) —
   громкие 98 и 330 Гц, [leave, length) — снова тихий тон. */
function song(length, choir, leave) {
  const samples = new Float32Array(Math.round(length * RATE));
  for (let i = 0; i < samples.length; i++) {
    const t = i / RATE;
    const phrase = Math.sin(2 * Math.PI * t / 4.1) > -0.7 ? 1 : 0;      /* паузы на вдох */
    if (t >= choir && t < leave) {
      samples[i] = 0.5 * Math.sin(2 * Math.PI * 98 * t) + 0.3 * Math.sin(2 * Math.PI * 330 * t) + 0.05 * Math.sin(2 * Math.PI * 1320 * t);
    } else {
      samples[i] = 0.12 * phrase * Math.sin(2 * Math.PI * 1320 * t);
    }
  }
  return samples;
}

section('Преобразование Фурье');
{
  const n = 256;
  const re = new Float32Array(n);
  const im = new Float32Array(n);
  for (let i = 0; i < n; i++) { re[i] = Math.cos(2 * Math.PI * 19 * i / n); }
  Score.fft(re, im);
  let peak = 0;
  for (let k = 1; k < n / 2; k++) { if (Math.hypot(re[k], im[k]) > Math.hypot(re[peak], im[peak])) { peak = k; } }
  check('пик там, где частота сигнала', peak === 19, peak);
  check('высота пика — половина длины', Math.abs(Math.hypot(re[19], im[19]) - n / 2) < 0.01, Math.hypot(re[19], im[19]));
  check('в соседних частотах пусто', Math.hypot(re[40], im[40]) < 0.01, Math.hypot(re[40], im[40]));
}

section('Прослушивание записи');
const samples = song(100, 40, 80);
const job = Score.analysis([samples], RATE);
let share = 0;
let steps = 0;
while (share < 1) { share = job.run(500); steps++; }
const features = job.finish();
{
  check('счёт идёт по частям', steps > 3, steps);
  check('тридцать значений в секунду', Math.abs(features.length - 3000) <= 1, features.length);
  check('длина записи известна', Math.abs(features.duration - 100) < 0.01, features.duration);
  const at = (name, t) => Score.sample(features[name], t);
  check('в хоре громко', at('loud', 60) > 0.8, at('loud', 60));
  check('до хора тихо', at('loud', 20.5) < 0.6, at('loud', 20.5));
  check('бас слышен только в хоре', at('low', 60) > 0.8 && at('low', 20.5) < 0.1, at('low', 60) + ' / ' + at('low', 20.5));
  check('середина слышна в хоре', at('mid', 60) > 0.8 && at('mid', 20.5) < 0.1, at('mid', 60) + ' / ' + at('mid', 20.5));
  check('верх слышен у солистки', at('high', 20.5) > 0.5, at('high', 20.5));
  let inside = true;
  ['level', 'loud', 'low', 'mid', 'high'].forEach((name) => {
    for (let i = 0; i < features.length; i++) {
      if (!(features[name][i] >= 0 && features[name][i] <= 1.25)) { inside = false; }
    }
  });
  check('все признаки — от нуля до единицы с небольшим', inside);
  check('до записи и после неё — тишина', Score.sample(features.loud, -3) === 0 && Score.sample(features.loud, 140) === 0);
  /* стерео даёт то же, что моно: каналы усредняются */
  const stereo = Score.analysis([samples, samples], RATE).finish();
  check('два одинаковых канала — тот же результат', Math.abs(stereo.low[1800] - features.low[1800]) < 1e-4, stereo.low[1800]);
}

section('Поиск большого хора');
{
  const cues = Score.detectCues(features, 100);
  check('хор найден', cues.found === true);
  check('начало — на вступлении', Math.abs(cues.choir - 40) < 1.2, cues.choir);
  check('конец — где хор смолкает', Math.abs(cues.leave - 80) < 2.5, cues.leave);

  const late = Score.detectCues(Score.analysis([song(120, 75, 104)], RATE).finish(), 120);
  check('другая запись — другие метки', late.found && Math.abs(late.choir - 75) < 1.2 && Math.abs(late.leave - 104) < 2.5,
    late.choir + ' – ' + late.leave);

  /* ровная запись: громкой части нет */
  const flat = new Float32Array(60 * RATE);
  for (let i = 0; i < flat.length; i++) { flat[i] = 0.3 * Math.sin(2 * Math.PI * 440 * i / RATE); }
  const none = Score.detectCues(Score.analysis([flat], RATE).finish(), 60);
  check('в ровной записи хор не выдумывается', none.found === false);
  check('метки тогда ставятся по долям записи', none.choir > 20 && none.choir < 32 && none.leave > 42 && none.leave < 53,
    none.choir + ' – ' + none.leave);

  const guess = Score.guess(150);
  check('без записи метки тоже есть', guess.choir > 10 && guess.leave > guess.choir + 12 && guess.leave < 150);
  const fixed = Score.settle({ choir: 2, leave: 149 }, 150);
  check('метки не прижимаются к краям записи', fixed.choir >= 10 && fixed.leave <= 142, fixed.choir + ' – ' + fixed.leave);
  const swapped = Score.settle({ choir: 90, leave: 60 }, 150);
  check('конец хора — после начала', swapped.leave >= swapped.choir + 12, swapped.choir + ' – ' + swapped.leave);
  const short = Score.settle({ choir: 5, leave: 9 }, 20);
  check('короткая запись делится на части', short.choir > 0 && short.leave > short.choir && short.leave < 20);
}

section('Ролик без записи');
{
  const cues = Score.guess(150);
  const quiet = Score.silent(150, cues);
  check('признаки придуманы на всю длину', quiet.length === 150 * Score.RATE && quiet.silent === true);
  let moves = 0;
  for (let i = 1; i < quiet.length; i++) { if (Math.abs(quiet.high[i] - quiet.high[i - 1]) > 0.02) { moves++; } }
  check('рты всё равно двигаются', moves > 500, moves);
  check('бас — только в хоре', Score.sample(quiet.low, cues.choir - 10) < 0.1 && Score.sample(quiet.low, (cues.choir + cues.leave) / 2 + 0.4) > 0.2);
}

section('Путь лифта');
{
  const plan = Score.plan(154, { choir: 70, leave: 118 });
  let rising = true;
  for (let t = -2; t < 190; t += 0.05) { if (plan.altitude(t + 0.05) < plan.altitude(t) - 1e-9) { rising = false; } }
  check('лифт едет только вверх', rising);
  check('до первой ноты стоит', plan.altitude(-1) === 0 && plan.altitude(0) === 0 && plan.speed(-0.5) === 0);
  check('после выхода стоит', plan.altitude(plan.arrive + 5) === plan.top && plan.speed(plan.arrive + 1) === 0);
  check('на подъёме идёт ровно', Math.abs(plan.speed(30) - 150) < 0.01, plan.speed(30));
  const travel = plan.altitude(plan.leave) - plan.altitude(plan.choir);
  check('за весь хор проходит один и тот же отрезок', Math.abs(travel - Score.HALL_TRAVEL) < 3, travel);
  check('в зале почти стоит', plan.speed(94) < 12, plan.speed(94));
  check('после зала идёт быстрее', plan.speed(plan.leave + 6) > 200, plan.speed(plan.leave + 6));
  check('выход — после зала, к концу записи', plan.arrive >= plan.leave + 10 && plan.arrive <= 154, plan.arrive);
  check('нижняя кромка зала в момент вступления — у низа кадра',
    Math.abs(450 - (plan.hall.bottom - plan.altitude(plan.choir)) - 840) < 1);
  check('верхняя кромка весь хор за кадром', 450 - (plan.hall.top - plan.altitude(plan.leave)) < 0);
  let inverse = true;
  [3, 20, 50, 66, 69, 90, 119, 130, plan.arrive - 1].forEach((t) => {
    if (Math.abs(plan.when(plan.altitude(t)) - t) > 0.05) { inverse = false; }
  });
  check('по высоте находится секунда', inverse);
  check('ниже дна — нулевая секунда, выше выхода — секунда выхода', plan.when(-50) === 0 && plan.when(plan.top + 500) === plan.arrive);
  check('действия идут по порядку', ['wait', 'rise', 'hall', 'leave', 'surface'].join() ===
    [-1, 10, 90, 125, plan.arrive + 1].map((t) => Score.act(plan, t)).join());

  /* хор до самого конца записи: выход всё равно случается, уже в тишине */
  const tail = Score.plan(120, { choir: 60, leave: 119 });
  check('хор до конца записи: зал всё равно кончается', tail.leave <= 112 && tail.arrive >= tail.leave + 10, tail.leave + ' → ' + tail.arrive);
  const tiny = Score.plan(18, { choir: 3, leave: 5 });
  check('очень короткая запись не ломает расписание', tiny.choir > 0 && tiny.leave > tiny.choir && isFinite(tiny.top) && tiny.top > 0);
}

section('Случайные числа с зерном');
{
  const a = Score.random(42);
  const b = Score.random(42);
  const c = Score.random(43);
  const first = [a(), a(), a()];
  check('одно зерно — одна последовательность', first.join() === [b(), b(), b()].join());
  check('другое зерно — другая', first.join() !== [c(), c(), c()].join());
  check('числа от нуля до единицы', first.every((value) => value >= 0 && value < 1));
}

console.log('\nпроверок: ' + checks + ', ошибок: ' + failures);
process.exit(failures ? 1 : 0);
