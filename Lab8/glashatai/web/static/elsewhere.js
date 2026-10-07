/* Из других программ: включить слежение за буфером обмена и горячие клавиши,
 * показать, что прочитано. Состояние приходит потоком событий сервера. */

(function (global) {
  'use strict';

  var G = global.Glashatai;

  G.ready(function () {
    var $ = function (id) { return document.getElementById(id); };
    var boot = JSON.parse($('boot').textContent);
    var prefs = G.loadPrefs({ settings: boot.settings, options: boot.options });
    var voice = (boot.voices || []).filter(function (v) { return v.id === prefs.settings.voice; })[0];
    $('reading-voice').textContent = (voice ? voice.title : prefs.settings.voice) + ', темп ×' +
      Number(prefs.settings.rate).toFixed(2).replace('.', ',') + ', громкость ' + Math.round(prefs.settings.volume) + ' %' +
      (voice && voice.engine === 'browser' ? ' (голос браузера в других программах заменяет ' + boot.default + ')' : '');
    /* настройки «Чтеца» — те, которыми читаются тексты из других программ */
    G.savePrefs(prefs);

    var labels = { clipboard: 'буфер обмена', selection: 'выделено, Ctrl+Alt+R', stop: 'замолчать', empty: 'пусто' };

    function show(state) {
      [['clipboard', state.clipboard], ['hotkeys', state.hotkeys]].forEach(function (pair) {
        var button = $(pair[0] + '-toggle');
        button.dataset.on = pair[1] ? '1' : '0';
        button.textContent = pair[1] ? 'Выключить' : 'Включить';
        button.className = pair[1] ? '' : 'ghost';
      });
      $('desktop-problem').textContent = state.problem || '';
      var list = $('events');
      list.textContent = '';
      var events = (state.events || []).slice().reverse();
      if (!events.length) { list.appendChild(G.element('li', 'muted', 'Пока ничего.')); }
      events.forEach(function (event) {
        var item = G.element('li');
        item.appendChild(G.element('time', '', event.time));
        item.appendChild(G.element('span', 'tag tag-gold', labels[event.kind] || event.kind));
        item.appendChild(document.createTextNode(' ' + event.text));
        list.appendChild(item);
      });
    }
    show(JSON.parse($('desktop-state').textContent));

    function toggle(name) {
      var button = $(name + '-toggle');
      var body = {};
      body[name] = button.dataset.on !== '1';
      G.api('POST', '/api/desktop', body).then(function (state) {
        if (state.error) { G.toast(state.error, 4000); return; }
        show(state);
        if (name === 'clipboard' && state.clipboard) { G.say('Копируй — прочту.'); }
        if (name === 'hotkeys' && state.hotkeys) { G.say('Выдели текст и нажми Ctrl+Alt+R.'); }
      });
    }
    $('clipboard-toggle').addEventListener('click', function () { toggle('clipboard'); });
    $('hotkeys-toggle').addEventListener('click', function () { toggle('hotkeys'); });
    $('desk-stop').addEventListener('click', function () { G.api('POST', '/api/stop'); });

    $('bookmarklet').addEventListener('click', function (event) {
      event.preventDefault();
      G.toast('Перетащите кнопку на панель закладок, а потом нажмите её на нужной странице.', 4000);
    });

    if (global.EventSource) {
      var events = new global.EventSource('/api/events?role=status');
      events.onmessage = function (message) {
        var event;
        try { event = JSON.parse(message.data); } catch (e) { return; }
        if (event.state) { show(event.state); }
      };
    }
  });
})(window);
