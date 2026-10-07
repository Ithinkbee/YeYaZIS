/* Текст для чтения: абзацы и предложения, подсветка прочитанного.
 *
 * Сервер присылает разбор текста (/api/prepare): абзацы, предложения с
 * положением в исходном тексте и токены, которые читаются не так, как
 * написаны. Здесь из этого строится страница: каждое предложение — отдельный
 * элемент, по которому можно щёлкнуть; изменённые токены подчёркнуты, а
 * подсказка над ними говорит, как они прозвучат. Звучащее слово (у голоса
 * браузера) отмечается через CSS Custom Highlight API — без изменения
 * разметки.
 */

(function (global) {
  'use strict';

  var G = global.Glashatai;

  function flat(doc) {
    var list = [];
    (doc.paragraphs || []).forEach(function (paragraph) {
      paragraph.sentences.forEach(function (sentence) { list.push(sentence); });
    });
    return list;
  }

  /** Предложение в разметке: текст с отмеченными изменёнными токенами. */
  function sentenceNode(text, sentence) {
    var span = G.element('span', 'sent');
    span.dataset.index = sentence.index;
    var position = sentence.start;
    (sentence.changes || []).forEach(function (change) {
      if (change.start < position) { return; }
      if (change.start > position) { span.appendChild(document.createTextNode(text.slice(position, change.start))); }
      var mark = G.element('span', 'chg', text.slice(change.start, change.end));
      mark.title = change.kind_ru + (change.say ? ': «' + change.say + '»' : ': не читается');
      span.appendChild(mark);
      position = change.end;
    });
    if (position < sentence.end) { span.appendChild(document.createTextNode(text.slice(position, sentence.end))); }
    return span;
  }

  /**
   * Строит текст в container. options.onPick(index, event) — щелчок по предложению.
   * Возвращает объект с методами подсветки.
   */
  function render(container, text, doc, options) {
    options = options || {};
    container.textContent = '';
    var sentences = flat(doc);
    var spans = [];
    (doc.paragraphs || []).forEach(function (paragraph) {
      var block = G.element(paragraph.heading ? 'h3' : 'p');
      var position = null;
      paragraph.sentences.forEach(function (sentence) {
        if (position !== null && sentence.start > position) {
          block.appendChild(document.createTextNode(' '));
        }
        var node = sentenceNode(text, sentence);
        spans[sentence.index] = node;
        block.appendChild(node);
        position = sentence.end;
      });
      container.appendChild(block);
    });
    container.addEventListener('click', function (event) {
      var target = event.target.closest('.sent');
      if (target && options.onPick) { options.onPick(Number(target.dataset.index), event); }
    });

    var current = -1;
    var highlight = global.CSS && CSS.highlights && global.Highlight ? new global.Highlight() : null;
    if (highlight) { CSS.highlights.set('now-word', highlight); }

    return {
      sentences: sentences,
      span: function (index) { return spans[index]; },
      /** Подсветить предложение index; state — loading или speaking. */
      mark: function (index, state, scroll) {
        if (current >= 0 && spans[current]) {
          spans[current].classList.remove('is-current', 'is-loading');
        }
        spans.forEach(function (node, i) {
          if (node) { node.classList.toggle('is-read', index >= 0 && i < index); }
        });
        current = index;
        if (highlight) { highlight.clear(); }
        var node = spans[index];
        if (!node) { return; }
        node.classList.add(state === 'loading' ? 'is-loading' : 'is-current');
        node.classList.remove(state === 'loading' ? 'is-current' : 'is-loading');
        if (scroll !== false) {
          var at = node.getBoundingClientRect();
          if (container.scrollHeight > container.clientHeight + 4) {
            /* текст в своей прокручиваемой области */
            var box = container.getBoundingClientRect();
            if (at.top < box.top + 30 || at.bottom > box.bottom - 30) {
              container.scrollTop += at.top - box.top - box.height / 3;
            }
          } else if (at.top < 70 || at.bottom > global.innerHeight - 40) {
            /* текст во всю страницу — прокручивается страница */
            node.scrollIntoView({ block: 'center', behavior: 'smooth' });
          }
        }
      },
      clear: function () {
        spans.forEach(function (node) { if (node) { node.classList.remove('is-current', 'is-loading', 'is-read'); } });
        current = -1;
        if (highlight) { highlight.clear(); }
      },
      /**
       * Звучащее слово. Браузер сообщает положение в нормализованном тексте; в
       * исходном оно приблизительно пропорционально — слово ищется рядом.
       */
      word: function (index, at, length, written) {
        var node = spans[index];
        var sentence = sentences[index];
        if (!highlight || !node || !sentence) { return; }
        var source = text.slice(sentence.start, sentence.end);
        var share = written ? at / Math.max(1, written.length) : 0;
        var guess = Math.round(share * source.length);
        var left = guess;
        while (left > 0 && /\S/.test(source[left - 1])) { left--; }
        var right = guess;
        while (right < source.length && /\S/.test(source[right])) { right++; }
        if (right <= left) { return; }
        var range = rangeFor(node, left, right);
        highlight.clear();
        if (range) { highlight.add(range); }
      }
    };
  }

  /** Диапазон по смещениям символов внутри элемента. */
  function rangeFor(node, start, end) {
    var walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    var offset = 0;
    var range = document.createRange();
    var started = false;
    var text;
    while ((text = walker.nextNode())) {
      var length = text.nodeValue.length;
      if (!started && start <= offset + length) {
        range.setStart(text, Math.max(0, start - offset));
        started = true;
      }
      if (started && end <= offset + length) {
        range.setEnd(text, Math.max(0, end - offset));
        return range;
      }
      offset += length;
    }
    return null;
  }

  /** «Как прочтёт»: текст, каким его получит синтезатор, изменённое отмечено. */
  function spoken(container, text, doc) {
    container.textContent = '';
    (doc.paragraphs || []).forEach(function (paragraph) {
      var block = G.element(paragraph.heading ? 'h3' : 'p');
      paragraph.sentences.forEach(function (sentence) {
        var position = sentence.start;
        (sentence.changes || []).forEach(function (change) {
          if (change.start < position) { return; }
          block.appendChild(document.createTextNode(text.slice(position, change.start)));
          if (change.say) {
            var mark = G.element('span', 'chg-out' + (change.kind === 'english' ? ' en' : ''), change.say.trim());
            mark.title = change.kind_ru + ': «' + change.text + '»';
            block.appendChild(mark);
          }
          position = change.end;
        });
        block.appendChild(document.createTextNode(text.slice(position, sentence.end) + ' '));
      });
      container.appendChild(block);
    });
  }

  G.DocView = { render: render, spoken: spoken, flat: flat };
})(window);
