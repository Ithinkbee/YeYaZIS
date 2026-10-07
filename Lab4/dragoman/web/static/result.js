// Страница перевода: подсветка соответствия слов, вкладки, дерево выбранного предложения.

(function () {
  // --- соответствие слов: немецкое слово знает свои английские (data-src) --------
  function words(selector) {
    return Array.prototype.slice.call(document.querySelectorAll(selector));
  }

  function clear() {
    words('.w.is-hl').forEach(function (w) { w.classList.remove('is-hl'); });
    words('.sent.is-on').forEach(function (s) { s.classList.remove('is-on'); });
  }

  function highlight(sentence, sources) {
    clear();
    words('.sent[data-s="' + sentence + '"]').forEach(function (s) { s.classList.add('is-on'); });
    sources.forEach(function (i) {
      words('.en .w[data-s="' + sentence + '"][data-i="' + i + '"]').forEach(function (w) { w.classList.add('is-hl'); });
    });
    words('.de .w[data-s="' + sentence + '"]').forEach(function (w) {
      var src = (w.dataset.src || '').split(',');
      if (sources.some(function (i) { return src.indexOf(String(i)) >= 0; })) w.classList.add('is-hl');
    });
  }

  var parallel = document.getElementById('parallel');
  if (parallel) {
    parallel.addEventListener('mouseover', function (event) {
      var w = event.target.closest('.w');
      if (!w) return;
      var sentence = w.dataset.s;
      if (w.dataset.src !== undefined) {
        highlight(sentence, (w.dataset.src || '').split(',').filter(Boolean).map(Number));
      } else if (w.dataset.i !== undefined) {
        highlight(sentence, [Number(w.dataset.i)]);
      }
    });
    parallel.addEventListener('mouseleave', clear);
  }

  // --- параллельно / только перевод ----------------------------------------------
  var layout = document.getElementById('layout-switch');
  if (layout && parallel) {
    layout.addEventListener('click', function (event) {
      var link = event.target.closest('a');
      if (!link) return;
      event.preventDefault();
      layout.querySelectorAll('a').forEach(function (a) { a.classList.toggle('on', a === link); });
      parallel.classList.toggle('german-only', link.dataset.layout === 'german');
    });
  }

  // --- копирование перевода ----------------------------------------------------------
  var copy = document.getElementById('copy-german');
  if (copy) {
    copy.addEventListener('click', function () {
      var text = document.getElementById('german-text').value;
      var note = document.getElementById('copy-note');
      var done = function () { note.textContent = 'скопировано'; setTimeout(function () { note.textContent = ''; }, 2000); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { note.textContent = 'не удалось скопировать'; });
      } else {
        var area = document.getElementById('german-text');
        area.hidden = false;
        area.select();
        try { document.execCommand('copy'); done(); } catch (e) { note.textContent = 'не удалось скопировать'; }
        area.hidden = true;
      }
    });
  }

  // --- вкладки без перезагрузки ---------------------------------------------------------
  var tabs = document.getElementById('tabs');
  if (tabs) {
    tabs.addEventListener('click', function (event) {
      var link = event.target.closest('a[data-tab]');
      if (!link) return;
      event.preventDefault();
      var name = link.dataset.tab;
      tabs.querySelectorAll('a').forEach(function (a) { a.classList.toggle('on', a === link); });
      document.querySelectorAll('.tab-panel').forEach(function (panel) { panel.hidden = panel.dataset.panel !== name; });
      var url = new URL(location.href);
      url.searchParams.set('tab', name);
      history.replaceState(null, '', url.pathname + url.search + '#tabs');
    });
  }

  // --- дерево выбранного предложения ------------------------------------------------------
  var select = document.getElementById('tree-select');
  if (select) {
    select.addEventListener('change', function () {
      var view = document.getElementById('tree-view');
      var url = '/t/' + select.dataset.uid + '/tree?s=' + select.value;
      view.style.opacity = 0.5;
      fetch(url).then(function (r) { return r.text(); }).then(function (html) {
        view.innerHTML = html;
        view.style.opacity = 1;
        var page = new URL(location.href);
        page.searchParams.set('tab', 'tree');
        page.searchParams.set('s', select.value);
        history.replaceState(null, '', page.pathname + page.search + '#tabs');
      }, function () {
        location.href = '?tab=tree&s=' + select.value + '#tabs';
      });
    });
  }
})();
