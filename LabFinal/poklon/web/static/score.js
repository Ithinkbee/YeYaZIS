/* Партитура: что «Поклон» знает о музыке и как по ней едет лифт.
 *
 * Ролик не идёт «по секундомеру»: запись у каждого своя, и хор в ней вступает
 * в своё время. Поэтому запись сначала прослушивается целиком — тридцать раз
 * в секунду считаются громкость и три полосы спектра: низ, середина, верх.
 *
 * По громкости находится самая громкая протяжённая часть записи — «большой
 * хор». Её начало и конец — две метки, от которых отсчитывается всё
 * остальное: когда лифт тормозит перед залом, когда вспыхивает свет, когда
 * кабина уходит вверх и когда выходит на поверхность. Метки можно поправить
 * на репетиции — тогда расписание строится заново.
 *
 * По полосам спектра пауки открывают рты: паучата — на верхах, хор — на
 * середине, Большой паук — на басах.
 *
 * В файле нет ни DOM, ни звука — только расчёты. Поэтому он подключается и
 * страницей, и проверками в node (tests/score.test.js).
 */

(function (global) {
  'use strict';

  var RATE = 30;                /* значений признаков в секунду */
  var LEAD = 1.5;               /* секунды от нажатия кнопки до первой ноты */
  var FINALE = 40;              /* на столько секунд после выхода можно перемотать: дальше всё уже показано */

  var RISE_SPEED = 150;         /* скорость подъёма, единиц сцены в секунду */
  var LEAVE_SPEED = 240;        /* после зала лифт идёт быстрее */
  var HALL_TRAVEL = 260;        /* за весь хор кабина проходит только столько: зал — почти стоп-кадр */

  function clamp(value, low, high) { return value < low ? low : value > high ? high : value; }
  function mix(a, b, t) { return a + (b - a) * t; }
  function ease(t) { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); }

  /* Случайные числа с зерном (mulberry32): расстановка пауков должна быть
     одной и той же при каждом показе и при перемотке. */
  function random(seed) {
    var state = seed >>> 0;
    return function () {
      state = (state + 0x6D2B79F5) >>> 0;
      var t = state;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* --- спектр ------------------------------------------------------------- */

  /* Быстрое преобразование Фурье на месте; длина — степень двойки. */
  function fft(re, im) {
    var n = re.length;
    var i, j, bit, tmp;
    for (i = 1, j = 0; i < n; i++) {
      for (bit = n >> 1; j & bit; bit >>= 1) { j ^= bit; }
      j ^= bit;
      if (i < j) {
        tmp = re[i]; re[i] = re[j]; re[j] = tmp;
        tmp = im[i]; im[i] = im[j]; im[j] = tmp;
      }
    }
    for (var len = 2; len <= n; len <<= 1) {
      var angle = -2 * Math.PI / len;
      var wr = Math.cos(angle);
      var wi = Math.sin(angle);
      var half = len >> 1;
      for (var start = 0; start < n; start += len) {
        var cr = 1;
        var ci = 0;
        for (var k = 0; k < half; k++) {
          var a = start + k;
          var b = a + half;
          var xr = re[b] * cr - im[b] * ci;
          var xi = re[b] * ci + im[b] * cr;
          re[b] = re[a] - xr; im[b] = im[a] - xi;
          re[a] += xr; im[a] += xi;
          var next = cr * wr - ci * wi;
          ci = cr * wi + ci * wr;
          cr = next;
        }
      }
    }
  }

  /* Полосы голосов, Гц. Бас — основные тоны низкого голоса, середина —
     основные тоны хора, верх — сопрано и обертоны. */
  var BANDS = { low: [55, 230], mid: [230, 900], high: [900, 4200] };
  var FRAME = 1024;

  function percentile(values, share) {
    if (!values.length) { return 0; }
    var sorted = Array.prototype.slice.call(values).sort(function (a, b) { return a - b; });
    return sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(share * (sorted.length - 1))))];
  }

  /* Среднее в окне с центром в точке: сглаживает, не сдвигая во времени. */
  function movingAverage(series, width) {
    var n = series.length;
    var sums = new Float64Array(n + 1);
    for (var i = 0; i < n; i++) { sums[i + 1] = sums[i] + series[i]; }
    var half = Math.max(1, Math.round(width / 2));
    var out = new Float32Array(n);
    for (var k = 0; k < n; k++) {
      var from = Math.max(0, k - half);
      var to = Math.min(n, k + half + 1);
      out[k] = (sums[to] - sums[from]) / (to - from);
    }
    return out;
  }

  /* Рот открывается быстро, закрывается медленнее — как у поющего. */
  function follow(series, attack, release) {
    var out = new Float32Array(series.length);
    var value = 0;
    for (var i = 0; i < series.length; i++) {
      value += (series[i] - value) * (series[i] > value ? attack : release);
      out[i] = value;
    }
    return out;
  }

  /**
   * Прослушивание записи. channels — массивы отсчётов по каналам, sampleRate
   * — частота записи. Работа делится на части, чтобы страница не замирала:
   * run(count) обрабатывает ещё count кадров и возвращает долю готового,
   * finish() отдаёт признаки.
   */
  function analysis(channels, sampleRate) {
    /* голосам хватает полосы до 5 кГц: запись прореживается, счёт идёт быстрее */
    var step = Math.max(1, Math.floor(sampleRate / 16000));
    var rate = sampleRate / step;
    var total = channels[0].length;
    var hop = sampleRate / RATE;
    var frames = Math.max(1, Math.floor(total / hop));
    var re = new Float32Array(FRAME);
    var im = new Float32Array(FRAME);
    var hann = new Float32Array(FRAME);
    for (var w = 0; w < FRAME; w++) { hann[w] = 0.5 - 0.5 * Math.cos(2 * Math.PI * w / (FRAME - 1)); }
    var raw = { level: new Float32Array(frames) };
    var bins = {};
    Object.keys(BANDS).forEach(function (name) {
      raw[name] = new Float32Array(frames);
      bins[name] = [
        Math.max(1, Math.round(BANDS[name][0] * FRAME / rate)),
        Math.min(FRAME / 2 - 1, Math.round(BANDS[name][1] * FRAME / rate))
      ];
    });
    var done = 0;
    var scale = 1 / (channels.length * step);

    function run(count) {
      var end = Math.min(frames, done + count);
      for (; done < end; done++) {
        var start = Math.round(done * hop) - (FRAME * step >> 1);
        var energy = 0;
        for (var i = 0; i < FRAME; i++) {
          var at = start + i * step;
          var value = 0;
          if (at >= 0 && at + step <= total) {
            for (var c = 0; c < channels.length; c++) {
              for (var s = 0; s < step; s++) { value += channels[c][at + s]; }
            }
            value *= scale;
          }
          energy += value * value;
          re[i] = value * hann[i];
          im[i] = 0;
        }
        fft(re, im);
        raw.level[done] = Math.sqrt(energy / FRAME);
        for (var name in bins) {
          var sum = 0;
          for (var bin = bins[name][0]; bin <= bins[name][1]; bin++) { sum += re[bin] * re[bin] + im[bin] * im[bin]; }
          raw[name][done] = Math.sqrt(sum);
        }
      }
      return done / frames;
    }

    function finish() {
      run(frames);
      var features = { rate: RATE, length: frames, duration: total / sampleRate };
      Object.keys(raw).forEach(function (name) {
        /* каждая полоса приводится к своему обычному максимуму: тихий бас
           всё равно должен открывать рот Большого паука во всю ширь */
        var top = percentile(raw[name], 0.97) || 1;
        var series = new Float32Array(frames);
        for (var i = 0; i < frames; i++) { series[i] = Math.min(1.25, raw[name][i] / top); }
        if (name === 'level') {
          features.level = series;
          var loud = new Float32Array(frames);
          for (var k = 0; k < frames; k++) { loud[k] = Math.pow(Math.min(1, series[k]), 0.7); }
          features.loud = follow(loud, 0.7, 0.2);
        } else {
          for (var j = 0; j < frames; j++) { series[j] = Math.pow(Math.min(1, series[j]), 0.8); }
          features[name] = follow(series, 0.75, 0.24);
        }
      });
      return features;
    }

    return { frames: frames, run: run, finish: finish };
  }

  /** Значение признака в момент t (секунды) — между соседними кадрами. */
  function sample(series, t) {
    if (!series || !series.length) { return 0; }
    var at = t * RATE;
    if (at <= 0) { return at < -1 ? 0 : series[0]; }
    if (at >= series.length - 1) { return at > series.length ? 0 : series[series.length - 1]; }
    var index = Math.floor(at);
    return mix(series[index], series[index + 1], at - index);
  }

  /* --- метки ---------------------------------------------------------------- */

  /* Разумные границы: до хора лифт должен успеть разогнаться и проехать
     хоть несколько этажей, после хора — успеть выйти на поверхность. */
  function settle(cues, duration) {
    var before = Math.max(10, duration * 0.12);
    var during = Math.max(12, duration * 0.1);
    var after = Math.max(8, duration * 0.06);
    if (duration < before + during + after + 2) {
      /* запись слишком коротка — делим её на части как придётся */
      return { choir: duration * 0.4, leave: duration * 0.78 };
    }
    var choir = clamp(cues.choir, before, duration - during - after);
    var leave = clamp(cues.leave, choir + during, duration - after);
    return { choir: choir, leave: leave };
  }

  function guess(duration) {
    var cues = settle({ choir: duration * 0.45, leave: duration * 0.8 }, duration);
    cues.found = false;
    return cues;
  }

  /**
   * Ищет большой хор: самый «весомый» по громкости сплошной отрезок записи.
   * Громкость сглаживается окном в три секунды; порог ставится между тихими
   * и громкими местами; затем находится отрезок, на котором сумма превышений
   * порога наибольшая (алгоритм Кадане) — он переживает короткие провалы
   * внутри хора и не цепляется за одиночные всплески. Начало отрезка
   * уточняется по самому резкому подъёму громкости рядом: свет в зале должен
   * вспыхнуть на вступлении, а не «где-то около».
   */
  function detectCues(features, duration) {
    var fallback = guess(duration);
    if (!features || !features.level || features.length < RATE * 30) { return fallback; }
    var level = features.level;
    var slow = movingAverage(level, RATE * 3);
    var heard = [];
    for (var i = 0; i < slow.length; i++) { if (slow[i] > 0.03) { heard.push(slow[i]); } }
    var quiet = percentile(heard, 0.2);
    var loud = percentile(heard, 0.95);
    if (loud - quiet < 0.15 * loud) { return fallback; }     /* запись ровная: громкой части не выделить */

    var threshold = quiet + (loud - quiet) * 0.55;
    var best = -Infinity, bestFrom = 0, bestTo = 0, sum = 0, from = 0;
    for (var k = 0; k < slow.length; k++) {
      var gain = slow[k] - threshold;
      if (sum <= 0) { sum = gain; from = k; } else { sum += gain; }
      if (sum > best) { best = sum; bestFrom = from; bestTo = k; }
    }
    if (bestTo - bestFrom < RATE * 6) { return fallback; }   /* всплеск, а не хор */

    var quick = movingAverage(level, Math.round(RATE * 0.6));
    var reach = Math.round(RATE * 0.5);
    var onset = bestFrom, jump = -Infinity;
    for (var p = Math.max(reach, bestFrom - RATE * 3); p <= Math.min(slow.length - reach - 1, bestFrom + RATE * 2); p++) {
      var rise = quick[p + reach] - quick[p - reach];
      if (rise > jump) { jump = rise; onset = p; }
    }
    var cues = settle({ choir: onset / RATE, leave: bestTo / RATE }, duration);
    cues.found = true;
    return cues;
  }

  /* --- ролик без записи ------------------------------------------------------- */

  /* Без музыки ролик идёт в тишине, но пауки всё равно поют: признаки
     придумываются — фразы с паузами на вдох, слоги внутри фраз. */
  function silent(duration, cues) {
    var frames = Math.round(duration * RATE);
    var features = { rate: RATE, length: frames, duration: duration, silent: true };
    ['level', 'loud', 'low', 'mid', 'high'].forEach(function (name) { features[name] = new Float32Array(frames); });
    for (var i = 0; i < frames; i++) {
      var t = i / RATE;
      var phrase = Math.sin(2 * Math.PI * t / 5.6) > -0.72 ? 1 : 0.12;
      var syllable = 0.55 + 0.45 * Math.abs(Math.sin(Math.PI * t * 2.1 + Math.sin(t * 0.7)));
      var inside = t >= cues.choir && t < cues.leave;
      var fade = ease((duration - t) / 6);
      var base = (inside ? 0.9 : t < cues.choir ? 0.4 + 0.12 * t / cues.choir : 0.42) * fade;
      features.level[i] = base * phrase * syllable;
      features.high[i] = Math.min(1, (inside ? 0.8 : 0.95) * phrase * syllable * fade);
      features.mid[i] = inside ? 0.9 * phrase * (0.6 + 0.4 * Math.abs(Math.sin(Math.PI * t * 1.4))) : 0.1 * phrase;
      features.low[i] = inside ? 0.95 * Math.pow(Math.abs(Math.sin(Math.PI * t * 0.62)), 0.7) : 0.04;
    }
    features.loud = follow(features.level, 0.7, 0.2);
    features.high = follow(features.high, 0.75, 0.24);
    features.mid = follow(features.mid, 0.75, 0.24);
    features.low = follow(features.low, 0.75, 0.24);
    return features;
  }

  /* --- расписание и путь лифта --------------------------------------------------- */

  /**
   * Расписание ролика по длине записи и двум меткам.
   *
   * Время t — секунды музыки: t = 0 — первая нота, t < 0 — лифт ещё стоит.
   * Высота кабины — интеграл скорости: разгон, ровный подъём, торможение
   * перед залом, почти остановка на время хора, быстрый подъём к выходу.
   * Все, кого лифт проезжает, расставлены по высоте через эту же функцию:
   * «паук в центре кадра на двадцатой секунде» значит «паук на высоте,
   * где кабина будет на двадцатой секунде».
   */
  function plan(duration, cues) {
    var fixed = settle(cues, duration);
    var choir = fixed.choir;
    var leave = fixed.leave;
    var arrive = Math.max(leave + 10, duration - 12);
    var hallSpeed = HALL_TRAVEL / (leave - choir);
    var keys = [
      [0, 0], [2.6, RISE_SPEED], [choir - 6, RISE_SPEED], [choir - 0.4, hallSpeed],
      [leave, hallSpeed], [leave + 3.5, LEAVE_SPEED], [arrive - 3.5, LEAVE_SPEED], [arrive, 0]
    ];

    function speed(t) {
      if (t <= 0 || t >= arrive) { return 0; }
      for (var i = 1; i < keys.length; i++) {
        if (t <= keys[i][0]) {
          var span = keys[i][0] - keys[i - 1][0];
          return mix(keys[i - 1][1], keys[i][1], span > 0 ? ease((t - keys[i - 1][0]) / span) : 1);
        }
      }
      return 0;
    }

    var count = Math.ceil(arrive * RATE) + 1;
    var table = new Float64Array(count);
    for (var i = 1; i < count; i++) {
      table[i] = table[i - 1] + (speed((i - 1) / RATE) + speed(i / RATE)) / (2 * RATE);
    }

    function altitude(t) {
      if (t <= 0) { return 0; }
      var at = t * RATE;
      if (at >= count - 1) { return table[count - 1]; }
      var index = Math.floor(at);
      return mix(table[index], table[index + 1], at - index);
    }

    /* Обратный вопрос: на какой секунде кабина окажется на высоте h. */
    function when(height) {
      if (height <= 0) { return 0; }
      if (height >= table[count - 1]) { return arrive; }
      var lower = 0;
      var upper = count - 1;
      while (upper - lower > 1) {
        var middle = (lower + upper) >> 1;
        if (table[middle] < height) { lower = middle; } else { upper = middle; }
      }
      var step = table[upper] - table[lower];
      return (lower + (step > 0 ? (height - table[lower]) / step : 0)) / RATE;
    }

    var result = {
      duration: duration,
      lead: LEAD,
      choir: choir,             /* вступает большой хор: в зале вспыхивает свет */
      leave: leave,             /* хор смолкает: кабина уходит вверх */
      arrive: arrive,           /* лифт выходит на поверхность */
      end: arrive + FINALE,
      dusk: choir - 7.5,        /* в кадре показывается тёмный зал */
      speed: speed,
      altitude: altitude,
      when: when,
      top: table[count - 1]
    };
    /* Зал — проём в стене шахты от нижней кромки до верхней. Нижняя кромка в
       момент вступления хора стоит у самого низа кадра, верхняя весь хор
       остаётся за кадром и опускается, когда кабина уходит. */
    result.hall = { bottom: altitude(choir) - 390, top: altitude(leave) + 520, middle: altitude((choir + leave) / 2) };
    return result;
  }

  /** Как называется то, что сейчас на экране. */
  function act(schedule, t) {
    if (t < 0) { return 'wait'; }
    if (t < schedule.choir) { return 'rise'; }
    if (t < schedule.leave) { return 'hall'; }
    if (t < schedule.arrive) { return 'leave'; }
    return 'surface';
  }

  var api = {
    RATE: RATE, LEAD: LEAD, FINALE: FINALE, HALL_TRAVEL: HALL_TRAVEL, BANDS: BANDS,
    clamp: clamp, mix: mix, ease: ease, random: random,
    fft: fft, percentile: percentile, movingAverage: movingAverage,
    analysis: analysis, sample: sample,
    settle: settle, guess: guess, detectCues: detectCues, silent: silent,
    plan: plan, act: act
  };

  if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
  global.Score = api;
})(typeof window !== 'undefined' ? window : globalThis);
