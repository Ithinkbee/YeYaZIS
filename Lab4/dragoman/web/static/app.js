// Небольшие удобства интерфейса. Всё работает и без JavaScript: формы
// отправляются кнопками, вкладки — ссылками, меню «Сохранить» — элемент
// <details>. Без JavaScript не работает только тир Пафнутия.

(function (global) {
  // меню «Сохранить» закрывается при щелчке мимо него
  document.addEventListener('click', function (event) {
    document.querySelectorAll('details.menu[open]').forEach(function (menu) {
      if (!menu.contains(event.target)) menu.removeAttribute('open');
    });
  });

  // кнопка «Пример» на главной
  var example = document.getElementById('example-button');
  if (example) {
    example.addEventListener('click', function () {
      var area = document.getElementById('text');
      area.value = example.dataset.example;
      area.focus();
    });
  }

  // --- реплики Пафнутия ------------------------------------------------------

  var said = [];
  var bubbleTimer = null;
  var spokenAt = 0;

  function say(text) {
    if (!text) return;
    said.push(text);
    if (said.length > 12) said.shift();
    var companion = document.getElementById('companion');
    var bubble = document.getElementById('companion-bubble');
    if (!companion || !bubble) return;
    var now = Date.now();
    var line = document.createElement('p');
    line.textContent = text;
    if (companion.classList.contains('speaking') && now - spokenAt < 2500) {
      while (bubble.children.length > 1) bubble.removeChild(bubble.firstChild);
    } else {
      bubble.textContent = '';
    }
    bubble.appendChild(line);
    spokenAt = now;
    companion.classList.add('speaking');
    clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(function () { companion.classList.remove('speaking'); }, 4000 + 45 * bubble.textContent.length);
  }

  function pick(lines, occasion, fields) {
    var variants = (lines && lines[occasion]) || [];
    var filled = variants.map(function (text) {
      var complete = true;
      var result = text.replace(/\{(\w+)\}/g, function (all, name) {
        if (fields && fields[name] !== undefined) return fields[name];
        complete = false;
        return all;
      });
      return complete ? result : '';
    }).filter(Boolean);
    var fresh = filled.filter(function (text) { return said.indexOf(text) < 0; });
    var pool = fresh.length ? fresh : filled;
    return pool.length ? pool[Math.floor(Math.random() * pool.length)] : '';
  }

  var brand = document.querySelector('header.top .brand');
  var nav = document.querySelector('header.top nav');
  function checkHeader() {
    if (brand && nav) document.body.classList.toggle('header-wrapped', nav.offsetTop > brand.offsetTop + 10);
  }
  checkHeader();
  window.addEventListener('resize', checkHeader);

  var companion = document.getElementById('companion');
  var bubble = document.getElementById('companion-bubble');
  if (companion && bubble && companion.dataset.speaks) {
    var greeting = bubble.textContent.trim();
    setTimeout(function () { say(greeting); }, 300);
  }

  global.Dragoman = { say: say, pick: pick, said: said };
})(window);
