// Клиентская часть интерфейса: автодополнение, фоновые задачи, языковой помощник,
// реплики паука-компаньона.

(function () {
  "use strict";

  // --- Автодополнение запроса ---------------------------------------------

  const input = document.getElementById("q");
  const list = document.getElementById("suggestions");

  if (input && list) {
    let timer = null;
    let active = -1;

    const hide = () => { list.hidden = true; active = -1; };

    const render = (items) => {
      list.innerHTML = "";
      if (!items.length) { hide(); return; }
      items.forEach((text) => {
        const item = document.createElement("li");
        item.textContent = text;
        item.addEventListener("mousedown", (event) => {
          event.preventDefault();
          input.value = text;
          hide();
          input.form.submit();
        });
        list.appendChild(item);
      });
      list.hidden = false;
    };

    const request = () => {
      const value = input.value.trim();
      if (value.length < 2) { hide(); return; }
      fetch("/api/suggest?q=" + encodeURIComponent(value))
        .then((response) => response.json())
        .then((data) => render(data.suggestions || []))
        .catch(hide);
    };

    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(request, 160);
    });

    input.addEventListener("keydown", (event) => {
      const items = Array.from(list.children);
      if (list.hidden || !items.length) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        items.forEach((item) => item.classList.remove("active"));
        active += event.key === "ArrowDown" ? 1 : -1;
        if (active < 0) active = items.length - 1;
        if (active >= items.length) active = 0;
        items[active].classList.add("active");
        input.value = items[active].textContent;
      } else if (event.key === "Enter" && active >= 0) {
        hide();
      } else if (event.key === "Escape") {
        hide();
      }
    });

    input.addEventListener("blur", () => setTimeout(hide, 150));
  }

  // --- Прогресс фоновой задачи (обход, индексация) ------------------------

  if (window.ARACHNE_WATCH_TASK) {
    const panel = document.getElementById("task-panel");
    const bar = document.getElementById("task-bar");
    const message = document.getElementById("task-message");
    const kind = document.getElementById("task-kind");
    let wasActive = false;

    const names = { crawl: "обход локальной сети", index: "построение индекса" };

    const poll = () => {
      fetch("/api/task")
        .then((response) => response.json())
        .then((task) => {
          if (task.active) {
            wasActive = true;
            panel.hidden = false;
            kind.textContent = names[task.kind] || task.kind;
            const percent = task.total ? Math.round((task.done / task.total) * 100) : 8;
            bar.style.width = percent + "%";
            message.textContent = (task.message || "") +
              (task.total ? ` (${task.done} из ${task.total})` : "");
            setTimeout(poll, 700);
          } else if (wasActive) {
            bar.style.width = "100%";
            message.textContent = task.result || "готово";
            setTimeout(() => window.location.reload(), 1200);
          }
        })
        .catch(() => setTimeout(poll, 2000));
    };
    poll();
  }

  // --- Языковой помощник ---------------------------------------------------

  const panel = document.getElementById("llm-panel");

  const show = (html, loading) => {
    if (!panel) return;
    panel.hidden = false;
    panel.className = "llm-panel" + (loading ? " loading" : "");
    panel.innerHTML = html;
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const post = (url, data) =>
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(data),
    }).then((response) => response.json());

  const escape = (text) =>
    String(text).replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));

  const answerButton = document.getElementById("llm-answer-btn");
  if (answerButton) {
    answerButton.addEventListener("click", () => {
      const query = answerButton.dataset.query;
      show("Читаю найденные документы…", true);
      post("/api/llm/answer", { q: query, top: 5 })
        .then((data) => {
          if (data.error) { show("Помощник недоступен: " + escape(data.error)); return; }
          const sources = (data.sources || [])
            .map((s) => `<a href="/doc/${s.id}?q=${encodeURIComponent(query)}">[${s.n}] ${escape(s.title)}</a>`)
            .join(" · ");
          show(`<b>Кратко по найденному</b>\n${escape(data.answer)}\n\n<small>${sources}</small>`);
        })
        .catch(() => show("Не удалось получить ответ помощника."));
    });
  }

  const rephrase = (button) => {
    const query = button.dataset.query;
    show("Подбираю формулировки…", true);
    post("/api/llm/rephrase", { q: query })
      .then((data) => {
        if (data.error) { show("Помощник недоступен: " + escape(data.error)); return; }
        const links = (data.variants || [])
          .map((v) => `<li><a href="/search?q=${encodeURIComponent(v)}">${escape(v)}</a></li>`)
          .join("");
        show(`<b>Попробуйте иначе</b><ul>${links}</ul>`);
      })
      .catch(() => show("Не удалось получить варианты."));
  };

  ["llm-rephrase-btn", "llm-rephrase-empty"].forEach((id) => {
    const button = document.getElementById(id);
    if (button) button.addEventListener("click", () => rephrase(button));
  });

  document.querySelectorAll(".llm-explain").forEach((button) => {
    button.addEventListener("click", () => {
      const box = button.nextElementSibling;
      box.hidden = false;
      box.textContent = "Думаю…";
      post("/api/llm/explain", { q: button.dataset.query, doc_id: button.dataset.doc })
        .then((data) => {
          box.textContent = data.error ? "Помощник недоступен: " + data.error : data.explanation;
        })
        .catch(() => { box.textContent = "Не удалось получить объяснение."; });
    });
  });

  // --- Разметка релевантности без перезагрузки страницы ---------------------
  //
  // Прогрессивное улучшение: формы остаются обычными формами и работают без
  // JavaScript, скрипт лишь перехватывает их submit. Раньше после оценки
  // браузер вставал в начало страницы, и казалось, что ничего не произошло.

  if (window.ARACHNE_QRELS) {
    const grid = document.getElementById("quality-grid");
    const counter = document.getElementById("judged-count");
    const capital = document.getElementById("capital-value");
    const names = { precision: "P", recall: "R", f1: "F1", ap: "AP", ndcg: "nDCG", bpref: "bpref" };

    const paintQuality = (values) => {
      if (!grid) return;
      grid.innerHTML = values
        .map((item) => {
          const was = item.delta
            ? `<span class="quality-was">${item.previous.toFixed(3)} →</span>`
            : "";
          const delta = item.delta
            ? `<span class="delta ${item.up ? "delta-up" : "delta-down"}">${item.delta}</span>`
            : "";
          return `<div class="quality-item flash" data-key="${item.key}">
            <span class="quality-name">${names[item.key] || item.key}</span>
            <span class="quality-value">${was}
              <b class="quality-now">${item.value.toFixed(3)}</b> ${delta}</span>
          </div>`;
        })
        .join("");
    };

    document.querySelectorAll(".judge-form").forEach((form) => {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const data = new FormData(form);
        const row = form.closest("tr");
        const rel = data.get("rel");

        fetch("/api/qrels/judge", { method: "POST", body: new URLSearchParams(data) })
          .then((response) => response.json())
          .then((result) => {
            row.className = "rel-" + (rel === "-1" ? "none" : rel);
            row.querySelectorAll(".judge-form button").forEach((button) => {
              button.classList.remove("judged", "judged-0", "judged-1", "judged-2");
            });
            if (rel !== "-1") {
              form.querySelector("button").classList.add("judged", "judged-" + rel);
            }
            // форма снятия оценки — последняя в ячейке
            const forms = Array.from(row.querySelectorAll(".judge-form"));
            forms[forms.length - 1].hidden = rel === "-1";

            paintQuality(result.rows || []);
            if (counter) counter.textContent = result.judged;
            if (capital) capital.textContent = String(result.capital).replace(
              /\B(?=(\d{3})+(?!\d))/g, " ");

            const note = document.getElementById("quality-map");
            if (note) {
              const share = result.map_share >= 0 ? "+" : "";
              note.innerHTML = `Вклад в общий MAP: <b>${share}${result.map_share.toFixed(3)}</b>
                (сейчас MAP = ${result.map.toFixed(3)}).`;
            }
          })
          .catch(() => form.submit());
      });
    });
  }

  // --- Модалка «Вы уверены?» ------------------------------------------------
  //
  // Escape закрывает её всегда — иначе это не шутка, а ловушка, из которой
  // нельзя выйти. Поведение кнопок зависит от покупки «Честные подтверждения».

  const shifty = window.ARACHNE_UI && window.ARACHNE_UI.shifty_modals;

  const ask = (text) =>
    new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "modal-overlay";
      overlay.innerHTML = `<div class="modal" role="dialog" aria-modal="true">
        <p class="modal-text"></p>
        <div class="modal-buttons"></div>
        <p class="muted small">Escape — закрыть</p></div>`;
      overlay.querySelector(".modal-text").textContent = text;

      const yes = document.createElement("button");
      yes.textContent = "Да";
      yes.className = "modal-yes";
      const no = document.createElement("button");
      no.textContent = "Нет";
      no.className = "ghost";

      const buttons = overlay.querySelector(".modal-buttons");
      buttons.append(yes, no);

      let swapTimer = null;
      const swap = () => {
        buttons.append(buttons.firstElementChild);
        swapTimer = setTimeout(swap, 800);
      };

      const close = (answer) => {
        clearTimeout(swapTimer);
        document.removeEventListener("keydown", onKey);
        overlay.remove();
        resolve(answer);
      };
      const onKey = (event) => { if (event.key === "Escape") close(false); };

      yes.addEventListener("click", () => close(true));
      no.addEventListener("click", () => close(false));
      document.addEventListener("keydown", onKey);
      overlay.addEventListener("click", (event) => {
        if (event.target === overlay) close(false);
      });

      if (shifty) {
        swapTimer = setTimeout(swap, 1200);
        let dodged = false;
        yes.addEventListener("mouseenter", () => {
          if (dodged) return;
          dodged = true;
          yes.classList.add("dodge");
          setTimeout(() => yes.classList.remove("dodge"), 400);
        });
      }

      document.body.appendChild(overlay);
      no.focus();
    });

  document.querySelectorAll("form.confirm-danger").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.confirmed === "yes") return;
      event.preventDefault();
      ask(form.dataset.confirm || "Вы уверены?").then((answer) => {
        if (!answer) return;
        form.dataset.confirmed = "yes";
        form.submit();
      });
    });
  });

  // --- Инвертированный скролл на разметке -----------------------------------
  //
  // Отключается на тач-устройствах и при prefers-reduced-motion; клавиатурный
  // скролл (PgUp/PgDn/пробел) не трогаем вовсе. Снимается покупкой или честно —
  // разметкой двадцати документов.

  const touch = window.matchMedia("(pointer: coarse)").matches;
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (window.ARACHNE_QRELS && window.ARACHNE_UI
      && window.ARACHNE_UI.invert_scroll && !touch && !calm) {
    window.addEventListener(
      "wheel",
      (event) => {
        if (event.ctrlKey) return;               // масштабирование не трогаем
        event.preventDefault();
        window.scrollBy(0, -event.deltaY);
      },
      { passive: false }
    );
  }

  // --- Паутина при бездействии ----------------------------------------------

  const cobwebAllowed =
    document.querySelector(".results") && window.ARACHNE_UI && window.ARACHNE_UI.cobweb && !calm;

  if (cobwebAllowed) {
    const NS = "http://www.w3.org/2000/svg";
    let web = null;
    let idle = null;
    let grow = null;

    const corner = (x, y, flipX, flipY) => {
      const group = document.createElementNS(NS, "g");
      for (let ring = 1; ring <= 5; ring += 1) {
        const size = ring * 55;
        const path = document.createElementNS(NS, "path");
        path.setAttribute(
          "d",
          `M ${x + flipX * size} ${y} Q ${x + flipX * size * 0.62} ${y + flipY * size * 0.62}
             ${x} ${y + flipY * size}`
        );
        group.appendChild(path);
      }
      for (let ray = 0; ray <= 4; ray += 1) {
        const angle = (Math.PI / 2) * (ray / 4);
        const line = document.createElementNS(NS, "line");
        line.setAttribute("x1", x);
        line.setAttribute("y1", y);
        line.setAttribute("x2", x + flipX * Math.cos(angle) * 290);
        line.setAttribute("y2", y + flipY * Math.sin(angle) * 290);
        group.appendChild(line);
      }
      return group;
    };

    const spin = () => {
      if (web) return;
      web = document.createElementNS(NS, "svg");
      web.setAttribute("class", "cobweb");
      web.setAttribute("preserveAspectRatio", "none");
      const width = window.innerWidth;
      const height = window.innerHeight;
      web.setAttribute("viewBox", `0 0 ${width} ${height}`);
      web.append(
        corner(0, 0, 1, 1),
        corner(width, 0, -1, 1),
        corner(0, height, 1, -1),
        corner(width, height, -1, -1)
      );
      document.body.appendChild(web);

      const started = Date.now();
      grow = setInterval(() => {
        const share = Math.min(1, (Date.now() - started) / 40000);
        web.style.opacity = String(0.75 * share);
      }, 400);
    };

    const tear = () => {
      if (!web) return;
      clearInterval(grow);
      web.classList.add("torn");
      const dying = web;
      web = null;
      setTimeout(() => dying.remove(), 500);
    };

    const reset = () => {
      tear();
      clearTimeout(idle);
      idle = setTimeout(spin, 12000);
    };

    ["click", "scroll", "keydown", "input", "pointerdown"].forEach((event) => {
      window.addEventListener(event, reset, { passive: true });
    });
    reset();
  }

  // --- Таймер блица ---------------------------------------------------------

  const blitzTimer = document.getElementById("blitz-timer");
  if (blitzTimer) {
    const limit = Number(blitzTimer.dataset.limit);
    let elapsed = Number(blitzTimer.dataset.elapsed);
    setInterval(() => {
      elapsed += 1;
      const left = limit - elapsed;
      blitzTimer.textContent = left > 0 ? String(left) : "0";
      blitzTimer.classList.toggle("expired", left <= 0);
    }, 1000);
  }

  // --- Паук-компаньон -------------------------------------------------------

  const companion = document.getElementById("companion");
  const bubble = document.getElementById("companion-bubble");
  if (companion && bubble) {
    let hideTimer = null;

    const say = (text) => {
      bubble.textContent = text;
      bubble.classList.add("visible");
      clearTimeout(hideTimer);
      hideTimer = setTimeout(() => bubble.classList.remove("visible"), 6000);
    };

    if (bubble.textContent.trim()) {
      setTimeout(() => say(bubble.textContent.trim()), 600);
    }

    companion.addEventListener("click", () => {
      const events = ["welcome", "results", "night", "metrics", "index", "document"];
      const event = events[Math.floor(Math.random() * events.length)];
      fetch("/api/companion?event=" + event)
        .then((response) => response.json())
        .then((data) => say(data.line))
        .catch(() => say("Кажется, я запутался в паутине."));
    });

    // Проклятие: если пользователь не заметил подмену, паук признаётся сам
    if (window.ARACHNE_CURSED) {
      setTimeout(
        () => say("Признаюсь: одно слово в запросе я подменил синонимом. Снимите проклятие."),
        20000
      );
    }
  }
})();
