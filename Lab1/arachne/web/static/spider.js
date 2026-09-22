/* Пасьянс «Паук» для ИПС «Арахна».
 *
 * Игра целиком живёт в браузере: на сервер она не ходит и ничего там не
 * хранит. Это осознанно — пасьянс ничего не начисляет и ни на что в системе
 * не влияет, поэтому держать его состояние на сервере значило бы заводить
 * сессии ради развлечения.
 *
 * Файл разделён надвое. Сверху — чистые правила: колода, раздача, проверка
 * ходов. Они не знают про DOM и вынесены в module.exports, чтобы их можно
 * было проверить тестами вне браузера. Снизу — отрисовка и обработка щелчков.
 */

(function (global) {
  'use strict';

  /* --- правила ----------------------------------------------------------- */

  var RANKS = ['', 'A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'];
  var SUITS = ['♠', '♥', '♦', '♣'];  /* пики, червы, бубны, трефы */
  var RED = [1, 2];                                      /* червы и бубны — красные */

  var COLUMNS = 10;
  var FULL_RUN = 13;        /* от короля до туза */
  var GOAL = 8;             /* восемь собранных последовательностей — победа */

  /* Раздача: первые четыре столбца по шесть карт, остальные по пять. */
  var FIRST_DEEP = 4;
  var DEEP_SIZE = 6;
  var SHALLOW_SIZE = 5;

  /**
   * Генератор псевдослучайных чисел с зерном.
   * Нужен, чтобы раздачу можно было повторить по её номеру: без этого
   * «та же партия ещё раз» была бы невозможна.
   */
  function seededRandom(seed) {
    var state = seed >>> 0;
    return function () {
      state += 0x6D2B79F5;
      var t = state;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /**
   * Колода из 104 карт: восемь наборов от туза до короля.
   * Число мастей задаёт трудность: одна масть — простая игра, четыре — полная.
   */
  function createDeck(suitCount, random) {
    var deck = [];
    var sets = 8 / suitCount;
    for (var suit = 0; suit < suitCount; suit++) {
      for (var copy = 0; copy < sets; copy++) {
        for (var rank = 1; rank <= 13; rank++) {
          deck.push({ rank: rank, suit: suit, up: false });
        }
      }
    }
    /* перемешивание Фишера — Йетса */
    for (var i = deck.length - 1; i > 0; i--) {
      var j = Math.floor(random() * (i + 1));
      var swap = deck[i];
      deck[i] = deck[j];
      deck[j] = swap;
    }
    return deck;
  }

  /** Раскладывает колоду по столбцам; остаток уходит в запас. */
  function deal(deck) {
    var columns = [];
    var position = 0;
    for (var column = 0; column < COLUMNS; column++) {
      var size = column < FIRST_DEEP ? DEEP_SIZE : SHALLOW_SIZE;
      var pile = deck.slice(position, position + size);
      position += size;
      if (pile.length) { pile[pile.length - 1].up = true; }
      columns.push(pile);
    }
    return { columns: columns, stock: deck.slice(position) };
  }

  function newGame(suitCount, seed) {
    var random = seededRandom(seed);
    var laid = deal(createDeck(suitCount, random));
    return {
      suits: suitCount,
      seed: seed,
      columns: laid.columns,
      stock: laid.stock,
      collected: [],
      moves: 0,
      history: []
    };
  }

  /**
   * Можно ли поднять карту с указанной позиции.
   * Поднимается только открытая карта, за которой идёт убывающая
   * последовательность одной масти до конца столбца.
   */
  function canPickUp(column, index) {
    if (index < 0 || index >= column.length) { return false; }
    if (!column[index].up) { return false; }
    for (var i = index; i < column.length - 1; i++) {
      var card = column[i];
      var next = column[i + 1];
      if (card.suit !== next.suit || card.rank !== next.rank + 1) { return false; }
    }
    return true;
  }

  /**
   * Можно ли положить карту на столбец.
   * Масть при укладке значения не имеет — только достоинство на единицу выше.
   * Пустой столбец принимает что угодно.
   */
  function canDrop(card, targetColumn) {
    if (!targetColumn.length) { return true; }
    var top = targetColumn[targetColumn.length - 1];
    return top.up && top.rank === card.rank + 1;
  }

  /** Есть ли в конце столбца готовая последовательность от короля до туза. */
  function completedRunAt(column) {
    if (column.length < FULL_RUN) { return -1; }
    var start = column.length - FULL_RUN;
    if (!column[start].up || column[start].rank !== 13) { return -1; }
    for (var i = start; i < column.length - 1; i++) {
      if (column[i].suit !== column[i + 1].suit) { return -1; }
      if (column[i].rank !== column[i + 1].rank + 1) { return -1; }
    }
    return start;
  }

  /**
   * Снимает со столбцов все собранные последовательности.
   * Возвращает, сколько их оказалось: этого хватает, чтобы понять, надо ли
   * перерисовывать поле сбора.
   */
  function collect(state) {
    var found = 0;
    state.columns.forEach(function (column) {
      var start = completedRunAt(column);
      if (start < 0) { return; }
      state.collected.push(column.splice(start, FULL_RUN));
      found++;
      /* карта, оказавшаяся сверху после снятия, открывается */
      if (column.length && !column[column.length - 1].up) {
        column[column.length - 1].up = true;
      }
    });
    return found;
  }

  /** Раздача из запаса разрешена, только если пустых столбцов нет. */
  function canDealRow(state) {
    if (!state.stock.length) { return false; }
    return state.columns.every(function (column) { return column.length > 0; });
  }

  function snapshot(state) {
    return JSON.stringify({
      columns: state.columns,
      stock: state.stock,
      collected: state.collected.length,
      moves: state.moves
    });
  }

  function remember(state) {
    state.history.push(snapshot(state));
    if (state.history.length > 200) { state.history.shift(); }
  }

  /** Переносит карты между столбцами. Возвращает true, если ход состоялся. */
  function move(state, fromIndex, cardIndex, toIndex) {
    if (fromIndex === toIndex) { return false; }
    var from = state.columns[fromIndex];
    var to = state.columns[toIndex];
    if (!from || !to || !canPickUp(from, cardIndex)) { return false; }
    if (!canDrop(from[cardIndex], to)) { return false; }

    remember(state);
    var run = from.splice(cardIndex);
    run.forEach(function (card) { to.push(card); });
    if (from.length && !from[from.length - 1].up) {
      from[from.length - 1].up = true;
    }
    state.moves++;
    collect(state);
    return true;
  }

  /** Сдаёт по одной карте в каждый столбец. */
  function dealRow(state) {
    if (!canDealRow(state)) { return false; }
    remember(state);
    for (var column = 0; column < COLUMNS && state.stock.length; column++) {
      var card = state.stock.pop();
      card.up = true;
      state.columns[column].push(card);
    }
    state.moves++;
    collect(state);
    return true;
  }

  function undo(state) {
    var previous = state.history.pop();
    if (!previous) { return false; }
    var saved = JSON.parse(previous);
    state.columns = saved.columns;
    state.stock = saved.stock;
    state.collected = state.collected.slice(0, saved.collected);
    state.moves = saved.moves;
    return true;
  }

  function isWon(state) {
    return state.collected.length >= GOAL;
  }

  /** Остались ли ходы: хоть один перенос или возможность сдать карты. */
  function hasMoves(state) {
    if (canDealRow(state)) { return true; }
    for (var from = 0; from < COLUMNS; from++) {
      var column = state.columns[from];
      for (var index = 0; index < column.length; index++) {
        if (!canPickUp(column, index)) { continue; }
        for (var to = 0; to < COLUMNS; to++) {
          if (to === from) { continue; }
          /* перенос всего столбца в пустой ничего не меняет */
          if (index === 0 && !state.columns[to].length) { continue; }
          if (canDrop(column[index], state.columns[to])) { return true; }
        }
      }
    }
    return false;
  }

  var rules = {
    RANKS: RANKS, SUITS: SUITS, RED: RED, COLUMNS: COLUMNS, GOAL: GOAL,
    seededRandom: seededRandom, createDeck: createDeck, deal: deal,
    newGame: newGame, canPickUp: canPickUp, canDrop: canDrop,
    completedRunAt: completedRunAt, collect: collect, canDealRow: canDealRow,
    move: move, dealRow: dealRow, undo: undo, isWon: isWon, hasMoves: hasMoves
  };

  /* Вне браузера файл подключается тестами: отрисовка тогда не нужна. */
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = rules;
    return;
  }
  global.SpiderRules = rules;

  /* --- отрисовка и управление -------------------------------------------- */

  function ready(callback) {
    if (document.readyState !== 'loading') { callback(); }
    else { document.addEventListener('DOMContentLoaded', callback); }
  }

  ready(function () {
    var board = document.getElementById('spider-board');
    if (!board) { return; }

    var stockBox = document.getElementById('spider-stock');
    var collectedBox = document.getElementById('spider-collected');
    var movesBox = document.getElementById('spider-moves');
    var dealBox = document.getElementById('spider-deal');
    var noteBox = document.getElementById('spider-note');
    var suitsPicker = document.getElementById('spider-suits');

    var state = null;
    var picked = null;   /* {column, index} — что поднято */

    function note(text, kind) {
      noteBox.textContent = text || '';
      noteBox.className = 'spider-note' + (kind ? ' is-' + kind : '');
    }

    function start(suitCount, seed) {
      state = rules.newGame(suitCount, seed);
      picked = null;
      note('Раздача № ' + seed + '. Собирайте от короля к тузу одной мастью.');
      render();
    }

    function cardFace(card) {
      /* Все классы пасьянса носят собственный префикс. Короткое имя вроде
         .card в «Арахне» уже занято — им размечены панели на всех страницах,
         и общий стиль разъехался бы по всему интерфейсу. */
      var face = document.createElement('div');
      face.classList.add('spider-card');
      if (!card.up) {
        face.classList.add('is-down');
        return face;
      }
      if (rules.RED.indexOf(card.suit) >= 0) { face.classList.add('is-red'); }
      var rank = document.createElement('span');
      rank.className = 'spider-card-rank';
      rank.textContent = rules.RANKS[card.rank];
      var suit = document.createElement('span');
      suit.className = 'spider-card-suit';
      suit.textContent = rules.SUITS[card.suit];
      face.appendChild(rank);
      face.appendChild(suit);
      return face;
    }

    function render() {
      board.innerHTML = '';
      state.columns.forEach(function (column, columnIndex) {
        var pile = document.createElement('div');
        pile.classList.add('spider-pile');
        pile.dataset.column = String(columnIndex);

        if (!column.length) {
          pile.classList.add('is-empty');
          pile.addEventListener('click', function () { onColumnClick(columnIndex, -1); });
        }

        column.forEach(function (card, cardIndex) {
          var element = cardFace(card);
          element.style.top = (cardIndex * (card.up ? 26 : 12)) + 'px';
          if (picked && picked.column === columnIndex && cardIndex >= picked.index) {
            element.classList.add('is-picked');
          }
          element.addEventListener('click', function (event) {
            event.stopPropagation();
            onColumnClick(columnIndex, cardIndex);
          });
          pile.appendChild(element);
        });

        /* высота столбца задаётся вручную: карты лежат абсолютно */
        var last = column.length ? column.length - 1 : 0;
        var height = column.reduce(function (sum, card, index) {
          return index === last ? sum : sum + (card.up ? 26 : 12);
        }, 0);
        pile.style.minHeight = (height + 96) + 'px';
        board.appendChild(pile);
      });
      refreshCounters();
    }

    function refreshCounters() {
      stockBox.textContent = Math.ceil(state.stock.length / rules.COLUMNS);
      collectedBox.textContent = state.collected.length + ' из ' + rules.GOAL;
      movesBox.textContent = String(state.moves);
      dealBox.disabled = !rules.canDealRow(state);
    }

    function onColumnClick(columnIndex, cardIndex) {
      if (!state) { return; }

      if (!picked) {
        if (cardIndex < 0) { return; }
        if (!rules.canPickUp(state.columns[columnIndex], cardIndex)) {
          note('Поднять можно только убывающую последовательность одной масти.', 'warn');
          return;
        }
        picked = { column: columnIndex, index: cardIndex };
        note('');
        render();
        return;
      }

      if (picked.column === columnIndex && picked.index === cardIndex) {
        picked = null;                        /* повторный щелчок отменяет выбор */
        render();
        return;
      }

      var before = state.collected.length;
      if (rules.move(state, picked.column, picked.index, columnIndex)) {
        picked = null;
        render();
        if (state.collected.length > before) {
          note('Последовательность собрана и снята.', 'good');
        }
        checkEnd();
        return;
      }

      /* не легло — пробуем считать щелчок выбором новой карты */
      if (cardIndex >= 0 && rules.canPickUp(state.columns[columnIndex], cardIndex)) {
        picked = { column: columnIndex, index: cardIndex };
        note('');
      } else {
        note('Сюда положить нельзя: нужна карта на единицу старше.', 'warn');
      }
      render();
    }

    function checkEnd() {
      if (rules.isWon(state)) {
        note('Пасьянс сошёлся! Все восемь последовательностей собраны.', 'good');
        return;
      }
      if (!rules.hasMoves(state)) {
        note('Ходов больше нет. Отмените ход или начните заново.', 'warn');
      }
    }

    document.getElementById('spider-new').addEventListener('click', function () {
      start(Number(suitsPicker.value), Math.floor(Math.random() * 100000));
    });

    document.getElementById('spider-again').addEventListener('click', function () {
      start(state.suits, state.seed);
    });

    dealBox.addEventListener('click', function () {
      var before = state.collected.length;
      if (!rules.dealRow(state)) {
        note('Сдавать нельзя, пока есть пустой столбец.', 'warn');
        return;
      }
      picked = null;
      render();
      note(state.collected.length > before ? 'Последовательность собрана и снята.' : '');
      checkEnd();
    });

    document.getElementById('spider-undo').addEventListener('click', function () {
      if (!rules.undo(state)) {
        note('Отменять нечего.', 'warn');
        return;
      }
      picked = null;
      render();
      note('Ход отменён.');
    });

    suitsPicker.addEventListener('change', function () {
      start(Number(suitsPicker.value), Math.floor(Math.random() * 100000));
    });

    start(Number(suitsPicker.value), Math.floor(Math.random() * 100000));
  });
})(typeof window !== 'undefined' ? window : globalThis);
