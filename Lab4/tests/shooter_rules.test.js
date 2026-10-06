/* Проверка правил тира Пафнутия вне браузера.
 *
 * Правила лежат в dragoman/web/static/shooter_rules.js и экспортируются через
 * module.exports — ради этой проверки. Запускается из pytest
 * (tests/test_game.py), а вручную так:
 *
 *     node tests/shooter_rules.test.js
 *
 * Проверяются расписание появления слов (каждое слово выходит ровно один раз,
 * мелочь — стайками, ворота чередуются), уровни сложности, прочность и
 * раскрытие перевода мини-босса, запас паутины, площадка, попадание снаряда
 * и подсчёт переведённой доли текста.
 */

'use strict';

const path = require('path');
const rules = require(path.join(__dirname, '..', 'dragoman', 'web', 'static', 'shooter_rules.js'));

let failures = 0;
let checks = 0;

function check(name, condition, detail) {
  checks++;
  if (condition) { return; }
  failures++;
  console.log('  ОШИБКА: ' + name + (detail ? ' — ' + detail : ''));
}

function section(title) { console.log('\n' + title); }

function near(a, b, eps) { return Math.abs(a - b) <= (eps || 1e-9); }

// --- противники и сложность ----------------------------------------------------------
section('Противники и сложность');
['swarm', 'walker', 'gunner', 'boss'].forEach((kind) => {
  check('у «' + kind + '» есть скорость, урон и имя',
    rules.KINDS[kind].speed > 0 && rules.KINDS[kind].damage > 0 && rules.KINDS[kind].name);
});
check('мелочь быстрее обычного слова', rules.KINDS.swarm.speed > rules.KINDS.walker.speed);
check('слово с пушкой стреляет издалека и держит дистанцию',
  rules.KINDS.gunner.shootRange > rules.KINDS.gunner.keep && rules.KINDS.gunner.keep > rules.KINDS.walker.melee);
check('мини-босс крупнее всех', rules.KINDS.boss.scale > rules.KINDS.walker.scale);
check('мини-босс кусает вблизи и стреляет очередями издалека',
  rules.KINDS.boss.melee > 0 && rules.KINDS.boss.shootRange > rules.KINDS.boss.melee && rules.KINDS.boss.volley >= 2);
check('трудный уровень опаснее лёгкого',
  rules.damage('walker', 'hard') > rules.damage('walker', 'normal') &&
  rules.damage('walker', 'normal') > rules.damage('walker', 'easy'));
check('и быстрее', rules.speed('swarm', 'hard') > rules.speed('swarm', 'easy'));
check('неизвестная сложность — обычная', rules.damage('gunner', 'nonsense') === rules.damage('gunner', 'normal'));

// --- расписание волны ------------------------------------------------------------------
section('Расписание волны');
function enemies(kinds) {
  return kinds.split('').map((k, i) => ({
    id: i + 1, en: 'w' + i, kind: { s: 'swarm', w: 'walker', g: 'gunner' }[k]
  }));
}
const wave = rules.groupSwarms(enemies('swwgsssgwssws'));
check('перестановка не теряет и не дублирует слова', wave.length === 13 &&
  new Set(wave.map((e) => e.id)).size === 13);
const schedule = rules.spawnSchedule(wave, 'normal', 42);
check('каждое слово выходит ровно один раз',
  schedule.length === wave.length && new Set(schedule.map((s) => s.enemy.id)).size === wave.length);
check('время не убывает', schedule.every((s, i) => i === 0 || s.t >= schedule[i - 1].t));
check('первое слово выходит сразу', schedule[0].t < 1);
check('ворота — в пределах парапета', schedule.every((s) => s.gate >= 0 && s.gate < rules.GATES));
const packs = [];
schedule.forEach((s, i) => {
  if (s.enemy.kind === 'swarm' && i > 0 && schedule[i - 1].enemy.kind === 'swarm' &&
      s.t - schedule[i - 1].t < 0.5) { packs.push(i); }
});
check('мелочь бежит стайками из одних ворот', packs.length > 0 &&
  packs.every((i) => schedule[i].gate === schedule[i - 1].gate));
check('следующая группа выходит из других ворот', schedule.every((s, i) => i === 0 || packs.includes(i) ||
  s.gate !== schedule[i - 1].gate));
const again = rules.spawnSchedule(wave, 'normal', 42);
check('с тем же зерном — то же расписание', JSON.stringify(again) === JSON.stringify(schedule));
const hard = rules.spawnSchedule(wave, 'hard', 42);
const easy = rules.spawnSchedule(wave, 'easy', 42);
check('на трудном уровне волна выходит быстрее', hard[hard.length - 1].t < easy[easy.length - 1].t);
check('пустая волна — пустое расписание', rules.spawnSchedule([], 'normal', 1).length === 0);

// --- мини-босс -----------------------------------------------------------------------------
section('Мини-босс');
check('прочность зависит от сложности',
  rules.bossHp(20, 'easy') < rules.bossHp(20, 'normal') && rules.bossHp(20, 'normal') < rules.bossHp(20, 'hard'));
check('прочность не меньше четырёх', rules.bossHp(1, 'easy') === 4);
check('целый босс — перевод скрыт', rules.bossReveal('Implementierung', 10, 10) === '·'.repeat(15));
check('половина прочности — половина слова', rules.bossReveal('Implementierung', 5, 10) === 'Implemen' + '·'.repeat(7));
check('побеждён — слово целиком', rules.bossReveal('Implementierung', 0, 10) === 'Implementierung');
check('пробелы оборота не прячутся', rules.bossReveal('neuronales Netz', 10, 10) === '·'.repeat(10) + ' ' + '·'.repeat(4));
check('умлауты — одна буква', rules.bossReveal('Übersetzungsfähigkeit', 0, 4).length === 21);

// --- Пафнутий --------------------------------------------------------------------------------
section('Пафнутий');
check('паутина восстанавливается', rules.regenAmmo(0, 1) > 0);
check('но не больше запаса', rules.regenAmmo(rules.PLAYER.ammo - 1, 10) === rules.PLAYER.ammo);
const inside = rules.clampToArena(3, 4, 0.9);
check('внутри площадки точка не двигается', inside[0] === 3 && inside[1] === 4);
const outside = rules.clampToArena(100, 0, 0.9);
check('за краем — возвращается на край', near(outside[0], rules.ARENA_RADIUS - 0.9) && outside[1] === 0);
for (let g = 0; g < rules.GATES; g++) {
  const p = rules.gatePosition(g);
  check('ворота ' + g + ' — у парапета', near(Math.hypot(p[0], p[1]), rules.ARENA_RADIUS - 1.5, 1e-6));
}

// --- попадание ---------------------------------------------------------------------------------
section('Попадание');
const word = [0, 1, 10];
check('снаряд прямо в слово', rules.segmentHitsCylinder([0, 1, 9.5], [0, 1, 10.5], 0.1, word, 0.8, 1));
check('быстрый снаряд, пролетевший слово за кадр, тоже попал',
  rules.segmentHitsCylinder([0, 1, 0], [0, 1, 20], 0.1, word, 0.8, 1));
check('мимо сбоку', !rules.segmentHitsCylinder([3, 1, 0], [3, 1, 20], 0.1, word, 0.8, 1));
check('над словом', !rules.segmentHitsCylinder([0, 4, 0], [0, 4, 20], 0.1, word, 0.8, 1));
check('не долетел', !rules.segmentHitsCylinder([0, 1, 0], [0, 1, 5], 0.1, word, 0.8, 1));
check('неподвижный снаряд внутри слова', rules.segmentHitsCylinder([0.2, 1, 10], [0.2, 1, 10], 0.1, word, 0.8, 1));

// --- итог боя ------------------------------------------------------------------------------------
section('Итог боя');
const words = [{ en: 'the', count: 10 }, { en: 'Compiler', count: 3 }, { en: 'translates', count: 2 }];
check('доля — по вхождениям слов', near(rules.progress({ the: 'der' }, words), 10 / 15));
check('регистр не важен', near(rules.progress({ compiler: 'Compiler' }, words), 3 / 15));
check('ничего не переведено', rules.progress({}, words) === 0);
check('пустой текст', rules.progress({}, []) === 0);
check('поражение — одна звезда', rules.stars({ won: false, shots: 10, hits: 10, hp: 100 }) === 1);
check('победа с меткой стрельбой — три', rules.stars({ won: true, shots: 10, hits: 8, hp: 10 }) === 3);
check('победа «на последнем издыхании» и мимо — две', rules.stars({ won: true, shots: 10, hits: 2, hp: 10 }) === 2);

console.log('\nПроверок: ' + checks + ', ошибок: ' + failures);
process.exit(failures ? 1 : 0);
