// Небольшие удобства интерфейса. Всё работает и без JavaScript: формы
// отправляются кнопками, меню «Сохранить» — это элемент <details>. Без
// JavaScript не работают только игры Пафнутия.

(function (global) {
  // Исходный документ: показать вес всех предложений (тепловая карта)
  var toggle = document.getElementById("heat-toggle");
  var source = document.getElementById("source");
  if (toggle && source) {
    var key = "izbornik-heat";
    try { toggle.checked = localStorage.getItem(key) === "1"; } catch (e) {}
    var apply = function () { source.classList.toggle("heat", toggle.checked); };
    toggle.addEventListener("change", function () {
      apply();
      try { localStorage.setItem(key, toggle.checked ? "1" : "0"); } catch (e) {}
    });
    apply();
    // прокрутка к первому предложению реферата
    var first = source.querySelector(".picked");
    if (first && location.hash === "#first") first.scrollIntoView({ block: "center" });
  }

  // меню «Сохранить в файл» закрывается при щелчке мимо него
  document.addEventListener("click", function (event) {
    document.querySelectorAll("details.menu[open]").forEach(function (menu) {
      if (!menu.contains(event.target)) menu.removeAttribute("open");
    });
  });

  // --- реплики Пафнутия ------------------------------------------------------

  // недавно сказанное: такие реплики повторяются, только если других не осталось
  var said = [];
  var bubbleTimer = null;
  var spokenAt = 0;

  /* Пафнутий говорит из угла: реплика появляется в облачке под пауком. Если
     предыдущая прозвучала только что, новая дописывается к ней — иначе
     первую никто не успел бы прочесть. */
  function say(text) {
    if (!text) return;
    said.push(text);
    if (said.length > 12) said.shift();

    var companion = document.getElementById("companion");
    var bubble = document.getElementById("companion-bubble");
    if (!companion || !bubble) return;

    var now = Date.now();
    var line = document.createElement("p");
    line.textContent = text;
    if (companion.classList.contains("speaking") && now - spokenAt < 2500) {
      while (bubble.children.length > 1) bubble.removeChild(bubble.firstChild);
    } else {
      bubble.textContent = "";
    }
    bubble.appendChild(line);
    spokenAt = now;

    companion.classList.add("speaking");
    clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(function () {
      companion.classList.remove("speaking");
    }, 4000 + 45 * bubble.textContent.length);
  }

  /* Реплика по поводу из набора, присланного страницей: {повод: [варианты]}.
     Поля вида {word} подставляются; вариант, которому поля не хватило, не
     выбирается. */
  function pick(lines, occasion, fields) {
    var variants = (lines && lines[occasion]) || [];
    var filled = variants.map(function (text) {
      var complete = true;
      var result = text.replace(/\{(\w+)\}/g, function (all, name) {
        if (fields && fields[name] !== undefined) return fields[name];
        complete = false;
        return all;
      });
      return complete ? result : "";
    }).filter(Boolean);
    var fresh = filled.filter(function (text) { return said.indexOf(text) < 0; });
    var pool = fresh.length ? fresh : filled;
    return pool.length ? pool[Math.floor(Math.random() * pool.length)] : "";
  }

  // меню ушло на вторую строку шапки — облачко паука не должно его закрывать
  var brand = document.querySelector("header.top .brand");
  var nav = document.querySelector("header.top nav");
  function checkHeader() {
    if (brand && nav) document.body.classList.toggle("header-wrapped", nav.offsetTop > brand.offsetTop + 10);
  }
  checkHeader();
  window.addEventListener("resize", checkHeader);

  // вердикт или приветствие игры звучит сам, без наведения на паука
  var companion = document.getElementById("companion");
  var bubble = document.getElementById("companion-bubble");
  if (companion && bubble && companion.dataset.speaks) {
    var greeting = bubble.textContent.trim();
    setTimeout(function () { say(greeting); }, 300);
  }

  global.Izbornik = { say: say, pick: pick, said: said };
})(window);
