/* Проверка правил боя с Пафнутием вне браузера.
 *
 * Правила лежат в izbornik/web/static/battle.js и экспортируются через
 * module.exports — ради этой проверки. Запускается из pytest
 * (tests/test_games.py), а вручную так:
 *
 *     node tests/battle_rules.test.js
 *
 * Проверяются расписание пауков, действие яда, огня и паутины, выход самого
 * Пафнутия, монеты и лавка, выделение слов в поле букв и главное свойство
 * дорожки — никто не проходит сквозь врага.
 */

'use strict';

const path = require('path');
const rules = require(path.join(__dirname, '..', 'izbornik', 'web', 'static', 'battle.js'));

let failures = 0;
let checks = 0;

function check(name, condition, detail) {
  checks++;
  if (condition) { return; }
  failures++;
  console.log('  ОШИБКА: ' + name + (detail ? ' — ' + detail : ''));
}

function section(title) { console.log('\n' + title); }

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

const DT = 1 / 30;

/** Прогоняет бой seconds секунд; каждое событие передаётся в watch. */
function run(state, seconds, watch) {
  const steps = Math.round(seconds / DT);
  for (let i = 0; i < steps && !state.over; i++) {
    const events = rules.step(state, DT);
    if (watch) { events.forEach(event => watch(event, state)); }
  }
}

/** Бой без пауков из паутины: только те, кого выпустил тест. */
function quiet(random) {
  const state = rules.createBattle(random || seeded(1));
  state.spiderTimer = 1e9;
  return state;
}

/* --- пауки по расписанию ----------------------------------------------------- */

section('Пауки по расписанию');

let state = rules.createBattle(seeded(7));
state.base.hp = state.base.max = 1e9;              /* бой не должен кончиться раньше расписания */
const spawns = [];
run(state, 96, event => {
  if (event.type === 'spawn' && event.unit.side === 'spider') { spawns.push([state.time, event.unit.kind]); }
});
check('первый паук — через 5 секунд', Math.abs(spawns[0][0] - rules.FIRST_SPIDER) < DT + 1e-9, spawns[0][0]);
check('дальше — каждые 10 секунд', spawns.slice(1).every((s, i) =>
  Math.abs(s[0] - spawns[i][0] - rules.SPIDER_INTERVAL) < DT + 1e-9));
check('первые пауки выходят по порядку знакомства',
  spawns.slice(0, rules.INTRO.length).map(s => s[1]).join() === rules.INTRO.join(), spawns.map(s => s[1]).join());
const kinds = new Set();
const mixState = rules.createBattle(seeded(3));
for (let n = 1; n <= 400; n++) { kinds.add(rules.spiderKind(n, mixState.random)); }
check('после знакомства выходят пауки всех шести видов', ['brown', 'green', 'red', 'white', 'yellow', 'black']
  .every(k => kinds.has(k)), [...kinds].join());
check('Пафнутий по расписанию не выходит', !kinds.has('boss'));

state = quiet();
state.spawned = 0;
const first = rules.spawnSpider(state, 'brown');
state.spawned = 10;
const eleventh = rules.spawnSpider(state, 'brown');
check('каждый следующий паук крепче', eleventh.maxHp > first.maxHp && eleventh.damage > first.damage);
check('рост — 4 % на паука', Math.abs(eleventh.maxHp / first.maxHp - (1 + rules.GROWTH * 10)) < 1e-9);

/* --- слова ----------------------------------------------------------------------- */

section('Слова-воины');

check('длинное слово крепче и сильнее короткого',
  rules.wordStats(9).hp > rules.wordStats(4).hp && rules.wordStats(9).damage > rules.wordStats(4).damage);
state = quiet();
const warrior = rules.sendWord(state, 'онтология');
check('слово выходит от Изборника', warrior.x === rules.BASE_FRONT && warrior.side === 'word');
check('счёт слов и самое длинное слово', state.words === 1 && state.longest === 'онтология');
run(state, 3);
check('слово идёт к паутине', warrior.x > rules.BASE_FRONT + 100, warrior.x);
run(state, 30);
check('дойдя до паутины, слово бьёт по ней', state.web.hp < rules.BASE_HP, state.web.hp);
check('и стоит у её края, не заходя внутрь', warrior.x <= rules.WEB_FRONT - rules.MELEE + 1e-6, warrior.x);

/* --- бой один на один ---------------------------------------------------------------- */

section('Схватка');

state = quiet();
const word = rules.sendWord(state, 'архитектура');
const brown = rules.spawnSpider(state, 'brown');
let met = false;
run(state, 30, (event, s) => {
  if (event.type === 'hit') { met = true; }
});
check('слово и паук встречаются и дерутся', met);
check('длинное слово побеждает бурого паука', brown.hp <= 0 && word.hp > 0);
check('за паука дают монеты', state.coins === rules.SPIDERS.brown.coins && state.killed === 1, state.coins);

/* --- никто не проходит сквозь врага ------------------------------------------------ */

section('Дорожка');

let crossing = '';
for (let seed = 1; seed <= 40 && !crossing; seed++) {
  const random = seeded(seed);
  const battle = rules.createBattle(random);
  let nextWord = 2;
  for (let i = 0; i < 9000 && !battle.over; i++) {
    rules.step(battle, DT);
    if (battle.time >= nextWord) {
      rules.sendWord(battle, 'слово'.repeat(1 + Math.floor(random() * 2)).slice(0, 4 + Math.floor(random() * 7)));
      nextWord += 3 + random() * 12;
    }
    const words = battle.units.filter(u => u.side === 'word');
    const spiders = battle.units.filter(u => u.side === 'spider');
    if (!words.length || !spiders.length) { continue; }
    const gap = Math.min(...spiders.map(s => s.x)) - Math.max(...words.map(w => w.x));
    if (gap < rules.MELEE - 1e-6) { crossing = 'зазор ' + gap.toFixed(3) + ', зерно ' + seed; }
    if (battle.units.some(u => u.x < rules.BASE_FRONT - 1e-6 || u.x > rules.WEB_FRONT + 1e-6)) {
      crossing = 'боец за пределами дорожки, зерно ' + seed;
    }
    if (crossing) { break; }
  }
}
check('в 40 случайных боях слова и пауки не проходят друг сквозь друга', !crossing, crossing);

/* --- яд, огонь, паутина --------------------------------------------------------------- */

section('Яд, огонь и паутина');

state = quiet();
const bitten = rules.sendWord(state, 'параметр');
bitten.hp = bitten.maxHp = 1e6;                 /* слово не должно погибнуть за время опыта */
const green = rules.spawnSpider(state, 'green');
green.hp = green.maxHp = 1e6;
const wordHits = [];
run(state, 40, event => {
  if (event.type === 'hit' && event.unit === bitten) { wordHits.push(state.time); }
});
const gaps = wordHits.slice(3).map((t, i) => t - wordHits[i + 2]);
const poisoned = 1 + rules.POISON_SLOW;
check('отравленное слово бьёт медленнее',
  gaps.length > 3 && gaps.every(g => Math.abs(g - poisoned) < 2 * DT + 1e-9), gaps.map(g => g.toFixed(2)).join());

state = quiet();
state.levels.antidote = 3;
const cured = rules.sendWord(state, 'параметр');
cured.hp = cured.maxHp = 1e6;
const green2 = rules.spawnSpider(state, 'green');
green2.hp = green2.maxHp = 1e6;
const curedHits = [];
run(state, 40, event => {
  if (event.type === 'hit' && event.unit === cured) { curedHits.push(state.time); }
});
const curedGap = curedHits[curedHits.length - 1] - curedHits[curedHits.length - 2];
check('противоядие ослабляет яд', curedGap < poisoned - 0.3, curedGap.toFixed(2));

state = quiet();
const burning = rules.sendWord(state, 'шифрование');
const red = rules.spawnSpider(state, 'red');
run(state, 30, event => {
  if (event.type === 'hit' && event.unit === red) { red.hp = 0; }   /* укусил — и сразу погиб */
});
check('красный паук поджигает слово', red.hp <= 0 && burning.hp < burning.maxHp);
const afterBite = burning.hp;
check('огонь горит и без паука', burning.burn === 0 && afterBite < burning.maxHp - rules.SPIDERS.red.damage,
  (burning.maxHp - afterBite).toFixed(1));

state = quiet();
const walker = rules.sendWord(state, 'модель');
const white = rules.spawnSpider(state, 'white');
let firstShot = null;
run(state, 20, event => {
  if (event.type === 'shot' && !firstShot) { firstShot = event.target.x; }
});
check('белый паук стреляет издалека', firstShot !== null);
check('и стоит на расстоянии, а не вплотную', white.x - walker.x > 5 * rules.MELEE || white.hp <= 0,
  (white.x - walker.x).toFixed(1));

state = quiet();
const plain = rules.sendWord(state, 'модель');
const webbed = rules.sendWord(state, 'модель');
webbed.web = 5;
rules.step(state, DT);
check('опутанное слово идёт вдвое медленнее',
  Math.abs((webbed.x - rules.BASE_FRONT) - (plain.x - rules.BASE_FRONT) * rules.WEB_SLOW) < 1e-9);

/* --- Пафнутий выходит сам -------------------------------------------------------------- */

section('Пафнутий');

state = quiet();
state.web.hp = state.web.max * rules.BOSS_AT + 1;
let bosses = 0;
state.web.hp -= 2;
run(state, 5, event => { if (event.type === 'spawn' && event.unit.kind === 'boss') { bosses++; } });
state.web.hp = state.web.max * 0.1;
run(state, 5, event => { if (event.type === 'spawn' && event.unit.kind === 'boss') { bosses++; } });
check('когда паутина почти порвана, Пафнутий выходит — ровно один раз', bosses === 1, bosses);

/* --- монеты и лавка -------------------------------------------------------------------- */

section('Лавка');

state = quiet();
check('без монет ничего не купить', !rules.buy(state, 'damage'));
state.coins = 1000;
check('улучшение покупается', rules.buy(state, 'damage') && state.levels.damage === 1 &&
  state.coins === 1000 - rules.UPGRADES.damage.costs[0]);
check('следующий уровень дороже', rules.price(state, 'damage') === rules.UPGRADES.damage.costs[1]);
while (rules.buy(state, 'damage')) { /* до предела */ }
check('у улучшения есть предел', state.levels.damage === rules.UPGRADES.damage.costs.length &&
  rules.price(state, 'damage') === null);
check('починка не покупается, пока Изборник цел', !rules.buy(state, 'repair'));
state.base.hp = 100;
check('починка возвращает прочность', rules.buy(state, 'repair') && state.base.hp === 100 + rules.REPAIR);
state.base.hp = state.base.max - 10;
check('но не выше предела', rules.buy(state, 'repair') && state.base.hp === state.base.max);
const veteran = rules.sendWord(state, 'данные');
veteran.hp = veteran.maxHp - 5;
const hpBefore = veteran.hp;
rules.buy(state, 'hp');
check('прочность прибавляется и словам в бою', veteran.hp > hpBefore &&
  Math.abs(veteran.maxHp - veteran.baseHp * 1.2) < 1e-9);
state.over = 'win';
check('после боя лавка закрыта', !rules.buy(state, 'speed'));

/* --- исход боя ---------------------------------------------------------------------- */

section('Исход боя');

state = rules.createBattle(seeded(11));
run(state, 300);
check('без слов Изборник падает', state.over === 'lose', state.over);
check('и не позже чем за две минуты', state.time < 120, state.time.toFixed(1));
const frozen = JSON.stringify({ units: state.units.map(u => u.x), time: state.time });
rules.step(state, 1);
check('после конца боя ничего не меняется', JSON.stringify({ units: state.units.map(u => u.x), time: state.time }) === frozen);

state = rules.createBattle(seeded(12));
let lastWord = 0;
for (let i = 0; i < 30 * 600 && !state.over; i++) {
  rules.step(state, DT);
  if (state.time - lastWord >= 4) { rules.sendWord(state, 'обнаружение'); lastWord = state.time; }
  ['damage', 'hp', 'antidote', 'speed'].some(key => rules.buy(state, key));
}
check('игрок, находящий длинное слово каждые 4 с, побеждает', state.over === 'win', state.over);
check('но не мгновенно: паутину надо ещё продавить', state.time > 30, state.time.toFixed(1));

/* --- поле букв ---------------------------------------------------------------------- */

section('Выделение слов');

const line = rules.selectLine({ row: 2, col: 1 }, { row: 2, col: 4 });
check('слева направо', line.map(c => c.row + ':' + c.col).join() === '2:1,2:2,2:3,2:4');
const back = rules.selectLine({ row: 2, col: 4 }, { row: 2, col: 1 });
check('справа налево — те же клетки в порядке чтения', JSON.stringify(back) === JSON.stringify(line));
const down = rules.selectLine({ row: 5, col: 3 }, { row: 1, col: 4 });
check('наискосок — прилипает к вертикали', down.every(c => c.col === 3) && down.length === 5 && down[0].row === 1);
const flat = rules.selectLine({ row: 0, col: 0 }, { row: 1, col: 5 });
check('наискосок — прилипает к горизонтали', flat.every(c => c.row === 0) && flat.length === 6);

const words = [
  { text: 'сеть', letters: 'СЕТЬ', row: 2, col: 1, dir: 'right' },
  { text: 'слой', letters: 'СЛОЙ', row: 3, col: 7, dir: 'down' }
];
check('слово узнаётся по своим клеткам', rules.matchWord(words, [false, false], line) === 0);
check('вертикальное слово тоже',
  rules.matchWord(words, [false, false], rules.selectLine({ row: 6, col: 7 }, { row: 3, col: 7 })) === 1);
check('найденное слово второй раз не засчитывается', rules.matchWord(words, [true, false], line) === -1);
check('часть слова — не слово',
  rules.matchWord(words, [false, false], rules.selectLine({ row: 2, col: 1 }, { row: 2, col: 3 })) === -1);
check('лишняя буква — тоже',
  rules.matchWord(words, [false, false], rules.selectLine({ row: 2, col: 1 }, { row: 2, col: 5 })) === -1);

console.log('\nПроверок: ' + checks + ', ошибок: ' + failures);
process.exit(failures ? 1 : 0);
