/* «Мой говорящий Пафнутий» — паук вместо кота из «Говорящего Тома».
 *
 * Как в «Говорящем Томе»:
 *  • игрок говорит в микрофон — паук слушает (поднимает передние лапы) и
 *    повторяет сказанное смешным голосом. Начало и конец фразы находит
 *    детектор по громкости; запись уходит на сервер, там её поднимают на
 *    7 полутонов (или превращают в робота, шёпот, бас, эхо);
 *  • тычки: голова, глаза, брюшко (щекотно), любая из восьми ног (паук
 *    поджимает именно её), нить. Много тычков подряд — обида: паук уходит
 *    вверх по нити и возвращается через несколько секунд. Провести по
 *    брюшку — погладить; схватить и утащить в сторону — раскачать на нити
 *    (маятник; сильно раскачанный — кружится голова);
 *  • кнопки: муха (покормить), тарелки (напугать), торт (в мордочку),
 *    паутина (сплести), свет (уложить спать), «почитай» — фраза из научной
 *    статьи в очках;
 *  • как в «Моём говорящем Томе» — потребности: сытость, бодрость,
 *    настроение. Они убывают и пока страница закрыта; голодный паук грустит
 *    и просит мух, уставший засыпает сам. Опыт за заботу даёт уровни, уровни
 *    открывают гардероб.
 *
 * Говорит паук по-немецки голосом, который строит сервер, — в облачке
 * перевод. Сверху — правила без DOM (потребности, уровни, попадание по
 * частям тела, детектор фразы), их проверяют тесты; снизу — сцена.
 */

(function (global) {
  'use strict';

  /* --- правила ------------------------------------------------------------------- */

  var NEEDS = ['food', 'energy', 'mood'];
  /** изменение потребностей за минуту бодрствования */
  var DECAY = { food: -0.6, energy: -0.4, mood: -0.5 };
  /** сколько бодрости прибавляется за минуту сна */
  var SLEEP_GAIN = 5;
  /** опыт, с которого начинается уровень */
  var LEVELS = [0, 25, 70, 140, 240, 380, 560, 800, 1100];
  var WARDROBE = [
    { id: 'hat', title: 'цилиндр', icon: '🎩', level: 2 },
    { id: 'glasses', title: 'очки', icon: '👓', level: 3 },
    { id: 'bowtie', title: 'бабочка', icon: '🎀', level: 4 },
    { id: 'headphones', title: 'наушники', icon: '🎧', level: 5 },
    { id: 'crown', title: 'корона', icon: '👑', level: 6 },
    { id: 'cap', title: 'шапочка магистра', icon: '🎓', level: 7 }
  ];
  /** что даёт каждое действие */
  var GAINS = {
    poke: { xp: 1, mood: -2 }, tickle: { xp: 1, mood: 3 }, stroke: { xp: 2, mood: 5 },
    fly: { xp: 6, mood: 6, food: 25, energy: -1 }, web: { xp: 8, mood: 10, energy: -6 },
    echo: { xp: 4, mood: 5, energy: -1 }, say: { xp: 3, mood: 3 }, read: { xp: 5, mood: 4, energy: -1 },
    cymbal: { xp: 1, mood: -6, energy: -1 }, pie: { xp: 1, mood: -8 }, swing: { xp: 2, mood: 2, energy: -2 },
    angry: { mood: -10 }, sleep: { xp: 2 }, dress: { xp: 1, mood: 2 }
  };

  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }

  function fresh(now) {
    return { food: 70, energy: 80, mood: 70, xp: 0, asleep: false, wearing: [], webs: 0, time: now || 0,
             stats: { pokes: 0, legs: 0, flies: 0, echoes: 0, says: 0, webs: 0, pies: 0, cymbals: 0, strokes: 0 } };
  }

  /** Потребности через minutes минут: убывают; во сне прибавляется бодрость. Не больше суток. */
  function decay(state, minutes, asleep) {
    var next = JSON.parse(JSON.stringify(state));
    minutes = clamp(minutes, 0, 24 * 60);
    next.food = clamp(next.food + DECAY.food * minutes, 0, 100);
    next.mood = clamp(next.mood + DECAY.mood * minutes * (asleep ? 0.3 : 1), 0, 100);
    next.energy = clamp(next.energy + (asleep ? SLEEP_GAIN : DECAY.energy) * minutes, 0, 100);
    return next;
  }

  /** Уровень по опыту: номер, границы и доля пути до следующего. */
  function level(xp) {
    var number = 1;
    for (var i = 1; i < LEVELS.length; i++) { if (xp >= LEVELS[i]) { number = i + 1; } }
    var from = LEVELS[number - 1];
    var to = LEVELS[number] === undefined ? null : LEVELS[number];
    return { level: number, from: from, to: to, share: to === null ? 1 : (xp - from) / (to - from) };
  }

  /** Действие -> новое состояние и признак нового уровня. */
  function gain(state, action) {
    var change = GAINS[action] || {};
    var next = JSON.parse(JSON.stringify(state));
    var before = level(next.xp).level;
    next.xp += change.xp || 0;
    NEEDS.forEach(function (need) { next[need] = clamp(next[need] + (change[need] || 0), 0, 100); });
    return { state: next, levelUp: level(next.xp).level > before };
  }

  function unlocked(levelNumber) {
    return WARDROBE.filter(function (item) { return item.level <= levelNumber; });
  }

  /** Выражение «по самочувствию», когда ничего не происходит. */
  function baseline(state) {
    if (state.asleep) { return 'sleeping'; }
    if (state.energy < 15) { return 'sleepy'; }
    if (state.food < 20 || state.mood < 20) { return 'sad'; }
    if (state.mood > 85) { return 'happy'; }
    return 'idle';
  }

  function segmentDistance(px, py, ax, ay, bx, by) {
    var dx = bx - ax;
    var dy = by - ay;
    var length = dx * dx + dy * dy;
    var t = length ? clamp(((px - ax) * dx + (py - ay) * dy) / length, 0, 1) : 0;
    var cx = ax + t * dx - px;
    var cy = ay + t * dy - py;
    return Math.sqrt(cx * cx + cy * cy);
  }

  /**
   * Куда попал тычок: точка в координатах модели (120 × 120), суставы ног —
   * из последней позы, head — сдвиг головы {dx, dy}. Глаза и голова проверяются
   * раньше ног: ноги лежат под ними.
   */
  function hitTest(x, y, joints, head) {
    head = head || { dx: 0, dy: 0 };
    var hx = x - head.dx;
    var hy = y - head.dy;
    var eyes = [[52.5, 68], [67.5, 68]];
    for (var e = 0; e < eyes.length; e++) {
      var ex = hx - eyes[e][0];
      var ey = hy - eyes[e][1];
      if (ex * ex + ey * ey <= 7.5 * 7.5) { return { part: 'eye', side: e }; }
    }
    var head2 = Math.pow((hx - 60) / 20, 2) + Math.pow((hy - 70) / 18, 2);
    if (head2 <= 1) { return { part: 'head' }; }
    var belly = Math.pow((x - 60) / 28, 2) + Math.pow((y - 44) / 26, 2);
    if (belly <= 1) { return { part: 'belly' }; }
    var best = null;
    (joints || []).forEach(function (joint, index) {
      var distance = Math.min(segmentDistance(x, y, joint.ax, joint.ay, joint.kx, joint.ky),
                              segmentDistance(x, y, joint.kx, joint.ky, joint.fx, joint.fy));
      if (distance <= 6 && (!best || distance < best.distance)) { best = { part: 'leg', leg: index, distance: distance }; }
    });
    if (best) { return best; }
    if (Math.abs(x - 60) <= 6 && y < 22) { return { part: 'thread' }; }
    return { part: null };
  }

  /**
   * Детектор фразы по уровню (дБ, каждые 20 мс). Шум комнаты отслеживается,
   * пока игрок молчит; фраза начинается, когда три кадра из пяти громче
   * шума на 12 дБ (и громче −48 дБ), кончается после 700 мс тишины.
   */
  function Detector() {
    this.noise = -60;
    this.speaking = false;
    this.recent = [];
    this.quiet = 0;
    this.length = 0;
  }
  Detector.prototype.feed = function (db) {
    var start = Math.max(this.noise + 12, -48);
    var stay = Math.max(this.noise + 7, -52);
    if (!this.speaking) {
      this.noise += (db - this.noise) * (db > this.noise ? 0.02 : 0.2);
      this.recent.push(db > start);
      if (this.recent.length > 5) { this.recent.shift(); }
      if (this.recent.filter(Boolean).length >= 3) {
        this.speaking = true;
        this.quiet = 0;
        this.length = 0;
        this.recent = [];
        return 'start';
      }
      return null;
    }
    this.length += 20;
    this.quiet = db < stay ? this.quiet + 20 : 0;
    if (this.quiet >= 700 || this.length >= 8000) {
      this.speaking = false;
      return 'end';
    }
    return null;
  };

  var rules = {
    NEEDS: NEEDS, DECAY: DECAY, SLEEP_GAIN: SLEEP_GAIN, LEVELS: LEVELS, WARDROBE: WARDROBE, GAINS: GAINS,
    fresh: fresh, decay: decay, level: level, gain: gain, unlocked: unlocked, baseline: baseline,
    hitTest: hitTest, segmentDistance: segmentDistance, Detector: Detector
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = rules;
    return;
  }
  global.TalkingRules = rules;
  if (!global.Glashatai || !document.getElementById('room')) { return; }

  /* --- сцена ------------------------------------------------------------------------- */

  var G = global.Glashatai;
  var STORE = 'glashatai-pafnuty';

  G.ready(function () {
    var $ = function (id) { return document.getElementById(id); };
    var data = JSON.parse($('game').textContent);
    var room = $('room');
    var hang = $('hang');
    var thread = $('thread');
    var body = $('body');
    var speech = $('speech');
    var model = global.Pafnuty.create({ mode: 'hang' });
    body.appendChild(model.el);

    /* --- состояние ----------------------------------------------------------------- */

    var state = fresh(Date.now());
    try {
      var saved = JSON.parse(global.localStorage.getItem(STORE) || 'null');
      if (saved && typeof saved === 'object') {
        state = Object.assign(fresh(Date.now()), saved);
        state.stats = Object.assign(fresh().stats, saved.stats || {});
        var away = (Date.now() - (saved.time || Date.now())) / 60000;
        state = decay(state, away, state.asleep);
      }
    } catch (e) { /* без хранилища — паук с нуля */ }
    state.time = Date.now();

    function save() {
      state.time = Date.now();
      try { global.localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) { /* без хранилища */ }
    }

    function pick(list) { return list[Math.floor(Math.random() * list.length)]; }
    function lines(occasion) { return data.lines[occasion] || []; }

    function reward(action) {
      var result = gain(state, action);
      state = result.state;
      if (result.levelUp) {
        var number = level(state.xp).level;
        sfx.levelUp();
        var item = WARDROBE.filter(function (w) { return w.level === number; })[0];
        G.toast('Уровень ' + number + '!' + (item ? ' В гардеробе: ' + item.icon + ' ' + item.title : ''), 4000);
        setTimeout(function () { talk('level'); }, 900);
      }
      render();
      save();
    }

    /* --- звук ------------------------------------------------------------------------ */

    var context = null;
    var analyser = null;
    var output = null;
    var current = null;         /* звучащая реплика */
    var speaking = false;
    var talkToken = 0;

    function audio() {
      if (context) { return context; }
      var Context = global.AudioContext || global.webkitAudioContext;
      context = new Context();
      output = context.createGain();
      analyser = context.createAnalyser();
      analyser.fftSize = 512;
      output.connect(analyser);
      analyser.connect(context.destination);
      return context;
    }

    /* звуки игры синтезируются тут же, без файлов */
    var sfx = {
      noise: function (seconds) {
        var ctx = audio();
        var buffer = ctx.createBuffer(1, Math.round(ctx.sampleRate * seconds), ctx.sampleRate);
        var channel = buffer.getChannelData(0);
        for (var i = 0; i < channel.length; i++) { channel[i] = Math.random() * 2 - 1; }
        var source = ctx.createBufferSource();
        source.buffer = buffer;
        return source;
      },
      envelope: function (peak, attack, release) {
        var ctx = audio();
        var gainNode = ctx.createGain();
        var now = ctx.currentTime;
        gainNode.gain.setValueAtTime(0.0001, now);
        gainNode.gain.exponentialRampToValueAtTime(peak, now + attack);
        gainNode.gain.exponentialRampToValueAtTime(0.0001, now + attack + release);
        gainNode.connect(context.destination);
        return gainNode;
      },
      cymbal: function () {
        var source = sfx.noise(1.6);
        var filter = context.createBiquadFilter();
        filter.type = 'highpass';
        filter.frequency.value = 4500;
        source.connect(filter);
        filter.connect(sfx.envelope(0.6, 0.005, 1.4));
        source.start();
      },
      splat: function () {
        var source = sfx.noise(0.35);
        var filter = context.createBiquadFilter();
        filter.type = 'lowpass';
        filter.frequency.value = 900;
        source.connect(filter);
        filter.connect(sfx.envelope(0.8, 0.005, 0.3));
        source.start();
      },
      crunch: function () {
        [0, 0.12, 0.26].forEach(function (delay) {
          var source = sfx.noise(0.06);
          var filter = context.createBiquadFilter();
          filter.type = 'bandpass';
          filter.frequency.value = 2500;
          source.connect(filter);
          var envelope = context.createGain();
          envelope.gain.setValueAtTime(0.5, context.currentTime + delay);
          envelope.gain.exponentialRampToValueAtTime(0.001, context.currentTime + delay + 0.06);
          filter.connect(envelope);
          envelope.connect(context.destination);
          source.start(context.currentTime + delay);
        });
      },
      tone: function (frequency, delay, length, type, volume) {
        var ctx = audio();
        var oscillator = ctx.createOscillator();
        oscillator.type = type || 'sine';
        oscillator.frequency.value = frequency;
        var envelope = ctx.createGain();
        var start = ctx.currentTime + delay;
        envelope.gain.setValueAtTime(0.0001, start);
        envelope.gain.exponentialRampToValueAtTime(volume || 0.25, start + 0.02);
        envelope.gain.exponentialRampToValueAtTime(0.0001, start + length);
        oscillator.connect(envelope);
        envelope.connect(ctx.destination);
        oscillator.start(start);
        oscillator.stop(start + length + 0.05);
        return oscillator;
      },
      levelUp: function () {
        [523, 659, 784, 1046].forEach(function (note, i) { sfx.tone(note, i * 0.11, 0.25, 'triangle', 0.2); });
      },
      trill: function () {
        for (var i = 0; i < 8; i++) { sfx.tone(330 + (i % 2) * 40, i * 0.07, 0.09, 'sine', 0.08); }
      },
      buzz: function (seconds) {
        var ctx = audio();
        var oscillator = ctx.createOscillator();
        oscillator.type = 'sawtooth';
        oscillator.frequency.value = 210;
        var wobble = ctx.createOscillator();
        wobble.frequency.value = 23;
        var depth = ctx.createGain();
        depth.gain.value = 30;
        wobble.connect(depth);
        depth.connect(oscillator.frequency);
        var envelope = ctx.createGain();
        envelope.gain.value = 0.025;
        oscillator.connect(envelope);
        envelope.connect(ctx.destination);
        oscillator.start();
        wobble.start();
        oscillator.stop(ctx.currentTime + seconds);
        wobble.stop(ctx.currentTime + seconds);
      },
      snore: function () {
        var source = sfx.noise(1.4);
        var filter = context.createBiquadFilter();
        filter.type = 'lowpass';
        filter.frequency.value = 380;
        source.connect(filter);
        var envelope = context.createGain();
        var now = context.currentTime;
        envelope.gain.setValueAtTime(0.0001, now);
        envelope.gain.exponentialRampToValueAtTime(0.35, now + 0.7);
        envelope.gain.exponentialRampToValueAtTime(0.0001, now + 1.35);
        filter.connect(envelope);
        envelope.connect(context.destination);
        source.start();
      }
    };

    function stopTalking() {
      talkToken++;
      if (current) {
        try { current.onended = null; current.stop(); } catch (e) { /* уже остановлен */ }
        current = null;
      }
      speaking = false;
    }

    /** Проиграть WAV голосом Пафнутия; обещание выполняется, когда он договорил. */
    function play(buffer) {
      var ctx = audio();
      if (ctx.state === 'suspended') { ctx.resume(); }
      return new Promise(function (resolve) {
        ctx.decodeAudioData(buffer, function (decoded) {
          stopTalking();
          var mine = talkToken;
          var source = ctx.createBufferSource();
          source.buffer = decoded;
          source.connect(output);
          source.onended = function () {
            if (mine === talkToken) { speaking = false; current = null; }
            resolve();
          };
          current = source;
          speaking = true;
          source.start();
        }, function () { resolve(); });
      });
    }

    function voiceMode() { return $('voice-mode').value; }

    /** Сказать реплику: {de, ru, emotion}. */
    function sayLine(line, bubbleRu) {
      bubble(line.de, bubbleRu === undefined ? line.ru : bubbleRu);
      return fetch('/api/talking/say', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: line.de, emotion: line.emotion || 'neutral', mode: voiceMode() })
      }).then(function (response) {
        if (!response.ok) { throw new Error('голос не синтезирован'); }
        return response.arrayBuffer();
      }).then(play).catch(function () { /* без звука — хватит облачка */ });
    }

    var lastLine = {};
    function talk(occasion) {
      var options = lines(occasion).filter(function (line) { return line.de !== lastLine[occasion]; });
      var line = pick(options.length ? options : lines(occasion));
      if (!line) { return Promise.resolve(); }
      lastLine[occasion] = line.de;
      return sayLine(line);
    }

    /* --- облачко --------------------------------------------------------------------- */

    var bubbleTimer = null;
    function bubble(de, ru) {
      $('speech-de').textContent = de || '';
      $('speech-ru').textContent = ru || '';
      speech.classList.add('show');
      clearTimeout(bubbleTimer);
      bubbleTimer = setTimeout(function () { if (!speaking) { speech.classList.remove('show'); } else { bubble(de, ru); } },
        2600 + 60 * ((de || '').length + (ru || '').length) / 2);
    }

    /* --- выражение и движения ---------------------------------------------------------- */

    var expression = { name: null, until: 0 };
    function express(name, ms) {
      expression = { name: name, until: performance.now() + (ms || 1200) };
    }

    var motion = {
      angle: 0, velocity: 0,            /* маятник: угол нити, рад */
      length: 0, lengthVelocity: 0,     /* длина нити сверх обычной, px */
      lean: 0, leanVelocity: 0,         /* подпрыгивание тела */
      lift: [0, 0, 0, 0, 0, 0, 0, 0], raise: 0, air: 0, wipe: 0,
      hidden: false, climb: 0,          /* ушёл вверх по нити */
      look: { x: 0, y: 0 }, target: null
    };

    var size = { width: 0, height: 0, rest: 0, scale: 2.5 };
    function measure() {
      var box = room.getBoundingClientRect();
      size.width = box.width;
      size.height = box.height;
      var spider = Math.min(300, box.width * 0.36);
      model.el.style.width = spider + 'px';
      model.el.style.left = (-spider / 2) + 'px';
      size.scale = spider / 120;
      size.rest = box.height * 0.09;
    }
    measure();
    global.addEventListener('resize', measure);

    /* где голова паука в координатах комнаты — для облачка и мухи */
    function headPoint() {
      var roomBox = room.getBoundingClientRect();
      var matrix = model.el.getScreenCTM();
      if (!matrix) { return { x: size.width / 2, y: size.height / 3 }; }
      var point = model.el.createSVGPoint();
      point.x = 60;
      point.y = 72;
      var screen = point.matrixTransform(matrix);
      return { x: screen.x - roomBox.left, y: screen.y - roomBox.top };
    }

    function toModel(clientX, clientY) {
      var matrix = model.el.getScreenCTM();
      if (!matrix) { return null; }
      var point = model.el.createSVGPoint();
      point.x = clientX;
      point.y = clientY;
      return point.matrixTransform(matrix.inverse());
    }

    var pointer = { x: 0, y: 0 };
    room.addEventListener('pointermove', function (event) {
      var head = headPoint();
      var box = room.getBoundingClientRect();
      var dx = event.clientX - box.left - head.x;
      var dy = event.clientY - box.top - head.y;
      var length = Math.sqrt(dx * dx + dy * dy) || 1;
      var strength = Math.min(1, length / 200);
      pointer.x = dx / length * strength;
      pointer.y = dy / length * strength;
    });

    var started = performance.now();
    var nextBlink = 2000;
    var lastTick = performance.now();
    var lastNeeds = performance.now();
    var lastPrompt = performance.now();
    var lastAction = performance.now();
    var data32 = new Float32Array(512);

    function frame(now) {
      var dt = Math.min(0.05, (now - lastTick) / 1000);
      lastTick = now;
      var t = (now - started) / 1000;

      /* маятник: θ'' = −(g/L)·sin θ − трение; пока игрок держит паука — следует за указателем */
      if (!drag.grabbing) {
        var length = (size.rest + motion.length + 80) / 100;
        motion.velocity += (-9.8 / length * Math.sin(motion.angle) - 0.9 * motion.velocity) * dt;
        motion.angle += motion.velocity * dt;
        /* нить пружинит к обычной длине */
        var restTarget = motion.hidden ? -(size.rest + 140 * size.scale) : 0;
        motion.lengthVelocity += ((restTarget - motion.length) * 14 - motion.lengthVelocity * 3.2) * dt;
        motion.length += motion.lengthVelocity * dt;
      }
      motion.leanVelocity += (-motion.lean * 60 - motion.leanVelocity * 7) * dt;
      motion.lean += motion.leanVelocity * dt;
      for (var i = 0; i < 8; i++) { motion.lift[i] = Math.max(0, motion.lift[i] - dt * 1.4); }
      motion.air = Math.max(0, motion.air - dt * 0.9);
      motion.raise += ((listening.hearing ? 1 : motion.wipe > 0 ? 1 : 0) - motion.raise) * Math.min(1, dt * 8);
      motion.wipe = Math.max(0, motion.wipe - dt);

      /* куда смотреть: на муху, на указатель или по настроению */
      var aim = motion.target ? motion.target() : pointer;
      motion.look.x += (aim.x - motion.look.x) * 0.15;
      motion.look.y += (aim.y - motion.look.y) * 0.15;

      var mood = expression.name && now < expression.until ? expression.name : baseline(state);
      if (speaking && (mood === 'idle' || mood === 'happy' || mood === 'sad' || mood === 'sleepy')) { mood = 'speaking'; }
      if (listening.hearing) { mood = 'hearing'; }
      model.mood(mood);
      model.set({
        mode: 'hang', sway: t * (state.asleep ? 0.6 : 1.4), look: mood === 'sleeping' ? { x: 0, y: 0.4 } : motion.look,
        raise: motion.raise, air: motion.air, lift: motion.lift, facing: Math.sin(motion.angle) * -1.6,
        lean: motion.lean + Math.sin(t * 1.6) * 0.9
      });
      if (speaking && analyser) {
        analyser.getFloatTimeDomainData(data32);
        var sum = 0;
        for (var k = 0; k < data32.length; k++) { sum += data32[k] * data32[k]; }
        var db = 20 * Math.log10(Math.sqrt(sum / data32.length) + 1e-9);
        model.talk(clamp((db + 46) / 30, 0, 1));
      } else if (mood === 'chewing' || mood === 'laughing') {
        model.talk(0.3 + 0.5 * Math.abs(Math.sin(t * 12)));
      }
      if (now > nextBlink && mood !== 'sleeping' && mood !== 'sleepy') {
        model.blink();
        nextBlink = now + 2400 + Math.random() * 3600;
      }

      /* положение на сцене */
      var drop = size.rest + motion.length;
      hang.style.transform = 'rotate(' + (-motion.angle) + 'rad)';
      thread.style.height = Math.max(0, drop) + 'px';
      body.style.transform = 'translateY(' + drop + 'px)';
      var head = headPoint();
      var left = Math.min(size.width - 300, Math.max(10, head.x + 50 * size.scale * 0.45));
      speech.style.left = left + 'px';
      speech.style.top = Math.max(10, head.y - 60 * size.scale * 0.55) + 'px';
      $('shadow').style.opacity = String(clamp(1 - Math.abs(motion.angle), 0.2, 1) * (motion.hidden ? 0.2 : 1));
      $('shadow').style.transform = 'translateX(calc(-50% + ' + (Math.sin(motion.angle) * (drop + 200)) + 'px))';

      /* потребности — раз в секунду */
      if (now - lastNeeds > 1000) {
        state = decay(state, (now - lastNeeds) / 60000, state.asleep);
        lastNeeds = now;
        if (state.asleep && Math.random() < 0.25) { snoreTick(); }
        if (!state.asleep && state.energy < 4) { fallAsleep(false); }
        render();
      }
      /* сам напоминает о себе, если долго ничего не происходит */
      if (now - lastPrompt > 26000 && now - lastAction > 18000 && !speaking && !state.asleep && !motion.hidden) {
        lastPrompt = now;
        if (state.food < 25) { express('sad', 2500); talk('hungry'); }
        else if (state.energy < 20) { express('sleepy', 2500); talk('tired'); }
        else if (state.mood < 25) { express('sad', 2500); talk('bored'); }
      }
      global.requestAnimationFrame(frame);
    }

    /* --- сон -------------------------------------------------------------------------------- */

    function snoreTick() {
      if (!context) { return; }
      sfx.snore();
      var head = headPoint();
      var z = G.element('span', 'zzz', 'z');
      z.style.left = (head.x + 30) + 'px';
      z.style.top = (head.y - 30) + 'px';
      room.appendChild(z);
      setTimeout(function () { z.remove(); }, 2700);
    }

    function fallAsleep(dark) {
      state.asleep = true;
      room.classList.toggle('is-dark', !!dark);
      $('light').classList.toggle('is-on', !!dark);
      stopTalking();
      talk('sleep');
      reward('sleep');
    }

    function wake() {
      state.asleep = false;
      room.classList.remove('is-dark');
      $('light').classList.remove('is-on');
      express('happy', 1500);
      talk('wake');
      render();
      save();
    }

    /* --- тычки и перетаскивание ------------------------------------------------------------- */

    var pokes = [];
    var headPokes = [];
    var drag = { down: false, grabbing: false, part: null, x: 0, y: 0, start: 0, path: 0, lastX: 0, lastY: 0, lastT: 0, vx: 0 };

    function ceiling() {
      var box = room.getBoundingClientRect();
      return { x: box.left + box.width / 2, y: box.top };
    }

    model.el.addEventListener('pointerdown', function (event) {
      event.preventDefault();
      audio();
      if (context.state === 'suspended') { context.resume(); }
      var point = toModel(event.clientX, event.clientY);
      if (!point) { return; }
      var facing = Math.sin(motion.angle) * -1.6;
      var hit = hitTest(point.x, point.y, model.joints(), { dx: clamp(facing, -1, 1) * 5, dy: motion.lean });
      drag = { down: true, grabbing: false, part: hit.part, leg: hit.leg, x: event.clientX, y: event.clientY,
               start: performance.now(), path: 0, lastX: event.clientX, lastY: event.clientY,
               lastT: performance.now(), vx: 0, stroke: 0 };
      model.el.setPointerCapture(event.pointerId);
    });

    model.el.addEventListener('pointermove', function (event) {
      if (!drag.down) { return; }
      var now = performance.now();
      var step = Math.hypot(event.clientX - drag.lastX, event.clientY - drag.lastY);
      drag.path += step;
      drag.vx = (event.clientX - drag.lastX) / Math.max(1, now - drag.lastT);
      drag.lastX = event.clientX;
      drag.lastY = event.clientY;
      drag.lastT = now;
      var away = Math.hypot(event.clientX - drag.x, event.clientY - drag.y);
      if (!drag.grabbing && (drag.part === 'thread' || away > 90)) {
        drag.grabbing = true;
        if (drag.part === 'thread') { talk('pull_thread'); }
      }
      if (drag.grabbing && !state.asleep) {
        /* паук висит там, куда его тянут: угол и длина нити от точки подвеса */
        var top = ceiling();
        var dx = event.clientX - top.x;
        var dy = Math.max(30, event.clientY - top.y);
        motion.angle = clamp(Math.atan2(dx, dy), -1.3, 1.3);
        motion.velocity = 0;
        var wanted = Math.hypot(dx, dy) - 60 * size.scale;
        motion.length = clamp(wanted - size.rest, -size.rest * 0.6, size.height * 0.45);
        motion.lengthVelocity = 0;
      } else if ((drag.part === 'belly' || drag.part === 'head') && step > 2) {
        /* провести по брюшку — погладить */
        drag.stroke += step;
        if (drag.stroke > 220) {
          drag.stroke = -400;
          stroke();
        }
      }
    });

    function release(event) {
      if (!drag.down) { return; }
      drag.down = false;
      if (drag.grabbing) {
        drag.grabbing = false;
        motion.velocity = drag.vx * 2.2;
        lastAction = performance.now();
        if (Math.abs(motion.angle) > 0.55 || Math.abs(motion.velocity) > 2.5) {
          reward('swing');
          talk('swing');
          state.stats.swings = (state.stats.swings || 0) + 1;
          setTimeout(function () {
            if (Math.abs(motion.velocity) > 1.2 || Math.abs(motion.angle) > 0.4) { express('dizzy', 2500); talk('dizzy'); }
          }, 1800);
        }
        return;
      }
      var quick = performance.now() - drag.start < 450 && drag.path < 25;
      if (quick && drag.part) { poke(drag.part, drag.leg); }
      if (event && model.el.hasPointerCapture && model.el.hasPointerCapture(event.pointerId)) {
        model.el.releasePointerCapture(event.pointerId);
      }
    }
    model.el.addEventListener('pointerup', release);
    model.el.addEventListener('pointercancel', release);

    function stroke() {
      if (state.asleep) { return; }
      lastAction = performance.now();
      state.stats.strokes++;
      express('happy', 2200);
      sfx.trill();
      heart();
      talk('stroke');
      reward('stroke');
    }

    function heart() {
      var head = headPoint();
      var item = G.element('span', 'heart', '♥');
      item.style.left = (head.x + (Math.random() * 60 - 30)) + 'px';
      item.style.top = (head.y - 40) + 'px';
      room.appendChild(item);
      setTimeout(function () { item.remove(); }, 1500);
    }

    var leaving = false;
    function poke(part, leg) {
      var now = performance.now();
      lastAction = now;
      if (motion.hidden) { return; }
      if (state.asleep) {
        express('sleepy', 1500);
        talk('wake_angry');
        return;
      }
      state.stats.pokes++;
      pokes = pokes.filter(function (time) { return now - time < 6000; });
      pokes.push(now);
      if (pokes.length >= 7 && !leaving) { leave(); return; }
      if (part === 'head') {
        headPokes = headPokes.filter(function (time) { return now - time < 4000; });
        headPokes.push(now);
        motion.leanVelocity += 90;
        if (headPokes.length >= 3) {
          headPokes = [];
          express('dizzy', 2600);
          talk('dizzy');
        } else {
          express('startled', 900);
          talk('poke_head');
        }
        reward('poke');
      } else if (part === 'eye') {
        model.blink();
        express('angry', 1300);
        talk('poke_eye');
        reward('poke');
      } else if (part === 'belly') {
        motion.leanVelocity -= 70;
        express('laughing', 1400);
        talk('poke_belly');
        reward('tickle');
      } else if (part === 'leg') {
        motion.lift[leg] = 1;
        state.stats.legs++;
        express('startled', 900);
        talk('poke_leg');
        reward('poke');
      } else if (part === 'thread') {
        motion.lengthVelocity += 260;
        talk('pull_thread');
        reward('poke');
      }
    }

    function leave() {
      leaving = true;
      pokes = [];
      model.angry(true);
      express('angry', 2500);
      reward('angry');
      talk('angry').then(function () {
        motion.hidden = true;
        setTimeout(function () {
          motion.hidden = false;
          model.angry(false);
          leaving = false;
          setTimeout(function () { talk('back'); }, 900);
        }, 5200);
      });
    }

    /* --- кнопки -------------------------------------------------------------------------------- */

    function busy() {
      if (motion.hidden) { G.toast('Он обиделся и ушёл. Подождите.'); return true; }
      return false;
    }

    var actions = {
      fly: function () {
        if (busy()) { return; }
        if (state.asleep) { G.toast('Он спит. Включите свет.'); return; }
        var fly = G.element('div', 'fly');
        fly.innerHTML = '<b></b><i></i><b></b>';
        room.appendChild(fly);
        sfx.buzz(2.6);
        var fromLeft = Math.random() < 0.5;
        var startX = fromLeft ? -30 : size.width + 30;
        var full = state.food >= 95;
        var begin = performance.now();
        var position = { x: startX, y: size.height * 0.25 };
        motion.target = function () {
          var head = headPoint();
          var dx = position.x - head.x;
          var dy = position.y - head.y;
          var length = Math.hypot(dx, dy) || 1;
          return { x: dx / length * Math.min(1, length / 150), y: dy / length * Math.min(1, length / 150) };
        };
        function step(now) {
          var t = (now - begin) / 1000;
          var head = headPoint();
          if (t < 2.2) {
            /* кружит около паука */
            var aroundX = head.x + Math.cos(t * 3.1) * 110 + Math.sin(t * 7) * 12;
            var aroundY = head.y - 40 + Math.sin(t * 4.3) * 60;
            var share = Math.min(1, t / 0.9);
            position.x = startX + (aroundX - startX) * share;
            position.y = size.height * 0.25 + (aroundY - size.height * 0.25) * share;
          } else if (full) {
            position.x += (fromLeft ? 1 : -1) * 9;
            position.y -= 2;
          } else if (t < 2.7) {
            /* передние лапы хватают */
            motion.wipe = 0.6;
            position.x += (head.x - position.x) * 0.25;
            position.y += (head.y + 10 - position.y) * 0.25;
          } else {
            fly.remove();
            motion.target = null;
            state.stats.flies++;
            sfx.crunch();
            express('chewing', 1600);
            setTimeout(function () { talk('fly_eat'); }, 700);
            reward('fly');
            return;
          }
          fly.style.left = (position.x - 13) + 'px';
          fly.style.top = (position.y - 10) + 'px';
          fly.style.transform = 'scaleX(' + (position.x > head.x ? -1 : 1) + ')';
          if (full && (position.x < -60 || position.x > size.width + 60)) {
            fly.remove();
            motion.target = null;
            return;
          }
          if (full && t > 2.2 && !step.refused) {
            step.refused = true;
            express('disgusted', 1300);
            talk('fly_full');
          }
          global.requestAnimationFrame(step);
        }
        global.requestAnimationFrame(step);
        lastAction = performance.now();
      },
      cymbal: function () {
        if (busy()) { return; }
        audio();
        sfx.cymbal();
        var flash = G.element('div', 'cymbal-flash');
        room.appendChild(flash);
        setTimeout(function () { flash.remove(); }, 600);
        state.stats.cymbals++;
        lastAction = performance.now();
        if (state.asleep) { state.asleep = false; room.classList.remove('is-dark'); $('light').classList.remove('is-on'); }
        motion.air = 1;
        motion.lengthVelocity -= 420;
        express('startled', 1600);
        setTimeout(function () { talk('cymbal'); }, 350);
        reward('cymbal');
      },
      pie: function () {
        if (busy()) { return; }
        if (state.asleep) { G.toast('Спящего тортом? Это слишком.'); return; }
        var pie = G.element('div', 'pie');
        room.appendChild(pie);
        var begin = performance.now();
        var from = { x: size.width * 0.12, y: size.height * 0.95 };
        function step(now) {
          var t = Math.min(1, (now - begin) / 650);
          var head = headPoint();
          var x = from.x + (head.x - from.x) * t;
          var y = from.y + (head.y - from.y) * t - Math.sin(Math.PI * t) * 120;
          pie.style.left = (x - 30) + 'px';
          pie.style.top = (y - 15) + 'px';
          pie.style.transform = 'rotate(' + (t * 300) + 'deg)';
          if (t < 1) { global.requestAnimationFrame(step); return; }
          pie.remove();
          sfx.splat();
          model.cream(true);
          motion.leanVelocity += 60;
          express('disgusted', 2800);
          state.stats.pies++;
          talk('pie');
          reward('pie');
          setTimeout(function () { motion.wipe = 1.2; }, 2200);
          setTimeout(function () { model.cream(false); express('idle', 400); }, 3300);
        }
        global.requestAnimationFrame(step);
        lastAction = performance.now();
      },
      web: function () {
        if (busy()) { return; }
        if (state.asleep) { G.toast('Он спит.'); return; }
        if (state.energy < 10) { express('sleepy', 2000); talk('tired'); return; }
        lastAction = performance.now();
        state.webs = Math.min(9, (state.webs || 0) + 1);
        state.stats.webs++;
        motion.velocity += 1.6;
        drawWeb(true);
        setTimeout(function () { express('happy', 2000); talk('web'); reward('web'); }, 3600);
      },
      light: function () {
        if (busy()) { return; }
        lastAction = performance.now();
        if (state.asleep) { wake(); } else { fallAsleep(true); }
      },
      read: function () {
        if (busy()) { return; }
        if (state.asleep) { G.toast('Он спит.'); return; }
        lastAction = performance.now();
        var wore = state.wearing.indexOf('glasses') >= 0;
        model.wear('glasses', true);
        talk('read').then(function () {
          return G.api('GET', '/api/talking/read');
        }).then(function (found) {
          if (!found || found.error) { return; }
          return sayLine({ de: found.text, emotion: 'neutral' }, 'Из статьи «' + found.title + '»');
        }).then(function () {
          if (!wore) { model.wear('glasses', false); }
          reward('read');
        });
      }
    };

    document.querySelectorAll('[data-action]').forEach(function (button) {
      button.addEventListener('click', function () {
        audio();
        if (context.state === 'suspended') { context.resume(); }
        actions[button.dataset.action]();
      });
    });

    $('say-form').addEventListener('submit', function (event) {
      event.preventDefault();
      var text = $('say-text').value.trim();
      if (!text || busy()) { return; }
      audio();
      if (state.asleep) { G.toast('Он спит. Включите свет.'); return; }
      lastAction = performance.now();
      state.stats.says++;
      sayLine({ de: text, emotion: /!/.test(text) ? 'amused' : /\?/.test(text) ? 'surprised' : 'neutral' }, '');
      reward('say');
      $('say-text').select();
    });

    /* --- паутина ------------------------------------------------------------------------------- */

    function drawWeb(animate) {
      var svg = $('web');
      var rings = state.webs || 0;
      svg.textContent = '';
      if (!rings) { return; }
      var cx = 500;
      var cy = 250;
      var spokes = 12;
      var radius = 70 + rings * 22;
      var ns = 'http://www.w3.org/2000/svg';
      var parts = [];
      for (var s = 0; s < spokes; s++) {
        var a = s / spokes * Math.PI * 2;
        var line = document.createElementNS(ns, 'line');
        line.setAttribute('x1', cx);
        line.setAttribute('y1', cy);
        line.setAttribute('x2', cx + Math.cos(a) * radius * 1.1);
        line.setAttribute('y2', cy + Math.sin(a) * radius * 1.1);
        parts.push(line);
      }
      var d = '';
      var turns = rings + 2;
      for (var k = 0; k <= turns * spokes; k++) {
        var angle = k / spokes * Math.PI * 2;
        var r = 18 + (radius - 18) * k / (turns * spokes);
        var sag = 0.92 + 0.08 * Math.cos((k % 1) * Math.PI);
        d += (k ? ' L' : 'M') + (cx + Math.cos(angle) * r * sag).toFixed(1) + ' ' + (cy + Math.sin(angle) * r * sag).toFixed(1);
      }
      var spiral = document.createElementNS(ns, 'path');
      spiral.setAttribute('d', d);
      parts.push(spiral);
      parts.forEach(function (part, index) {
        svg.appendChild(part);
        if (animate && part.getTotalLength) {
          var total = part.getTotalLength();
          part.style.strokeDasharray = total;
          part.style.strokeDashoffset = total;
          part.style.transition = 'stroke-dashoffset ' + (part === spiral ? 2.6 : 0.5) + 's ease ' + (part === spiral ? 0.9 : index * 0.07) + 's';
          global.requestAnimationFrame(function () {
            global.requestAnimationFrame(function () { part.style.strokeDashoffset = '0'; });
          });
        }
      });
    }

    /* --- панель: потребности, уровень, гардероб -------------------------------------------------- */

    function render() {
      NEEDS.forEach(function (need) {
        var row = $('need-' + need);
        var value = Math.round(state[need]);
        row.querySelector('.bar i').style.width = value + '%';
        row.querySelector('output').textContent = value;
        row.classList.toggle('is-low', value < 25);
        row.classList.toggle('is-mid', value >= 25 && value < 50);
      });
      var info = level(state.xp);
      $('level').textContent = info.level;
      $('level-text').textContent = info.level;
      $('xp').style.width = Math.round(info.share * 100) + '%';
      var upcoming = WARDROBE.filter(function (item) { return item.level > info.level; })[0];
      $('next-unlock').textContent = (info.to === null ? 'Высший уровень.' : 'До уровня ' + (info.level + 1) + ': ' +
        (info.to - state.xp) + ' опыта') + (upcoming ? ' · откроется ' + upcoming.icon + ' ' + upcoming.title : '');
      var open = unlocked(info.level).map(function (item) { return item.id; });
      document.querySelectorAll('#wardrobe button').forEach(function (button) {
        var id = button.dataset.item;
        button.disabled = open.indexOf(id) < 0;
        button.classList.toggle('on', state.wearing.indexOf(id) >= 0);
      });
      WARDROBE.forEach(function (item) { model.wear(item.id, state.wearing.indexOf(item.id) >= 0); });
      var stats = $('stats');
      var s = state.stats;
      stats.innerHTML = '';
      [['Тычков', s.pokes], ['Из них в ноги', s.legs], ['Съедено мух', s.flies], ['Повторил за вами', s.echoes],
       ['Сказал по просьбе', s.says], ['Сплёл паутин', s.webs], ['Тортов в мордочку', s.pies],
       ['Погладили', s.strokes], ['Опыт', state.xp]].forEach(function (pair) {
        var item = G.element('li');
        item.appendChild(document.createTextNode(pair[0] + ': '));
        item.appendChild(G.element('b', '', String(pair[1] || 0)));
        stats.appendChild(item);
      });
    }

    var wardrobe = $('wardrobe');
    WARDROBE.forEach(function (item) {
      var button = G.element('button');
      button.type = 'button';
      button.dataset.item = item.id;
      button.appendChild(G.element('span', 'ico', item.icon));
      button.appendChild(document.createTextNode(item.title));
      button.appendChild(G.element('small', '', 'с уровня ' + item.level));
      button.addEventListener('click', function () {
        var index = state.wearing.indexOf(item.id);
        if (index >= 0) { state.wearing.splice(index, 1); }
        else {
          /* на голове одна шляпа: цилиндр, корона и шапочка друг друга снимают */
          var hats = ['hat', 'crown', 'cap'];
          if (hats.indexOf(item.id) >= 0) {
            state.wearing = state.wearing.filter(function (id) { return hats.indexOf(id) < 0; });
          }
          state.wearing.push(item.id);
          express('happy', 1500);
          audio();
          talk('dress');
          reward('dress');
        }
        render();
        save();
      });
      wardrobe.appendChild(button);
    });

    $('reset').addEventListener('click', function () {
      if (!global.confirm('Начать с начала? Уровень, гардероб и счёт пропадут.')) { return; }
      state = fresh(Date.now());
      room.classList.remove('is-dark');
      drawWeb(false);
      render();
      save();
      talk('hello');
    });

    /* голос и эффект запоминаются */
    try {
      var savedEffect = global.localStorage.getItem('glashatai-effect');
      var savedMode = global.localStorage.getItem('glashatai-voice-mode');
      if (savedEffect) { $('effect').value = savedEffect; }
      if (savedMode && !$('voice-mode').querySelector('option[value="' + savedMode + '"]').disabled) {
        $('voice-mode').value = savedMode;
      } else {
        $('voice-mode').value = data.mode;
      }
    } catch (e) { $('voice-mode').value = data.mode; }
    $('effect').addEventListener('change', function () {
      try { global.localStorage.setItem('glashatai-effect', $('effect').value); } catch (e) { /* без хранилища */ }
    });
    $('voice-mode').addEventListener('change', function () {
      try { global.localStorage.setItem('glashatai-voice-mode', $('voice-mode').value); } catch (e) { /* без хранилища */ }
      talk('hello');
    });

    /* --- микрофон: повторить за игроком --------------------------------------------------------- */

    var listening = { on: false, hearing: false, stream: null, context: null, node: null, detector: null,
                      chunks: [], preroll: [], muteUntil: 0 };

    function micLabel(text) { $('mic-label').textContent = text; }

    function startMic() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !global.AudioWorkletNode) {
        G.toast('Браузер не умеет записывать звук. Пишите Пафнутию в поле ниже.');
        bubble(data.hints.no_mic, '');
        return;
      }
      navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true,
                                                     autoGainControl: true } }).then(function (stream) {
        listening.stream = stream;
        var Context = global.AudioContext || global.webkitAudioContext;
        var ctx = new Context();
        listening.context = ctx;
        return ctx.audioWorklet.addModule((G.config && G.config.worklet) || '/static/capture-worklet.js').then(function () {
          var source = ctx.createMediaStreamSource(stream);
          var node = new global.AudioWorkletNode(ctx, 'glashatai-capture');
          node.port.onmessage = onCapture;
          source.connect(node);
          listening.node = node;
          listening.detector = new Detector();
          listening.on = true;
          $('mic').classList.add('is-on');
          micLabel('Слушаю — говорите');
          bubble(data.hints.listen, '');
        });
      }).catch(function (problem) {
        stopMic();
        var name = problem && problem.name;
        G.toast(name === 'NotAllowedError' ? 'Браузер не дал микрофон — разрешите его в адресной строке.' :
          'Микрофон недоступен. Пишите Пафнутию в поле ниже.', 4500);
      });
    }

    function stopMic() {
      if (listening.stream) { listening.stream.getTracks().forEach(function (track) { track.stop(); }); }
      if (listening.context) { listening.context.close(); }
      listening.on = false;
      listening.hearing = false;
      listening.stream = listening.context = listening.node = null;
      $('mic').classList.remove('is-on', 'is-hearing');
      $('mic').style.removeProperty('--level');
      micLabel('Говори — повторю');
    }

    function onCapture(event) {
      var message = event.data;
      if (message.type === 'pcm') {
        if (listening.hearing) { listening.chunks.push(message.samples); }
        else {
          listening.preroll.push(message.samples);
          if (listening.preroll.length > 3) { listening.preroll.shift(); }
        }
        return;
      }
      var db = 20 * Math.log10(message.rms + 1e-9);
      $('mic').style.setProperty('--level', clamp((db + 60) / 50, 0, 1).toFixed(2));
      /* пока паук говорит, микрофон не слушается: иначе он передразнит сам себя */
      if (speaking || performance.now() < listening.muteUntil || state.asleep || motion.hidden) { return; }
      var change = listening.detector.feed(db);
      if (change === 'start') {
        listening.hearing = true;
        listening.chunks = listening.preroll.slice();
        listening.preroll = [];
        $('mic').classList.add('is-hearing');
        micLabel('Слышу…');
        stopTalking();
      } else if (change === 'end') {
        listening.hearing = false;
        $('mic').classList.remove('is-hearing');
        micLabel('Слушаю — говорите');
        echo(listening.chunks);
        listening.chunks = [];
      }
    }

    function echo(chunks) {
      var total = chunks.reduce(function (sum, chunk) { return sum + chunk.length; }, 0);
      if (total < 16000 * 0.3) { return; }
      var pcm = new Int16Array(total);
      var offset = 0;
      chunks.forEach(function (chunk) { pcm.set(chunk, offset); offset += chunk.length; });
      lastAction = performance.now();
      express('thinking', 600);
      fetch('/api/talking/echo?effect=' + encodeURIComponent($('effect').value), {
        method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: pcm.buffer
      }).then(function (response) {
        if (!response.ok) { throw new Error('не обработано'); }
        return response.arrayBuffer();
      }).then(function (buffer) {
        state.stats.echoes++;
        reward('echo');
        speech.classList.remove('show');
        return play(buffer);
      }).then(function () {
        listening.muteUntil = performance.now() + 450;
      }).catch(function () { G.toast('Пафнутий не расслышал. Ещё раз?'); });
    }

    $('mic').addEventListener('click', function () {
      audio();
      if (listening.on) { stopMic(); } else { startMic(); }
    });

    /* --- начало -------------------------------------------------------------------------------- */

    render();
    drawWeb(false);
    if (state.asleep) {
      room.classList.add('is-dark');
      $('light').classList.add('is-on');
    }
    global.requestAnimationFrame(frame);
    setTimeout(function () {
      if (!state.asleep) { talk('hello'); }
      else { bubble('Chrrr…', 'Хррр… Он спит. Включите свет.'); }
    }, 700);
    global.addEventListener('beforeunload', save);
    setInterval(save, 5000);

    G.talking = {
      state: function () { return state; }, poke: poke, actions: actions, model: model, motion: motion,
      echo: echo, hitTest: hitTest, stroke: stroke, toModel: toModel
    };
  });
})(typeof window !== 'undefined' ? window : globalThis);
