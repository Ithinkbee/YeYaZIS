/* Проверка правил прогулки с Пафнутием вне браузера.
 *
 * Правила лежат в sluhach/web/static/walk.js и экспортируются через
 * module.exports — ради этой проверки. Запускается из pytest
 * (tests/test_games.py), а вручную так:
 *
 *     node tests/walk_rules.test.js
 *
 * Проверяются разбор карты, перевод голоса в движение (тишина, тихий и
 * громкий голос, один прыжок на один испуг), вода, овраги и ступени,
 * настройка порогов громкости по шуму комнаты и голосу игрока, а главное —
 * что каждая карта проходима: по всем картам, включая случайные, идёт
 * «игрок», который кричит ровно настолько, насколько нужно.
 */

'use strict';

const path = require('path');
const rules = require(path.join(__dirname, '..', 'sluhach', 'web', 'static', 'walk.js'));

let failures = 0;
let checks = 0;

function check(name, condition, detail) {
  checks++;
  if (condition) { return; }
  failures++;
  console.log('  ОШИБКА: ' + name + (detail !== undefined ? ' — ' + detail : ''));
}

function section(title) { console.log('\n' + title); }

function near(a, b, tolerance) { return Math.abs(a - b) <= tolerance; }

const DT = 1 / 120;
const SOFT = 0.4;                                  /* тихий голос: между порогами «идти» и «прыгать» */

function loudLevel(power) { return rules.LOUD + (1 - rules.LOUD) * power; }

/** Прогоняет прогулку seconds секунд; voice — число или функция от состояния. */
function walk(state, seconds, voice, watch) {
  const steps = Math.round(seconds / DT);
  for (let i = 0; i < steps && !state.over; i++) {
    const level = typeof voice === 'function' ? voice(state, i * DT) : voice;
    const events = rules.step(state, DT, level);
    if (watch) { events.forEach(event => watch(event, state)); }
  }
  return state;
}

function start(spec) { return rules.createRun(rules.buildLevel(spec)); }

function types(state, seconds, voice) {
  const seen = [];
  walk(state, seconds, voice, event => seen.push(event.type));
  return seen;
}

/* --- разбор карты ------------------------------------------------------------ */

section('Разбор карты');

let level = rules.buildLevel('G100 W50 G60 G40 U20 G100 R80 G50 C D20 G100 F G50');
check('соседние отрезки одной высоты сливаются', level.segments.length === 6, level.segments.length);
check('длина карты — сумма отрезков и воды', level.length === 630, level.length);
check('над водой земли нет', rules.groundAt(level, 120) === -Infinity);
check('высота земли в начале', rules.groundAt(level, 10) === rules.START_HEIGHT);
check('после U20 земля выше на 20', rules.groundAt(level, 260) === rules.START_HEIGHT + 20);
check('дно оврага ниже на глубину оврага',
  rules.groundAt(level, 380) === rules.START_HEIGHT + 20 - rules.RAVINE_DEPTH && rules.segmentAt(level, 380).ravine);
check('после D20 земля прежней высоты', rules.groundAt(level, 500) === rules.START_HEIGHT);
check('метка и финиш стоят там, где записаны', level.checkpoints[0] === 480 && level.finish === 580);
check('граница отрезка относится к следующему', rules.groundAt(level, 100) === -Infinity && rules.groundAt(level, 150) === rules.START_HEIGHT);

['G100 G100', 'G100 X5 F', 'G0 F', 'W F G10', 'G100 D50 G10 F G10', 'G100 D40 R60 G10 F G10'].forEach(spec => {
  let refused = false;
  try { rules.buildLevel(spec); } catch (error) { refused = true; }
  check('негодная запись отклоняется: ' + spec, refused);
});

rules.LEVELS.forEach(item => {
  const built = rules.buildLevel(item.spec);
  check('карта «' + item.name + '» разбирается', built.segments.length > 3 && built.finish > 1000, built.finish);
  check('у карты «' + item.name + '» есть метки', built.checkpoints.length >= 1);
  check('старт карты «' + item.name + '» на земле', rules.groundAt(built, rules.START_X) === rules.START_HEIGHT);
});

/* --- голос -------------------------------------------------------------------- */

section('Голос');

const flat = 'G5000 F G100';
let state = start(flat);
walk(state, 3, 0);
check('в тишине паук стоит', state.x === rules.START_X && state.jumps === 0, state.x);

state = start(flat);
walk(state, 3, rules.QUIET - 0.02);
check('шум тише порога — тоже тишина', state.x === rules.START_X, state.x);

state = start(flat);
walk(state, 2, SOFT);
check('тихий голос ведёт вперёд со скоростью шага', near(state.x, rules.START_X + 2 * rules.WALK_SPEED, 2), state.x);
check('от тихого голоса паук не прыгает', state.jumps === 0 && state.grounded);

state = start(flat);
walk(state, 2, (s, t) => (t % 0.3 < 0.15 ? SOFT : 0));          /* слоги с паузами по 0,15 с */
check('паузы между слогами шаг не останавливают', near(state.x, rules.START_X + 2 * rules.WALK_SPEED, 4), state.x);

state = start(flat);
walk(state, 2, (s, t) => (t < 1 ? SOFT : 0));
const stopped = state.x;
walk(state, 1, 0);
check('замолчали — паук остановился', state.x === stopped && near(stopped, rules.START_X + (1 + rules.VOICE_HOLD) * rules.WALK_SPEED, 3), stopped);

function jumpOnce(power, voiceInAir) {
  const run = start(flat);
  let top = run.y;
  let events = [];
  walk(run, 0.3, SOFT);
  const from = run.x;
  const ground = run.y;
  walk(run, 3, (s, t) => (t < rules.STARTLE + 0.02 ? loudLevel(power) : voiceInAir), event => events.push(event));
  /* высота и длина — до первого приземления */
  const again = start(flat);
  walk(again, 0.3, SOFT);
  let landedAt = null;
  walk(again, 3, (s, t) => {
    if (s.y > top) { top = s.y; }
    return t < rules.STARTLE + 0.02 ? loudLevel(power) : voiceInAir;
  }, (event, s) => { if (event.type === 'land' && landedAt === null) { landedAt = s.x; } });
  return { height: top - ground, length: landedAt - from, events: events, jumps: run.jumps };
}

const small = jumpOnce(0, SOFT);
const big = jumpOnce(1, SOFT);
check('громкий звук — прыжок', small.jumps === 1 && small.events.some(e => e.type === 'jump'));
check('перед прыжком — испуг', small.events[0].type === 'startle', small.events[0].type);
check('высота слабого прыжка — по формуле', near(small.height, rules.jumpHeight(0), 2.5), small.height);
check('высота сильного прыжка — по формуле', near(big.height, rules.jumpHeight(1), 3.5), big.height);
check('чем громче, тем выше и дальше', big.height > small.height * 2 && big.length > small.length * 1.4,
  small.length + ' / ' + big.length);
check('длина прыжка близка к расчётной', near(big.length, rules.jumpLength(1), 22), big.length + ' / ' + rules.jumpLength(1));
const silent = jumpOnce(1, 0);
check('без голоса в полёте прыжок короче', silent.length < big.length * 0.65, silent.length + ' / ' + big.length);
check('высота прыжка от голоса в полёте не зависит', near(silent.height, big.height, 0.5));

state = start(flat);
walk(state, 4, 1);
check('непрерывный крик — один прыжок, дальше шаг', state.jumps === 1 && state.grounded, state.jumps);

state = start(flat);
walk(state, 6, (s, t) => (t % 2 < 0.25 ? 1 : SOFT));
check('каждый новый крик после затишья — новый прыжок', state.jumps === 3, state.jumps);

state = start(flat);
walk(state, 4, (s, t) => (t % 2 < 0.25 ? 1 : rules.LOUD * rules.REARM + 0.02));
check('голос не стих ниже порога — второго прыжка нет', state.jumps === 1, state.jumps);

/* крик нарастает: первый миг едва громче порога, потом в полную силу */
state = start(flat);
let peak = state.y;
walk(state, 2, (s, t) => {
  if (s.y > peak) { peak = s.y; }
  return t < 0.02 ? rules.LOUD + 0.01 : t < 0.2 ? 1 : SOFT;
});
check('прыжок берёт силу всего крика, а не его первого мига', near(peak - rules.START_HEIGHT, rules.jumpHeight(1), 4),
  peak - rules.START_HEIGHT);

/* --- вода, овраги, ступени --------------------------------------------------- */

section('Вода, овраги, ступени');

state = start('G200 W80 G300 F G100');
let seen = types(state, 2.2, SOFT);
check('шагом в воду — всплеск', seen.includes('splash') && state.falls === 1, seen.join(','));
check('после всплеска паук тонет и ждёт', state.respawn > 0 && state.y < rules.WATER_LEVEL);
walk(state, rules.RESPAWN + 0.1, 0);
check('потом возвращается в начало карты', state.x === rules.START_X && state.y === rules.START_HEIGHT && state.grounded, state.x);

state = start('G200 C G100 W80 G300 F G100');
seen = types(state, 1.5, SOFT);
check('метка отмечается на ходу', seen.includes('checkpoint') && state.checkpoint === 0, seen.join(','));
walk(state, 1.2, SOFT);                                          /* дальше — в воду */
check('за меткой — вода', state.falls === 1 && state.respawn > 0, state.x);
walk(state, rules.RESPAWN + 0.1, 0);
check('после метки паук возвращается к ней, а не в начало',
  state.x === 200 - rules.FOOT - 6 && state.grounded && state.falls === 1, state.x);

/* метка на самом краю: перед ней вода, за ней овраг — паук встаёт туда, где есть земля */
let edge = rules.createRun(rules.buildLevel('G200 W60 C G100 F G50'));
edge.checkpoint = 0;
check('метка сразу за водой: паук встаёт за меткой', rules.respawnPoint(edge).x === 260 + rules.FOOT + 6);
edge = rules.createRun(rules.buildLevel('G200 C R80 G100 F G50'));
edge.checkpoint = 0;
check('метка перед оврагом: паук встаёт до оврага', rules.respawnPoint(edge).x === 200 - rules.FOOT - 6 &&
  rules.respawnPoint(edge).y === rules.START_HEIGHT);

/* возвращается под крик, с которым упал, — и не должен тут же прыгнуть снова */
state = start('G200 W80 G300 F G100');
walk(state, 1.5 + rules.RESPAWN + 1, 1);
const afterRespawn = state.jumps;
walk(state, 0.5, 1);
check('тот же крик после возвращения прыжка не даёт', state.jumps === afterRespawn, state.jumps + ' / ' + afterRespawn);

state = start('G200 W80 G300 F G100');
seen = types(state, 6, (s) => (s.grounded && rules.groundAt(s.level, s.x + rules.FOOT + 4) === -Infinity ? 1 : SOFT));
check('крик у кромки переносит через воду', state.falls === 0 && state.over === 'win', state.x + ' ' + seen.join(','));

state = start('G200 R90 G300 F G100');
seen = types(state, 6, SOFT);
check('шагом в овраг — паук в овраге, но цел', seen.includes('ravine') && state.falls === 0 && state.inRavine);
check('шагом из оврага не выйти', state.x <= 290 - rules.FOOT && seen.includes('wall'), state.x);
seen = types(state, 3, (s, t) => (t < 0.1 ? 0 : t < 0.3 ? 1 : SOFT));
check('прыжком — выйти', seen.includes('ravine_out') && state.x > 290 && !state.inRavine, state.x + ' ' + seen.join(','));

state = start('G200 U' + rules.STEP_UP + ' G200 F G100');
walk(state, 4, SOFT);
check('низкую ступеньку паук одолевает шагом', state.over === 'win', state.x);

state = start('G200 U' + (rules.STEP_UP + 6) + ' G200 F G100');
seen = types(state, 4, SOFT);
check('высокая ступенька — стена', state.x <= 200 - rules.FOOT && seen.includes('wall'), state.x);
check('о стене сообщается один раз', seen.filter(type => type === 'wall').length === 1);
walk(state, 4, (s, t) => (t < 0.1 ? 0 : t < 0.3 ? loudLevel(0.3) : SOFT));
check('на высокую ступеньку — прыжком', state.over === 'win', state.x);

state = start('G200 D40 G200 F G100');
walk(state, 4, SOFT);
check('со ступеньки вниз паук просто спрыгивает', state.over === 'win' && state.falls === 0, state.x);

/* паук ни в какой момент не оказывается внутри земли */
state = start(rules.LEVELS[1].spec);
let inside = 0;
walk(state, 40, (s, t) => (t % 1.3 < 0.2 ? 1 : SOFT), (event, s) => {
  if (s.respawn <= 0 && s.y < rules.groundAt(s.level, s.x) - rules.STEP_UP - 0.01) { inside++; }
});
check('паук не проваливается в землю', inside === 0, inside);

/* --- карты проходимы ----------------------------------------------------------- */

section('Карты проходимы');

function clone(run) { return Object.assign({}, run); }

/** Куда приведёт прыжок силы power с этого места: 'ground', 'ravine' или 'water'. */
function outcome(run, power) {
  const probe = clone(run);
  probe.armed = true;
  let t = 0;
  while (t < 4) {
    rules.step(probe, DT, t < rules.STARTLE + 0.02 ? loudLevel(power) : SOFT);
    t += DT;
    if (probe.respawn > 0) { return 'water'; }
    if (probe.grounded && t > rules.STARTLE + 0.05) { return probe.inRavine ? 'ravine' : 'ground'; }
  }
  return 'water';
}

/** Игрок, который идёт вполголоса и перед препятствием кричит с наименьшей достаточной силой. */
function pilot() {
  let shout = null;                                /* {level, until} — крик в разгаре */
  return function (run, t) {
    if (shout) {
      if (t < shout.until) { return shout.level; }
      shout = null;
    }
    if (!run.grounded || run.startle >= 0 || !run.armed) { return SOFT; }
    const lead = run.x + rules.FOOT + 5;
    const here = run.y;
    const ahead = rules.segmentAt(run.level, lead);
    const water = !ahead;
    const wall = ahead && ahead.top > here + rules.STEP_UP;
    const pit = ahead && ahead.ravine && ahead.top < here - rules.STEP_UP;
    if (!water && !wall && !pit) { return SOFT; }
    const powers = [0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1];
    let chosen = powers.find(power => outcome(run, power) === 'ground');
    if (chosen === undefined && (water || wall)) { chosen = powers.find(power => outcome(run, power) === 'ravine'); }
    if (chosen === undefined) { return SOFT; }       /* рано: ещё шаг */
    shout = { level: loudLevel(chosen), until: t + rules.STARTLE + 0.03 };
    return shout.level;
  };
}

function attempt(spec, seconds) {
  const run = start(spec);
  walk(run, seconds, pilot());
  return run;
}

rules.LEVELS.forEach(item => {
  const run = attempt(item.spec, 150);
  check('карта «' + item.name + '» проходима без купаний', run.over === 'win' && run.falls === 0,
    'x=' + Math.round(run.x) + ' из ' + run.level.finish + ', купаний ' + run.falls);
  check('карта «' + item.name + '» проходится быстрее двух минут', run.time < 120, run.time);
  check('за прохождение карты «' + item.name + '» — три звезды', rules.stars(run) === 3);

  const quiet = start(item.spec);
  walk(quiet, 60, SOFT);
  check('одним тихим голосом карту «' + item.name + '» не пройти', quiet.over !== 'win' && quiet.falls > 0);
});

/* на третьей карте без сильного крика не обойтись */
const hardest = rules.buildLevel(rules.LEVELS[2].spec);
let widest = 0;
let previous = hardest.segments[0];
hardest.segments.slice(1).forEach(segment => {
  widest = Math.max(widest, segment.x0 - previous.x1);
  previous = segment;
});
check('самая широкая вода шире слабого прыжка', widest > rules.jumpLength(0) + 2 * rules.FOOT, widest);
check('и уже сильного', widest < rules.jumpLength(1) + 2 * rules.FOOT, widest);

let passed = 0;
let total = 0;
const stuck = [];
[0, 0.5, 1].forEach(difficulty => {
  for (let seed = 1; seed <= 40; seed++) {
    total++;
    const spec = rules.generate(seed * 7919 + Math.round(difficulty * 10), difficulty);
    const run = attempt(spec, 180);
    if (run.over === 'win' && run.falls === 0) { passed++; } else { stuck.push(spec); }
  }
});
check('случайные карты проходимы без купаний', passed === total, passed + ' из ' + total + '; ' + (stuck[0] || ''));
check('одно зерно — одна карта', rules.generate(42, 0.5) === rules.generate(42, 0.5));
check('разные зёрна — разные карты', rules.generate(42, 0.5) !== rules.generate(43, 0.5));

check('звёзды: без купаний — три', rules.stars({ falls: 0 }) === 3);
check('звёзды: два купания — две', rules.stars({ falls: 2 }) === 2);
check('звёзды: три купания — одна', rules.stars({ falls: 3 }) === 1);

/* --- громкость в уровень голоса ------------------------------------------------ */

section('Громкость в уровень голоса');

let calibration = rules.calibrate(-58);
check('порог «идти» — выше шума комнаты', calibration.quiet === -58 + rules.QUIET_MARGIN, calibration.quiet);
check('порог «прыгать» — выше порога «идти»', calibration.loud === calibration.quiet + rules.LOUD_MARGIN, calibration.loud);
check('шум комнаты — тишина', rules.levelFromDb(-58, calibration) === 0);
check('на пороге «идти» уровень равен QUIET', near(rules.levelFromDb(calibration.quiet, calibration), rules.QUIET, 1e-9));
check('на пороге «прыгать» уровень равен LOUD', near(rules.levelFromDb(calibration.loud, calibration), rules.LOUD, 1e-9));
check('чуть ниже порога «идти» — ещё тишина', rules.levelFromDb(calibration.quiet - 0.5, calibration) < rules.QUIET);
check('самый громкий звук — единица', rules.levelFromDb(calibration.loud + rules.LOUD_RANGE, calibration) === 1 &&
  rules.levelFromDb(0, calibration) === 1);
let rising = true;
for (let db = -80; db < 0; db += 0.5) {
  if (rules.levelFromDb(db + 0.5, calibration) < rules.levelFromDb(db, calibration)) { rising = false; }
}
check('уровень растёт вместе с громкостью', rising);

calibration = rules.calibrate(-20);                                /* очень шумная комната */
check('в шуме пороги не уходят за край шкалы', calibration.quiet <= -24 && calibration.loud <= -8 &&
  calibration.loud >= calibration.quiet + 8, JSON.stringify(calibration));
calibration = rules.calibrate(-95);                                /* цифровая тишина */
check('в полной тишине порог «идти» не опускается до шороха', calibration.quiet === -52, calibration.quiet);

calibration = { quiet: -40, loud: -12 };                           /* высокий порог: выше −5 дБ микрофон не передаёт */
check('до самого сильного прыжка можно докричаться', rules.levelFromDb(rules.LOUD_TOP, calibration) === 1 &&
  rules.levelFromDb(rules.LOUD_TOP - 1, calibration) < 1 && rules.levelFromDb(-12, calibration) === rules.LOUD,
  rules.levelFromDb(rules.LOUD_TOP, calibration));

/* --- настройка по шуму и голосу -------------------------------------------------- */

section('Настройка по шуму и голосу');

const silence = [-61, -58, -60, -12, -59];                         /* в тишине что-то стукнуло */
check('шум комнаты — медиана: стук её не сдвигает', rules.noiseOf(silence) === -59, rules.noiseOf(silence));
check('замеры при этом не переставляются', silence.join() === '-61,-58,-60,-12,-59');
check('без замеров шума нет', rules.noiseOf([]) === null);

const NOISE = -58;
const VOICE = -30;

/** 150 замеров (2,5 с): фраза в to замеров (гласные около vowel дБ, согласные на 12 дБ тише), дальше тишина. */
function phrase(vowel, to) {
  const values = [];
  for (let i = 0; i < 150; i++) {
    if (i >= to) { values.push(NOISE + (i % 3)); }
    else { values.push(i % 5 < 3 ? vowel + (i % 3) - 1 : vowel - 12); }
  }
  return values;
}

let heard = rules.voiceOf(phrase(VOICE, 110), NOISE);
check('спокойный голос — громкость ударных гласных', heard !== null && Math.abs(heard - VOICE) <= 1, heard);
check('одного слова хватает', rules.voiceOf(phrase(VOICE, 30), NOISE) !== null);                /* полсекунды */
check('кашель — не голос', rules.voiceOf(phrase(VOICE, 12), NOISE) === null);                  /* пятая доля секунды */
check('тишина — не голос', rules.voiceOf(phrase(VOICE, 0), NOISE) === null && rules.voiceOf([], NOISE) === null);
check('шёпот на уровне шума — не голос', rules.voiceOf(phrase(NOISE + 4, 110), NOISE) === null);

calibration = rules.calibrate(NOISE, heard);
check('порог «идти» — между шумом и голосом', calibration.quiet > NOISE + rules.VOICE_GAP && calibration.quiet < heard - 3,
  JSON.stringify(calibration));
check('порог «прыгать» — громче спокойного голоса', calibration.loud === heard + rules.VOICE_HEADROOM, calibration.loud);
const felt = db => rules.levelFromDb(db, calibration);
check('от спокойного голоса паук идёт, а не прыгает', felt(heard) >= rules.QUIET && felt(heard) < rules.LOUD, felt(heard));
check('ударный слог — ещё не прыжок', felt(heard + 5) < rules.LOUD, felt(heard + 5));
check('согласные паука не останавливают', felt(heard - 12) >= rules.QUIET, felt(heard - 12));
check('шум комнаты — тишина и после настройки', felt(NOISE + 3) < rules.QUIET, felt(NOISE + 3));
check('громкий голос — прыжок', felt(heard + rules.VOICE_HEADROOM) >= rules.LOUD);
check('самый сильный прыжок — от крика', felt(heard + rules.VOICE_HEADROOM + rules.LOUD_RANGE) === 1);
/* ради этого голос и замеряется: по одному шуму тот же голос в тихой комнате уже «громкий» */
check('по одному шуму спокойный голос был бы прыжком', rules.levelFromDb(heard, rules.calibrate(NOISE)) >= rules.LOUD,
  rules.levelFromDb(heard, rules.calibrate(NOISE)));

check('голос не громче шума — пороги по шуму', JSON.stringify(rules.calibrate(NOISE, NOISE + rules.VOICE_GAP)) ===
  JSON.stringify(rules.calibrate(NOISE)) && JSON.stringify(rules.calibrate(NOISE, null)) === JSON.stringify(rules.calibrate(NOISE)));
calibration = rules.calibrate(-100, VOICE);                        /* микрофон сам глушит тишину */
check('у микрофона без шума порог «идти» держится возле голоса', calibration.quiet === VOICE - rules.VOICE_REACH,
  calibration.quiet);
calibration = rules.calibrate(-45, -12);                           /* голос доходит слишком громким */
check('порог «прыгать» оставляет место для крика', calibration.loud <= rules.LOUD_TOP - 5 &&
  rules.levelFromDb(rules.LOUD_TOP, calibration) === 1, JSON.stringify(calibration));

let sane = true;
let odd = '';
for (let noise = -80; noise <= -35; noise += 5) {
  for (let voice = noise + 10; voice <= -19; voice += 3) {
    if (voice < -50) { continue; }                                 /* тише −50 дБ игра советует прибавить усиление */
    const found = rules.calibrate(noise, voice);
    const walking = rules.levelFromDb(voice, found);
    if (!(found.quiet > noise && found.quiet <= voice - 3 && found.quiet >= -60 &&
        found.loud === voice + rules.VOICE_HEADROOM && walking >= rules.QUIET && walking < rules.LOUD &&
        rules.levelFromDb(noise, found) < rules.QUIET && rules.levelFromDb(rules.LOUD_TOP, found) === 1)) {
      sane = false;
      odd = odd || JSON.stringify(found);
    }
  }
}
check('при любом шуме и голосе: шум — стоять, спокойный голос — идти, до крика есть запас', sane, odd);

console.log('\n' + (failures ? 'Провалено проверок: ' + failures + ' из ' + checks : 'Все проверки пройдены: ' + checks));
process.exit(failures ? 1 : 0);
