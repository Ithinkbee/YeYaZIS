/* Проверка правил сапёра вне браузера.
 *
 * Правила лежат в izbornik/web/static/sweeper.js и экспортируются через
 * module.exports — ради этой проверки. Запускается из pytest
 * (tests/test_games.py), а вручную так:
 *
 *     node tests/sweeper_rules.test.js
 *
 * Главная проверка — случайные партии: после каждого хода число открытых
 * клеток, флажков и паучат обязано сходиться с полем, а открытая клетка —
 * никогда не быть паучонком, кроме той, что проиграла партию.
 */

'use strict';

const path = require('path');
const rules = require(path.join(__dirname, '..', 'izbornik', 'web', 'static', 'sweeper.js'));

let failures = 0;
let checks = 0;

function check(name, condition, detail) {
  checks++;
  if (condition) { return; }
  failures++;
  console.log('  ОШИБКА: ' + name + (detail ? ' — ' + detail : ''));
}

function section(title) { console.log('\n' + title); }

/* генератор с зерном: партии воспроизводимы */
function seeded(seed) {
  let state = seed >>> 0;
  return function () {
    state += 0x6D2B79F5;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const spiders = game => game.cells.filter(c => c.spider).length;

/* --- размеры ------------------------------------------------------------- */

section('Размеры и число паучат');

let size = rules.normalize({ rows: 2, cols: 100, spiders: 0 });
check('высота не меньше 5', size.rows === 5, size.rows);
check('ширина не больше 40', size.cols === 40, size.cols);
check('паучат хотя бы один', size.spiders === 1, size.spiders);
size = rules.normalize({ rows: 5, cols: 5, spiders: 999 });
check('паучат меньше, чем клеток', size.spiders === 24, size.spiders);
size = rules.normalize({ rows: 'x', cols: '9.4', spiders: '10' });
check('нечисла и дроби приводятся к целым в пределах', size.rows === 5 && size.cols === 9 && size.spiders === 10,
  JSON.stringify(size));
['novice', 'amateur', 'expert'].forEach(name => {
  const preset = rules.PRESETS[name];
  const game = rules.createGame(preset);
  check('уровень ' + name + ' принимается как есть',
    game.rows === preset.rows && game.cols === preset.cols && game.spiders === preset.spiders);
});

/* --- соседи ---------------------------------------------------------------- */

section('Соседи');

const small = rules.createGame({ rows: 5, cols: 6, spiders: 3 });
check('у угловой клетки 3 соседа', rules.neighbors(small, 0).length === 3);
check('у клетки края 5 соседей', rules.neighbors(small, 2).length === 5);
check('у внутренней клетки 8 соседей', rules.neighbors(small, 7).length === 8);
check('соседи правого края не переносятся на следующую строку',
  rules.neighbors(small, 5).every(n => n % 6 >= 4), rules.neighbors(small, 5).join(','));

/* --- первый ход ---------------------------------------------------------- */

section('Первый ход');

for (let seed = 1; seed <= 200; seed++) {
  const game = rules.createGame({ rows: 9, cols: 9, spiders: 10 });
  const first = (seed * 7) % 81;
  const opened = rules.open(game, first, seeded(seed));
  if (spiders(game) !== 10) { check('паучат ровно 10 (зерно ' + seed + ')', false, spiders(game)); break; }
  const safe = [first].concat(rules.neighbors(game, first));
  if (safe.some(i => game.cells[i].spider)) { check('рядом с первым ходом паучат нет', false, 'зерно ' + seed); break; }
  if (game.cells[first].count !== 0 || opened.length < 2) {
    check('первый ход открывает область', false, 'зерно ' + seed); break;
  }
}
check('200 первых ходов безопасны и открывают область', true);

const crowded = rules.createGame({ rows: 5, cols: 5, spiders: 20 });
rules.open(crowded, 12, seeded(3));
check('на тесном поле первая клетка всё равно свободна', !crowded.cells[12].spider && spiders(crowded) === 20);
check('на тесном поле паучата могут стоять вокруг первой клетки', crowded.cells[12].count > 0);

/* --- цифры ------------------------------------------------------------------ */

section('Цифры');

const counted = rules.createGame({ rows: 16, cols: 30, spiders: 99 });
rules.open(counted, 200, seeded(42));
const wrongCount = counted.cells.findIndex((cell, index) =>
  cell.count !== rules.neighbors(counted, index).filter(n => counted.cells[n].spider).length);
check('каждая цифра равна числу паучат вокруг', wrongCount < 0, 'клетка ' + wrongCount);

/* --- флажки и открытие по цифре ----------------------------------------------- */

section('Флажки и открытие по цифре');

const flagged = rules.createGame({ rows: 9, cols: 9, spiders: 10 });
rules.open(flagged, 40, seeded(5));
const closedIndex = flagged.cells.findIndex(c => !c.open);
check('флажок ставится на закрытую клетку', rules.toggleFlag(flagged, closedIndex) && flagged.flags === 1);
check('клетка с флажком не открывается', rules.open(flagged, closedIndex).length === 0 &&
  !flagged.cells[closedIndex].open);
check('флажок снимается', rules.toggleFlag(flagged, closedIndex) && flagged.flags === 0);
const openIndex = flagged.cells.findIndex(c => c.open);
check('на открытую клетку флажок не ставится', !rules.toggleFlag(flagged, openIndex));

/* цифра, вокруг которой флажками помечены все паучата, открывает соседей */
const number = flagged.cells.findIndex((c, i) => c.open && c.count > 0 &&
  rules.neighbors(flagged, i).some(n => !flagged.cells[n].open && !flagged.cells[n].spider));
if (number >= 0) {
  const around = rules.neighbors(flagged, number);
  check('без флажков цифра соседей не открывает', rules.chord(flagged, number).length === 0);
  around.filter(n => flagged.cells[n].spider).forEach(n => rules.toggleFlag(flagged, n));
  const before = flagged.opened;
  rules.chord(flagged, number);
  check('с верными флажками цифра открывает соседей', flagged.opened > before && !flagged.over);
  check('после этого закрытыми вокруг остались только паучата',
    around.every(n => flagged.cells[n].open || flagged.cells[n].spider));
}

const wrong = rules.createGame({ rows: 9, cols: 9, spiders: 10 });
rules.open(wrong, 40, seeded(8));
const target = wrong.cells.findIndex((c, i) => c.open && c.count > 0 &&
  rules.neighbors(wrong, i).some(n => !wrong.cells[n].open && !wrong.cells[n].spider));
if (target >= 0) {
  const around = rules.neighbors(wrong, target);
  const innocent = around.filter(n => !wrong.cells[n].open && !wrong.cells[n].spider);
  let placed = 0;
  /* флажки на пустых клетках вместо паучат: столько же, сколько цифра */
  for (const n of innocent) {
    if (placed < wrong.cells[target].count) { rules.toggleFlag(wrong, n); placed++; }
  }
  if (placed === wrong.cells[target].count) {
    rules.chord(wrong, target);
    check('ошибочный флажок проигрывает партию при открытии по цифре', wrong.over === 'lose');
  }
}

/* --- случайные партии --------------------------------------------------------- */

section('Случайные партии');

let wins = 0;
let losses = 0;
let broken = '';
for (let seed = 1; seed <= 300 && !broken; seed++) {
  const random = seeded(seed * 31);
  const game = rules.createGame({ rows: 8 + seed % 9, cols: 8 + seed % 23, spiders: 5 + seed % 40 });
  const total = game.rows * game.cols;
  /* нечётные партии играет «ясновидец», который открывает только свободные
     клетки, — так проверяется путь к победе; чётные — случайные щелчки */
  const clairvoyant = seed % 2 === 1;
  for (let move = 0; move < 3000 && !game.over; move++) {
    let index = Math.floor(random() * total);
    if (clairvoyant && game.laid) {
      const safe = game.cells.map((c, i) => i).filter(i => !game.cells[i].open && !game.cells[i].spider);
      index = safe[Math.floor(random() * safe.length)];
      if (game.cells[index].flag) { rules.toggleFlag(game, index); }
      rules.open(game, index, random);
    } else if (!clairvoyant && random() < 0.15) { rules.toggleFlag(game, index); }
    else if (game.cells[index].open) { rules.chord(game, index, random); }
    else { rules.open(game, index, random); }

    const opened = game.cells.filter(c => c.open).length;
    const flags = game.cells.filter(c => c.flag).length;
    if (game.over !== 'lose' && opened !== game.opened) { broken = 'счётчик открытых, зерно ' + seed; }
    if (flags !== game.flags) { broken = 'счётчик флажков, зерно ' + seed; }
    if (game.laid && spiders(game) !== game.spiders) { broken = 'число паучат, зерно ' + seed; }
    const openSpider = game.cells.findIndex((c, i) => c.open && c.spider && i !== game.exploded);
    if (openSpider >= 0) { broken = 'открыт паучонок, зерно ' + seed; }
    if (game.cells.some(c => c.open && c.flag)) { broken = 'флажок на открытой клетке, зерно ' + seed; }
    if (broken) { break; }
  }
  if (game.over === 'win') {
    wins++;
    check('при победе открыты все свободные клетки (зерно ' + seed + ')',
      game.opened === total - game.spiders);
    check('при победе помечены все паучата (зерно ' + seed + ')',
      game.cells.every(c => !c.spider || c.flag));
  }
  if (game.over === 'lose') { losses++; }
}
check('300 случайных партий без нарушений', !broken, broken);
check('в случайных партиях бывают и победы, и поражения', wins > 0 && losses > 0, wins + ' / ' + losses);
const finished = rules.createGame({ rows: 5, cols: 5, spiders: 1 });
rules.open(finished, 0, seeded(1));
check('после конца партии ходов нет', !finished.over || rules.open(finished, 1).length === 0);

console.log('\nПроверок: ' + checks + ', ошибок: ' + failures);
process.exit(failures ? 1 : 0);
