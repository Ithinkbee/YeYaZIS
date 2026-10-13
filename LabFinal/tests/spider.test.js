/* Проверка геометрии паука вне браузера.
 *
 * Геометрия лежит в poklon/web/static/spider.js. Запускается из pytest
 * (tests/test_scripts.py), а вручную так:
 *
 *     node tests/spider.test.js
 *
 * Ноги паука не нарисованы, а вычисляются: по креплению и стопе находится
 * колено. Здесь то же, что проверялось в лабораторных, — сегменты ног не
 * растягиваются, стопы стоят на земле, левая сторона отражает правую, — но
 * для каждого вида: у сенокосца ноги вдвое длиннее, у птицееда — короче.
 *
 * Рисунок тоже проверяется, насколько это возможно без браузера: паук
 * рисуется на поддельном холсте, который принимает любые команды. Так
 * ловятся опечатки в рисунке видов, гардероба и вещей лабораторных.
 */

'use strict';

const path = require('path');
const Spider = require(path.join(__dirname, '..', 'poklon', 'web', 'static', 'spider.js'));

let failures = 0;
let checks = 0;

function check(name, condition, detail) {
  checks++;
  if (condition) { return; }
  failures++;
  console.log('  ОШИБКА: ' + name + (detail !== undefined ? ' — ' + detail : ''));
}

function section(title) { console.log('\n' + title); }

const kinds = Object.keys(Spider.KINDS);
const modes = ['hang', 'stand', 'splay'];

section('Колено по креплению и стопе');
{
  const solved = Spider.solveLeg(0, 0, 30, 20, 26, 40, 1, false);
  check('бедро не растянуто', Math.abs(Math.hypot(solved.kx, solved.ky) - 26) < 1e-6);
  check('голень не растянута', Math.abs(Math.hypot(solved.fx - solved.kx, solved.fy - solved.ky) - 40) < 1e-6);
  check('колено выше прямой «крепление — стопа»', solved.ky < 20 * solved.kx / 30);
  const far = Spider.solveLeg(0, 0, 500, 0, 26, 40, 1, false);
  check('до далёкой точки нога вытягивается в прямую', Math.abs(far.fx - 65.99) < 0.02 && Math.abs(far.fy) < 1e-6, far.fx);
  const left = Spider.solveLeg(0, 0, -30, 20, 26, 40, -1, false);
  check('левая нога — отражение правой', Math.abs(left.kx + solved.kx) < 1e-9 && Math.abs(left.ky - solved.ky) < 1e-9);
}

section('Виды');
kinds.forEach((kind) => {
  const form = Spider.shape(kind);
  check(kind + ': восемь ног', form.legs.length === 8);
  check(kind + ': глаза помещаются на голове', form.eyeX + form.eye <= form.head.rx - 0.5, form.eyeX + form.eye + ' > ' + form.head.rx);
  check(kind + ': глаза не слипаются', form.eyeX >= form.eye + 0.5, form.eyeX + ' / ' + form.eye);
  check(kind + ': рот — на голове', form.mouthY + 4.8 * form.hy <= form.head.ry + 0.6, form.mouthY);
  check(kind + ': брюшко касается головы', form.abdomen.y + form.abdomen.ry > -form.head.ry && form.abdomen.y < 0);
  check(kind + ': нить крепится к верху брюшка', form.thread < form.abdomen.y && form.thread > form.abdomen.y - form.abdomen.ry - 0.01);

  modes.forEach((mode) => {
    [0, 1].forEach((raise) => {
      const joints = Spider.pose(form, { mode: mode, sway: 1.7, lean: -1.5, raiseRight: raise, raiseLeft: raise * 0.5, wave: 2.2 });
      let exact = true;
      joints.forEach((joint, i) => {
        const leg = form.legs[i];
        if (Math.abs(Math.hypot(joint.kx - joint.ax, joint.ky - joint.ay) - leg.femur) > 1e-6) { exact = false; }
        if (Math.abs(Math.hypot(joint.fx - joint.kx, joint.fy - joint.ky) - leg.tibia) > 1e-6) { exact = false; }
      });
      check(kind + ', ' + mode + (raise ? ', нога поднята' : '') + ': сегменты не растянуты', exact);
    });
  });

  const standing = Spider.pose(form, { mode: 'stand' });
  check(kind + ': стоящий стоит на земле', standing.every((joint) => Math.abs(joint.fy - form.ground) < 1e-6));
  check(kind + ': колени стоящего выше стоп', standing.every((joint) => joint.ky < joint.fy));
  let mirrored = true;
  for (let i = 0; i < 8; i += 2) {
    if (Math.abs(standing[i].fx + standing[i + 1].fx) > 1e-9 || Math.abs(standing[i].kx + standing[i + 1].kx) > 1e-9) { mirrored = false; }
  }
  check(kind + ': левая сторона — отражение правой', mirrored);
  let fan = true;
  for (let i = 2; i < 8; i += 2) { if (standing[i].fx >= standing[i - 2].fx) { fan = false; } }
  check(kind + ': стопы стоят веером, не пересекаясь', fan);

  const waving = Spider.pose(form, { mode: 'stand', raiseRight: 1 });
  check(kind + ': поднятая нога выше головы', waving[0].fy < -form.head.ry, waving[0].fy);
  check(kind + ': остальные ноги стоят', waving.slice(1).every((joint) => Math.abs(joint.fy - form.ground) < 1e-6));
  const bowing = Spider.pose(form, { mode: 'stand', lean: 3 });
  check(kind + ': приседая, стопы не отрывает', bowing.every((joint) => Math.abs(joint.fy - form.ground) < 1e-6));
});

section('Отличия видов');
{
  const cross = Spider.shape('cross');
  check('сенокосец стоит выше крестовика', Spider.shape('longlegs').ground > cross.ground * 1.5);
  check('у скакуна самые большие глаза', kinds.every((kind) => Spider.shape(kind).eye <= Spider.shape('jumper').eye));
  check('птицеед мохнатый и толстоногий', Spider.shape('tarantula').fuzz && Spider.shape('tarantula').thick > 1.5);
  check('бокоход шире крестовика', Spider.shape('crab').width > cross.width);
  check('крестовик — как в лабораторных', cross.head.rx === 19 && cross.abdomen.rx === 27 && Math.abs(cross.abdomen.y + 26) < 0.05 && cross.eye === 6.3);
  check('у каждого вида свой рисунок или своя стать', new Set(kinds.map((kind) => {
    const form = Spider.shape(kind);
    return [form.pattern, form.head.rx, form.abdomen.rx, form.thick].join();
  })).size === kinds.length);
}

section('Опора и цвета');
{
  const form = Spider.shape('cross');
  check('висящий держится за нить', Spider.anchorOffset(form, 'thread') === form.thread);
  check('стоящий — за землю', Spider.anchorOffset(form, 'feet') === form.ground);
  const eyes = Spider.eyes(100, 200, 2, 'feet', { kind: 'cross' });
  check('глаза — по обе стороны от оси', Math.abs((eyes.left + eyes.right) / 2 - 100) < 1e-9 && eyes.r === 12.6);
  check('глаза выше стоп', eyes.y < 200);
  const colours = Spider.tones(350, 58, 44);
  check('тона — строки цвета', ['body', 'dark', 'light', 'leg', 'mark'].every((key) => typeof colours[key] === 'string'));
  check('тень темнее тела, блик светлее', colours.dark !== colours.body && colours.light !== colours.body);
  check('Пафнутий фиолетовый, как в лабораторных', Spider.PAFNUTY.body === '#5b3d8a' && Spider.PAFNUTY.leg === '#2f1f4d');
  check('в гардеробе есть бабочка', typeof Spider.WEAR.bowtie === 'function');
}

section('Вещи лабораторных');
{
  const form = Spider.shape('cross');
  const one = Spider.pose(form, { mode: 'stand', raiseRight: 0.8, raiseLeft: 0.8, wave: 1.3, hand: 1 });
  const two = Spider.pose(form, { mode: 'stand', raiseRight: 0.8, raiseLeft: 0.8, wave: 2.9, hand: 1 });
  check('нога с вещью не машет', one[0].fx === two[0].fx && one[0].fy === two[0].fy);
  check('свободная нога машет', one[1].fx !== two[1].fx);
  check('вещь поднята выше головы', one[0].fy < -form.head.ry * 0.8, one[0].fy);
  const left = Spider.pose(form, { mode: 'stand', raiseRight: 0.8, raiseLeft: 0.8, wave: 1.3, hand: -1 });
  const leftAgain = Spider.pose(form, { mode: 'stand', raiseRight: 0.8, raiseLeft: 0.8, wave: 2.9, hand: -1 });
  check('вещь можно держать и левой', left[1].fx === leftAgain[1].fx && left[0].fx !== leftAgain[0].fx);
  check('вещей восемь', ['lens', 'page', 'card', 'scroll', 'scissors', 'note', 'horn', 'mic'].every((name) => typeof Spider.HOLD[name] === 'function') &&
    Object.keys(Spider.HOLD).length === 8, Object.keys(Spider.HOLD).join());
}

section('Рисунок на поддельном холсте');
{
  /* холст, который принимает любые команды и считает их */
  let calls = 0;
  let texts = [];
  const canvas = new Proxy({}, {
    get: (target, name) => {
      if (name === 'measureText') { return (text) => ({ width: String(text).length * 6 }); }
      if (name === 'fillText') { return (text) => { calls++; texts.push(text); }; }
      if (name === 'createRadialGradient' || name === 'createLinearGradient') { return () => ({ addColorStop: () => {} }); }
      if (name in target) { return target[name]; }
      return () => { calls++; };
    },
    set: (target, name, value) => { target[name] = value; return true; }
  });
  const draws = (spec, state, tiny) => {
    const before = calls;
    try {
      Spider.place(canvas, 100, 100, 1.2, 'feet', spec, state, tiny);
    } catch (error) {
      return error.message;
    }
    return calls > before ? '' : 'ничего не нарисовано';
  };
  kinds.forEach((kind) => {
    const spec = { kind: kind, tones: Spider.tones(200, 50, 50), wear: [], seed: 5 };
    const failed = modes.map((mode) => draws(spec, { mode: mode, mouth: 0.7, blink: 0, look: { x: 0.3, y: -0.2 } })).filter(Boolean);
    check(kind + ': рисуется во всех позах', failed.length === 0, failed.join('; '));
    check(kind + ': рисуется издалека', draws(spec, { mode: 'stand', mouth: 0.5 }, true) === '');
  });
  ['open', 'wide', 'happy', 'closed'].forEach((eyes) => {
    check('глаза «' + eyes + '» рисуются', draws({ kind: 'cross', tones: Spider.PAFNUTY, wear: [] }, { mode: 'hang', eyes: eyes, mouth: 0 }) === '');
  });
  Object.keys(Spider.WEAR).forEach((item) => {
    check('из гардероба рисуется ' + item, draws({ kind: 'jumper', tones: Spider.PAFNUTY, wear: [item] }, { mode: 'stand' }) === '');
  });
  Object.keys(Spider.HOLD).forEach((item) => {
    const spec = { kind: 'baby', tones: Spider.PAFNUTY, wear: [], prop: item === 'card' ? 'card:RU' : item };
    const right = draws(spec, { mode: 'stand', raiseRight: 0.8, hand: 1, mouth: 0.8 });
    const other = draws(spec, { mode: 'stand', raiseLeft: 0.8, hand: -1, mouth: 0 });
    check('вещь рисуется в любой ноге: ' + item, right === '' && other === '', right || other);
  });
  check('надпись на табличке — та, что задана', texts.indexOf('RU') >= 0, texts.join());
  texts = [];
  check('надпись с двоеточием не теряется', draws({ kind: 'cross', tones: Spider.PAFNUTY, prop: 'card:a:b' }, { mode: 'stand', raiseRight: 0.8, hand: 1 }) === '' &&
    texts.join() === 'a:b', texts.join());
  const unknown = { kind: 'cross', tones: Spider.PAFNUTY, wear: ['нет такого'], prop: 'нет такой' };
  check('неизвестная вещь просто не рисуется', draws(unknown, { mode: 'stand', raiseRight: 0.8, hand: 1 }) === '');
  const count = (spec, state) => { const before = calls; draws(spec, state); return calls - before; };
  const held = { kind: 'cross', tones: Spider.PAFNUTY, wear: [], prop: 'lens' };
  check('без поднятой ноги вещь не рисуется', count(held, { mode: 'stand' }) < count(held, { mode: 'stand', raiseRight: 0.8, hand: 1 }));
  check('дирижёрская палочка рисуется', count({ kind: 'cross', tones: Spider.PAFNUTY, wear: ['bowtie'] }, { mode: 'hang', baton: true }) >
    count({ kind: 'cross', tones: Spider.PAFNUTY, wear: ['bowtie'] }, { mode: 'hang' }));
}

console.log('\nпроверок: ' + checks + ', ошибок: ' + failures);
process.exit(failures ? 1 : 0);
