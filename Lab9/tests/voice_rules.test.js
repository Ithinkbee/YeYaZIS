/* Проверка правил голосового вывода и шкалы громкости вне браузера.
 *
 * Правила лежат в sluhach/web/static/voice.js и mic.js и экспортируются
 * через module.exports — ради этой проверки. Запускается из pytest
 * (tests/test_games.py), а вручную так:
 *
 *     node tests/voice_rules.test.js
 *
 * Длинный ответ (абзац сочинения) синтезатор читает по частям; проверяется,
 * что при делении не теряется ни одного слова и ни одна часть не длиннее
 * предела. Ещё — выбор голоса по языку и пересчёт уровня сигнала в децибелы.
 */

'use strict';

const path = require('path');
const voice = require(path.join(__dirname, '..', 'sluhach', 'web', 'static', 'voice.js'));
const mic = require(path.join(__dirname, '..', 'sluhach', 'web', 'static', 'mic.js'));

let failures = 0;
let checks = 0;

function check(name, condition, detail) {
  checks++;
  if (condition) { return; }
  failures++;
  console.log('  ОШИБКА: ' + name + (detail !== undefined ? ' — ' + detail : ''));
}

function section(title) { console.log('\n' + title); }

function words(text) { return String(text).split(/\s+/).filter(Boolean); }

/* --- деление текста на части --------------------------------------------------- */

section('Деление текста на части');

check('короткий ответ — одна часть', voice.chunks('Молчу.').length === 1 && voice.chunks('Молчу.')[0] === 'Молчу.');
check('пустой текст — ни одной части', voice.chunks('').length === 0 && voice.chunks('   ').length === 0 &&
  voice.chunks(null).length === 0);

const paragraph = 'Maximilian, regierender Graf von Moor, hat zwei ungleiche Söhne: Karl und Franz. Franz, von Natur aus ' +
  'hässlich, wurde in seiner Kindheit vernachlässigt und hat als Zweitgeborener kein Anrecht auf das Erbe. Karl dagegen ' +
  'war immer des Vaters Lieblingssohn, führte dann aber als Student in Leipzig ein recht leichtsinniges und ungezügeltes ' +
  'Studentenleben und verstrickte sich in Schulden, bevor er Besserung gelobte und seinem Vater einen Brief schrieb, mit ' +
  'dem er seinen Wunsch um Vergebung zum Ausdruck brachte.';
let parts = voice.chunks(paragraph);
check('абзац делится на несколько частей', parts.length >= 3, parts.length);
check('ни одна часть не длиннее предела', parts.every(part => part.length <= voice.CHUNK), parts.map(p => p.length).join(','));
check('слова не теряются и не переставляются', words(parts.join(' ')).join(' ') === words(paragraph).join(' '));
check('первая часть — целые предложения, сколько поместилось', parts[0].startsWith('Maximilian') &&
  parts[0].endsWith('kein Anrecht auf das Erbe.'), parts[0]);
check('длинное предложение делится по запятым', parts.slice(1).some(part => /[,;:]$/.test(part)));

const endless = Array(80).join('слово ') + 'конец';
parts = voice.chunks(endless, 60);
check('текст без знаков препинания делится по словам', parts.length > 5 && parts.every(part => part.length <= 60));
check('и в нём слова не теряются', words(parts.join(' ')).join(' ') === words(endless).join(' '));

parts = voice.chunks('Первое. Второе! Третье? Четвёртое…', 12);
check('короткие предложения — каждое своей частью', parts.length === 4 && parts[1] === 'Второе!', parts.join('|'));
parts = voice.chunks('Первое. Второе! Третье? Четвёртое…', 200);
check('а если помещаются — вместе', parts.length === 1);
parts = voice.chunks('Он сказал: «Кто там?» Никто не ответил.', 22);
check('закрывающая кавычка остаётся при своём предложении', parts[0].endsWith('»'), parts.join('|'));
check('лишние пробелы и переводы строк убираются', voice.chunks('  Раз,\n\n два.   Три.  ')[0] === 'Раз, два. Три.');
const long = 'Сверхдлинноесловобезпробеловкотороенепомещаетсявпредел';
check('слово длиннее предела не теряется', voice.chunks('Вот ' + long + '.', 20).join(' ').indexOf(long) >= 0);

/* --- выбор голоса -------------------------------------------------------------- */

section('Выбор голоса');

const voices = [
  { name: 'Google Deutsch', lang: 'de-DE', localService: false, voiceURI: 'g-de' },
  { name: 'Microsoft Stefan', lang: 'de-DE', localService: true, voiceURI: 'ms-stefan' },
  { name: 'Microsoft Hedda', lang: 'de-DE', localService: true, voiceURI: 'ms-hedda' },
  { name: 'Microsoft Irina', lang: 'ru-RU', localService: true, voiceURI: 'ms-irina' },
  { name: 'Microsoft David', lang: 'en-US', localService: true, voiceURI: 'ms-david' },
  { name: 'Deutsch (Österreich)', lang: 'de_AT', localService: false, voiceURI: 'at' }
];
let ranked = voice.rank(voices, 'de-DE');
check('голоса только нужного языка', ranked.length === 4 && ranked.every(item => /^de/i.test(item.lang)));
check('сначала те, что работают без сети', ranked[0].localService && ranked[1].localService && !ranked[2].localService);
check('внутри группы — по имени', ranked[0].name === 'Microsoft Hedda' && ranked[1].name === 'Microsoft Stefan');
check('русский голос — для русского', voice.rank(voices, 'ru-RU').length === 1 && voice.rank(voices, 'ru')[0].name === 'Microsoft Irina');
check('нет голосов — пустой список', voice.rank(voices, 'fr-FR').length === 0 && voice.rank(null, 'de-DE').length === 0 &&
  voice.rank([], 'de-DE').length === 0);

/* --- громкость ------------------------------------------------------------------ */

section('Громкость');

check('полная шкала — 0 дБ', Math.abs(mic.toDb(1)) < 1e-9);
check('в десять раз тише — на 20 дБ ниже', Math.abs(mic.toDb(0.1) + 20) < 1e-9 && Math.abs(mic.toDb(0.001) + 60) < 1e-9);
check('тишина — нижний предел', mic.toDb(0) === mic.SILENCE_DB && mic.toDb(-1) === mic.SILENCE_DB && mic.toDb(NaN) === mic.SILENCE_DB);
check('очень слабый сигнал не уходит ниже предела', mic.toDb(1e-12) === mic.SILENCE_DB);
check('шкала: края и середина', mic.scale(-70, -70, 0) === 0 && mic.scale(0, -70, 0) === 1 && mic.scale(-35, -70, 0) === 0.5);
check('шкала не выходит за края', mic.scale(-200, -70, 0) === 0 && mic.scale(12, -70, 0) === 1);

console.log('\n' + (failures ? 'Провалено проверок: ' + failures + ' из ' + checks : 'Все проверки пройдены: ' + checks));
process.exit(failures ? 1 : 0);
