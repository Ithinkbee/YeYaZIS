/* Статья: чтение по щелчку, под указателем мыши и выделенного фрагмента.
 *
 * «Под указателем» — так экранные дикторы читают то, на что смотрит мышь:
 * если задержать указатель на предложении на 0,7 с, оно прочитается само.
 * Полоска, бегущая по предложению, показывает, сколько осталось ждать.
 * Выделенный мышью фрагмент читается кнопкой, которая появляется рядом с
 * выделением.
 */

(function (global) {
  'use strict';

  var G = global.Glashatai;
  var DWELL = 700;

  G.ready(function () {
    var $ = function (id) { return document.getElementById(id); };
    var boot = JSON.parse($('boot').textContent);
    var text = JSON.parse($('article-text').textContent);
    var container = $('reading');
    var view = null;

    var settings = G.Settings(boot, function (kind) {
      if (kind === 'volume') { player.setVolume(settings.prefs().settings.volume); }
      if (kind === 'synthesis') { player.invalidate(); }
      if (kind === 'options') { player.stop(); parse(); }
    });

    var player = new G.Player({
      prefs: settings.prefs,
      onState: function (state, info) {
        $('status').className = 'status-line state-' + (state === 'idle' ? 'ready' : state);
        $('play-label').textContent = state === 'speaking' || state === 'loading' ? 'Пауза' :
          state === 'paused' ? 'Дальше' : 'Читать статью';
        document.querySelector('#play .glyph').textContent = state === 'speaking' || state === 'loading' ? '⏸' : '▶';
        $('status-text').textContent = { idle: info.finished ? 'Дочитано' : 'Готов читать', loading: 'Синтезирую…',
                                         speaking: 'Читаю', paused: 'Пауза' }[state];
        if (view && (state === 'loading' || state === 'speaking')) { view.mark(player.index, state); }
      },
      onSentence: function (index) { if (view) { view.mark(index, 'loading'); } },
      onWord: function (index, at, length) {
        if (view) { view.word(index, at, length, (player.sentences[index] || {}).written); }
      },
      onError: function (message) { G.toast('Не прочитано: ' + message, 4500); }
    });

    function parse() {
      return G.api('POST', '/api/prepare', { text: text, options: settings.prefs().options }).then(function (doc) {
        if (doc.error) { container.textContent = doc.error; return; }
        view = G.DocView.render(container, text, doc, {
          onPick: function (index) {
            if (hoverMode.checked) { return; }
            player.play(index, single.checked ? index : undefined);
          }
        });
        player.load(view.sentences);
      });
    }
    parse();

    $('play').addEventListener('click', function () {
      if (player.state === 'idle') { player.play(Math.max(0, player.index)); }
      else { player.toggle(); }
    });
    $('stop').addEventListener('click', function () { player.stop(); if (view) { view.clear(); } });
    $('next').addEventListener('click', function () { player.next(); });
    $('prev').addEventListener('click', function () { player.prev(); });
    var selectionPlayer = null;
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        player.stop();
        if (selectionPlayer) { selectionPlayer.stop(); }
      }
    });

    /* --- под указателем ----------------------------------------------------------- */

    var hoverMode = $('hover-mode');
    var single = $('single');
    try {
      hoverMode.checked = global.localStorage.getItem('glashatai-hover') === '1';
      single.checked = global.localStorage.getItem('glashatai-single') === '1';
    } catch (e) { /* без хранилища */ }
    function applyHover() {
      container.classList.toggle('hover-mode', hoverMode.checked);
      try {
        global.localStorage.setItem('glashatai-hover', hoverMode.checked ? '1' : '0');
        global.localStorage.setItem('glashatai-single', single.checked ? '1' : '0');
      } catch (e) { /* без хранилища */ }
      if (hoverMode.checked) { G.say('Наведи мышь на предложение и подержи — прочитаю.'); }
    }
    hoverMode.addEventListener('change', applyHover);
    single.addEventListener('change', applyHover);
    applyHover();

    var armed = null;
    var armedAt = 0;
    var frame = null;
    function disarm() {
      if (armed) { armed.classList.remove('is-armed'); armed.style.removeProperty('--armed'); }
      armed = null;
      if (frame) { global.cancelAnimationFrame(frame); frame = null; }
    }
    function tick(now) {
      if (!armed) { return; }
      var share = Math.min(1, (now - armedAt) / DWELL);
      armed.style.setProperty('--armed', Math.round(share * 100) + '%');
      if (share >= 1) {
        var index = Number(armed.dataset.index);
        disarm();
        if (index !== player.index || player.state === 'idle') { player.play(index, index); }
        return;
      }
      frame = global.requestAnimationFrame(tick);
    }
    container.addEventListener('mouseover', function (event) {
      if (!hoverMode.checked) { return; }
      var target = event.target.closest('.sent');
      if (!target || target === armed) { return; }
      disarm();
      if (Number(target.dataset.index) === player.index && player.state !== 'idle') { return; }
      armed = target;
      armed.classList.add('is-armed');
      armedAt = performance.now();
      frame = global.requestAnimationFrame(tick);
    });
    container.addEventListener('mouseleave', disarm);

    /* --- выделенный фрагмент --------------------------------------------------------- */

    var button = G.element('button', 'gold selection-button', '▶ Прочитать выделенное');
    button.type = 'button';
    button.hidden = true;
    document.body.appendChild(button);
    var selected = '';
    document.addEventListener('mouseup', function (event) {
      if (event.target === button) { return; }
      setTimeout(function () {
        var selection = global.getSelection();
        selected = selection ? String(selection).trim() : '';
        if (!selected || selected.length < 2 || !container.contains(selection.anchorNode)) {
          button.hidden = true;
          return;
        }
        var box = selection.getRangeAt(0).getBoundingClientRect();
        button.style.left = (global.scrollX + box.left) + 'px';
        button.style.top = (global.scrollY + box.bottom + 8) + 'px';
        button.hidden = false;
      }, 10);
    });
    button.addEventListener('click', function () {
      button.hidden = true;
      var fragment = selected;
      G.api('POST', '/api/prepare', { text: fragment, options: settings.prefs().options }).then(function (doc) {
        if (doc.error) { G.toast(doc.error); return; }
        var sentences = G.DocView.flat(doc);
        var temporary = new G.Player({
          prefs: settings.prefs,
          onError: function (message) { G.toast('Не прочитано: ' + message, 4500); }
        });
        player.stop();
        if (selectionPlayer) { selectionPlayer.stop(); }
        selectionPlayer = temporary;
        temporary.load(sentences);
        temporary.play(0);
      });
    });

    G.article = { player: player, settings: settings };
  });
})(window);
