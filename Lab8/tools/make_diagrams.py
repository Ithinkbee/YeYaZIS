"""Схемы для отчёта: структура системы и блок-схемы алгоритмов.

    python tools/make_diagrams.py

Рисунки — report/structure.png и report/algo_*.png. Рисуются matplotlib:
у каждого блока заданы место и размер в условных единицах, стрелки
соединяют стороны блоков.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon, Circle  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from glashatai import config  # noqa: E402

INK = "#211c1a"
MUTED = "#776c64"
LINE = "#7a6f66"
BOX = "#b8aca0"
ACCENT = "#9b2f2f"
GOLD = "#b88a22"
FONT = "DejaVu Sans"
BELOW = (1.2, 2.5)  # подпись под нижним углом ромба
plt.rcParams["font.family"] = FONT


class Chart:
    """Холст в условных единицах: x вправо, y вниз."""

    def __init__(self, width: float, height: float, title: str, scale: float = 0.085) -> None:
        self.fig = plt.figure(figsize=(width * scale, height * scale), dpi=150)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, width)
        self.ax.set_ylim(height, 0)
        self.ax.axis("off")
        self.ax.text(width / 2, 4, title, ha="center", va="center", fontsize=15, fontweight="bold", color=INK)

    def box(self, x, y, w, h, text, kind="step", size=9.5, bold=False):
        """Блок с центром (x, y). kind: step, start, decision, group."""
        if kind == "decision":
            points = [(x, y - h / 2), (x + w / 2, y), (x, y + h / 2), (x - w / 2, y)]
            self.ax.add_patch(Polygon(points, closed=True, facecolor="#f8efd8", edgecolor=GOLD, linewidth=1.6))
        elif kind == "start":
            self.ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle=f"round,pad=0,rounding_size={h / 2}",
                                             facecolor="#f6e7e3", edgecolor=ACCENT, linewidth=1.6))
            bold = True
        else:
            self.ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0,rounding_size=1.2",
                                             facecolor="white", edgecolor=BOX, linewidth=1.3))
        self.ax.text(x, y, text, ha="center", va="center", fontsize=size, color=INK, linespacing=1.35,
                     fontweight="bold" if bold else "normal", wrap=False)
        return (x, y, w, h)

    def group(self, x0, y0, x1, y1, title, color, fill):
        self.ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=2",
                                         facecolor=fill, edgecolor=color, linewidth=1.8))
        self.ax.text(x0 + 2.2, y0 + 2.6, title, ha="left", va="center", fontsize=11.5, fontweight="bold", color=color)

    def connector(self, x, y, label):
        self.ax.add_patch(Circle((x, y), 2.2, facecolor="white", edgecolor=ACCENT, linewidth=1.5))
        self.ax.text(x, y, label, ha="center", va="center", fontsize=10, fontweight="bold", color=INK)

    def arrow(self, points, label=None, label_at=0, dashed=False, both=False, label_side=(1.2, -1.0)):
        """Ломаная стрелка через точки; label — подпись у точки label_at."""
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        style = (0, (4, 3)) if dashed else "solid"
        self.ax.plot(xs[:-1] + [xs[-1]], ys[:-1] + [ys[-1]], color=LINE, linewidth=1.3, linestyle=style,
                     solid_capstyle="butt")
        self.ax.annotate("", xy=points[-1], xytext=points[-2],
                         arrowprops=dict(arrowstyle="-|>", color=LINE, lw=1.3, shrinkA=0, shrinkB=0,
                                         mutation_scale=11))
        if both:
            self.ax.annotate("", xy=points[0], xytext=points[1],
                             arrowprops=dict(arrowstyle="-|>", color=LINE, lw=1.3, shrinkA=0, shrinkB=0,
                                             mutation_scale=11))
        if label:
            lx, ly = points[label_at]
            self.ax.text(lx + label_side[0], ly + label_side[1], label, fontsize=9, color=MUTED, ha="left",
                         va="bottom")

    def save(self, name: str) -> None:
        path = config.REPORT_DIR / name
        self.fig.savefig(path, facecolor="white")
        plt.close(self.fig)
        print(f"  {path.relative_to(ROOT)}")


def top(b):
    return (b[0], b[1] - b[3] / 2)


def bottom(b):
    return (b[0], b[1] + b[3] / 2)


def left(b):
    return (b[0] - b[2] / 2, b[1])


def right(b):
    return (b[0] + b[2] / 2, b[1])


# --- структура -------------------------------------------------------------------------------

def structure() -> None:
    c = Chart(150, 116, "Структура системы «Глашатай»", scale=0.075)
    user = c.box(52, 11, 64, 5.5, "Пользователь: текст, файлы, мышь, колонки, микрофон", bold=True)
    windows = c.box(126, 11, 40, 5.5, "Другие программы Windows", bold=True)

    c.group(4, 17, 146, 44, "Браузер — glashatai/web/static", "#3a6383", "#e6eef5")
    b1 = c.box(22, 30.5, 32, 15, "reader.js, article.js,\ndocview.js — ввод,\nразбор, подсветка,\nчтение под указателем")
    b2 = c.box(58, 31, 32, 15, "player.js — очередь\nпредложений,\nпредзагрузка, пауза,\nгромкость (Web Audio)")
    b3 = c.box(93, 31, 32, 15, "settings.js — голос,\nтемп, громкость, высота,\nживость, паузы, правила;\nголос браузера")
    b4 = c.box(128, 31, 30, 15, "talking.js, pafnuty.js,\ncapture-worklet.js —\n«Мой говорящий\nПафнутий»")

    c.group(4, 50, 146, 94, "Сервер — glashatai (FastAPI, web/app.py)", "#4c6b3c", "#eef4e8")
    s1 = c.box(22, 62, 32, 10, "text/segment.py —\nабзацы, предложения")
    s2 = c.box(22, 76, 32, 10, "text/normalize.py —\nтокены, нормализация")
    s3 = c.box(22, 89, 32, 7.5, "lexicon.py, numbers.py,\nacronyms.py, units.py", size=9)
    s4 = c.box(58, 62, 32, 10, "speaker.py — диктор:\nвыбор движка, кэш")
    s5 = c.box(58, 76, 32, 10, "engines/piper.py —\nнейросеть VITS (ONNX)")
    s6 = c.box(58, 89, 32, 7.5, "engines/sapi.py —\nголоса Windows", size=9)
    s7 = c.box(93, 62, 32, 10, "engines/formant.py —\nформантный синтезатор")
    s8 = c.box(93, 76, 32, 10, "phonetics/g2p.py,\nprosody.py — фонемы,\nдлительности, мелодия", size=9)
    s9 = c.box(93, 89, 32, 7.5, "dsp.py — уровень, WSOLA,\nсдвиг тона, LPC, WAV", size=9)
    s10 = c.box(128, 62, 30, 10, "desktop.py — буфер\nобмена, Ctrl+Alt+R")
    s11 = c.box(128, 76, 30, 10, "talking.py, voicefx.py —\nголос паука, эффекты")
    s12 = c.box(128, 89, 30, 7.5, "extract.py — HTML,\nPDF, DOCX, адрес", size=9)

    c.group(4, 97, 80, 114, "Данные", "#776c64", "#f4efe8")
    c.box(42, 107, 72, 9, "data/articles — 5 статей; pronunciation/*.tsv — сокращения,\nаббревиатуры, термины; lexicon.json, settings.json;\nvoices/ — модели Piper", size=8.8)
    c.group(86, 97, 146, 114, "Проверка", "#776c64", "#faf7f2")
    c.box(116, 107, 56, 9, "evaluation.py, asr.py (Vosk), tools/evaluate.py:\nнормализация, произношение, разборчивость", size=8.8)

    c.arrow([bottom(user), (52, 17)], both=True)
    c.arrow([right(windows), (148, 11), (148, 62), right(s10)], dashed=True, label="Ctrl+C, Ctrl+Alt+R",
            label_at=1, label_side=(-18.5, 37.8))
    c.arrow([(22, 44), (22, 50)], label="текст → /api/prepare", label_at=0, label_side=(1.2, 3.5), both=True)
    c.arrow([(58, 44), (58, 50)], label="предложение → WAV", label_at=0, label_side=(1.2, 3.5), both=True)
    c.arrow([(110, 44), (110, 50)], label="запись → эффект", label_at=0, label_side=(1.2, 3.5), both=True)
    c.arrow([bottom(s1), top(s2)])
    c.arrow([bottom(s2), top(s3)], both=True)
    c.arrow([right(s1), left(s4)])
    c.arrow([bottom(s4), top(s5)])
    c.arrow([right(s4), left(s7)])
    c.arrow([bottom(s7), top(s8)], both=True)
    c.arrow([right(s5), left(s8)])
    c.arrow([bottom(s5), top(s6)], dashed=True)
    c.arrow([left(s9), right(s6)], both=True)
    c.arrow([top(s10), (128, 44)], dashed=True, label="текст (SSE)", label_at=0, label_side=(1.2, -0.3))
    c.arrow([bottom(s10), top(s11)], dashed=True)
    c.arrow([(42, 94), (42, 97)], dashed=True)
    c.arrow([(116, 97), (116, 94)], dashed=True)
    c.save("structure.png")


# --- подготовка текста ----------------------------------------------------------------------------

def algo_text() -> None:
    c = Chart(110, 152, "Алгоритм подготовки текста к синтезу")
    a = c.box(55, 12, 46, 6, "Начало: исходный текст", kind="start")
    b = c.box(55, 24, 92, 10, "Абзацы: пустая строка — граница; одиночный перевод строки — граница,\nесли строка кончилась точкой или это заголовок «# …», пункт списка;\nиначе перенос внутри абзаца (текст из PDF)")
    d = c.box(55, 37, 74, 7, "Следующий знак конца: «.», «!», «?», «…» + пробел")
    e = c.box(55, 51, 46, 12, "Дальше заглавная буква,\nцифра или кавычка?", kind="decision")
    f = c.box(55, 66, 50, 12, "Точка внутри или в конце\nсокращения («z. B.», «S.»)?", kind="decision")
    g = c.box(55, 81, 50, 12, "Перед точкой число («19.»),\nномер раздела или инициал?", kind="decision")
    h = c.box(14, 81, 24, 13, "«usw.» и дальше\nначало фразы?", kind="decision", size=8.6)
    k = c.box(95, 81, 24, 12, "Дальше слово —\nначало фразы?", kind="decision", size=9)
    m = c.box(55, 95, 46, 6.5, "Граница предложения")
    n = c.box(55, 107, 92, 8, "Длинное (> 400 знаков) — на части по «;», «:», запятым ближе к середине;\nпредложение = место в тексте + вид: утверждение, вопрос, восклицание")
    o = c.box(55, 119, 92, 8, "Токены: одно регулярное выражение, 25 видов (адрес, дата, сокращение, число\nс единицей, аббревиатура, слово…); у каждого — место, запись, произношение")
    p = c.box(55, 131, 92, 8, "Контекст: окончание порядкового по слову перед ним, «ein / eine / einem»\nпо роду и предлогу; затем английские термины и словарь пользователя")
    q = c.box(55, 143, 70, 6, "Конец: предложения для синтезатора и для подсветки", kind="start")

    c.arrow([bottom(a), top(b)])
    c.arrow([bottom(b), top(d)])
    c.arrow([bottom(d), top(e)])
    c.arrow([bottom(e), top(f)], label="да", label_side=BELOW)
    c.arrow([right(e), (101, 51), (101, 37), right(d)], label="нет", label_at=0, label_side=(1, -1.2))
    c.arrow([bottom(f), top(g)], label="нет", label_side=BELOW)
    c.arrow([left(f), (14, 66), top(h)], label="да", label_at=0, label_side=(-4, -1.2))
    c.arrow([right(g), left(k)], label="да", label_at=0, label_side=(0.5, -1.4))
    c.arrow([bottom(g), top(m)], label="нет", label_side=BELOW)
    c.arrow([bottom(h), (14, 95), left(m)], label="да", label_at=0, label_side=(1.2, 0.5))
    c.arrow([left(h), (2, 81), (2, 37), left(d)], label="нет", label_at=0, label_side=(-1.6, -1.2))
    c.arrow([bottom(k), (95, 95), right(m)], label="да", label_at=0, label_side=(1.2, 0.5))
    c.arrow([right(k), (108, 81), (108, 37), right(d)], label="нет", label_at=0, label_side=(-3.5, -1.2))
    c.arrow([bottom(m), top(n)])
    c.arrow([bottom(n), top(o)])
    c.arrow([bottom(o), top(p)])
    c.arrow([bottom(p), top(q)])
    c.save("algo_text.png")


# --- синтез и чтение --------------------------------------------------------------------------------

def algo_speak() -> None:
    c = Chart(116, 156, "Алгоритм чтения текста по предложениям")
    a = c.box(58, 12, 52, 6, "Начало: читать с предложения i", kind="start")
    b = c.box(58, 24, 80, 7.5, "Страница запрашивает звук предложений i, i+1, i+2\n(POST /api/speak; громкость не передаётся)")
    d = c.box(58, 38, 40, 11, "Звук предложения\nуже в кэше?", kind="decision")
    e = c.box(58, 53, 40, 11, "Выбранный голос\nдоступен?", kind="decision")
    f = c.box(98, 53, 22, 7, "голос по\nумолчанию", size=9)
    g = c.box(58, 68, 32, 10, "Движок?", kind="decision")
    p1 = c.box(20, 85, 28, 15, "Piper: термины —\nфонемами [[…]];\nдлина по калибровке,\nостаток — WSOLA", size=9)
    p2 = c.box(58, 85, 30, 15, "Формантный:\nфонемы, партитура,\nформанты, источник\nи фильтры", size=9)
    p3 = c.box(97, 85, 28, 15, "Windows: задание\nпроцессу PowerShell,\nтемп — System.Speech", size=9)
    h = c.box(58, 102, 92, 7.5, "Сдвиг тона, если движок не умеет; срезать тишину по краям; уровень −18 дБ;\nплавные края 6 мс; положить в кэш")
    k = c.box(58, 114, 92, 7.5, "Страница: декодировать, проиграть через усилитель громкости,\nподсветить предложение i; во время звучания готовятся следующие")
    m = c.box(58, 127, 92, 7.5, "Пауза после: 40 мс — часть длинного предложения; после абзаца или заголовка —\n«пауза абзаца»; иначе — «пауза предложения»")
    n = c.box(58, 140, 40, 10, "Есть предложение i+1?", kind="decision")
    q = c.box(58, 151.5, 36, 5.5, "Конец: дочитано", kind="start")

    c.arrow([bottom(a), top(b)])
    c.arrow([bottom(b), top(d)])
    c.arrow([bottom(d), top(e)], label="нет", label_side=BELOW)
    c.arrow([right(d), (114, 38), (114, 102), right(h)], label="да", label_at=0, label_side=(1, -1.2))
    c.arrow([bottom(e), top(g)], label="да", label_side=(-3.2, 2.5))
    c.arrow([right(e), left(f)], label="нет", label_at=0, label_side=(1, -1.2))
    c.arrow([bottom(f), (98, 60.5), (58.4, 60.5)])
    c.arrow([left(g), (20, 68), top(p1)], label="piper", label_at=0, label_side=(-8, -1.2))
    c.arrow([bottom(g), top(p2)], label="formant", label_side=BELOW)
    c.arrow([right(g), (97, 68), top(p3)], label="sapi", label_at=0, label_side=(1, -1.2))
    c.arrow([bottom(p1), (20, 98.25)])
    c.arrow([bottom(p2), top(h)])
    c.arrow([bottom(p3), (97, 98.25)])
    c.arrow([bottom(h), top(k)])
    c.arrow([bottom(k), top(m)])
    c.arrow([bottom(m), top(n)])
    c.arrow([bottom(n), top(q)], label="нет", label_side=BELOW)
    c.arrow([left(n), (3, 140), (3, 24), left(b)], label="да, i ← i + 1", label_at=0, label_side=(-12, -1.2))
    c.save("algo_speak.png")


# --- формантный синтез -------------------------------------------------------------------------------

def algo_formant() -> None:
    c = Chart(110, 146, "Алгоритм собственного формантного синтеза")
    a = c.box(55, 12, 70, 6, "Начало: произношение предложения («Mä'schien 'Lörning …»)", kind="start")
    b = c.box(55, 25, 94, 10, "Правила произношения для каждого слова: исключения; деление сложного слова,\nприставки, суффиксы; буквы → фонемы (долгота, «ch», «r», оглушение);\nслоги; ударение (основа, иноязычный суффикс, апостроф)")
    d = c.box(55, 39, 94, 9, "Длительности: собственная фонемы × ударение (1,15 / 0,75) × скопление (0,8)\n× конец фразы (1,4) ÷ темп; паузы на «,» 170 мс, на «;» 260 мс")
    e = c.box(55, 52, 94, 9, "Мелодия: снижение тона от 1,12 до 0,92 за предложение; подъём на ударном\nслоге знаменательных слов; конец: падение — утверждение, подъём — вопрос")
    f = c.box(55, 65, 94, 9, "Цели по кадрам 5 мс: форманты F1–F3 гласной или локуса согласной; громкость\nголоса AV, шума AF, придыхания AH; спектр шума A2–A6; носовой нуль")
    g = c.box(55, 77, 94, 7, "Сглаживание: форманты — окном 35 мс (переходы между звуками), громкости — 15 мс")
    h = c.box(55, 89, 94, 7, "Источник: импульсы Розенберга с частотой F0 (производная — излучение губ) + шум")
    k1 = c.box(29, 104, 46, 13, "Каскад: голос + придыхание →\nносовой нуль и полюс →\nрезонаторы R5…R1:\ny = A·x + B·y₋₁ + C·y₋₂", size=9)
    k2 = c.box(81, 104, 46, 13, "Параллельная ветвь: шум × AF →\nрезонаторы R2…R6 с усилителями\nA2…A6 (знаки чередуются)\n+ обход AB", size=9)
    m = c.box(55, 120, 94, 7, "Сумма ветвей (шум × 16 — калибровка уровней согласных), срез постоянной составляющей")
    n = c.box(55, 132, 70, 6, "Конец: звук 22 050 Гц", kind="start")

    c.arrow([bottom(a), top(b)])
    c.arrow([bottom(b), top(d)])
    c.arrow([bottom(d), top(e)])
    c.arrow([bottom(e), top(f)])
    c.arrow([bottom(f), top(g)])
    c.arrow([bottom(g), top(h)])
    c.arrow([(40, 92.5), (40, 97.5)])
    c.arrow([(70, 92.5), (70, 97.5)])
    c.arrow([bottom(k1), (29, 116.5)])
    c.arrow([bottom(k2), (81, 116.5)])
    c.arrow([bottom(m), top(n)])
    c.ax.text(55, 140.5, "B = 2·e^(−π·b·T)·cos(2π·f·T),   C = −e^(−2π·b·T),   A = 1 − B − C   (f — частота, b — полоса, T = 1/22 050 с)",
              ha="center", fontsize=9, color=MUTED)
    c.save("algo_formant.png")


# --- повтор за игроком ------------------------------------------------------------------------------

def algo_echo() -> None:
    c = Chart(110, 122, "Алгоритм «Повтор за игроком» («Мой говорящий Пафнутий»)")
    a = c.box(55, 12, 66, 6, "Начало: уровень звука микрофона каждые 20 мс, L дБ", kind="start")
    b = c.box(55, 26, 40, 11, "Паук говорит\nсам?", kind="decision")
    d = c.box(55, 42, 40, 11, "Идёт фраза?", kind="decision")
    e = c.box(20, 58, 32, 10, "Шум N ← N + α·(L − N):\nα = 0,02 вверх,\n0,2 вниз", size=9)
    f = c.box(20, 75, 34, 12, "3 из 5 кадров\nгромче max(N+12, −48)?", kind="decision", size=9)
    g = c.box(20, 93, 32, 10, "Начало: запись с 300 мс\nдо фразы; паук\nподнимает лапы", size=9)
    h = c.box(84, 58, 40, 12, "700 мс тише\nmax(N+7, −52)\nили 8 с?", kind="decision", size=9)
    k = c.box(84, 77, 36, 9, "Запись 16 кГц →\nPOST /api/talking/echo", size=9)
    m = c.box(84, 93, 36, 12, "Эффект: писк +7 пт;\nбас −5 пт; робот, шёпот —\nLPC; эхо +3 пт и повторы", size=9)
    n = c.box(55, 112, 92, 8, "Проиграть; рот открывается по громкости звука;\nмикрофон не слушается ещё 450 мс после конца")
    q = c.connector(102, 12, "A")

    c.arrow([bottom(a), top(b)])
    c.arrow([bottom(b), top(d)], label="нет", label_side=BELOW)
    c.arrow([right(b), (102, 26), (102, 14.2)], label="да", label_at=0, label_side=(1, -1.2))
    c.arrow([left(d), (20, 42), top(e)], label="нет", label_at=0, label_side=(-5, -1.2))
    c.arrow([right(d), (84, 42), top(h)], label="да", label_at=0, label_side=(1, -1.2))
    c.arrow([bottom(e), top(f)])
    c.arrow([bottom(f), top(g)], label="да", label_side=BELOW)
    c.arrow([left(f), (2, 75), (2, 12), left(a)], label="нет", label_at=0, label_side=(-1.5, -1.2))
    c.arrow([bottom(g), (20, 104), (2, 104), (2, 75)])
    c.arrow([bottom(h), top(k)], label="да", label_side=BELOW)
    c.arrow([right(h), (106, 58), (106, 12), (104.2, 12)], label="нет", label_at=0, label_side=(-4, -1.2))
    c.arrow([bottom(k), top(m)])
    c.arrow([bottom(m), (84, 108)])
    c.arrow([right(n), (106, 112), (106, 58)])
    c.arrow([(99.8, 12), right(a)])
    del q
    c.save("algo_echo.png")


def main() -> None:
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    structure()
    algo_text()
    algo_speak()
    algo_formant()
    algo_echo()


if __name__ == "__main__":
    main()
