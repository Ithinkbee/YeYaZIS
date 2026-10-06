/* Проверка геометрии модели Пафнутия вне браузера.
 *
 * Геометрия лежит в sluhach/web/static/pafnuty.js и экспортируется через
 * module.exports — ради этой проверки. Запускается из pytest
 * (tests/test_games.py), а вручную так:
 *
 *     node tests/pafnuty_model.test.js
 *
 * Ноги паука не нарисованы, а вычисляются: по креплению и стопе находится
 * колено. Проверяется, что сегменты ног при этом не растягиваются, стопы
 * стоят на земле, походка замкнута в цикл, а левая сторона — отражение
 * правой.
 */

'use strict';

const path = require('path');
const model = require(path.join(__dirname, '..', 'sluhach', 'web', 'static', 'pafnuty.js'));

let failures = 0;
let checks = 0;

function check(name, condition, detail) {
  checks++;
  if (condition) { return; }
  failures++;
  console.log('  ОШИБКА: ' + name + (detail !== undefined ? ' — ' + detail : ''));
}

function section(title) { console.log('\n' + title); }

function near(a, b, tolerance) { return Math.abs(a - b) <= (tolerance || 1e-6); }

function distance(ax, ay, bx, by) { return Math.sqrt((ax - bx) * (ax - bx) + (ay - by) * (ay - by)); }

/* --- строение -------------------------------------------------------------- */

section('Строение');

check('ног восемь', model.LEGS.length === 8, model.LEGS.length);
check('по четыре с каждой стороны', model.LEGS.filter(leg => leg.side > 0).length === 4 &&
  model.LEGS.filter(leg => leg.side < 0).length === 4);
model.LEGS.filter(leg => leg.side > 0).forEach(right => {
  const left = model.LEGS.find(leg => leg.side < 0 && leg.index === right.index);
  check('левая нога ' + right.index + ' — отражение правой',
    near(left.anchor[0], 2 * model.CENTER - right.anchor[0]) && near(left.anchor[1], right.anchor[1]) &&
    near(left.stand[0], 2 * model.CENTER - right.stand[0]) && left.femur === right.femur && left.tibia === right.tibia);
  check('парные ноги ' + right.index + ' шагают в противофазе', near(Math.abs(left.phase - right.phase), 0.5));
});
const rightSide = model.LEGS.filter(leg => leg.side > 0);
check('соседние ноги одной стороны шагают в противофазе', rightSide.every((leg, i) =>
  i === 0 || near(Math.abs((leg.phase - rightSide[i - 1].phase) % 1), 0.5, 0.06)));
check('чем дальше нога от головы, тем она короче', rightSide.every((leg, i) =>
  i === 0 || leg.femur + leg.tibia < rightSide[i - 1].femur + rightSide[i - 1].tibia));
check('стоя стопы не пересекаются: передняя нога — самая дальняя', rightSide.every((leg, i) =>
  i === 0 || leg.stand[0] < rightSide[i - 1].stand[0]));
check('все стопы стоят на одной высоте', model.LEGS.every(leg => leg.stand[1] === model.GROUND));

/* --- колено ------------------------------------------------------------------- */

section('Колено');

let solved = model.solveLeg(0, 0, 30, 40, 30, 40, 1);
check('сегменты сохраняют длину', near(distance(0, 0, solved.kx, solved.ky), 30, 1e-6) &&
  near(distance(solved.kx, solved.ky, solved.fx, solved.fy), 40, 1e-6));
check('стопа остаётся там, куда её поставили', near(solved.fx, 30) && near(solved.fy, 40));

solved = model.solveLeg(0, 0, 500, 0, 30, 40, 1);
check('до далёкой точки нога вытягивается в прямую', near(solved.fx, 70, 0.05) && near(solved.fy, 0, 0.05) &&
  near(solved.kx, 30, 0.6), solved.fx + ', ' + solved.kx);
solved = model.solveLeg(0, 0, 1, 0, 30, 40, 1);
check('слишком близкая точка отодвигается: нога не складывается внутрь себя',
  near(distance(0, 0, solved.fx, solved.fy), 10, 0.05), distance(0, 0, solved.fx, solved.fy));
solved = model.solveLeg(5, 5, 5, 5, 30, 40, 1);
check('стопа в точке крепления не ломает расчёт', Number.isFinite(solved.kx) && Number.isFinite(solved.ky));

const up = model.solveLeg(0, 0, 40, 40, 30, 40, 1);
check('у правой ноги колено выше прямой «крепление — стопа»', up.ky < up.kx * 1, up.kx + ', ' + up.ky);
const mirrored = model.solveLeg(0, 0, -40, 40, 30, 40, -1);
check('у левой ноги колено — зеркально', near(mirrored.kx, -up.kx, 1e-6) && near(mirrored.ky, up.ky, 1e-6));

/* --- позы --------------------------------------------------------------------- */

section('Позы');

function intact(joints, legs) {
  return joints.every((joint, i) =>
    near(distance(joint.ax, joint.ay, joint.kx, joint.ky), legs[i].femur, 1e-6) &&
    near(distance(joint.kx, joint.ky, joint.fx, joint.fy), legs[i].tibia, 1e-6));
}

const poses = {
  'висит': { mode: 'hang' },
  'висит и качается': { mode: 'hang', sway: 2.4, lean: 1.5 },
  'прислушивается': { mode: 'hang', raise: 1, facing: -0.35 },
  'стоит': { mode: 'stand' },
  'идёт': { mode: 'stand', walk: 0.37, moving: 1, facing: 1 },
  'приседает': { mode: 'stand', lean: 7 },
  'прыгает': { mode: 'stand', air: 1, lean: -3, facing: 1 },
  'в воде': { mode: 'swim', sway: 5.1 }
};
Object.keys(poses).forEach(name => {
  const joints = model.pose(poses[name]);
  check('поза «' + name + '»: восемь ног', joints.length === 8);
  check('поза «' + name + '»: сегменты ног не растянуты', intact(joints, model.LEGS));
  check('поза «' + name + '»: все координаты — числа', joints.every(joint =>
    [joint.ax, joint.ay, joint.kx, joint.ky, joint.fx, joint.fy].every(Number.isFinite)));
});

let standing = model.pose({ mode: 'stand' });
check('стоя все стопы на земле', standing.every(joint => near(joint.fy, model.GROUND, 1e-6) && joint.grounded));
check('стоя колени выше стоп', standing.every(joint => joint.ky < joint.fy));
check('стоя колени снаружи от креплений', standing.every(joint => joint.side * (joint.kx - joint.ax) > 0));
check('стоя поза симметрична', standing.filter(j => j.side > 0).every(right => {
  const left = standing.find(j => j.side < 0 && j.index === right.index);
  return near(left.kx, 2 * model.CENTER - right.kx, 1e-6) && near(left.ky, right.ky, 1e-6);
}));

const hanging = model.pose({ mode: 'hang' });
check('вися стопы ниже тела', hanging.every(joint => joint.fy > 80));
const listening = model.pose({ mode: 'hang', raise: 1 });
check('прислушиваясь, паук поднимает передние ноги', listening.filter(j => j.index === 0).every(j => j.fy < 50) &&
  listening.filter(j => j.index > 0).every((j, i) => near(j.fy, hanging.filter(h => h.index > 0)[i].fy, 1e-6)));
const jumping = model.pose({ mode: 'stand', air: 1 });
check('в прыжке ноги растопырены шире, чем стоя', jumping.every((joint, i) =>
  Math.abs(joint.fx - model.CENTER) >= Math.abs(standing[i].fx - model.CENTER) - 1e-6 && !joint.grounded));

/* --- походка -------------------------------------------------------------------- */

section('Походка');

check('шаг замкнут в цикл', near(model.gait(0.25).dx, model.gait(1.25).dx) && near(model.gait(0.8).dy, model.gait(3.8).dy));
check('на опоре стопа не поднимается', [0, 0.1, 0.3, 0.59].every(phase => model.gait(phase).dy === 0 && model.gait(phase).grounded));
check('в переносе стопа поднята', [0.65, 0.8, 0.95].every(phase => model.gait(phase).dy < 0 && !model.gait(phase).grounded));
check('высота переноса — не больше заданной', near(model.gait(model.STANCE + (1 - model.STANCE) / 2).dy, -model.LIFT, 1e-6));
check('на опоре стопа едет назад', model.gait(0.05).dx > model.gait(0.3).dx && model.gait(0.3).dx > model.gait(0.55).dx);
check('в переносе — вперёд', model.gait(0.65).dx < model.gait(0.8).dx && model.gait(0.8).dx < model.gait(0.95).dx);
check('размах шага — заданный', near(model.gait(0).dx - model.gait(model.STANCE - 1e-9).dx, model.STRIDE, 1e-3));
let jump = 0;
for (let phase = 0; phase < 1; phase += 0.001) {
  jump = Math.max(jump, Math.abs(model.gait(phase + 0.001).dx - model.gait(phase).dx));
}
check('стопа движется без рывков', jump < 0.1, jump);

let lifted = 0;
for (let phase = 0; phase < 1; phase += 0.01) {
  const walking = model.pose({ mode: 'stand', walk: phase, moving: 1, facing: 1 });
  lifted = Math.max(lifted, walking.filter(joint => !joint.grounded).length);
  if (walking.filter(joint => joint.grounded).length < 4) { check('на ходу на земле не меньше четырёх ног', false, phase); }
  if (!intact(walking, model.LEGS)) { check('на ходу сегменты ног не растянуты', false, phase); }
}
check('на ходу паук переносит ноги четвёрками', lifted === 4, lifted);

const still = model.pose({ mode: 'stand', walk: 0.4, moving: 0 });
check('без движения походки нет', still.every((joint, i) => near(joint.fx, standing[i].fx, 1e-6)));

/* стопа ищет землю: под правой половиной земля ниже на 10 */
const uneven = model.pose({ mode: 'stand', ground: offset => (offset > 0 ? 10 : 0) });
check('на ступеньке стопы стоят на разной высоте',
  uneven.filter(j => j.side > 0).every(j => near(j.fy, model.GROUND + 10, 1e-6)) &&
  uneven.filter(j => j.side < 0).every(j => near(j.fy, model.GROUND, 1e-6)));
const cliff = model.pose({ mode: 'stand', ground: () => 1000 });
check('над обрывом нога свисает, но не вытягивается без предела', cliff.every(j => j.fy <= model.GROUND + 16 + 1e-6));

console.log('\n' + (failures ? 'Провалено проверок: ' + failures + ' из ' + checks : 'Все проверки пройдены: ' + checks));
process.exit(failures ? 1 : 0);
