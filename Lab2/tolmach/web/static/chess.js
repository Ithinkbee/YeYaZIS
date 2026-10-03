/* Шахматная доска для «Толмача».
 *
 * Правила здесь не проверяются: и генерация ходов, и мат, и ответы Пафнутия
 * считаются на сервере. Этот файл занят только двумя вещами — рисует доску и
 * ведёт разговор с сервером. Дублировать правила в браузере не стоило бы:
 * тогда задачу «мат в два хода» пришлось бы проверять дважды, и рано или
 * поздно две проверки разошлись бы.
 *
 * Список законных ходов сервер присылает вместе с позицией. По нему доска
 * рисует ход игрока сразу, не дожидаясь ответа: сервер затем присылает
 * настоящую позицию, и она заменяет предварительную.
 */

(function (global) {
  'use strict';

  var FILES = 'abcdefgh';
  var RANKS = '87654321';

  /* Фигуры рисуются символами Unicode: шрифт есть везде, картинки не нужны. */
  var GLYPHS = {
    K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘', P: '♙',
    k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟'
  };

  function squareName(index) {
    return FILES[index % 8] + RANKS[Math.floor(index / 8)];
  }

  /* Разбор расстановки из FEN в массив из 64 символов. */
  function parseFen(fen) {
    var rows = fen.split(' ')[0].split('/');
    var squares = [];
    rows.forEach(function (row) {
      for (var i = 0; i < row.length; i++) {
        var char = row[i];
        if (char >= '1' && char <= '8') {
          for (var n = 0; n < Number(char); n++) { squares.push('.'); }
        } else {
          squares.push(char);
        }
      }
    });
    return squares;
  }

  function turnOf(fen) {
    return fen.split(' ')[1] || 'w';
  }

  /**
   * Доска.
   *
   * @param {HTMLElement} root  куда рисовать
   * @param {Object} options
   *   onMove(from, to, done)  — игрок двинул фигуру; done(ok) вернёт управление
   *   interactive             — можно ли двигать фигуры
   */
  function Board(root, options) {
    this.root = root;
    this.options = options || {};
    this.fen = null;
    this.squares = null;
    /* законные ходы белых в записи e2e4; null — список неизвестен */
    this.legal = null;
    this.selected = -1;
    this.highlight = [];
    this.cells = [];
    this.locked = false;
    this.build();
  }

  Board.prototype.build = function () {
    this.root.innerHTML = '';
    this.root.classList.add('board');
    for (var index = 0; index < 64; index++) {
      var cell = document.createElement('button');
      cell.type = 'button';
      /* a8 — светлое поле: сумма номеров ряда и столбца там чётная */
      cell.classList.add('cell', (Math.floor(index / 8) + index % 8) % 2 ? 'dark' : 'light');
      cell.dataset.index = String(index);
      cell.dataset.square = squareName(index);
      cell.setAttribute('aria-label', squareName(index));
      cell.addEventListener('click', this.onClick.bind(this, index));
      this.root.appendChild(cell);
      this.cells.push(cell);
    }
  };

  Board.prototype.setPosition = function (fen, highlight, legal) {
    this.fen = fen;
    this.squares = parseFen(fen);
    this.highlight = highlight || [];
    this.legal = legal === undefined ? null : legal;
    this.selected = -1;
    this.render();
  };

  /** Законен ли ход по присланному сервером списку (без списка — не известно). */
  Board.prototype.isLegal = function (from, to) {
    if (!this.legal) { return true; }
    var key = from + to;
    return this.legal.some(function (move) { return move.slice(0, 4) === key; });
  };

  /** Берёт ли ход фигуру — включая взятие на проходе (пешка идёт наискосок на пустое поле). */
  Board.prototype.isCapture = function (from, to) {
    var squares = this.squares || parseFen(this.fen);
    var target = squares[indexOf(to)];
    if (target !== '.') { return target === target.toLowerCase(); }
    return squares[indexOf(from)] === 'P' && from[0] !== to[0];
  };

  /**
   * Рисует ход белых сразу, до ответа сервера. Правила здесь не нужны:
   * ход уже сверен со списком законных, остаётся переставить фигуры —
   * с ладьёй при рокировке, пешкой при взятии на проходе и ферзём при
   * превращении (сервер по умолчанию превращает пешку в ферзя).
   */
  Board.prototype.preview = function (from, to) {
    var squares = (this.squares || parseFen(this.fen)).slice();
    var a = indexOf(from);
    var b = indexOf(to);
    var piece = squares[a];
    if (piece === 'P' && to[0] !== from[0] && squares[b] === '.') {
      squares[b + 8] = '.';                         /* взятие на проходе */
    }
    if (piece === 'K' && Math.abs(a - b) === 2) {  /* рокировка */
      var rookFrom = b > a ? a + 3 : a - 4;
      var rookTo = b > a ? a + 1 : a - 1;
      squares[rookTo] = squares[rookFrom];
      squares[rookFrom] = '.';
    }
    squares[b] = piece === 'P' && to[1] === '8' ? 'Q' : piece;
    squares[a] = '.';
    this.squares = squares;
    this.highlight = [from, to];
    this.selected = -1;
    this.render();
  };

  function indexOf(square) {
    return RANKS.indexOf(square[1]) * 8 + FILES.indexOf(square[0]);
  }

  Board.prototype.render = function () {
    if (!this.fen) { return; }
    var squares = this.squares || parseFen(this.fen);
    for (var index = 0; index < 64; index++) {
      var cell = this.cells[index];
      var piece = squares[index];
      cell.textContent = piece === '.' ? '' : GLYPHS[piece] || '';
      cell.classList.toggle('white-piece', piece !== '.' && piece === piece.toUpperCase());
      cell.classList.toggle('black-piece', piece !== '.' && piece === piece.toLowerCase());
      cell.classList.toggle('selected', index === this.selected);
      cell.classList.toggle('marked', this.highlight.indexOf(squareName(index)) >= 0);
    }
  };

  Board.prototype.onClick = function (index) {
    if (this.locked || !this.options.interactive || !this.fen) { return; }

    var squares = this.squares || parseFen(this.fen);
    var piece = squares[index];
    var isOwn = piece !== '.' && piece === piece.toUpperCase();

    /* Первый щелчок выбирает свою фигуру, второй задаёт поле назначения.
       Щелчок по другой своей фигуре переносит выбор, а не считается ходом. */
    if (this.selected < 0 || isOwn) {
      if (!isOwn || turnOf(this.fen) !== 'w') { return; }
      this.selected = index;
      this.render();
      return;
    }

    var from = squareName(this.selected);
    var to = squareName(index);
    this.selected = -1;
    this.render();

    if (typeof this.options.onMove === 'function') {
      this.locked = true;
      var board = this;
      var release = function () { board.locked = false; };
      /* Ошибка в обработчике не должна оставить доску запертой навсегда. */
      try {
        this.options.onMove(from, to, release);
      } catch (error) {
        release();
        throw error;
      }
    }
  };

  Board.prototype.lock = function (value) { this.locked = !!value; };

  /* --- разговор с сервером ------------------------------------------------ */

  function post(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (response) { return response.json(); });
  }

  function get(url) {
    return fetch(url).then(function (response) { return response.json(); });
  }

  /* --- викторина при взятии ------------------------------------------------ */

  /* --- реплики Пафнутия ---------------------------------------------------- */

  /* Недавно сказанное: уходит на сервер, чтобы паук не повторялся. */
  var said = [];
  var bubbleTimer = null;
  var spokenAt = 0;

  /**
   * Пафнутий говорит из своего угла: реплика появляется в облачке над пауком.
   * Если предыдущая прозвучала только что (ход игрока, сразу за ним — ответ
   * паука), новая дописывается к ней, иначе первую никто не успел бы прочесть.
   */
  function say(text) {
    if (!text) { return; }
    said.push(text);
    if (said.length > 10) { said.shift(); }

    var companion = document.getElementById('companion');
    var bubble = document.getElementById('companion-bubble');
    if (!companion || !bubble) { return; }

    var now = Date.now();
    var line = document.createElement('p');
    line.textContent = text;
    if (companion.classList.contains('speaking') && now - spokenAt < 2500) {
      while (bubble.children.length > 1) { bubble.removeChild(bubble.firstChild); }
    } else {
      bubble.innerHTML = '';
    }
    bubble.appendChild(line);
    spokenAt = now;

    companion.classList.add('speaking');
    clearTimeout(bubbleTimer);
    var shown = 4500 + 45 * bubble.textContent.length;
    bubbleTimer = setTimeout(function () { companion.classList.remove('speaking'); }, shown);
  }

  /**
   * Показывает вопрос и возвращает обещание с ответом сервера.
   * Пока вопрос открыт, доска заблокирована вызывающей стороной.
   */
  function askQuiz(host) {
    return get('/api/quiz/word').then(function (question) {
      if (!question || !question.word) { return null; }
      return new Promise(function (resolve) {
        host.innerHTML = '';
        host.hidden = false;

        var title = document.createElement('p');
        title.className = 'quiz-prompt';
        title.textContent = question.prompt;
        host.appendChild(title);

        var word = document.createElement('p');
        word.className = 'quiz-word';
        word.textContent = question.word;
        host.appendChild(word);

        var note = document.createElement('p');
        note.className = 'note';
        note.textContent = 'Слово записано латиницей: алфавит подсказки не даёт.';
        host.appendChild(note);

        var row = document.createElement('div');
        row.className = 'quiz-options';
        question.options.forEach(function (option) {
          var button = document.createElement('button');
          button.type = 'button';
          button.textContent = option.name;
          button.addEventListener('click', function () {
            row.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
            post('/api/quiz/answer', { word: question.word, answer: option.code, said: said })
              .then(function (verdict) {
                showQuizVerdict(host, verdict);
                say(verdict.line);
                setTimeout(function () { resolve(verdict); }, 2600);
              });
          });
          row.appendChild(button);
        });
        host.appendChild(row);
      });
    });
  }

  function showQuizVerdict(host, verdict) {
    var box = document.createElement('div');
    box.className = 'quiz-verdict ' + (verdict.correct ? 'ok' : 'bad');

    var head = document.createElement('p');
    head.innerHTML = '<b>' + (verdict.correct ? 'Верно' : 'Неверно') + '.</b> «' +
      verdict.word + '» — ' + verdict.language_name +
      ' (в корпусе: ' + verdict.original + ').';
    box.appendChild(head);

    if (verdict.opinion_summary) {
      var note = document.createElement('p');
      note.className = 'note';
      note.textContent = verdict.opinion_summary;
      box.appendChild(note);
    }
    host.appendChild(box);
  }

  global.Tolmach = global.Tolmach || {};
  global.Tolmach.Board = Board;
  global.Tolmach.askQuiz = askQuiz;
  global.Tolmach.say = say;
  global.Tolmach.said = said;
  global.Tolmach.post = post;
  global.Tolmach.get = get;
  global.Tolmach.squareName = squareName;
  global.Tolmach.parseFen = parseFen;
  global.Tolmach.turnOf = turnOf;
})(window);
