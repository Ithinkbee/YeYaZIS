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

  // --- Паук-компаньон -------------------------------------------------------

  const companion = document.getElementById("companion");
  if (companion) {
    const bubble = document.getElementById("companion-bubble");
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
  }
})();
