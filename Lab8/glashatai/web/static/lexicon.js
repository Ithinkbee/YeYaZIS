/* Словарь произношения: записи пользователя, проверка фразы, поиск по встроенным словарям. */

(function (global) {
  'use strict';

  var G = global.Glashatai;

  G.ready(function () {
    var $ = function (id) { return document.getElementById(id); };
    var boot = JSON.parse($('boot').textContent);
    var prefs = G.loadPrefs({ settings: boot.settings, options: boot.options });
    if (String(prefs.settings.voice).indexOf('browser:') === 0) { prefs.settings.voice = boot.default; }
    var player = new G.Player({
      prefs: function () { return prefs; },
      onError: function (message) { G.toast('Не прочитано: ' + message, 4000); }
    });

    /* прочитать текст голосом «Чтеца» */
    function listen(text) {
      if (!text.trim()) { return; }
      G.api('POST', '/api/prepare', { text: text, options: prefs.options }).then(function (doc) {
        if (doc.error) { G.toast(doc.error); return; }
        player.load(G.DocView.flat(doc));
        player.play(0);
      });
    }

    function row(entry) {
      var line = G.element('tr', 'lex-row');
      var written = G.element('input');
      written.value = entry.written;
      written.maxLength = 60;
      var reading = G.element('input');
      reading.value = entry.reading;
      reading.maxLength = 120;
      [written, reading].forEach(function (input) {
        input.type = 'text';
        input.lang = 'de';
        var cell = G.element('td');
        cell.appendChild(input);
        line.appendChild(cell);
      });
      var actions = G.element('td', 'actions');
      var play = G.element('button', 'ghost small-button', '▶');
      play.type = 'button';
      play.title = 'Послушать';
      play.addEventListener('click', function () { listen(written.value); });
      var save = G.element('button', 'ghost small-button', 'Сохранить');
      save.type = 'button';
      save.addEventListener('click', function () {
        G.api('PUT', '/api/lexicon/' + encodeURIComponent(entry.id), { written: written.value, reading: reading.value })
          .then(update);
      });
      var remove = G.element('button', 'ghost small-button', 'Удалить');
      remove.type = 'button';
      remove.addEventListener('click', function () {
        G.api('DELETE', '/api/lexicon/' + encodeURIComponent(entry.id)).then(update);
      });
      [play, save, remove].forEach(function (button) {
        actions.appendChild(button);
        actions.appendChild(document.createTextNode(' '));
      });
      line.appendChild(actions);
      return line;
    }

    function show(entries) {
      var rows = $('lex-rows');
      rows.textContent = '';
      entries.forEach(function (entry) { rows.appendChild(row(entry)); });
      $('lex-table').hidden = !entries.length;
      $('lex-empty').hidden = !!entries.length;
      $('lex-count').textContent = entries.length ? entries.length + ' слов' : '';
    }

    function update(data) {
      $('lex-error').textContent = data.error ? 'Не сохранено: ' + data.error : '';
      if (data.entries) { show(data.entries); }
      if (!data.error) { probe(); }
      return data;
    }

    G.api('GET', '/api/lexicon').then(update);

    $('lex-add').addEventListener('submit', function (event) {
      event.preventDefault();
      G.api('POST', '/api/lexicon', { written: $('lex-written').value, reading: $('lex-reading').value }).then(function (data) {
        update(data);
        if (!data.error) {
          G.say('Записал. Теперь прочту «' + $('lex-written').value + '» по-твоему.');
          $('lex-written').value = '';
          $('lex-reading').value = '';
          $('lex-written').focus();
        }
      });
    });
    $('lex-listen').addEventListener('click', function () { listen($('lex-reading').value.replace(/'/g, '')); });

    function probe() {
      var text = $('probe').value;
      G.api('POST', '/api/prepare', { text: text, options: prefs.options }).then(function (doc) {
        if (doc.error) { $('probe-result').textContent = doc.error; return; }
        G.DocView.spoken($('probe-result'), text, doc);
      });
    }
    $('probe-form').addEventListener('submit', function (event) { event.preventDefault(); probe(); });
    $('probe-listen').addEventListener('click', function () { listen($('probe').value); });
    probe();

    $('filter').addEventListener('input', function () {
      var query = $('filter').value.trim().toLowerCase();
      document.querySelectorAll('.filterable tbody tr').forEach(function (line) {
        line.hidden = query && line.textContent.toLowerCase().indexOf(query) < 0;
      });
    });
  });
})(window);
