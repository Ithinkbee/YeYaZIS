/* Проверка правил пасьянса «Паук» вне браузера.
 *
 * Правила лежат в arachne/web/static/spider.js и экспортируются через
 * module.exports — именно ради этой проверки. Запускается из pytest
 * (tests/test_spider.py), а вручную так:
 *
 *     node tests/spider_rules.test.js
 *
 * Главная проверка — случайные партии: после каждого хода колода обязана
 * оставаться целой. Ошибка в splice или в снятии последовательности теряет
 * или размножает карты, и обычными точечными проверками это ловится плохо.
 */

'use strict';

const path = require('path');
const rules = require(path.join(__dirname, '..', 'arachne', 'web', 'static', 'spider.js'));

let failures = 0;
let checks = 0;

function check(name, condition, detail) {
  checks++;
  if (condition) { return; }
  failures++;
  console.log('  ОШИБКА: ' + name + (detail ? ' — ' + detail : ''));
}

function section(title) { console.log('\n' + title); }

const card = (rank, suit, up = true) => ({ rank, suit, up });

/* --- колода и раздача ---------------------------------------------------- */

section('Колода и раздача');

[1, 2, 4].forEach(function (suitCount) {
  const state = rules.newGame(suitCount, 12345);
  const all = state.columns.flat().concat(state.stock);

  check(`колода из 104 карт (${suitCount} м.)`, all.length === 104, `получено ${all.length}`);
  check(`столбцов 10 (${suitCount} м.)`, state.columns.length === 10);
  check(`в раскладе 54 карты (${suitCount} м.)`,
    state.columns.reduce((sum, c) => sum + c.length, 0) === 54);
  check(`в запасе 50 карт (${suitCount} м.)`, state.stock.length === 50);
  check(`открыто ровно 10 карт (${suitCount} м.)`, all.filter(c => c.up).length === 10);
  check(`мастей ровно ${suitCount}`, new Set(all.map(c => c.suit)).size === suitCount);

  const counts = new Map();
  all.forEach(c => {
    const key = c.suit + ':' + c.rank;
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  const copies = [...new Set(counts.values())];
  check(`каждая карта встречается поровну (${suitCount} м.)`,
    copies.length === 1 && copies[0] === 8 / suitCount, `копий: ${copies}`);

  const sizes = state.columns.map(c => c.length).join(',');
  check(`размеры столбцов (${suitCount} м.)`, sizes === '6,6,6,6,5,5,5,5,5,5', sizes);
});

const first = rules.newGame(2, 777);
const second = rules.newGame(2, 777);
check('раздача повторяется по номеру',
  JSON.stringify(first.columns) === JSON.stringify(second.columns));
check('разные номера дают разные раздачи',
  JSON.stringify(rules.newGame(2, 1).columns) !== JSON.stringify(rules.newGame(2, 2).columns));

/* --- подъём и укладка ---------------------------------------------------- */

section('Подъём карт');

check('убывающая одной масти поднимается',
  rules.canPickUp([card(5, 0, false), card(9, 0), card(8, 0), card(7, 0)], 1));
check('одиночная верхняя карта поднимается',
  rules.canPickUp([card(9, 0), card(3, 1)], 1));
check('закрытая карта не поднимается',
  !rules.canPickUp([card(9, 0, false), card(8, 0)], 0));
check('разные масти не поднимаются',
  !rules.canPickUp([card(9, 0), card(8, 1)], 0));
check('разрыв в достоинстве не поднимается',
  !rules.canPickUp([card(9, 0), card(7, 0)], 0));
check('выход за границы столбца', !rules.canPickUp([card(9, 0)], 5));

section('Укладка карт');

check('на карту на единицу старше', rules.canDrop(card(7, 0), [card(8, 2)]));
check('масть при укладке не важна', rules.canDrop(card(7, 3), [card(8, 0)]));
check('на равную нельзя', !rules.canDrop(card(7, 0), [card(7, 2)]));
check('на младшую нельзя', !rules.canDrop(card(8, 0), [card(7, 0)]));
check('через достоинство нельзя', !rules.canDrop(card(6, 0), [card(8, 0)]));
check('в пустой столбец можно', rules.canDrop(card(7, 0), []));
check('на закрытую нельзя', !rules.canDrop(card(7, 0), [card(8, 0, false)]));

/* --- снятие последовательности ------------------------------------------- */

section('Снятие собранной последовательности');

function fullRun(suit) {
  const run = [];
  for (let rank = 13; rank >= 1; rank--) { run.push(card(rank, suit)); }
  return run;
}

function emptyState(columns) {
  return { columns, stock: [], collected: [], moves: 0, history: [] };
}

let state = emptyState([[card(4, 1, false)].concat(fullRun(0))].concat(
  Array.from({ length: 9 }, () => [])
));
check('полная последовательность снимается', rules.collect(state) === 1);
check('в столбце осталась одна карта', state.columns[0].length === 1);
check('открылась карта под снятой', state.columns[0][0].up === true);
check('последовательность ушла в сбор', state.collected.length === 1);

const mixed = fullRun(0);
mixed[5] = card(mixed[5].rank, 1);
state = emptyState([mixed].concat(Array.from({ length: 9 }, () => [])));
check('разномастная последовательность не снимается', rules.collect(state) === 0);

const short = fullRun(0).slice(1);
state = emptyState([short].concat(Array.from({ length: 9 }, () => [])));
check('неполная последовательность не снимается', rules.collect(state) === 0);

/* --- сдача из запаса ------------------------------------------------------ */

section('Сдача из запаса');

state = emptyState(Array.from({ length: 10 }, () => [card(5, 0)]));
state.stock = Array.from({ length: 20 }, () => card(3, 0, false));
check('сдача разрешена без пустых столбцов', rules.canDealRow(state));
rules.dealRow(state);
check('каждому столбцу досталось по карте',
  state.columns.every(c => c.length === 2));
check('из запаса ушло 10 карт', state.stock.length === 10);
check('сданные карты открыты', state.columns.every(c => c[c.length - 1].up));

state.columns[3] = [];
check('с пустым столбцом сдавать нельзя', !rules.canDealRow(state));
check('dealRow отказывает', !rules.dealRow(state));

state = emptyState(Array.from({ length: 10 }, () => [card(5, 0)]));
state.stock = [];
check('пустой запас не сдаётся', !rules.canDealRow(state));

/* --- отмена хода ---------------------------------------------------------- */

section('Отмена хода');

state = emptyState([[card(8, 0)], [card(7, 0)]].concat(
  Array.from({ length: 8 }, () => [])
));
rules.move(state, 1, 0, 0);
check('ход состоялся', state.columns[0].length === 2 && state.columns[1].length === 0);
check('счётчик ходов вырос', state.moves === 1);
rules.undo(state);
check('отмена вернула карты', state.columns[0].length === 1 && state.columns[1].length === 1);
check('счётчик ходов откатился', state.moves === 0);
check('отменять больше нечего', !rules.undo(state));

state = emptyState([[card(8, 0)], [card(2, 1)]].concat(
  Array.from({ length: 8 }, () => [])
));
check('недопустимый ход не выполняется', !rules.move(state, 1, 0, 0));
check('недопустимый ход не пишется в историю', state.history.length === 0);
check('ход сам в себя не выполняется', !rules.move(state, 0, 0, 0));

/* --- случайные партии ----------------------------------------------------- */

section('Случайные партии: колода остаётся целой');

function fingerprint(state) {
  const all = state.columns.flat()
    .concat(state.stock)
    .concat(state.collected.flat());
  return all.map(c => c.suit + ':' + c.rank).sort().join(',');
}

function legalMoves(state) {
  const moves = [];
  for (let from = 0; from < 10; from++) {
    const column = state.columns[from];
    for (let index = 0; index < column.length; index++) {
      if (!rules.canPickUp(column, index)) { continue; }
      for (let to = 0; to < 10; to++) {
        if (to === from) { continue; }
        if (index === 0 && !state.columns[to].length) { continue; }
        if (rules.canDrop(column[index], state.columns[to])) {
          moves.push([from, index, to]);
        }
      }
    }
  }
  return moves;
}

let playouts = 0;
let collectedTotal = 0;
let wins = 0;

for (let game = 0; game < 40; game++) {
  const suitCount = [1, 2, 4][game % 3];
  const play = rules.newGame(suitCount, 1000 + game);
  const expected = fingerprint(play);
  const random = rules.seededRandom(game + 1);

  for (let step = 0; step < 400; step++) {
    const moves = legalMoves(play);
    const canDeal = rules.canDealRow(play);
    if (!moves.length && !canDeal) { break; }

    /* изредка сдаём карты, иначе партия быстро упирается */
    if (canDeal && (!moves.length || random() < 0.08)) {
      rules.dealRow(play);
    } else {
      const pick = moves[Math.floor(random() * moves.length)];
      rules.move(play, pick[0], pick[1], pick[2]);
    }

    if (fingerprint(play) !== expected) {
      check(`партия ${game}: колода цела на шаге ${step}`, false);
      break;
    }
    const total = play.columns.reduce((s, c) => s + c.length, 0)
      + play.stock.length + play.collected.length * 13;
    if (total !== 104) {
      check(`партия ${game}: карт ровно 104 на шаге ${step}`, false, `их ${total}`);
      break;
    }
  }

  /* собранные последовательности обязаны быть правильными */
  play.collected.forEach(function (run, number) {
    let valid = run.length === 13 && run[0].rank === 13;
    for (let i = 0; i < run.length - 1 && valid; i++) {
      valid = run[i].suit === run[i + 1].suit && run[i].rank === run[i + 1].rank + 1;
    }
    check(`партия ${game}: последовательность ${number} правильная`, valid);
  });

  playouts++;
  collectedTotal += play.collected.length;
  if (rules.isWon(play)) { wins++; }
  check(`партия ${game}: колода цела в конце`, fingerprint(play) === expected);
}

check('партий сыграно', playouts === 40);
console.log(`  сыграно партий: ${playouts}, собрано последовательностей: ${collectedTotal}, ` +
  `сошлось случайной игрой: ${wins}`);

/* --- итог ----------------------------------------------------------------- */

console.log(`\nпроверок: ${checks}, ошибок: ${failures}`);
process.exit(failures ? 1 : 0);
