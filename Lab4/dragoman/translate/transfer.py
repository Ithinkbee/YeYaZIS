"""Перевод с трансфером: английское дерево зависимостей → немецкое предложение.

Система второго поколения по классификации методички: соответствия
устанавливаются не напрямую, а после синтаксического анализа. Анализ ведётся в
категориях английского языка (дерево зависимостей Universal Dependencies),
синтез — в категориях немецкого, а между ними стоит трансфер — перестройка
структуры:

* **глагольная группа.** Английская цепочка вспомогательных глаголов
  превращается в немецкую рамку: «has been used» → «ist … verwendet worden»,
  «can be translated» → «kann … übersetzt werden», «does not use» →
  «verwendet … nicht» (do-конструкция исчезает), отделяемая приставка уходит
  в конец: «presents» → «stellt … vor»;
* **порядок слов.** В главном предложении спрягаемый глагол стоит вторым
  (V2): «In this paper we present a method» → «In diesem Artikel stellen wir
  eine Methode vor». В придаточном он уходит в конец: «…, dass der Compiler den
  Code übersetzt». Неличные формы — в конце предложения (рамочная конструкция);
* **падежи.** Подлежащее — Nominativ, прямое дополнение — Akkusativ (или Dativ,
  если немецкий глагол его требует: «helfen», «folgen»), после предлога —
  падеж, которым управляет немецкий предлог, «of» — Genitiv: «the structure of
  the program» → «die Struktur des Programms»;
* **согласование.** Артикль и прилагательное согласуются с родом, числом и
  падежом немецкого существительного: «a neural network» → «ein neuronales
  Netz», «the neural networks» → «die neuronalen Netze»;
* **словообразование.** Цепочка существительных становится сложным словом:
  «network protocol» → «Netzwerkprotokoll», «security risk» →
  «Sicherheitsrisiko»;
* **отрицание.** «not» + неопределённый артикль → «kein»: «does not contain an
  error» → «enthält keinen Fehler»;
* **придаточные.** Относительное местоимение выбирается по роду
  антецедента и роли в придаточном («the compiler, which…» → «der Compiler,
  der…»; «in which» → «in dem»), запятые ставятся по немецким правилам.

Каждое немецкое слово помнит английские слова, из которых получено.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from dragoman.english.analyzer import AnalyzedSentence, Word
from dragoman.german import morphology as gm
from dragoman.lexicon.db import Entry, clean
from dragoman.translate.lexical import DICT, NAME, NUMBER, RULE, UNKNOWN, Choice, Lexical, is_number
from dragoman.translate.output import G, Sentence, punct, word

SUBJ = {"nsubj", "nsubj:pass", "csubj", "csubj:pass", "nsubj:outer"}
NEGATIONS = {"not", "n't", "never"}
#: союзы-наречия, которые в немецком естественно стоят в середине предложения
MIDDLE_CONNECTORS = {"however", "also", "too", "though"}
#: глаголы «давать», при которых «to X» становится дательным падежом без предлога
GIVE_VERBS = {"give", "send", "show", "offer", "pass", "deliver", "present", "explain", "tell", "assign",
              "provide", "allocate", "attribute", "lend", "grant", "teach", "write"}
#: глаголы движения: после них двойственный предлог требует Akkusativ
MOTION_VERBS = {"go", "come", "move", "put", "place", "send", "bring", "translate", "convert", "insert", "load",
                "copy", "transfer", "divide", "split", "transform", "pass", "fall", "enter", "travel",
                "throw", "push", "integrate", "incorporate", "embed", "turn"}
TWO_WAY = {"in", "an", "auf", "über", "unter", "vor", "hinter", "neben", "zwischen"}
CONTRACTIONS = {("in", "dem"): "im", ("in", "das"): "ins", ("an", "dem"): "am", ("an", "das"): "ans",
                ("zu", "dem"): "zum", ("zu", "der"): "zur", ("von", "dem"): "vom", ("bei", "dem"): "beim"}
#: предлог перед местоимением-вещью: «with it» → «damit»
DA_COMPOUND = {"mit", "durch", "für", "von", "zu", "bei", "nach", "vor", "an", "auf", "aus", "in", "über", "um",
               "unter", "gegen", "zwischen", "neben", "hinter"}
QUOTES_OPEN = {'"', "“", "``", "‘", "'"}
QUOTES_CLOSE = {'"', "”", "''", "’", "'"}
BRACKETS = {"(": ")", "[": "]", "{": "}"}
#: английские модальные конструкции с инфинитивом, которые в немецком — модальный глагол
MODAL_XCOMP = {"have": "müssen", "need": "müssen", "want": "wollen", "wish": "wollen", "able": "können",
               "going": "werden", "ought": "sollen"}
WH_WORDS = {"who", "whom", "whose", "which", "what", "where", "when", "why", "how", "whether", "that"}


@dataclass
class Agr:
    """Признаки для согласования: лицо, число, род."""

    person: int = 3
    number: str = "sg"
    gender: str = "n"
    human: bool = False


@dataclass
class Part:
    """Член предложения в немецком переводе."""

    tokens: list[G]
    kind: str
    pos: int
    pronoun: bool = False
    clause: bool = False


@dataclass
class VerbGroup:
    finite: str = ""
    prefix: str = ""
    nonfinite: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    reflexive: bool = False
    finite_src: tuple[int, ...] = ()
    main_src: tuple[int, ...] = ()
    #: «sich» в каком падеже: обычно Akkusativ
    reflexive_case: str = "A"


@dataclass
class EnglishVerb:
    """Признаки английской глагольной группы."""

    tense: str = "pres"            # pres | past
    perfect: bool = False
    passive: bool = False
    progressive: bool = False
    modal: str = ""                # немецкий модальный глагол
    modal_tense: str = "pres"      # pres | past | subj
    infinitive: bool = False
    gerund: bool = False
    participle: bool = False
    finite_word: int = -1
    words: list[int] = field(default_factory=list)


MALE_TITLES = {"mr", "mr.", "sir", "lord", "king", "prince", "father", "uncle", "brother", "son", "duke", "count",
               "baron", "earl", "emperor", "husband", "dr", "dr.", "professor", "captain", "colonel", "general"}
FEMALE_TITLES = {"mrs", "mrs.", "miss", "ms", "ms.", "lady", "queen", "princess", "mother", "aunt", "sister",
                 "daughter", "duchess", "countess", "baroness", "empress", "wife"}
FEMALE_NAMES = {"jane", "elizabeth", "mary", "charlotte", "daisy", "ophelia", "gertrude", "lydia", "kitty", "helen",
                "ellen", "sarah", "emily", "anne", "ann", "catherine", "jordan", "myrtle", "julia", "bertha", "adele",
                "blanche", "georgiana", "eliza", "diana", "rosamond", "grace", "bessie", "maria", "margaret", "alice",
                "emma", "lucy", "victoria", "virginia", "harriet", "jeanette", "edith", "ginevra", "susan", "agnes",
                "isabella", "justine", "safie", "agatha", "caroline", "georgiana", "jill", "julie", "anna", "sophia"}


class DocContext:
    """Общее для документа: словарь, предметная область, антецеденты местоимений, род имён людей."""

    def __init__(self, lexical: Lexical) -> None:
        self.lexical = lexical
        self.lexicon = lexical.lexicon
        self.domain = lexical.domain
        #: (род, число) недавних существительных — для «it», «its», «which»
        self.recent: list[tuple[str, str]] = []
        self.unknown: list[tuple[str, str, str]] = []
        #: имя -> род (m, f) по титулам и местоимениям he/she
        self.names: dict[str, str] = {}
        #: слова, которые в тексте встречаются как имена собственные не в начале предложения
        self.proper: set[str] = set()

    def learn_names(self, sentences: list[AnalyzedSentence]) -> None:
        """Род имён людей: по титулу (Mr Darcy, Queen Gertrude), по списку женских имён и по тому,
        каким местоимением (he/she) текст продолжает предложение, где имя — подлежащее."""
        votes: dict[str, dict[str, int]] = {}

        def vote(name: str, gender: str, weight: int = 1) -> None:
            votes.setdefault(name, {"m": 0, "f": 0})[gender] += weight

        previous_subjects: list[str] = []
        for sentence in sentences:
            words = sentence.words
            subjects = []
            for w in words:
                if w.tag in {"NNP", "NNPS"} and w.index > 0:
                    self.proper.add(w.text)
                if w.tag in {"NNP", "NNPS"}:
                    if w.lower in FEMALE_NAMES:
                        vote(w.text, "f", 3)
                    if w.index > 0 and words[w.index - 1].lower in MALE_TITLES:
                        vote(w.text, "m", 5)
                    if w.index > 0 and words[w.index - 1].lower in FEMALE_TITLES:
                        vote(w.text, "f", 5)
                    if w.deprel in SUBJ:
                        subjects.append(w.text)
            pronouns = [w.lower for w in words if w.tag in {"PRP", "PRP$"}]
            for name in previous_subjects + subjects:
                if any(p in {"he", "him", "his", "himself"} for p in pronouns):
                    vote(name, "m")
                if any(p in {"she", "her", "hers", "herself"} for p in pronouns):
                    vote(name, "f")
            previous_subjects = subjects or previous_subjects[-1:]
        for name, count in votes.items():
            if count["m"] != count["f"]:
                self.names[name] = "m" if count["m"] > count["f"] else "f"

    def remember(self, gender: str, number: str) -> None:
        self.recent.append((gender, number))
        if len(self.recent) > 12:
            self.recent.pop(0)

    def antecedent(self, number: str = "sg") -> str:
        for gender, n in reversed(self.recent):
            if n == number:
                return gender
        return "n"


class SentenceTransfer:
    def __init__(self, sentence: AnalyzedSentence, ctx: DocContext) -> None:
        self.s = sentence
        self.ctx = ctx
        self.lex = ctx.lexical
        self.w: list[Word] = self._heading_words(sentence, sentence.words if sentence.heading else
                                                 sentence.words[:1]) if sentence.words else []
        self.w = self._known_names(self.w, sentence.heading)
        self.w = self._nouns_tagged_as_verbs(self.w)
        self.n = len(self.w)
        #: слово поглощено оборотом: номер -> номер вершины оборота
        self.absorbed: dict[int, int] = {}
        #: вершина оборота -> (статья, номера слов)
        self.phrases: dict[int, tuple[Entry, list[int]]] = {}
        self.kids: list[list[int]] = [list(w.children) for w in self.w]
        self.heads: list[int] = [w.head for w in self.w]
        self.deprels: list[str] = [w.deprel for w in self.w]
        self.status: dict[int, str] = {}
        self.choices: dict[int, Choice] = {}
        self.notes: list[str] = []
        self.done: set[int] = set()
        self._repair_root()
        self._repair_possessives()
        self._repair_initial_when()
        self._repair_punct_heads()
        self._repair_verb_conj()
        self._repair_aux_subjects()
        self._repair_infinitives()
        self._repair_compounds()
        self._merge_phrases()

    def _repair_compounds(self) -> None:
        """«the training samples»: существительное прямо перед существительным без предлога,
        разобранное как nmod, — это определение-композит (compound).
        «the faster algorithm»: сравнительная степень, принятая за существительное, — определение."""
        for w in self.w:
            i = w.index
            h = self.heads[i]
            if self.deprels[i] == "nmod" and h == i + 1 and w.tag in {"NN", "NNS"} and                     self.w[h].tag in {"NN", "NNS"} and                     not any(self.deprels[k] in {"case", "det", "nmod:poss"} for k in self.kids[i]):
                self.deprels[i] = "compound"
            # «The first machine translation software was …»: «translation» — не подлежащее при «software»,
            # а часть сложного слова; артикль и определения переходят к главному слову
            if self.deprels[i] == "nsubj" and h == i + 1 and w.tag in {"NN", "NNS"} and self.w[h].tag in {"NN", "NNS"}                     and not any(self.deprels[k] == "cop" for k in self.kids[h]) and self.deprels[h] in SUBJ | {"obj"}:
                self.deprels[i] = "compound"
                for k in [k for k in self.kids[i] if k < i and self.deprels[k] in {"det", "amod", "nummod", "nmod:poss"}]:
                    self._move(k, h, self.deprels[k])
            if self.deprels[i] == "compound" and w.tag == "NN" and w.lower.endswith("er") and                     self.lex.lookup(w.lower, "NOUN", strict=True) is None:
                stem = self._comparative_stem(w.lower)
                if stem:
                    self.w = list(self.w) if self.w is self.s.words else self.w
                    self.w[i] = replace(w, tag="JJR", upos="ADJ", lemma=stem)
                    self.deprels[i] = "amod"

    def _repair_possessives(self) -> None:
        """«His father's ghost appears»: анализатор сделал «father» вторым подлежащим. Слово с «'s» —
        притяжательное определение существительного, которое идёт следом."""
        for w in self.w:
            if w.tag != "POS":
                continue
            owner = self.heads[w.index]
            if owner < 0 or self.deprels[owner] == "nmod:poss":
                continue
            j = w.index + 1
            run = []
            while j < len(self.w) and self.w[j].tag in {"JJ", "JJR", "JJS", "NN", "NNS", "NNP", "NNPS", "CD", "VBG"}:
                run.append(j)
                j += 1
            nouns = [k for k in run if self.w[k].tag.startswith("NN")]
            if not nouns or owner in run:
                continue
            target = nouns[-1]
            if self.heads[target] == owner:
                continue
            old_role = self.deprels[owner]
            self._move(owner, target, "nmod:poss")
            if self.deprels[target] not in SUBJ | {"obj", "obl", "nmod", "root"} and old_role in SUBJ | {"obj"}:
                self.deprels[target] = old_role
            self.notes.append(f"«{self.w[owner].text}'s» — притяжательное определение: разбор исправлен")

    def _repair_initial_when(self) -> None:
        """«When Fitzgerald died in 1940, he believed …»: анализатор сделал «believed» однородным с «died».
        Предложение, начатое when/while/once, с запятой и вторым сказуемым со своим подлежащим, —
        придаточное времени при этом втором сказуемом."""
        if not self.w or self.w[0].lower not in {"when", "while", "once", "whenever", "after", "before"}:
            return
        root = next((w.index for w in self.w if self.heads[w.index] < 0), None)
        if root is None or self.heads[0] != root:
            return
        for c in self.kids[root]:
            if self.deprels[c] == "conj" and self.w[c].tag.startswith("VB") and c > root and \
                    any(self.deprels[k] in SUBJ for k in self.kids[c]) and \
                    any(self.w[k].text == "," for k in range(root, c)):
                self._move(c, -1, "root")
                for k in [k for k in self.kids[c] if self.deprels[k] == "cc"]:
                    self._move(k, root, "cc")          # союза «and» перед главным предложением нет
                self._move(root, c, "advcl")
                if self.w[0].tag != "WRB":
                    self.deprels[0] = "mark"
                self.notes.append("«When …, …»: придаточное времени, разобранное как однородное, исправлено")
                return

    def _move(self, i: int, head: int, deprel: str) -> None:
        old = self.heads[i]
        if old >= 0 and i in self.kids[old]:
            self.kids[old].remove(i)
        self.heads[i] = head
        self.deprels[i] = deprel
        if head >= 0:
            self.kids[head].append(i)
            self.kids[head].sort()

    def _repair_punct_heads(self) -> None:
        """«…, but rather by weight patterns»: анализатор иногда подвешивает союз к запятой, а
        второй однородный член — к союзу. Союз становится cc, его зависимые — однородными членами
        (для сказуемого — однородными с ближайшим глаголом выше)."""
        for w in self.w:
            c = w.index
            p = self.heads[c]
            if w.tag == "CC" and self.deprels[c] in {"case", "mark"} and p >= 0 and self.deprels[p] == "conj":
                self.deprels[c] = "cc"                  # «not a stack but a queue»: but — не предлог
                continue
            if p < 0 or self.w[p].upos != "PUNCT" or w.tag != "CC":
                continue
            target = self.heads[p] if self.heads[p] >= 0 else p
            members = [k for k in self.kids[c] if self.w[k].upos != "PUNCT"]
            for k in members:
                anchor = target
                if self.w[k].tag.startswith("VB"):
                    while anchor >= 0 and not self.w[anchor].tag.startswith("VB") and self.heads[anchor] >= 0:
                        anchor = self.heads[anchor]
                self._move(k, anchor, "conj")
            if members:
                self._move(c, members[0], "cc")
            else:
                self._move(c, target, "cc")
            self.notes.append(f"союз «{w.text}» был подвешен к знаку препинания — разбор исправлен")

    def _repair_infinitives(self) -> None:
        """«The model is easy to train»: инфинитив при прилагательном-сказуемом, у которого уже есть
        подлежащее, анализатор иногда метит obl или csubj — это xcomp."""
        for w in self.w:
            i = w.index
            h = self.heads[i]
            if h < 0 or w.tag != "VB" or self.deprels[i] not in {"obl", "csubj", "advcl", "ccomp"}:
                continue
            if self.w[h].upos != "ADJ" or not any(self.deprels[k] == "cop" for k in self.kids[h]):
                continue
            if not any(self.w[k].lower == "to" and self.deprels[k] == "mark" for k in self.kids[i]):
                continue
            if any(self.deprels[k] in {"nsubj", "nsubj:pass"} for k in self.kids[h] if k != i) and                     not any(self.deprels[k] == "expl" for k in self.kids[h]):
                self.deprels[i] = "xcomp"

    def _repair_verb_conj(self) -> None:
        """«… software that manages resources, and provides services»: второе сказуемое без своего
        подлежащего анализатор подвесил к существительному-сказуемому главного предложения. Оно
        однородно с ближайшим глаголом придаточного при этом существительном."""
        for w in self.w:
            c = w.index
            h = self.heads[c]
            if self.deprels[c] != "conj" or not w.tag.startswith("VB") or h < 0 or self.w[h].upos not in {"NOUN", "PROPN"}:
                continue
            if any(self.deprels[k] in SUBJ for k in self.kids[c]):
                continue
            verbs = [k for k in self.kids[h] if self.deprels[k] in {"acl:relcl", "acl"} and k < c
                     and self.w[k].tag.startswith("VB")]
            if verbs:
                self._move(c, verbs[-1], "conj")

    def _repair_aux_subjects(self) -> None:
        """«Which method does the compiler use?» — анализатор подвесил «which method» подлежащим
        к «does». У смыслового глагола уже есть подлежащее, значит, это дополнение."""
        for w in self.w:
            i = w.index
            aux = self.heads[i]
            if self.deprels[i] != "nsubj" or aux < 0 or self.deprels[aux] != "aux":
                continue
            verb = self.heads[aux]
            if verb < 0 or not any(self.deprels[k] in SUBJ for k in self.kids[verb]):
                continue
            if not any(self.w[k].tag in {"WDT", "WP", "WP$"} for k in self.kids[i]) and                     self.w[i].tag not in {"WP", "WDT"}:
                continue
            self.kids[aux].remove(i)
            self.kids[verb].append(i)
            self.kids[verb].sort()
            self.heads[i] = verb
            self.deprels[i] = "obj"

    def _comparative_stem(self, lower: str) -> str:
        """faster → fast, larger → large, bigger → big, easier → easy; '' — не сравнительная степень."""
        base = lower[:-2]
        candidates = [base, lower[:-1]]
        if len(base) > 2 and base[-1] == base[-2]:
            candidates.append(base[:-1])
        if base.endswith("i"):
            candidates.append(base[:-1] + "y")
        return next((c for c in candidates if self.lex.lookup(c, "ADJ", strict=True) is not None), "")

    def _nouns_tagged_as_verbs(self, words: list[Word]) -> list[Word]:
        """«He submitted it to editor Maxwell Perkins»: теггер принял «editor» за глагол после «to». Слово,
        у которого в словаре нет глагольной статьи, но есть статья существительного в той же форме, —
        существительное."""
        result = []
        for w in words:
            if w.tag in {"VB", "VBP", "VBZ"} and w.is_word and                     self.lex.lookup(w.lemma.lower(), "VERB", strict=True) is None and                     self.lex.lookup(w.lower, "VERB", strict=True) is None and                     not w.lower.endswith(("ize", "ise", "ify", "ate", "izes", "ises", "ifies", "ates")):
                if self.lex.lookup(w.lower, "NOUN", strict=True) is not None:
                    w = replace(w, tag="NN", upos="NOUN", lemma=w.lower)
                elif w.tag == "VBZ" and w.lower.endswith("s") and                         self.lex.lookup(w.lower[:-1], "NOUN", strict=True) is not None:
                    w = replace(w, tag="NNS", upos="NOUN", lemma=w.lower[:-1])
            result.append(w)
        return result

    def _known_names(self, words: list[Word], heading: bool) -> list[Word]:
        """«Microsoft Windows …, while Windows, macOS and Linux …»: слово, которое в документе уже
        встречалось как имя собственное не в начале предложения, — имя и тогда, когда теггер принял его
        за нарицательное во множественном числе."""
        if heading:
            return words
        result = []
        for w in words:
            if w.tag in {"NN", "NNS"} and w.text[:1].isupper() and w.text in self.ctx.proper:
                w = replace(w, tag="NNP", upos="PROPN", lemma=w.text)   # имя — ед. ч.: «Windows läuft»
            result.append(w)
        return result

    def _heading_words(self, sentence: AnalyzedSentence, capitalized: list[Word]) -> list[Word]:
        """В заголовке с прописных букв теггер видит имена: «Philosophical», «Early Life»; то же — с первым
        словом предложения («Machine translation systems …»). Слово, которого нет в словаре как имени, но есть
        как обычное слово, — обычное слово. Первое слово остаётся именем, если оно — часть имени из нескольких
        слов или встречается в документе как имя и не в начале предложения."""
        check = {w.index for w in capitalized}
        if not sentence.heading and capitalized:
            first = capitalized[0]
            nxt = sentence.words[1] if len(sentence.words) > 1 else None
            if first.text in self.ctx.proper or (nxt is not None and nxt.tag in {"NNP", "NNPS"}):
                check = set()
        words = []
        for w in sentence.words:
            if w.index in check and w.tag in {"NNP", "NNPS"} and self.lex.lookup(w.text, "PROPN", strict=True) is None:
                for pos, tag in (("ADJ", "JJ"), ("NOUN", "NNS" if w.tag == "NNPS" else "NN"), ("VERB", "VBG")):
                    if tag == "VBG" and not w.lower.endswith("ing"):
                        continue
                    lemma = self.lex.lemmatizer.lemma(w.lower, tag) if self.lex.lemmatizer else w.lower
                    if self.lex.lookup(lemma, pos, strict=True) is not None:
                        w = replace(w, tag=tag, upos=pos, lemma=lemma)
                        break
            words.append(w)
        return words

    def _repair_root(self) -> None:
        """Частая ошибка анализатора: «Design requirements include X» — корнем стало подлежащее,
        а сказуемое повисло на нём как parataxis. Сказуемое становится корнем, подлежащее — его nsubj."""
        root = next((w.index for w in self.w if self.heads[w.index] < 0), None)
        if root is None or self.w[root].upos not in {"NOUN", "PROPN"}:
            return
        if any(self.deprels[c] == "cop" for c in self.kids[root]):
            return
        for c in sorted(self.kids[root]):
            verb = self.w[c]
            if c > root and verb.tag in {"VBZ", "VBP", "VBD"} and self.deprels[c] in {"parataxis", "conj", "dep",
                                                                                     "acl", "acl:relcl"} \
                    and not any(self.deprels[k] in SUBJ for k in self.kids[c]) \
                    and not any(self.w[k].tag in {"WDT", "WP", "WRB"} for k in self.kids[c]) \
                    and (self.deprels[c] != "acl:relcl" or self.w[c - 1].text in {"—", "–", "-", "--", ")"}
                         or not any(self.w[k].text == "," for k in range(root, c))):
                self.heads[c], self.deprels[c] = -1, "root"
                self.heads[root], self.deprels[root] = c, "nsubj"
                self.kids[root].remove(c)
                for k in list(self.kids[root]):
                    if k > c:
                        self.kids[root].remove(k)
                        self.kids[c].append(k)
                        self.heads[k] = c
                self.kids[c].append(root)
                self.kids[c].sort()
                self.notes.append("исправлен разбор: сказуемое «" + verb.text + "» стало вершиной предложения")
                return
        # «Shakespeare's longest play is Hamlet», «The heroine, Elizabeth, is clever»: именная часть со связкой
        # повисла на подлежащем как appos или advmod — она и есть сказуемое
        for c in sorted(self.kids[root]):
            if c > root and self.deprels[c] in {"appos", "advmod", "amod", "acl", "parataxis", "dep", "conj"}                     and any(self.deprels[k] == "cop" for k in self.kids[c])                     and not any(self.deprels[k] in SUBJ for k in self.kids[c]):
                self._move(c, -1, "root")
                self._move(root, c, "nsubj")
                for k in [k for k in self.kids[root] if k > c]:
                    self._move(k, c, self.deprels[k])
                if self.w[c].upos == "ADV" and self.w[c].tag == "RB":
                    self.w = list(self.w) if self.w is self.s.words else self.w
                    self.w[c] = replace(self.w[c], tag="JJ", upos="ADJ")      # «is clever» — прилагательное
                self.notes.append("исправлен разбор: именная часть «" + self.w[c].text + "» стала сказуемым")
                return

    # ==================================================================================
    # обороты
    # ==================================================================================

    def _merge_phrases(self) -> None:
        i = 0
        while i < self.n:
            entry, length = self._phrase_at(i)
            if entry is None:
                i += 1
                continue
            span = list(range(i, i + length))
            outside = [j for j in span if not (i <= self.heads[j] < i + length)]
            if len(outside) != 1 and entry.pos in {"NOUN", "PROPN", "ADJ"}:
                i += 1
                continue
            head = outside[0] if outside else span[-1]
            if len(outside) > 1:
                # обороты-связки разобраны анализатором на части: вершина — ближайшая к корню
                head = min(outside, key=lambda j: self._depth(j))
            self.phrases[head] = (entry, span)
            for j in span:
                if j == head:
                    continue
                self.absorbed[j] = head
                for child in list(self.kids[j]):
                    if child not in span:
                        self.kids[head].append(child)
                        self.heads[child] = head
                self.kids[j] = []
            self.kids[head] = sorted(c for c in self.kids[head] if c not in span)
            if len(span) > 1:
                self.notes.append(f"оборот «{' '.join(self.w[j].text for j in span)}» → «{clean(entry.de)}»")
            i += length

    def _depth(self, j: int) -> int:
        depth = 0
        while self.heads[j] >= 0 and depth < 50:
            j = self.heads[j]
            depth += 1
        return depth

    def _phrase_at(self, i: int) -> tuple[Entry | None, int]:
        first = self.w[i].lower
        for entry in self.ctx.lexicon.phrases_from(first):
            if entry.pos == "VERB":
                continue
            words = entry.en.lower().split()
            if i + len(words) > self.n:
                continue
            ok = True
            for k, expected in enumerate(words):
                token = self.w[i + k]
                last = k == len(words) - 1
                if token.lower == expected:
                    continue
                if last and entry.pos in {"NOUN", "PROPN"} and token.lemma.lower() == expected:
                    continue
                ok = False
                break
            if not ok:
                continue
            # «the great gatsby» без артикля в тексте не ищется, артикль английский входит в название
            preferred = self.lex.phrase(entry.en, entry.pos)
            return (preferred or entry), len(words)
        return None, 0

    # ==================================================================================
    # вспомогательное
    # ==================================================================================

    def children(self, i: int, *deprels: str) -> list[Word]:
        result = [self.w[c] for c in sorted(self.kids[i]) if c not in self.absorbed]
        if deprels:
            result = [w for w in result if self.deprels[w.index] in deprels
                      or self.deprels[w.index].split(":")[0] in deprels]
        return result

    def rel(self, i: int) -> str:
        return self.deprels[i]

    def span(self, i: int) -> list[int]:
        """Все слова поддерева (с поглощёнными словами оборотов)."""
        stack, seen = [i], []
        while stack:
            node = stack.pop()
            seen.append(node)
            if node in self.phrases:
                seen.extend(j for j in self.phrases[node][1] if j != node)
            stack.extend(c for c in self.kids[node] if c not in self.absorbed)
        return sorted(set(seen))

    def src(self, i: int) -> tuple[int, ...]:
        if i in self.phrases:
            return tuple(self.phrases[i][1])
        return (i,)

    def mark(self, i: int, status: str) -> None:
        for j in self.src(i):
            self.status[j] = status
        self.done.add(i)

    def choice(self, i: int, pos: str | None = None) -> Choice:
        key = (i, pos)
        cached = self.choices.get(key)
        if cached is not None:
            return cached
        if i in self.phrases:
            entry = self.phrases[i][0]
            result = Choice(entry, DICT, entry.en)
        else:
            result = self.lex.word(self.w[i], pos)
        self.choices[key] = result
        return result

    def text_of(self, i: int) -> str:
        return " ".join(self.w[j].text for j in self.src(i))

    def unknown(self, i: int) -> G:
        w = self.w[i]
        if not w.is_word:
            # знак препинания, ставший вершиной группы из-за ошибки разбора, — не «неизвестное слово»
            self.mark(i, "punct")
            return punct(w.text, i)
        self.mark(i, UNKNOWN)
        self.ctx.unknown.append((w.lemma.lower() if w.upos != "PROPN" else w.lemma, w.upos, self.s.text))
        return word(w.text, i, "unknown", noun=w.upos in {"NOUN"})

    def wrap(self, i: int, tokens: list[G], skip_quotes: bool = False) -> list[G]:
        """Кавычки и скобки — зависимые слова i по краям его поддерева — обрамляют перевод."""
        pieces = [w for w in self.children(i, "punct")]
        span = self.span(i)
        if not span or not pieces:
            return tokens
        first, last = span[0], span[-1]
        before, after = [], []
        for p in pieces:
            if p.text in BRACKETS and p.index == first:
                before.append(punct(p.text, p.index))
                self.mark(p.index, "punct")
            elif p.text in BRACKETS.values() and p.index == last:
                after.append(punct(p.text, p.index))
                self.mark(p.index, "punct")
            elif not skip_quotes and p.text in QUOTES_OPEN and p.index == first:
                before.append(punct(p.text, p.index))
                self.mark(p.index, "punct")
            elif not skip_quotes and p.text in QUOTES_CLOSE and p.index == last:
                after.append(punct(p.text, p.index))
                self.mark(p.index, "punct")
        return before + tokens + after

    # ==================================================================================
    # предложение
    # ==================================================================================

    def run(self) -> Sentence:
        root = next((i for i in range(self.n) if self.heads[i] < 0), self.s.root)
        if self.s.heading or not self.is_predicate(root):
            tokens = self.fragment(root)
        else:
            tokens = self.clause(root, "question" if self._is_question(root) else "main")
        tokens = tokens + self._orphans()
        tokens = tokens + self._final_punct(root, tokens)
        return Sentence(self.s.index, self.s.text, tokens, self.notes, self.s.heading)

    def _orphans(self) -> list[G]:
        """Поддеревья, до которых трансфер не добрался (так бывает при ошибке разбора), — в конец:
        лучше слово не на месте, чем потерянное слово."""
        tokens: list[G] = []
        for w in self.w:
            i = w.index
            if i in self.status or i in self.absorbed or i in self.done or not (w.is_word or is_number(w.text)):
                continue
            top = i
            while self.heads[top] >= 0 and self.heads[top] not in self.status and \
                    self.heads[top] not in self.done and self.heads[top] not in self.absorbed:
                top = self.heads[top]
            if top in self.done:
                continue
            more = self.any_node(top)
            if more:
                self.notes.append(f"слова «{self.text_of(top)}» не нашли места в разборе — добавлены в конце")
                tokens += [punct(",")] + more if tokens or True else more
        return tokens

    def _final_punct(self, root: int, tokens: list[G]) -> list[G]:
        result = []
        last = self.w[-1]
        if last.text in {".", "!", "?", ":", ";", "…", "..."} and last.index not in self.done:
            result.append(punct(last.text if last.text != "..." else "…", last.index))
            self.mark(last.index, "punct")
        elif last.text in QUOTES_CLOSE | set(BRACKETS.values()) and last.index not in self.done and self.n > 1:
            before = self.w[-2]
            if before.text in {".", "!", "?"} and before.index not in self.done:
                result.append(punct(before.text, before.index))
                self.mark(before.index, "punct")
            result.append(punct(last.text, last.index))
            self.mark(last.index, "punct")
        return result

    def _is_question(self, root: int) -> bool:
        return self.w[-1].text == "?"

    def is_predicate(self, i: int) -> bool:
        w = self.w[i]
        if self.children(i, "cop"):
            return True
        if w.tag.startswith("VB") or w.tag == "MD":
            return True
        return bool(self.children(i, *SUBJ))

    def fragment(self, i: int) -> list[G]:
        """Заголовок или предложение без сказуемого: именная группа в Nominativ."""
        w = self.w[i]
        if w.tag.startswith("VB") and not self.children(i, *SUBJ):
            return self.clause(i, "main")
        tokens, _ = self.phrase_node(i, "N")
        # что не вошло — по порядку
        rest = []
        for child in self.children(i):
            if child.index not in self.done and self.rel(child.index) not in {"punct"}:
                rest += self.any_node(child.index)
        return tokens + rest

    def any_node(self, i: int, case: str = "N") -> list[G]:
        """Перевод поддерева, роль которого не определена."""
        if i in self.done:
            return []
        w = self.w[i]
        if self.rel(i) == "acl:relcl" and self.heads[i] >= 0:
            return [punct(",")] + self.relative_clause(i, self.heads[i], Agr()) + [punct(",")]
        if self.is_predicate(i) and (self.children(i, *SUBJ) or w.tag.startswith("VB")):
            ctype = "sub" if self.children(i, "mark") else "main"
            return [punct(",")] + self.clause(i, ctype)
        if w.tag == "UH" or w.upos == "INTJ":
            # междометие: «please» → «bitte», «yes» → «ja»
            entry = self.lex.lookup(w.lower, "INTJ", strict=True)
            self.mark(i, DICT if entry else UNKNOWN)
            self.done.add(i)
            return [word(clean(entry.de) if entry else w.text, i)]
        tokens, _ = self.phrase_node(i, case)
        return tokens

    # ==================================================================================
    # глагольная группа
    # ==================================================================================

    def english_verb(self, h: int, auxes: list[Word], cop: Word | None) -> EnglishVerb:
        v = EnglishVerb()
        chain = sorted(auxes + ([cop] if cop else []), key=lambda w: w.index)
        main = self.w[h]
        v.words = [w.index for w in chain]
        finite = chain[0] if chain else main
        v.finite_word = finite.index
        if finite.tag == "VBD":
            v.tense = "past"
        for k, a in enumerate(chain):
            lemma = a.lemma.lower()
            nxt = chain[k + 1] if k + 1 < len(chain) else (main if not cop else None)
            if a.tag == "MD" or lemma in {"will", "would", "shall", "should", "can", "could", "may", "might",
                                          "must", "'ll", "'d", "wo", "ca", "ought"}:
                entry = self.lex.lookup(a.lower, "VERB", strict=True)
                props = entry.props if entry else {}
                v.modal = props.get("modal", "werden")
                v.modal_tense = props.get("tense", "pres")
                if a.lower in {"could"} and nxt is not None and nxt.lemma == "have":
                    v.modal_tense = "subj"
            elif lemma == "have" and nxt is not None and nxt.tag == "VBN":
                v.perfect = True
            elif lemma in {"be", "get"} and self.rel(a.index) == "aux:pass":
                v.passive = True
            elif lemma == "be" and a is not cop and main.tag == "VBG" and nxt is main:
                v.progressive = True
            elif lemma == "be" and a is not cop and main.tag == "VBN" and nxt is main:
                v.passive = True
            elif lemma == "be" and a is not cop and k + 1 < len(chain) and chain[k + 1].lemma == "be":
                pass
        if not chain:
            if main.tag == "VBG":
                v.gerund = True
            elif main.tag == "VBN":
                v.participle = True
            elif main.tag == "VB" and any(m.lower == "to" for m in self.children(h, "mark")):
                v.infinitive = True
        elif chain[0].tag in {"VB", "TO"} or (chain[0].lower == "be" and chain[0].tag == "VB"):
            if any(m.lower == "to" for m in self.children(h, "mark")):
                v.infinitive = True
        if chain and chain[0].tag == "VBG":
            v.gerund = True
        return v

    def german_verb(self, h: int, cop: Word | None, objs: list[Word], obls: list[Word]) -> tuple[str, Entry | None, dict]:
        """Немецкий глагол для вершины h: (лемма с пометками, статья, сведения об управлении)."""
        info: dict = {"consumed": set(), "governed": None, "prep": None}
        if cop is not None:
            return "sein", None, info
        w = self.w[h]
        lemma = w.lemma.lower()
        if h in self.phrases:
            entry = self.phrases[h][0]
            return entry.de, entry, info
        # частица фразового глагола (анализатор иногда разбирает её как наречие)
        particles = self.children(h, "compound:prt") + [a for a in self.children(h, "advmod")
                                                        if a.lower in {"around", "out", "up", "down", "off", "away",
                                                                       "back", "over", "on", "forward"}]
        for prt in particles:
            entry = self.lex.phrase(f"{lemma} {prt.lower}", "VERB")
            if entry:
                info["consumed"].add(prt.index)
                self.notes.append(f"фразовый глагол «{lemma} {prt.lower}» → «{clean(entry.de)}»")
                return entry.de, entry, info
        # глагол + дополнение-существительное без артикля: take place, make sense
        for obj in objs:
            dets = self.children(obj.index, "det")
            others = [c for c in self.children(obj.index) if self.rel(c.index) not in {"det", "punct"}]
            # «exact revenge against his uncle»: предложная группа при дополнении-части оборота — к глаголу
            pps = [c for c in others if self.rel(c.index) == "nmod" and self.children(c.index, "case")]
            if len(pps) != len(others):
                continue
            key = f"{lemma} {' '.join(d.lower for d in dets)} {obj.lemma.lower()}".replace("  ", " ")
            entry = self.lex.phrase(key, "VERB")
            if entry:
                for pp in pps:
                    self._move(pp.index, h, "obl")
                    obls.append(pp)
                info["consumed"].add(obj.index)
                for d in dets:
                    info["consumed"].add(d.index)
                self.notes.append(f"глагольный оборот «{key}» → «{clean(entry.de)}»")
                return entry.de, entry, info
        # предложная группа внутри дополнения, которой управляет глагол: «focus development on the functions»
        for obj in objs:
            for nm in self.children(obj.index, "nmod"):
                for case in self.children(nm.index, "case"):
                    entry = self.lex.phrase(f"{lemma} {case.lower}", "VERB")
                    if (entry is None or "noobj" in entry.props) and case.lower == "to":
                        # «apply security to technology»: у глагола своё управление (anwenden auf + A)
                        base = self.choice(h, "VERB").entry
                        entry = base if base is not None and base.props.get("prep") else None
                    # «provide services for programs»: «provide for» (sorgen für) — оборот без прямого дополнения
                    if entry and entry.props.get("prep") and "noobj" not in entry.props:
                        self.kids[obj.index].remove(nm.index)
                        self.kids[h].append(nm.index)
                        self.kids[h].sort()
                        self.heads[nm.index] = h
                        self.deprels[nm.index] = "obl"
                        obls.append(nm)
                        self.notes.append(f"по управлению глагола «{lemma} {case.lower}» группа «{case.text} "
                                          f"{nm.text}» отнесена к глаголу")
        # предложный глагол: depend on, consist of
        for obl in obls:
            for case in self.children(obl.index, "case"):
                entry = self.lex.phrase(f"{lemma} {case.lower}", "VERB")
                if entry and "noobj" in entry.props and objs:
                    continue                            # «apply security to technology» — не «gelten für»
                if entry:
                    info["governed"] = obl.index
                    self.notes.append(f"управление «{lemma} {case.lower}» → «{clean(entry.de)} "
                                      f"{entry.props.get('prep', '')}»")
                    return entry.de, entry, info
        choice = self.choice(h, "VERB")
        if choice.entry is not None:
            # «call X Y», «is called Y» — «nennen», а не «aufrufen»
            if choice.entry.props.get("xverb") and (self.children(h, "xcomp") or
                                                     (self.w[h].tag == "VBN" and objs)):
                return choice.entry.props["xverb"], choice.entry, info
            # «know that …» — «wissen, dass …», а «know the city» — «kennen»
            if choice.entry.props.get("ccomp") and self.children(h, "ccomp"):
                return choice.entry.props["ccomp"], choice.entry, info
            return choice.entry.de, choice.entry, info
        return "", None, info

    def verb_group(self, gverb: str, entry: Entry | None, ev: EnglishVerb, agr: Agr, ctype: str,
                   has_object: bool, h: int) -> VerbGroup:
        g = VerbGroup()
        if entry is not None and not has_object and entry.props.get("intr"):
            gverb = entry.props["intr"]
        reflexive = gverb.startswith("sich ")
        verb = gverb.removeprefix("sich ")
        words = verb.split()
        fixed, verb = (words[:-1], words[-1]) if len(words) > 1 else ([], verb)
        g.fixed = fixed
        g.reflexive = reflexive
        person, number = agr.person, agr.number
        aux_verb = gm.auxiliary(verb) if not (entry and entry.props.get("aux")) else entry.props["aux"]
        if aux_verb in {"s", "sein"}:
            aux_verb = "sein"
        elif aux_verb in {"h", "haben"}:
            aux_verb = "haben"
        voice_active = bool(entry and entry.props.get("voice") == "active")
        passive = ev.passive and not voice_active

        def conj(lemma: str, tense: str) -> tuple[str, str]:
            if tense == "past":
                return gm.past(lemma, person, number)
            if tense == "subj":
                return gm.subjunctive(lemma, person, number)
            return gm.present(lemma, person, number)

        if ctype in {"zu", "um"}:
            if passive and ev.perfect:
                g.nonfinite = [gm.participle(verb), "worden", "zu sein"]
            elif passive:
                g.nonfinite = [gm.participle(verb), "zu werden"]
            elif ev.perfect:
                g.nonfinite = [gm.participle(verb), "zu " + aux_verb]
            else:
                g.nonfinite = [gm.zu_infinitive(verb)]
            return g
        if ev.modal:
            modal = ev.modal
            tense = ev.modal_tense
            g.finite, _ = conj(modal, tense)
            if passive and ev.perfect:
                g.nonfinite = [gm.participle(verb), "worden", "sein"]
            elif passive:
                g.nonfinite = [gm.participle(verb), "werden"]
            elif ev.perfect:
                g.nonfinite = [gm.participle(verb), aux_verb]
            else:
                g.nonfinite = [gm.infinitive(verb)]
            if modal == "werden" and tense == "subj" and verb in {"sein", "haben"} and not ev.perfect and not passive:
                g.finite, _ = conj(verb, "subj")
                g.nonfinite = []
            return g
        if ev.perfect:
            if passive:
                g.finite, _ = conj("sein", ev.tense)
                g.nonfinite = [gm.participle(verb), "worden"]
            else:
                g.finite, _ = conj(aux_verb, ev.tense)
                g.nonfinite = [gm.participle(verb)]
            return g
        if passive:
            g.finite, _ = conj("werden", ev.tense)
            g.nonfinite = [gm.participle(verb)]
            return g
        g.finite, g.prefix = conj(verb, ev.tense)
        return g

    # ==================================================================================
    # клауза
    # ==================================================================================

    def clause(self, h: int, ctype: str, *, intro: list[G] | None = None, skip: set[int] | None = None,
               subject_agr: Agr | None = None, forced: dict | None = None, subject_tokens: list[G] | None = None,
               relative_role: str = "", extra: list[Part] | None = None) -> list[G]:
        """Предложение с вершиной h.

        ctype: main — главное, question — вопрос, sub — придаточное с союзом (глагол в конец),
        rel — относительное придаточное, zu — инфинитивный оборот, um — «um … zu».
        """
        skip = set(skip or ())
        w = self.w[h]
        self.done.add(h)
        kids = [c for c in self.children(h) if c.index not in skip]

        subjects = [c for c in kids if self.rel(c.index) in SUBJ]
        expl = [c for c in kids if self.rel(c.index) == "expl"]
        auxes = [c for c in kids if self.rel(c.index) in {"aux", "aux:pass"}]
        cops = [c for c in kids if self.rel(c.index) == "cop"]
        cop = cops[0] if cops else None
        marks = [c for c in kids if self.rel(c.index) == "mark"]
        negs = [c for c in kids if self.rel(c.index) == "advmod" and c.lower in NEGATIONS]
        objs = [c for c in kids if self.rel(c.index) == "obj"]
        iobjs = [c for c in kids if self.rel(c.index) == "iobj"]
        obls = [c for c in kids if self.rel(c.index).split(":")[0] == "obl"]

        for c in auxes + cops + marks + negs:
            self.mark(c.index, DICT)

        # «The goal is to make data readable» → «Das Ziel ist, Daten lesbar zu machen»
        if w.upos == "VERB" and cop is not None and subjects and ctype in {"main", "sub", "rel"} and                 any(m.lower == "to" for m in marks) and not intro:
            return self.infinitive_predicate(h, subjects[0], cop, marks, ctype)

        # --- модальные обороты: have to, need to, want to, be able to ------------------
        modal_override = ""
        main = h
        xcomps = [c for c in kids if self.rel(c.index) == "xcomp"]
        lemma = w.lemma.lower()
        if cop is None and xcomps and lemma in MODAL_XCOMP and self.children(xcomps[0].index, "mark") and \
                any(m.lower == "to" for m in self.children(xcomps[0].index, "mark")):
            modal_override = MODAL_XCOMP[lemma]
        elif cop is not None and lemma in {"able", "unable", "capable"} and xcomps:
            modal_override = "können"
            if lemma == "unable":
                extra = (extra or []) + [Part([word("nicht", h)], "neg", h)]
        elif w.lower == "going" and xcomps and auxes:
            modal_override = "werden"
        if cop is not None and lemma in {"likely", "unlikely", "sure", "certain", "bound"} and xcomps and \
                any(m.lower == "to" for m in self.children(xcomps[0].index, "mark")):
            x = xcomps[0]
            self.mark(h, DICT)
            for m in self.children(x.index, "mark"):
                self.mark(m.index, DICT)
            ev = self.english_verb(h, auxes, cop)
            adverb = {"likely": "wahrscheinlich", "unlikely": "wahrscheinlich nicht", "sure": "sicher",
                      "certain": "sicher", "bound": "zwangsläufig"}[lemma]
            self.notes.append(f"«is {lemma} to …» → наречие «{adverb}»")
            moved = [c.index for c in kids if c.index != x.index and self.rel(c.index) not in {"cop", "xcomp"}]
            for c in moved:
                self.kids[x.index].append(c)
                self.heads[c] = x.index
            self.kids[x.index].sort()
            self.kids[h] = [x.index]
            forced = dict(forced or {})
            forced.update(infinitive=False, tense=ev.tense, modal=ev.modal, modal_tense=ev.modal_tense,
                          perfect=ev.perfect)
            part = Part([word(adverb, h)], "conn", h)
            return self.clause(x.index, ctype, intro=intro, skip=skip, subject_agr=subject_agr, forced=forced,
                               subject_tokens=subject_tokens, relative_role=relative_role,
                               extra=(extra or []) + [part])
        if modal_override:
            x = xcomps[0]
            self.notes.append(f"«{w.text} to …» → модальный глагол «{modal_override}»")
            self.mark(h, DICT)
            for m in self.children(x.index, "mark"):
                self.mark(m.index, DICT)
            ev = self.english_verb(h, auxes, cop)
            tense = ev.tense if ev.modal == "" else ev.modal_tense
            forced = dict(forced or {})
            forced.update(modal=modal_override, modal_tense=tense if tense != "pres" or not ev.modal else "pres",
                          infinitive=False)
            if ev.modal == "werden" and modal_override != "werden":
                forced["modal_tense"] = "pres"
            # остальные зависимые h переходят к инфинитиву
            moved = [c.index for c in kids if c.index != x.index and self.rel(c.index) not in {"aux", "cop", "xcomp"}]
            for c in moved:
                self.kids[x.index].append(c)
                self.heads[c] = x.index
            self.kids[x.index].sort()
            self.kids[h] = [x.index]
            return self.clause(x.index, ctype, intro=intro, skip=skip, subject_agr=subject_agr, forced=forced,
                               subject_tokens=subject_tokens, relative_role=relative_role, extra=extra)

        # --- английская глагольная группа --------------------------------------------
        ev = self.english_verb(h, auxes, cop)
        if forced:
            for key, value in forced.items():
                setattr(ev, key, value)
        if ev.infinitive and ctype not in {"zu", "um"}:
            ctype = "zu"

        # --- there is / there are → es gibt -------------------------------------------
        there = next((e for e in expl if e.lower == "there"), None)
        if there is not None and (w.lemma == "be" or (cop and cop.lemma == "be") or w.lemma in {"exist"}):
            gverb, gentry, info = "geben", None, {"consumed": set(), "governed": None}
            self.mark(there.index, DICT)
            self.notes.append("«there is/are» → «es gibt» + Akkusativ")
            objs = subjects + objs
            subjects = []
            if cop is not None:
                pass
            subject_tokens = [word("es", there.index)]
            subject_agr = Agr(3, "sg", "n")
            cop = None
        else:
            gverb, gentry, info = self.german_verb(h, cop, objs, obls)
        for c in info["consumed"]:
            self.mark(c, DICT)
        objs = [o for o in objs if o.index not in info["consumed"]]
        unknown_verb = False
        if cop is None and not gverb:
            # глагол без перевода: оставляем английское слово
            gverb = w.lemma
            unknown_verb = True
            self.unknown(h)

        # --- подлежащее ---------------------------------------------------------------------
        subj_part = None
        if subject_tokens is not None:
            agr = subject_agr or Agr()
            subj_pos = min((s.index for s in subjects), default=h)
            subj_part = Part(subject_tokens, "subj", subj_pos, pronoun=True)
        elif subjects and expl and self.rel(subjects[0].index).startswith("csubj"):
            e = expl[0]
            self.mark(e.index, DICT)
            subj_part = Part([word("es", e.index)], "subj", e.index, pronoun=True)
            agr = Agr(3, "sg", "n")
            clause_tokens = self.clausal_subject(subjects[0].index)
            while clause_tokens and clause_tokens[-1].kind == "punct" and clause_tokens[-1].text == ",":
                clause_tokens = clause_tokens[:-1]
            self.extraposed = [punct(",")] + clause_tokens
            self.notes.append("«it … that/to …» → «es … , dass/zu …»: придаточное в конце")
        elif subjects:
            s = subjects[0]
            if self.rel(s.index).startswith("csubj"):
                tokens = self.clausal_subject(s.index)
                agr = Agr(3, "sg", "n")
            else:
                tokens, agr = self.phrase_node(s.index, "N", role="subj")
            for other in subjects[1:]:
                more, _ = self.phrase_node(other.index, "N")
                tokens += more
            subj_part = Part(tokens, "subj", s.index, pronoun=self.w[s.index].tag == "PRP")
            if subject_agr is not None:
                agr = subject_agr
        elif expl:
            e = expl[0]
            self.mark(e.index, DICT)
            subj_part = Part([word("es", e.index)], "subj", e.index, pronoun=True)
            agr = Agr(3, "sg", "n")
        else:
            agr = subject_agr or Agr()
        # повелительное наклонение — только у вершины предложения («Install the program.»); глагол без
        # подлежащего, оторванный ошибкой разбора, — не просьба к читателю («…, sein Sie»), а инфинитив
        if ctype == "main" and subj_part is None and w.tag == "VB" and not auxes and not marks and not ev.modal                 and self.heads[h] < 0:
            ctype = "imperative"
            agr = Agr(2, "pl")
            subj_part = Part([word("Sie")], "subj", h, pronoun=True)
        if ctype == "question" and subj_part is None:
            ctype = "main"

        has_object = bool(objs) or ev.passive or cop is not None
        group = self.verb_group(gverb, gentry, ev, agr, ctype, has_object, h)
        if ctype == "imperative":
            group.finite = gm.infinitive(gverb.removeprefix("sich ").split()[-1])
            sep, _, base = gm.split_verb(gverb.removeprefix("sich ").split()[-1])
            if sep:
                group.finite = gm.split_verb(gverb.split()[-1])[1] + base
                group.prefix = sep
        if unknown_verb:
            if group.nonfinite:
                group.nonfinite[0] = w.text
            elif group.finite and ev.finite_word in {h, -1}:
                group.finite, group.prefix = w.text, ""
        # возвратный глагол с прямым дополнением: «focus development on X» → «konzentriert die Entwicklung auf X»
        if group.reflexive and objs and gentry is not None and gentry.props.get("prep"):
            group.reflexive = False
        elif group.reflexive and objs:
            group.reflexive_case = "D"
        group.finite_src = (ev.finite_word,) if ev.finite_word >= 0 else (h,)
        main_src = tuple([h] + [c for c in info["consumed"]])
        if cop is None:
            self.mark(h, DICT if gentry is not None or w.lemma in {"be", "have", "do"} else
                      self.status.get(h, DICT))

        # --- дополнения и обстоятельства --------------------------------------------------
        parts: list[Part] = list(extra or [])
        if subj_part is not None:
            parts.append(subj_part)
        if group.reflexive:
            refl = gm.REFLEXIVE[(agr.person, agr.number)][group.reflexive_case]
            parts.append(Part([word(refl, main_src)], "refl", h, pronoun=True))

        obj_case = "A"
        obj_prep = None
        if gentry is not None:
            setting = gentry.props.get("obj", "")
            if setting == "D":
                obj_case = "D"
            elif "+" in setting:
                obj_prep = setting
        negate_object = False
        if negs and objs:
            first_obj = objs[0]
            if self._indefinite(first_obj.index):
                negate_object = True
        if negs and cop is not None and self._indefinite(h):
            negate_object = True

        if gentry is not None and gentry.props.get("xcomp") and ev.passive and objs:
            o = objs.pop(0)
            tokens, _ = self.phrase_node(o.index, "N")
            parts.append(Part([word(gentry.props["xcomp"], h)] + tokens, "pred", o.index))
            self.notes.append(f"«{w.lemma} … X» → «{gentry.props['xcomp']} X»")
        for o in objs:
            if obj_prep:
                prep, _, case = obj_prep.partition("+")
                tokens, oagr = self.phrase_node(o.index, case or "A", negate=negate_object and o is objs[0])
                if prep:
                    tokens = self.attach_prep(prep, case, tokens)
            else:
                tokens, oagr = self.phrase_node(o.index, obj_case, negate=negate_object and o is objs[0])
            parts.append(Part(tokens, "obj", o.index, pronoun=self.w[o.index].tag == "PRP"))
        for o in iobjs:
            tokens, _ = self.phrase_node(o.index, "D")
            parts.append(Part(tokens, "iobj", o.index, pronoun=self.w[o.index].tag == "PRP"))

        governed = info.get("governed")
        verb_prep = gentry.props.get("prep", "") if gentry is not None else ""
        motion = w.lemma.lower() in MOTION_VERBS
        for o in obls:
            if o.index in info["consumed"]:
                continue
            governed_here = o.index == governed or (verb_prep and governed is None and len(
                [x for x in obls if self.children(x.index, "case")]) == 1 and self.children(o.index, "case"))
            prep_override = verb_prep if governed_here and verb_prep else None
            give_to = (w.lemma.lower() in GIVE_VERBS and objs and any(c.lower == "to" for c in self.children(o.index, "case")))
            if give_to:
                for c in self.children(o.index, "case"):
                    self.mark(c.index, DICT)
                tokens, _ = self.phrase_node(o.index, "D", skip_case=True)
                parts.append(Part(tokens, "iobj", o.index, pronoun=self.w[o.index].tag == "PRP"))
                self.notes.append("«to» при глаголе передачи → Dativ без предлога")
                continue
            tokens = self.adverbial(o.index, prep_override=prep_override, motion=motion,
                                    agent=self.rel(o.index) == "obl:agent", main_subject=agr)
            kind = "clause" if self._is_clausal(o.index) else "obl"
            parts.append(Part(tokens, kind, o.index, pronoun=self.w[o.index].tag == "PRP" and not self.children(o.index, "case")))

        # --- перечень после двоеточия: «… are extant: the First Quarto (1603); …» ----------------------
        colon = next((c.index for c in self.children(h, "punct") if c.text == ":" and c.index > h), None)
        after_colon = [c for c in kids if colon is not None and c.index > colon and self.rel(c.index) != "punct"
                       and c.index not in self.done]
        for c in after_colon:
            self.done.add(c.index)

        # --- остальные зависимые ------------------------------------------------------------------
        pred_part = None
        if cop is not None:
            tokens = self.predicate(h, negate=negate_object)
            pred_part = Part(tokens, "pred", h)
            parts.append(pred_part)

        for c in kids:
            r = self.rel(c.index)
            if c.index in self.done or c.index in info["consumed"]:
                continue
            if r in SUBJ or r in {"aux", "aux:pass", "cop", "mark", "obj", "iobj", "expl", "punct", "compound:prt"} \
                    or r.split(":")[0] == "obl":
                continue
            if r == "advmod":
                if c.lower in NEGATIONS:
                    continue
                parts.append(self.adverb_part(c.index, h))
            elif r == "advcl":
                parts.append(self.adverbial_clause(c.index, h, agr))
            elif r == "ccomp":
                parts.append(Part([punct(",")] + self.complement_clause(c.index), "nachfeld", c.index, clause=True))
            elif r == "xcomp" and self.children(c.index, *SUBJ):
                parts.append(Part([punct(",")] + self.clause(c.index, "main"), "nachfeld", c.index, clause=True))
            elif r == "xcomp" and pred_part is not None and self.w[h].upos == "ADJ" and                     any(m.lower == "to" for m in self.children(c.index, "mark")) and len(self.span(c.index)) <= 4:
                # «easy to train» → «leicht zu trainieren»: короткий инфинитив — при прилагательном, без запятых
                pred_part.tokens += self.clause(c.index, "zu", intro=[])
            elif r == "xcomp":
                parts.append(self.xcomp_part(c.index, h, gentry))
            elif r in {"conj", "cc", "parataxis"}:
                continue
            elif r in {"discourse", "vocative"} and c.index < h and self.w[c.index].tag in {"UH", "NNP", "NNPS"}                     and c.index + 1 < self.n and self.w[c.index + 1].text == ",":
                # «Yes, the program works» → «Ja, das Programm funktioniert»: междометие и обращение стоят
                # перед предложением и не занимают первое место (инверсии нет)
                tokens = self.any_node(c.index)
                parts.append(Part(tokens + [punct(",")], "pre", c.index))
            elif r in {"discourse", "vocative", "dislocated", "dep", "list", "reparandum", "orphan", "goeswith"}:
                tokens = self.any_node(c.index)
                parts.append(Part(tokens, "adv", c.index))
            elif r == "acl:relcl":
                parts.append(Part(self.any_node(c.index), "nachfeld", c.index, clause=True))
            elif r in {"nmod", "nmod:tmod", "nmod:unmarked", "nmod:npmod", "obl:npmod"}:
                tokens = self.adverbial(c.index)
                parts.append(Part(tokens, "obl", c.index))
            elif cop is None and r in {"det", "amod", "compound", "nummod", "acl", "acl:relcl", "appos", "nmod:poss",
                                      "flat", "fixed", "case"}:
                tokens = self.any_node(c.index)
                parts.append(Part(tokens, "obl", c.index))

        extraposed = getattr(self, "extraposed", None)
        if extraposed:
            parts.append(Part(extraposed, "nachfeld", 10_000, clause=True))
            self.extraposed = None
        if negs:
            if not negate_object:
                neg = negs[0]
                text = "nie" if neg.lower == "never" else "nicht"
                parts.append(Part([word(text, neg.index)], "neg", neg.index))
            else:
                self.notes.append("«not» + неопределённый артикль → «kein»")

        tokens = self.order(ctype, parts, group, main_src, intro or [], h, ev)
        if after_colon:
            self.mark(colon, "punct")
            tokens.append(punct(":", colon))
            for c in after_colon:
                self.done.discard(c.index)
                separators = [x for x in self.children(h, "punct") + self.children(c.index, "punct")
                              if x.index < c.index and x.index > colon and x.index not in self.done]
                if separators and c is not after_colon[0]:
                    sep = separators[-1]
                    self.mark(sep.index, "punct")
                    tokens.append(punct(sep.text, sep.index))
                if self.is_predicate(c.index) and self.children(c.index, *SUBJ):
                    tokens += self.clause(c.index, "main")
                else:
                    more, _ = self.phrase_node(c.index, "N")
                    tokens += more
        tokens = self.wrap(h, tokens, skip_quotes=True)

        # --- однородные сказуемые и сочинённые предложения ------------------------------------
        tokens += self.coordination(h, ctype, agr, skip)
        for p in self.children(h, "parataxis"):
            if p.index in skip or p.index in self.done:
                continue
            first = self.span(p.index)[0]
            sep = sorted([c for c in self.children(h, "punct") + self.children(p.index, "punct")
                          if c.index <= first and c.index not in self.done], key=lambda c: c.index)
            mark = sep[-1].text if sep and sep[-1].text in {";", ":", "—", "–", "-", "--"} else ","
            tokens += [punct({"—": "–", "--": "–", "-": "–"}.get(mark, mark))] + self.clause(p.index, "main") \
                if self.is_predicate(p.index) else [punct(",")] + self.any_node(p.index)
        return tokens

    def _indefinite(self, i: int) -> bool:
        """Именная группа без определённого артикля: её отрицание — «kein»."""
        w = self.w[i]
        if w.upos not in {"NOUN"} or w.tag.startswith("NNP"):
            return False
        dets = self.children(i, "det")
        if not dets:
            return not self.children(i, "nmod:poss", "nummod")
        return dets[0].lower in {"a", "an", "any"}

    def _is_clausal(self, i: int) -> bool:
        w = self.w[i]
        return w.tag == "VBG" and any(c.lower == "by" for c in self.children(i, "case", "mark"))

    # ------------------------------------------------------------------------------------------
    # порядок слов
    # ------------------------------------------------------------------------------------------

    def order(self, ctype: str, parts: list[Part], group: VerbGroup, main_src: tuple, intro: list[G], h: int,
              ev: EnglishVerb) -> list[G]:
        finite_tokens = [word(group.finite, group.finite_src)] if group.finite else []
        nonfinite = [word(x, main_src) for x in group.nonfinite]
        right: list[G] = []
        fixed = [word(x, main_src) for x in group.fixed]
        nachfeld = [p for p in parts if p.kind == "nachfeld"]
        pre = [t for p in sorted(parts, key=lambda p: p.pos) if p.kind == "pre" for t in p.tokens]
        parts = [p for p in parts if p.kind not in {"nachfeld", "pre"}]

        subject = next((p for p in parts if p.kind == "subj"), None)
        verb_pos = ev.finite_word if ev.finite_word >= 0 else h
        anchor = min(verb_pos, subject.pos if subject else verb_pos)

        def group_key(p: Part) -> tuple[int, int]:
            order = {"subj": 0, "refl": 1, "neg": 7, "pred": 8}.get(p.kind)
            if order is None:
                if p.pronoun and p.kind in {"obj", "iobj"}:
                    order = 2 if p.kind == "obj" else 3
                elif p.kind == "conn":
                    order = 4
                elif p.kind == "adv" and p.pos < verb_pos:
                    order = 4
                elif p.kind == "iobj":
                    order = 5
                else:
                    order = 6
            return order, p.pos

        if ctype in {"main", "imperative", "question"}:
            vorfeld: list[G] = []
            fronted = [p for p in parts if p.kind not in {"subj", "refl", "neg", "pred"} and p.pos < anchor]
            middle = [p for p in parts]
            if ctype == "main":
                candidates = [p for p in fronted if p.kind != "conn"]
                if candidates:
                    first = min(candidates, key=lambda p: p.pos)
                    vorfeld = first.tokens + ([punct(",")] if first.clause else [])
                    middle.remove(first)
                    self.notes.append("инверсия: на первом месте обстоятельство, глагол — второй (V2)")
                elif subject is not None:
                    vorfeld = subject.tokens
                    middle.remove(subject)
                elif fronted:
                    first = min(fronted, key=lambda p: p.pos)
                    vorfeld = first.tokens
                    middle.remove(first)
            elif ctype == "question":
                # «Which algorithm is faster?» — вопросительное слово в подлежащем: подлежащее впереди
                askable = fronted + ([subject] if subject is not None and subject.pos < verb_pos else [])
                wh = [p for p in askable if p.tokens and p.tokens[0].text.lower() in
                      {"wer", "was", "wen", "wem", "wessen", "wo", "wann", "wie", "warum", "welche", "welcher",
                       "welches", "welchen", "welchem", "woher", "wohin"}]
                if wh:
                    vorfeld = wh[0].tokens
                    middle.remove(wh[0])
            middle.sort(key=group_key)
            for p in middle:
                pass
            mf = [t for p in middle for t in p.tokens]
            if group.prefix and not group.nonfinite:
                right = [word(group.prefix, main_src)]
            tokens = intro + pre + vorfeld + finite_tokens + mf + fixed + right + nonfinite
            if group.nonfinite and len(group.nonfinite) > 1:
                self.notes.append(f"рамочная конструкция: {group.finite} … {' '.join(group.nonfinite)}")
            elif group.prefix:
                self.notes.append(f"отделяемая приставка: {group.finite} … {group.prefix}")
        else:
            parts.sort(key=group_key)
            mf = [t for p in parts for t in p.tokens]
            if ctype in {"zu", "um"}:
                tail = nonfinite
                head = [word("um", main_src)] if ctype == "um" else []
                tokens = intro + head + mf + fixed + tail
            else:
                finite_text = group.finite
                if group.prefix and not group.nonfinite:
                    finite_text = group.prefix + group.finite
                tail = nonfinite + ([word(finite_text, group.finite_src)] if finite_text else [])
                tokens = intro + mf + fixed + tail
                if ctype == "sub" and finite_text:
                    self.notes.append("придаточное: спрягаемый глагол в конце")
            if pre:                                     # в придаточном междометие не теряется
                tokens = tokens[:len(intro)] + pre + tokens[len(intro):]
        for p in sorted(nachfeld, key=lambda p: p.pos):
            tokens += p.tokens
        return tokens

    # ------------------------------------------------------------------------------------------
    # однородные члены
    # ------------------------------------------------------------------------------------------

    def coordination(self, h: int, ctype: str, agr: Agr, skip: set[int]) -> list[G]:
        tokens: list[G] = []
        conjs = [c for c in self.children(h, "conj") if c.index not in skip and c.index not in self.done]
        negated = any(c.lower in NEGATIONS for c in self.children(h, "advmod"))
        for c in conjs:
            ccs = [x for x in self.children(c.index, "cc") if x.index not in self.done]
            commas = [x for x in self.children(c.index, "punct") if x.index < c.index and x.text in {",", ";"}
                      and x.index not in self.done]
            for x in commas:
                self.mark(x.index, "punct")
            conj_tokens: list[G] = []
            if ccs:
                cc = ccs[0]
                text = self.coordinator(cc, negated)
                self.mark(cc.index, DICT)
                if text in {"aber", "sondern", "doch"}:
                    conj_tokens.append(punct(","))
                conj_tokens.append(word(text, cc.index))
            elif commas:
                conj_tokens.append(punct(commas[0].text))
            own_subject = bool(self.children(c.index, *SUBJ, "expl"))
            if self.is_predicate(c.index) or self.w[c.index].tag.startswith("VB"):
                if own_subject:
                    sub_type = ctype if ctype in {"sub", "rel", "zu", "um"} else "main"
                    conj_tokens += self.clause(c.index, sub_type)
                else:
                    sub_type = ctype if ctype in {"sub", "rel", "zu", "um"} else "main"
                    conj_tokens += self.clause(c.index, sub_type, subject_tokens=[], subject_agr=agr,
                                               forced=self._inherited_features(h, c.index))
            else:
                conj_tokens += self.any_node(c.index)
            tokens += conj_tokens
        return tokens

    def _negated_clause(self, i: int) -> bool:
        """Есть ли отрицание у сказуемого, к которому относится группа i: «not X but Y» → «nicht X, sondern Y»."""
        k = i
        while k >= 0:
            if any(c.lower in NEGATIONS for c in self.children(k, "advmod")):
                return True
            if self.is_predicate(k):
                return False
            k = self.heads[k]
        return False

    def coordinator(self, cc: Word, negated: bool) -> str:
        lower = cc.lower
        if lower == "but" and negated:
            return "sondern"
        choice = self.choice(cc.index, "CCONJ")
        return clean(choice.entry.de) if choice.entry else cc.text

    def _inherited_features(self, h: int, c: int) -> dict:
        """Однородное сказуемое без своих вспомогательных глаголов наследует время и залог первого."""
        if self.children(c, "aux", "aux:pass", "cop"):
            return {}
        auxes = self.children(h, "aux", "aux:pass")
        if not auxes:
            return {}
        ev = self.english_verb(h, auxes, None)
        result = {"tense": ev.tense, "perfect": ev.perfect, "modal": ev.modal, "modal_tense": ev.modal_tense}
        if self.w[c].tag == "VBN" and ev.passive:
            result["passive"] = True
        return result

    # ==================================================================================
    # придаточные и обороты
    # ==================================================================================

    def subordinator(self, marks: list[Word], verb: int) -> tuple[list[G], str]:
        """Немецкий союз придаточного и вид оборота (sub | zu | um)."""
        if not marks:
            return [], "sub"
        mark = marks[0]
        text = mark.lower
        if text == "to":
            for m in marks:
                self.mark(m.index, DICT)
            return [], "zu"
        if mark.index in self.phrases:
            entry = self.phrases[mark.index][0]
        else:
            entry = self.lex.lookup(text, "SCONJ")
        for m in marks:
            self.mark(m.index, DICT)
        if entry is None:
            return [word(mark.text, mark.index, "unknown")], "sub"
        if "inf" in entry.props:
            return [], "um"
        german = clean(entry.de)
        if text == "when" and self.english_verb(verb, self.children(verb, "aux", "aux:pass"),
                                                (self.children(verb, "cop") or [None])[0]).tense == "past":
            german = entry.props.get("past", german)
        if text == "if" and self.rel(verb) == "ccomp":
            german = "ob"
        return [word(german, self.src(mark.index))], "sub"

    def adverbial_clause(self, c: int, h: int, main_agr: Agr) -> Part:
        """Придаточное обстоятельственное (advcl): если/когда/потому что; to → um … zu; by -ing → indem."""
        marks = self.children(c, "mark")
        w = self.w[c]
        if w.tag == "VBG" and not self.children(c, "aux"):
            tokens = self.gerund_clause(c, marks, main_agr)
            return Part(tokens, "clause", c, clause=True)
        if w.tag == "VBN" and not self.children(c, "aux", "aux:pass") and not marks:
            # причастный оборот: «Written in 1600, Hamlet…»
            part_tokens = self.participial(c)
            return Part(part_tokens, "clause", c, clause=True)
        intro, ctype = self.subordinator(marks, c)
        if not marks:
            wh = [a for a in self.children(c, "advmod") if a.tag == "WRB" and a.index < c]
            if wh:
                ev_tense = self.english_verb(c, self.children(c, "aux", "aux:pass"),
                                             (self.children(c, "cop") or [None])[0]).tense
                german = {"when": "als" if ev_tense == "past" else "wenn", "where": "wo", "how": "wie",
                          "why": "warum", "whenever": "immer wenn", "while": "während"}.get(wh[0].lower, "wenn")
                self.mark(wh[0].index, DICT)
                intro = [word(german, wh[0].index)]
        if ctype == "zu":
            ctype = "um"
            self.notes.append("«to» (цель) → «um … zu»")
        if not self.children(c, *SUBJ, "expl") and ctype == "sub" and not self.children(c, "cop") and w.tag == "VB":
            ctype = "um" if not intro else ctype
        tokens = self.clause(c, ctype, intro=intro)
        comma = [punct(",")]
        return Part(comma + tokens + comma, "clause" if c < h else "nachfeld", c, clause=True)

    def gerund_clause(self, c: int, marks: list[Word], main_agr: Agr) -> list[G]:
        """-ing-оборот при глаголе: by doing → indem, without doing → ohne … zu, after doing → nachdem."""
        mark = marks[0].lower if marks else ""
        for m in marks:
            self.mark(m.index, DICT)
        cases = self.children(c, "case")
        if not mark and cases:
            mark = cases[0].lower
            for x in cases:
                self.mark(x.index, DICT)
        pronoun = gm.personal(main_agr.person, main_agr.number, main_agr.gender, "N") if main_agr else "man"
        if mark in {"by", "through"}:
            self.notes.append("«by + -ing» → придаточное с «indem»")
            return [punct(","), word("indem", marks[0].index if marks else c)] + self.clause(
                c, "sub", subject_tokens=[word(pronoun)], subject_agr=main_agr, forced={"gerund": False}) + [punct(",")]
        if mark == "without":
            return [punct(","), word("ohne", c)] + self.clause(c, "zu", forced={"gerund": False, "infinitive": True}) + [punct(",")]
        if mark in {"for", "in", "of", "about", "from"}:
            tokens, _ = self.gerund_noun(c, "D")
            prep = {"for": "zu", "in": "bei", "of": "von", "about": "über", "from": "von"}[mark]
            if mark == "about":
                tokens, _ = self.gerund_noun(c, "A")
            return self.attach_prep(prep, "D", tokens)
        if mark in {"after", "before", "while", "when", "since", "upon", "on"}:
            german = {"after": "nachdem", "before": "bevor", "while": "während", "when": "wenn", "since": "seit",
                      "upon": "als", "on": "als"}[mark]
            return [punct(","), word(german, c)] + self.clause(c, "sub", subject_tokens=[word(pronoun)],
                                                               subject_agr=main_agr, forced={"gerund": False}) + [punct(",")]
        # «Using X, we …» — в немецком придаточное с «indem»
        return [punct(","), word("indem", c)] + self.clause(c, "sub", subject_tokens=[word(pronoun)],
                                                            subject_agr=main_agr, forced={"gerund": False}) + [punct(",")]

    def participial(self, c: int) -> list[G]:
        """Причастный оборот с причастием II в конце: «Written in 1600» → «1600 geschrieben»."""
        self.done.add(c)
        choice = self.choice(c, "VERB")
        verb = choice.entry.de if choice.entry else self.w[c].lemma
        tokens: list[G] = []
        for k in self.children(c):
            if k.index in self.done or self.rel(k.index) == "punct":
                continue
            if self.rel(k.index).startswith("obl"):
                tokens += self.adverbial(k.index, agent=self.rel(k.index) == "obl:agent")
            elif self.rel(k.index) == "advmod":
                tokens += self.adverb_part(k.index, c).tokens
            else:
                tokens += self.any_node(k.index)
        self.mark(c, DICT if choice.entry else UNKNOWN)
        return tokens + [word(gm.participle(verb.removeprefix("sich ").split()[-1]), c)]

    def infinitive_predicate(self, h: int, subject: Word, cop: Word, marks: list[Word], ctype: str) -> list[G]:
        """Сказуемое — инфинитив со связкой: подлежащее + sein + «, … zu …»."""
        self.done.update({cop.index, subject.index} | {m.index for m in marks})
        subj_tokens, agr = self.phrase_node(subject.index, "N", role="subj")
        person, number = agr.person or 3, agr.number or "sg"
        form = gm.past("sein", person, number)[0] if cop.tag == "VBD" else gm.present("sein", person, number)[0]
        inner = self.clause(h, "zu", intro=[], skip={subject.index, cop.index} | {m.index for m in marks})
        self.notes.append("«… is to + инфинитив» → «… ist, … zu …»")
        if ctype == "main":
            return subj_tokens + [word(form, cop.index), punct(",")] + inner
        return subj_tokens + [word(form, cop.index), punct(",")] + inner

    def complement_clause(self, c: int) -> list[G]:
        """Дополнительное придаточное: that → dass, if/whether → ob, wh-слово — само."""
        marks = self.children(c, "mark")
        intro, ctype = self.subordinator(marks, c)
        w = self.w[c]
        if ctype == "zu" or (not marks and w.tag == "VB" and not self.children(c, *SUBJ)):
            return self.clause(c, "zu", intro=[])
        if not marks:
            wh = self._wh_word(c)
            if wh is not None:
                tokens, rest_skip = self.wh_intro(wh, c)
                return self.clause(c, "sub", intro=tokens, skip=rest_skip)
            intro = [word("dass")]
            self.notes.append("придаточное без союза → «dass»")
        return self.clause(c, ctype, intro=intro)

    def _wh_word(self, c: int) -> int | None:
        for k in self.children(c):
            if k.tag in {"WP", "WRB", "WDT", "WP$"} and k.index < c:
                return k.index
            for kk in self.children(k.index):
                if kk.tag in {"WP", "WRB", "WDT", "WP$"} and kk.index < c and kk.index < k.index + 3:
                    return kk.index
        return None

    def wh_intro(self, wh: int, c: int) -> tuple[list[G], set[int]]:
        word_ = self.w[wh]
        entry = self.lex.lookup(word_.lower, "ADV") if word_.tag == "WRB" else self.lex.lookup(word_.lower, "PRON")
        german = clean(entry.de) if entry else word_.text
        if word_.lower == "how" and self.rel(wh) == "advmod":
            parent = self.heads[wh]
            if parent != c and self.w[parent].upos in {"ADJ", "ADV"}:
                adj = self.choice(parent, self.w[parent].upos)
                self.mark(wh, DICT)
                self.mark(parent, DICT)
                return [word("wie", wh), word(clean(adj.de) if adj.entry else self.w[parent].text, parent)], {parent}
        if german == "wer" and self.rel(wh) == "obj":
            german = "wen"
        self.mark(wh, DICT)
        holder = wh if self.heads[wh] == c else self.heads[wh]
        return [word(german, wh)], {holder} if holder != wh else {wh}

    def clausal_subject(self, s: int) -> list[G]:
        w = self.w[s]
        if w.tag == "VBG":
            tokens, _ = self.gerund_noun(s, "N")
            return tokens
        marks = self.children(s, "mark")
        intro, ctype = self.subordinator(marks, s)
        if ctype == "zu":
            return self.clause(s, "zu") + [punct(",")]
        if not intro:
            wh = self._wh_word(s)
            if wh is not None:
                tokens, rest = self.wh_intro(wh, s)
                return self.clause(s, "sub", intro=tokens, skip=rest) + [punct(",")]
            intro = [word("dass")]
        return self.clause(s, ctype, intro=intro) + [punct(",")]

    def xcomp_part(self, x: int, h: int, gentry: Entry | None) -> Part:
        """Предикативное дополнение: инфинитив с to (→ zu) или признак (consider X important → als)."""
        w = self.w[x]
        if w.tag.startswith("VB") and not self.children(x, "cop"):
            if w.tag == "VBN" and not self.children(x, "mark"):
                tokens = self.participial(x)
                return Part(tokens, "pred", x)
            # seem/appear to — без запятой, «scheinen … zu»
            coherent = self.w[h].lemma.lower() in {"seem", "appear", "tend", "begin", "start", "continue", "try",
                                                   "fail", "use", "come"}
            tokens = self.clause(x, "zu")
            if coherent:
                return Part(tokens, "nachfeld", x)
            return Part([punct(",")] + tokens, "nachfeld", x, clause=True)
        cops = self.children(x, "cop")
        marks = [m for m in self.children(x, "mark") if m.lower == "to"]
        if cops and marks:
            # «is believed to be 1984» → «…, 1984 zu sein»: связка становится инфинитивом с zu
            for c in cops + marks:
                self.mark(c.index, DICT)
                self.done.add(c.index)
            tokens = self.predicate(x) + [word("zu sein", cops[0].index)]
            self.notes.append("«to be» + именная часть → «… zu sein»")
            return Part([punct(",")] + tokens, "nachfeld", x, clause=True)
        as_marker = gentry.props.get("xcomp") if gentry is not None else None
        cases = self.children(x, "case", "mark")
        if cases and cases[0].lower == "as":
            as_marker = "als"
            for c in cases:
                self.mark(c.index, DICT)
        tokens = self.predicate(x)
        if as_marker:
            tokens = [word(as_marker, self.w[h].index)] + tokens
        return Part(tokens, "pred", x)

    # ==================================================================================
    # сказуемое при связке, обстоятельства, наречия
    # ==================================================================================

    CLAUSE_LEVEL = {"nsubj", "nsubj:pass", "csubj", "csubj:pass", "nsubj:outer", "cop", "aux", "aux:pass", "mark",
                    "advcl", "ccomp", "xcomp", "parataxis", "expl", "discourse", "vocative", "obl", "obl:tmod",
                    "obl:npmod", "obl:unmarked", "obl:agent", "dislocated"}

    def predicate(self, i: int, negate: bool = False) -> list[G]:
        """Именная часть сказуемого при связке: «is a tragedy», «is important», «is in Denmark»."""
        w = self.w[i]
        exclude = {c.index for c in self.children(i) if self.rel(c.index) in self.CLAUSE_LEVEL}
        exclude |= {c.index for c in self.children(i) if c.index in self.done}
        exclude |= {c.index for c in self.children(i, "advmod") if c.lower in NEGATIONS}
        # «Why is the cache fast?», «Today the cache is fast» — обстоятельство всего предложения, не сказуемого
        cops = self.children(i, "cop")
        exclude |= {c.index for c in self.children(i, "advmod")
                    if c.tag == "WRB" or (cops and c.index < cops[0].index)}
        # однородные сказуемые со своим подлежащим или связкой — отдельные предложения
        for c in self.children(i, "conj"):
            if self.children(c.index, *SUBJ, "cop"):
                exclude.add(c.index)
                for cc in self.children(c.index, "cc"):
                    pass
        cases = [c for c in self.children(i, "case") if c.index not in exclude]
        if cases:
            return self.adverbial(i)
        if w.upos in {"ADJ"} or w.tag.startswith("JJ") or (w.tag in {"VBN", "VBG"} and not self.children(i, "det")):
            return self.adjective_phrase(i, None, "", "", "N", predicative=True, exclude=exclude)
        if w.upos == "ADV":
            return self.adverb_part(i, i).tokens
        tokens, _ = self.phrase_node(i, "N", exclude=exclude, negate=negate)
        return tokens

    def adverbial(self, i: int, *, prep_override: str | None = None, motion: bool = False, agent: bool = False,
                  main_subject: Agr | None = None) -> list[G]:
        """Обстоятельство или предложное дополнение: предлог + именная группа в нужном падеже."""
        w = self.w[i]
        cases = self.children(i, "case")
        if w.tag == "VBG" and not self.children(i, "aux"):
            if cases and cases[0].lower in {"by", "through"} and main_subject is not None:
                return self.gerund_clause(i, cases[:1], main_subject)
            tokens, _ = self.gerund_noun(i, "D")
            return tokens
        if not cases:
            if w.upos in {"ADV"}:
                return self.adverb_part(i, self.heads[i]).tokens
            tokens, _ = self.phrase_node(i, "A" if w.upos in {"NOUN", "PROPN", "NUM"} else "N")
            return tokens
        case_word = cases[0]
        for c in cases:
            self.mark(c.index, DICT)
        prep, gcase = self.preposition(case_word, i, prep_override, motion, agent)
        if prep == "":
            tokens, _ = self.phrase_node(i, gcase, skip_case=True)
            return tokens
        tokens, agr = self.phrase_node(i, gcase, skip_case=True)
        if w.lower in {"it", "this", "that", "them"} and w.tag in {"PRP", "DT"} and prep in DA_COMPOUND and \
                len(tokens) == 1:
            da = "dar" + prep if prep[0] in "aeiouäöü" else "da" + prep
            self.notes.append(f"«{case_word.lower} {w.lower}» → «{da}»")
            return [word(da, (case_word.index, i))]
        return self.attach_prep(prep, gcase, tokens, case_word.index)

    def attach_prep(self, prep: str, case: str, tokens: list[G], src: int | None = None) -> list[G]:
        src_t = (src,) if src is not None else ()
        if tokens and tokens[0].kind == "word" and (prep, tokens[0].text) in CONTRACTIONS:
            merged = CONTRACTIONS[(prep, tokens[0].text)]
            return [word(merged, src_t + tokens[0].src)] + tokens[1:]
        return [word(prep, src_t)] + tokens

    def preposition(self, case_word: Word, head: int, override: str | None, motion: bool,
                    agent: bool) -> tuple[str, str]:
        """Немецкий предлог и падеж для английского предлога в данном окружении."""
        lower = case_word.lower
        if override:
            prep, _, gcase = override.partition("+")
            return prep, gcase or "A"
        noun = self.w[head]
        if case_word.index in self.phrases:
            entry = self.phrases[case_word.index][0]
            return clean(entry.de), entry.props.get("case", "D")
        if lower == "by" and agent:
            return "von", "D"
        if lower == "by":
            if is_number(noun.text):
                return "bis", "A"
            parent = self.heads[head]
            if noun.upos == "PROPN" or (parent >= 0 and self.w[parent].upos in {"NOUN", "PROPN"}):
                return "von", "D"                      # «a novel by Jane Austen», «a play by Shakespeare»
            return "durch", "A"
        if lower == "in" and is_number(noun.text) and len(noun.text) == 4 and not self.children(head, "det"):
            return "", "N"
        if lower == "on" and noun.lemma.lower() in {"monday", "tuesday", "wednesday", "thursday", "friday",
                                                    "saturday", "sunday", "day", "date"}:
            return "an", "D"
        if lower == "on" and self.w[self.heads[head]].lemma.lower() in {"book", "essay", "article", "paper", "work",
                                                                        "study", "lecture", "report", "treatise",
                                                                        "chapter", "talk", "comment", "remark"}:
            return "über", "A"
        if lower == "to" and noun.upos == "PROPN":
            place = self.lex.lookup(noun.text, "PROPN", strict=True)
            if place is not None and place.gender == "n" and "article" not in place.props:
                return "nach", "D"
        entry = self.lex.lookup(lower, "ADP")
        if entry is None:
            return case_word.text, "D"
        prep = clean(entry.de)
        gcase = entry.props.get("case", "D")
        if prep in TWO_WAY and gcase == "D" and motion:
            gcase = "A"
        return prep, gcase

    def adverb_part(self, i: int, h: int) -> Part:
        w = self.w[i]
        self.done.add(i)
        if w.tag in {"WRB"} and self.rel(i) == "advmod":
            entry = self.lex.lookup(w.lower, "ADV")
            self.mark(i, DICT)
            return Part([word(clean(entry.de) if entry else w.text, i)], "adv", i)
        choice = self.choice(i, "ADV")
        mods = [c for c in self.children(i, "advmod") if c.index not in self.done]
        tokens: list[G] = []
        for m in mods:
            tokens += self.adverb_part(m.index, i).tokens
        if choice.entry is not None:
            text = clean(choice.entry.de)
            # «Also,» в начале предложения — не «also» (это «итак»), а «außerdem»
            if w.lower == "also" and i == 0:
                text = "außerdem"
            self.mark(i, choice.status)
            tokens.append(word(text, self.src(i), "rule" if choice.status == RULE else "word"))
        elif choice.status == NUMBER:
            self.mark(i, NUMBER)
            tokens.append(word(w.text, i, "number"))
        else:
            tokens.append(self.unknown(i))
        for c in self.children(i):
            if c.index in self.done or self.rel(c.index) in {"punct", "advmod"}:
                continue
            tokens += self.adverbial(c.index) if self.children(c.index, "case") else self.any_node(c.index)
        kind = "conn" if w.lower in MIDDLE_CONNECTORS else "adv"
        return Part(tokens, kind, i)

    # ==================================================================================
    # именная группа
    # ==================================================================================

    def phrase_node(self, i: int, case: str, *, role: str = "", exclude: set[int] | None = None,
                    negate: bool = False, skip_case: bool = False) -> tuple[list[G], Agr]:
        """Именная группа (или то, что стоит на её месте) в падеже case."""
        w = self.w[i]
        exclude = set(exclude or ())
        if not skip_case:
            cases = [c for c in self.children(i, "case") if c.index not in exclude]
            if cases and w.upos not in {"VERB"}:
                return self.adverbial(i), Agr()
        if w.tag in {"PRP", "EX", "WP", "PRP$"} or (w.upos == "PRON" and i not in self.phrases) or                 (w.tag in {"DT", "WDT"} and i not in self.phrases):
            return self.pronoun(i, case, role)
        if w.tag == "VBG" and not self.children(i, "aux", "aux:pass", "cop") and i not in self.phrases:
            return self.gerund_noun(i, case)
        if w.upos in {"VERB", "AUX"} and self.is_predicate(i) and i not in self.phrases and i not in self.done:
            return [punct(",")] + self.complement_clause(i) + [punct(",")], Agr()
        if w.upos == "ADJ" and not self.children(i, "det") and i not in self.phrases:
            return self.adjective_phrase(i, None, "", "", case, predicative=True, exclude=exclude), Agr()
        if w.upos == "ADJ" and i not in self.phrases and self.lex.lookup(w.lemma.lower(), "NOUN", strict=True) is None:
            return self.nominalized(i, case, exclude)
        if w.upos == "ADV" and i not in self.phrases:
            return self.adverb_part(i, self.heads[i]).tokens, Agr()
        if w.upos in {"ADP", "SCONJ", "CCONJ", "PART"} and i not in self.phrases and not self.children(i):
            choice = self.choice(i)
            self.mark(i, choice.status)
            return [word(clean(choice.entry.de) if choice.entry else w.text, i)], Agr()
        return self.noun_phrase(i, case, exclude=exclude, negate=negate)

    def pronoun(self, i: int, case: str, role: str = "") -> tuple[list[G], Agr]:
        w = self.w[i]
        lower = w.lower
        self.mark(i, DICT)
        if lower in {"a", "an", "the"}:
            return [], Agr()
        entry = self.lex.lookup(lower, "PRON")
        props = entry.props if entry else {}
        if "person" in props and "poss" not in props and "refl" not in props:
            person = int(props["person"])
            number = props.get("number", "sg")
            gender = props.get("gender", "")
            if lower in {"it"}:
                if self.rel(i) == "expl":
                    gender = "n"
                else:
                    gender = self.ctx.antecedent("sg")
            if lower == "one" and self.rel(i) not in SUBJ:
                return [word("einen" if case == "A" else "einem" if case == "D" else "man", i)], Agr(3, "sg", "m")
            if lower == "one":
                return [word("man", i)], Agr(3, "sg", "m")
            if lower in {"you"}:
                person, number = 2, "pl"
            text = gm.personal(person, number, gender or "n", case if case in "NADG" else "N")
            return [word(text, i)], Agr(person, number, gender or "n", human=lower not in {"it", "they", "them"})
        if "refl" in props:
            person = int(props.get("person", 3))
            number = props.get("number", "sg")
            if self.rel(i) in {"obj", "iobj"} or case in {"A", "D"}:
                return [word(gm.REFLEXIVE[(person, number)]["A" if case != "D" else "D"], i)], Agr(person, number)
            return [word("selbst", i)], Agr(person, number)
        if lower in {"this", "that", "these", "those"}:
            plural = lower in {"these", "those"}
            text = "diese" if plural else ("dies" if case in {"N", "A"} else "diesem")
            return [word(text, i)], Agr(3, "pl" if plural else "sg", "n")
        if lower in {"who", "whom", "what", "which"}:
            text = {"who": {"N": "wer", "A": "wen", "D": "wem", "G": "wessen"},
                    "whom": {"N": "wer", "A": "wen", "D": "wem", "G": "wessen"},
                    "what": {"N": "was", "A": "was", "D": "was", "G": "wessen"},
                    "which": {"N": "welches", "A": "welches", "D": "welchem", "G": "welches"}}[lower][case]
            return [word(text, i)], Agr()
        if entry is not None:
            text = clean(entry.de)
            if lower in {"others", "many", "several", "few", "both", "all", "most", "some"} or text in {"andere", "viele"}:
                agr = Agr(3, "pl")
                if case == "D" and text.endswith("e") and " " not in text:
                    text += "n"
            else:
                agr = Agr(3, "sg")
            tokens = [word(text, i)]
            # «one of the X», «some of the X», «each of them»
            tokens += self.post_modifiers(i, case, Agr(3, "pl"), set())
            return tokens, agr
        return [self.unknown(i)], Agr()

    def gerund_noun(self, i: int, case: str) -> tuple[list[G], Agr]:
        """Герундий как существительное: «translating texts» → «das Übersetzen von Texten»."""
        w = self.w[i]
        self.done.add(i)
        choice = self.choice(i, "VERB")
        if choice.entry is None:
            noun_choice = self.choice(i, "NOUN")
            if noun_choice.entry is not None:
                return self.noun_phrase(i, case)
            return [self.unknown(i)], Agr()
        verb = clean(choice.entry.de).removeprefix("sich ").split()[-1]
        noun = gm.infinitive(verb)
        noun = noun[:1].upper() + noun[1:]
        gen = noun + "s" if case == "G" else noun
        self.mark(i, choice.status)
        self.notes.append(f"герундий «{w.text}» → «das {noun}»")
        det = {"N": "das", "A": "das", "D": "dem", "G": "des"}[case]
        tokens: list[G] = []
        adjectives = []
        for c in self.children(i, "advmod"):
            if c.index in self.done:
                continue
            adj = self.choice(c.index, "ADV")
            self.mark(c.index, adj.status if adj.entry else UNKNOWN)
            if adj.entry:
                adjectives.append(word(gm.adjective_form(clean(adj.entry.de), "pos", gm.WEAK, "n", "sg", case), c.index))
        tokens = [word(det, i)] + adjectives + [word(gen, i, noun=True)]
        for o in self.children(i, "obj"):
            dets = self.children(o.index, "det", "nmod:poss")
            if dets and dets[0].lower not in {"a", "an", "some", "any"}:
                more, _ = self.phrase_node(o.index, "G")
                tokens += more
            else:
                more, _ = self.phrase_node(o.index, "D")
                tokens += [word("von", o.index)] + more
        for c in self.children(i):
            if c.index in self.done or self.rel(c.index) in {"punct", "case", "mark", "aux"}:
                continue
            if self.rel(c.index).startswith("obl") or self.children(c.index, "case"):
                tokens += self.adverbial(c.index)
            else:
                tokens += self.any_node(c.index)
        return tokens, Agr(3, "sg", "n")

    # ------------------------------------------------------------------------------------------

    def noun_entry(self, i: int) -> tuple[Choice, str]:
        """Словарная статья существительного; для «the Creature» и подобных — нарицательное."""
        w = self.w[i]
        if i in self.phrases:
            return self.choice(i), "phrase"
        if w.upos == "NUM" or (w.tag == "CD" and not is_number(w.text)):
            num = self.lex.lookup(w.lower, "NUM", strict=True)
            if num is not None:
                return Choice(num, DICT, w.lower), "number-word"
        if w.tag in {"NN", "NNS"} and w.lower in {"nothing", "something", "everything", "anything", "others",
                                                 "everyone", "someone", "nobody", "none"}:
            pron = self.lex.lookup(w.lower, "PRON", strict=True)
            if pron is not None:
                return Choice(pron, DICT, w.lower), "pronoun"
        choice = self.choice(i, "NOUN" if w.upos not in {"PROPN"} else "PROPN")
        if choice.status == UNKNOWN and w.text in self.ctx.proper:
            return Choice(None, NAME, w.text), "name"
        if choice.status == NAME and self.children(i, "det") and w.tag.startswith("NNP"):
            alt = self.lex.lookup(w.lemma.lower(), "NOUN", strict=True)
            if alt is not None:
                return Choice(alt, DICT, w.lemma.lower()), "common"
        if w.upos == "NUM" and choice.status == DICT:
            return choice, "number-word"
        return choice, ""

    def noun_phrase(self, i: int, case: str, *, exclude: set[int] | None = None,
                    negate: bool = False, article: bool = False, female: bool = False) -> tuple[list[G], Agr]:
        w = self.w[i]
        exclude = set(exclude or ())
        self.done.add(i)
        choice, how = self.noun_entry(i)
        entry = choice.entry
        kids = [c for c in self.children(i) if c.index not in exclude and c.index not in self.done]

        # --- число, имя, перевод ------------------------------------------------------------
        if choice.status == NUMBER or (w.tag == "CD" and entry is None):
            self.mark(i, NUMBER)
            text = self.number_text(w.text)
            tokens = [word(text, i, "number")]
            tokens += self.post_modifiers(i, case, Agr(3, "pl"), exclude)
            conj_tokens, _ = self.noun_coordination(i, case, exclude)
            return self.wrap(i, tokens + conj_tokens), Agr(3, "pl")
        if w.upos == "NUM" and entry is not None and entry.pos == "NUM" and not self.children(i, "det"):
            self.mark(i, DICT)
            text = clean(entry.de)
            if text == "eins":
                of = [c for c in self.children(i, "nmod") if any(x.lower == "of" for x in self.children(c.index, "case"))]
                inner = self.noun_entry(of[0].index)[0].entry if of else None
                g = inner.gender if inner is not None and inner.gender in {"m", "f", "n"} else self.ctx.antecedent()
                text = {"m": {"N": "einer", "A": "einen", "D": "einem", "G": "eines"},
                        "f": {"N": "eine", "A": "eine", "D": "einer", "G": "einer"},
                        "n": {"N": "eines", "A": "eines", "D": "einem", "G": "eines"}}[g][case]
            tokens = [word(text, i)]
            tokens += self.post_modifiers(i, case, Agr(3, "pl"), exclude)
            return self.wrap(i, tokens), Agr(3, "pl")

        if w.lemma.lower() == "one" and w.tag in {"NN", "NNS"} and i not in self.phrases:
            return self.proform(i, case, w.tag == "NNS", exclude)

        plural_en = w.tag in {"NNS", "NNPS"} or bool(re.fullmatch(r"[A-Z]{2,}s", w.text))   # «CPUs»
        if entry is not None:
            german = entry.de
            gender = entry.gender if entry.gender in {"m", "f", "n", "pl"} else "n"
            plural = entry.plural_form
            weak = "weak" in entry.props
            gen_form = entry.props.get("gen", "")
            if entry.pos == "PROPN" and not gen_form and " " not in clean(german):
                gen_form = self.genitive_name(clean(german))
            name = False
            status = choice.status
        elif choice.status == NAME:
            german = w.text if i not in self.phrases else self.text_of(i)
            gender = self.ctx.names.get(w.text, "n")
            plural, weak, gen_form, name = "", False, "", True
            status = NAME
            # части имени: «William Shakespeare», «Michel de Montaigne», «Pico della Mirandola»
            parts = [c for c in kids if self.rel(c.index) in {"flat", "flat:name"} or
                     (self.rel(c.index) in {"compound", "nmod:desc"} and c.tag.startswith("NNP") and c.index < i)]
            if parts:
                chain = sorted([i] + [c.index for c in parts] +
                               [g.index for c in parts for g in self.children(c.index, "flat", "compound")])
                for c in chain:
                    if c != i:
                        self.mark(c, NAME)
                        self.done.add(c)
                titles = [c for c in chain if c < i and self.w[c].lower in MALE_TITLES | FEMALE_TITLES]
                for t in titles:
                    gender = "m" if self.w[t].lower in MALE_TITLES else "f"
                pieces = []
                for c in chain:
                    title_entry = self.lex.lookup(self.w[c].lower, "PROPN", strict=True) if c in titles else None
                    pieces.append(clean(title_entry.de) if title_entry else self.w[c].text)
                german = " ".join(pieces)
                full = " ".join(self.w[c].text for c in chain)
                gender = self.ctx.names.get(full, self.ctx.names.get(self.w[chain[-1]].text, gender))
                name_src = tuple(chain)
            else:
                name_src = self.src(i)
            roles = [c for c in kids if self.rel(c.index) in {"compound", "nmod:desc", "amod"} and c.index < i
                     and c.index not in self.done and (
                         c.tag in {"NN", "NNS"} or
                         # «scholar Roger Pearson»: теггер счёл роль прилагательным
                         c.tag == "JJ" and self.lex.lookup(c.lower, "ADJ", strict=True) is None
                         and self.lex.lookup(c.lower, "NOUN", strict=True) is not None)]
            if roles:
                first = self.w[min(name_src)].text
                female = self.ctx.names.get(first) == "f" or first.lower() in FEMALE_NAMES
                role_tokens = []
                for role in roles:
                    if role.tag == "JJ":
                        role_tokens += self.role_noun(role.index, case, female)
                        continue
                    more, role_agr = self.noun_phrase(role.index, case, article=True, female=female)
                    role_tokens += more
                self.role_prefix = role_tokens
            # имя человека: род по местоимениям не узнать — мужской род для артикля не нужен
        else:
            german = None
            gender, plural, weak, gen_form, name = "n", "", False, "", False
            status = UNKNOWN

        number = "pl" if (plural_en or gender == "pl") else "sg"
        if number == "pl" and entry is not None and entry.plural == "-" and gender != "pl":
            number = "sg"
        # существительное-роль перед именем: «author Jane Austen», «writer George Orwell», «editor Maxwell Perkins»
        role_name = None
        if entry is not None and entry.pos == "NOUN" and number == "sg" and not self.children(i, "det", "nmod:poss"):
            role_name = next((c for c in self.children(i, "appos", "flat", "compound")
                              if c.index == i + 1 and c.tag.startswith("NNP")), None)
        if (role_name is not None or female) and gender == "m" and german and " " not in german:
            if role_name is not None:
                first = self.w[role_name.index].text
                full = " ".join(self.w[k].text for k in self.span(role_name.index) if self.w[k].tag.startswith("NNP"))
                female = self.ctx.names.get(full, self.ctx.names.get(first)) == "f" or first.lower() in FEMALE_NAMES
            if female and re.search(r"(or|er|ist|ent|ant|at|eur|ent)$", german):
                german, gender, plural, weak = german + "in", "f", german + "innen", False
                self.notes.append(f"женский род по имени: {german}")
        if any(self.rel(c.index) == "nummod" and c.lower not in {"one", "1"} for c in kids) and gender != "pl" \
                and entry is not None and entry.plural not in {"-"}:
            number = "pl"

        # --- зависимые ----------------------------------------------------------------------------
        dets = [c for c in kids if self.rel(c.index) in {"det", "det:predet"}]
        poss = [c for c in kids if self.rel(c.index) == "nmod:poss"]
        # прилагательное после существительного («the resources available», «a component responsible
        # for X») в немецком встаёт перед ним, со своими дополнениями: «eine für X verantwortliche Komponente»
        amods = [c for c in kids if self.rel(c.index) == "amod"]
        post_amods: list[Word] = []
        compounds = [c for c in kids if self.rel(c.index) in {"compound", "flat"} and c.index < i
                     and not (choice.status == NAME and (c.tag.startswith("NNP") or c.lower in MALE_TITLES | FEMALE_TITLES))]
        nummods = [c for c in kids if self.rel(c.index) == "nummod"]
        pre_adv = [c for c in kids if self.rel(c.index) == "advmod" and c.index < i]

        # --- определитель ---------------------------------------------------------------------------
        det_kind, det_stem, det_src, extra_adj = "none", "", (), ""
        predet_tokens: list[G] = []
        for d in dets:
            lower = d.lower
            self.mark(d.index, DICT)
            if self.rel(d.index) == "det:predet" or (lower in {"all", "both", "half", "such"} and len(dets) > 1):
                if lower == "such":
                    extra_adj = "solch"
                else:
                    text = {"all": "all", "both": "beid", "half": "halb"}.get(lower, lower)
                    predet_tokens.append(word(text, d.index))
                continue
            entry_d = self.lex.lookup(lower, "DET", strict=True)
            props = entry_d.props if entry_d else {}
            kind = props.get("kind", "none")
            det_src = (d.index,)
            if kind in {"def", "indef"}:
                det_kind = kind
                if "adj" in props:
                    extra_adj = props["adj"]
            elif kind in {"der", "ein"}:
                det_kind, det_stem = kind, props.get("stem", "")
                if lower == "any" and negate:
                    det_kind, det_stem = "ein", "kein"
                if lower in {"any", "some"} and number == "pl":
                    det_kind, det_stem = "none", ""
            elif kind == "adj":
                det_kind = "none"
                extra_adj = props.get("stem", "")
                if lower == "some" and number == "sg":
                    det_kind, det_stem = "word", "etwas"
            else:
                det_kind = "def" if lower == "the" else "none"
        if predet_tokens and det_kind == "def":
            det_kind = "der-all"
        for p in poss:
            if p.tag in {"PRP$", "PRP", "WP$"}:
                self.mark(p.index, DICT)
                det_kind, det_stem = "ein", self.possessive_stem(p)
                det_src = (p.index,)
        if negate and det_kind in {"indef", "none"} and not name:
            det_kind, det_stem = "ein", "kein"
            negate = False
        if (role_name is not None or article) and det_kind == "none" and not pre_adv_role(self, i):
            det_kind = "def"
        # «most computers» → «die meisten Computer»: превосходная степень требует артикля
        if det_kind == "none" and any(c.lower == "most" and self.rel(c.index) == "amod" for c in kids):
            det_kind = "def"
        if det_kind == "indef" and number == "pl":
            det_kind = "none"

        # --- определители-числа и количества ------------------------------------------------------
        num_tokens: list[G] = []
        for nm in nummods:
            if nm.index in self.done:
                continue
            self.done.add(nm.index)
            nchoice = self.choice(nm.index, "NUM")
            if nchoice.entry is not None and not is_number(nm.text):
                text = clean(nchoice.entry.de)
                if text == "eins":
                    text = gm.determiner("indef", gender, "sg", case)
                self.mark(nm.index, DICT)
                num_tokens.append(word(text, nm.index))
            else:
                self.mark(nm.index, NUMBER)
                num_tokens.append(word(self.number_text(nm.text), nm.index, "number"))

        # --- притяжательный падеж: «Hamlet's father» ----------------------------------------------
        pre_genitive: list[G] = []
        post_genitive: list[G] = []
        for p in poss:
            if p.tag in {"PRP$", "PRP", "WP$"}:
                continue
            for c in self.children(p.index, "case"):
                self.mark(c.index, DICT)
            if self.w[p.index].tag.startswith("NNP") and not self.children(p.index, "det"):
                name_tokens = self.proper_genitive(p.index)
                pre_genitive += name_tokens
                det_kind = "none" if det_kind in {"none", "def"} else det_kind
                det_src = ()
            else:
                more, _ = self.phrase_node(p.index, "G", skip_case=True)
                post_genitive += more
                if det_kind == "none":
                    det_kind = "def"

        # --- сложное слово из существительных-определений --------------------------------------------
        compound_parts: list[str] = []
        hoisted: list[Word] = []
        compound_src: list[int] = []
        for c in compounds:
            if c.index in self.done:
                continue
            part, adjs = self.compound_modifier(c.index)
            if part is None:
                continue
            if part:
                compound_parts.append(part)
            hoisted += adjs
            compound_src += self.span(c.index)
        if compound_parts and german is not None:
            self.notes.append("сложное слово: " + " + ".join(compound_parts + [clean(german)]))

        # --- склонение главного слова --------------------------------------------------------------
        head_tokens: list[G]
        if german is None:
            head_tokens = [self.unknown(i)]
            if compound_parts:
                head_tokens = [word("-".join(compound_parts) + "-" + w.text, tuple(compound_src) + (i,), "unknown")]
            noun_text = w.text
        elif name and not entry:
            self.mark(i, NAME)
            text = german
            role_prefix = getattr(self, "role_prefix", None)
            self.role_prefix = None
            if case == "G" and det_kind == "none" and not role_prefix:
                text = self.genitive_name(text)
            head_tokens = (role_prefix or []) + [word(text, name_src, "name", keep_case=True)]
            noun_text = text
        else:
            self.mark(i, status)
            adj_inline, noun_lemma, tail = self.split_phrase(german)
            if len(german.split()) > 1 and not adj_inline and "~" not in german:
                noun_lemma, tail = german, ""
            form = gm.noun_form(noun_lemma, gender, plural if number == "pl" else plural, number, case, weak,
                                gen_form)
            if number == "pl" and plural:
                form = gm.noun_form(noun_lemma, gender, plural, "pl", case)
            if compound_parts:
                form = gm.compound(compound_parts, form)
            kind = "rule" if status == RULE else ("name" if entry and entry.pos == "PROPN" and
                                                  " " not in clean(entry.de) and gender == "n" else "word")
            is_noun = entry is None or entry.pos in {"NOUN", "PROPN", "NUM"}
            head_tokens = [word(form, tuple(compound_src) + self.src(i), kind, noun=is_noun and form[:1].isalpha()
                                and not form[:1].isdigit())]
            if tail:
                head_tokens.append(word(tail, self.src(i)))
            noun_text = form
            if adj_inline:
                hoisted_inline = adj_inline
            else:
                hoisted_inline = []
        if german is None or (name and not entry):
            hoisted_inline = []

        agr = Agr(3, number, gender if gender != "pl" else "n", human=name)
        if german is not None and not name:
            self.ctx.remember(gender if gender != "pl" else "n", number)
        if det_kind == "none" and entry is not None and "article" in entry.props:
            det_kind = "def"

        # --- артикль и прилагательные -------------------------------------------------------------
        table = gm.adjective_table({"der-all": "der"}.get(det_kind, det_kind)) if det_kind != "word" else gm.STRONG_ADJ
        if num_tokens and det_kind == "none":
            table = gm.STRONG_ADJ
        if predet_tokens and det_kind in {"none", "der-all"}:
            table = gm.WEAK
        tokens: list[G] = []
        for p in pre_adv:
            tokens += self.adverb_part(p.index, i).tokens
        for t in predet_tokens:
            tokens.append(t.copy(text=t.text + gm.DER_ENDINGS["pl" if number == "pl" else gm.key(gender, number)][case]))
        if det_kind == "def" and not predet_tokens:
            tokens.append(word(gm.determiner("def", gender, number, case), det_src))
        elif det_kind == "indef":
            tokens.append(word(gm.determiner("indef", gender, number, case), det_src))
        elif det_kind in {"der", "ein"}:
            tokens.append(word(gm.determiner(det_kind, gender, number, case, det_stem), det_src))
        elif det_kind == "word":
            tokens.append(word(det_stem, det_src))
        tokens += pre_genitive
        tokens += num_tokens
        if extra_adj:
            tokens.append(word(gm.adjective_form(extra_adj, "pos", table, gender, number, case), det_src))
        # порядок как в английском: свои определения, затем прилагательные из составного слова
        # («the first statistical machine translation software» → «die erste statistische maschinelle …»)
        for a in amods:
            if a is None or a.index in self.done:
                continue
            tokens += self.adjective_phrase(a.index, table, gender, number, case)
        for a in hoisted:
            tokens += self.adjective_phrase(a if isinstance(a, _FakeAdjective) else a.index, table, gender, number,
                                            case)
        for adj in hoisted_inline:
            tokens.append(word(gm.adjective_form(adj, "pos", table, gender, number, case), self.src(i)))
        # «Echtzeit-», «Source-to-Source-»: прилагательное-приставка пишется слитно с существительным
        while tokens and tokens[-1].text.endswith("-") and head_tokens and head_tokens[0].kind != "unknown":
            prefix = tokens.pop()
            head = head_tokens[0]
            head_tokens[0] = head.copy(text=prefix.text + head.text, src=prefix.src + head.src)
        tokens += head_tokens
        tokens += post_genitive
        for a in post_amods:
            if a.index not in self.done:
                tokens += self.adjective_phrase(a.index, None, gender, number, case, predicative=True)
        tokens += self.post_modifiers(i, case, agr, exclude)
        # однородные члены
        conj_tokens, plural_conj = self.noun_coordination(i, case, exclude)
        if plural_conj:
            agr = Agr(3, "pl", agr.gender)
        tokens = self.wrap(i, tokens + conj_tokens)
        # союз при слове, которое анализатор не связал с первым членом: «… or operating system»
        ccs = [c for c in self.children(i, "cc") if c.index < i and c.index not in self.done
               and self.rel(i) != "conj"]
        if ccs:
            coordinator = self.coordinator(ccs[0], False)
            self.mark(ccs[0].index, DICT)
            tokens = [word(coordinator, ccs[0].index)] + tokens
        return tokens, agr

    def role_noun(self, i: int, case: str, female: bool) -> list[G]:
        """Роль перед именем с ошибочным тегом прилагательного: «scholar» → «der Wissenschaftler»."""
        entry = self.lex.lookup(self.w[i].lower, "NOUN", strict=True)
        self.mark(i, DICT)
        self.done.add(i)
        german, gender, plural = clean(entry.de), entry.gender or "m", entry.plural_form
        if female and gender == "m" and re.search(r"(or|er|ist|ent|ant|at|eur)$", german):
            german, gender, plural = german + "in", "f", german + "innen"
        noun = gm.noun_form(german, gender, plural, "sg", case, "weak" in entry.props)
        return [word(gm.determiner("def", gender, "sg", case), i), word(noun, i, noun=True)]

    def nominalized(self, i: int, case: str, exclude: set[int]) -> tuple[list[G], Agr]:
        """Прилагательное в роли существительного: «the other» → «der andere», «the poor» → «die Armen»."""
        w = self.w[i]
        gender = "n"
        number = "pl" if w.lower.endswith("s") and w.tag != "JJ" else "sg"
        tokens: list[G] = []
        kind = "none"
        for d in self.children(i, "det"):
            self.mark(d.index, DICT)
            kind = "def" if d.lower == "the" else "indef" if d.lower in {"a", "an"} else "der"
            text = gm.determiner(kind, gender, number, case, "dies") if kind == "der" else \
                gm.determiner(kind, gender, number, case)
            if text:
                tokens.append(word(text, d.index))
        table = gm.adjective_table(kind)
        adjective = self.adjective_phrase(i, table, gender, number, case)
        if adjective:
            last = adjective[-1]
            adjective[-1] = last.copy(noun=True) if w.lower not in {"other", "others", "same"} else last
        tokens += adjective
        tokens += self.post_modifiers(i, case, Agr(3, number, gender), exclude)
        return tokens, Agr(3, number, gender)

    def proform(self, i: int, case: str, plural: bool, exclude: set[int]) -> tuple[list[G], Agr]:
        """«the one on which…» → «das, auf dem…», «higher-level ones» → «höhere»: существительное опускается."""
        number = "pl" if plural else "sg"
        gender = self.ctx.antecedent(number) if number == "sg" else "n"
        self.mark(i, DICT)
        tokens: list[G] = []
        dets = [c for c in self.children(i, "det") if c.index not in self.done]
        kind = "none"
        for d in dets:
            self.mark(d.index, DICT)
            kind = "def" if d.lower == "the" else "indef" if d.lower in {"a", "an"} else "der"
            if kind == "der":
                tokens.append(word(gm.determiner("der", gender, number, case, "dies"), d.index))
            else:
                text = gm.determiner(kind, gender, number, case)
                if text:
                    tokens.append(word(text, d.index))
        table = gm.adjective_table(kind)
        for a in self.children(i, "amod"):
            tokens += self.adjective_phrase(a.index, table, gender, number, case)
        if not tokens:
            tokens = [word({"N": "einer", "A": "einen", "D": "einem", "G": "eines"}[case], i)]
        tokens += self.post_modifiers(i, case, Agr(3, number, gender), exclude)
        self.notes.append("«one» как заместитель существительного опущено")
        return tokens, Agr(3, number, gender)

    def split_phrase(self, german: str) -> tuple[list[str], str, str]:
        """«neuronal* Netz» → ([neuronal], Netz, ''); «Stand~ der Technik» → ([], Stand, 'der Technik')."""
        words = german.split()
        adjectives = [x[:-1] for x in words if x.endswith("*")]
        rest = [x for x in words if not x.endswith("*")]
        if any(x.endswith("~") for x in rest):
            k = next(n for n, x in enumerate(rest) if x.endswith("~"))
            return adjectives, " ".join(rest[:k + 1]).replace("~", ""), " ".join(rest[k + 1:])
        return adjectives, " ".join(rest), ""

    def compound_modifier(self, c: int) -> tuple[str | None, list[Word]]:
        """Существительное-определение → первая часть немецкого сложного слова."""
        w = self.w[c]
        self.done.add(c)
        hoisted = [a for a in self.children(c, "amod") if a.index not in self.done]
        inner: list[str] = []
        for cc in self.children(c, "compound"):
            part, more = self.compound_modifier(cc.index)
            if part:
                inner.append(part)
            hoisted += more
        choice, how = self.noun_entry(c)
        adjective = self.lex.lookup(w.lower, "ADJ", strict=True)
        if adjective is not None and w.tag.startswith("NNP") and choice.entry is not None and choice.entry.pos == "PROPN":
            choice = Choice(adjective, DICT, w.lower)
        if choice.entry is None or choice.status not in {DICT, RULE}:
            alt = self.lex.lookup(w.lower, "ADJ", strict=True)
            if alt is not None:
                choice = Choice(alt, DICT, w.lower)
        if choice.entry is not None and choice.entry.pos in {"NOUN", "PROPN"}:
            adjectives, noun, tail = self.split_phrase(choice.entry.de)
            if tail or " " in noun:
                self.mark(c, choice.status)
                return noun.replace(" ", "-"), hoisted
            self.mark(c, choice.status)
            part = gm.compound_part(noun, choice.entry.gender, choice.entry.props.get("cf", ""))
            if adjectives:
                # «maschinell* Übersetzung» + System → «maschinelles Übersetzungssystem»
                for adj in adjectives:
                    hoisted.append(_FakeAdjective(adj, c))
            return gm.compound(inner, part) if inner else part, hoisted
        if choice.entry is not None and choice.entry.pos == "ADJ":
            self.mark(c, choice.status)
            hoisted.append(_FakeAdjective(clean(choice.entry.de), c))
            return "", hoisted
        if is_number(w.text) or w.tag == "CD":
            self.mark(c, NUMBER)
            return w.text + "-", hoisted
        if choice.status == NAME or w.text.isupper():
            self.mark(c, NAME)
            return w.text + "-", hoisted
        self.mark(c, UNKNOWN)
        self.ctx.unknown.append((w.lemma.lower(), "NOUN", self.s.text))
        return w.text + "-", hoisted

    def adjective_phrase(self, a, table, gender: str, number: str, case: str, *, predicative: bool = False,
                         exclude: set[int] | None = None) -> list[G]:
        """Прилагательное с зависимыми: «very fast» → «sehr schnell», «more efficient» → «effizienter»."""
        if isinstance(a, _FakeAdjective):
            return [word(gm.adjective_form(a.text, "pos", table, gender, number, case), a.src)]
        w = self.w[a]
        self.done.add(a)
        exclude = set(exclude or ())
        degree = "comp" if w.tag in {"JJR", "RBR"} else "sup" if w.tag in {"JJS", "RBS"} else "pos"
        if w.lower in {"most", "least", "more", "less", "fewer"}:
            degree = "pos"                       # в словаре уже сама форма степени: meist, mehr, weniger
        tokens: list[G] = []
        for m in self.children(a, "advmod"):
            if m.index in exclude or m.index in self.done:
                continue
            if m.lower in {"more", "most"} and degree == "pos":
                degree = "comp" if m.lower == "more" else "sup"
                self.mark(m.index, DICT)
                continue
            if m.lower in {"less"}:
                self.mark(m.index, DICT)
                tokens.append(word("weniger", m.index))
                continue
            tokens += self.adverb_part(m.index, a).tokens
        # дополнения прилагательного: «responsible for X» → «für X verantwortlich»
        for c in self.children(a):
            if c.index in exclude or c.index in self.done or self.rel(c.index) in {"advmod", "punct", "cop", "conj",
                                                                                   "cc", "case"}:
                continue
            if self.rel(c.index) in self.CLAUSE_LEVEL - {"obl", "obl:npmod", "obl:tmod", "obl:unmarked"}:
                continue
            if self.children(c.index, "case"):
                entry = self.choice(a, "ADJ").entry
                prep = entry.props.get("prep") if entry else None
                if prep and prep.startswith("+"):
                    more, _ = self.phrase_node(c.index, prep[1:], skip_case=True)
                    for x in self.children(c.index, "case"):
                        self.mark(x.index, DICT)
                    tokens += more
                else:
                    tokens += self.adverbial(c.index, prep_override=prep)
            elif self.rel(c.index) in {"xcomp", "ccomp", "advcl"}:
                continue
            else:
                tokens += self.any_node(c.index)
        if w.tag in {"VBN", "VBG"} and a not in self.phrases:
            choice = self.choice(a, "ADJ")
            if choice.entry is not None and choice.entry.pos == "VERB":
                verb = clean(choice.entry.de).removeprefix("sich ").split()[-1]
                base = gm.participle(verb) if w.tag == "VBN" else gm.infinitive(verb) + "d"
                self.mark(a, choice.status)
                text = base if table is None else gm.adjective_form(base, "pos", table, gender, number, case)
                return tokens + [word(text, a)]
        else:
            choice = self.choice(a, "ADJ")
        head = self.heads[a]
        if w.lower == "little" and head >= 0 and self.w[head].tag == "NN" and self.deprels[head] != "compound" and                 not any(self.deprels[k] in {"det", "nmod:poss"} for k in self.kids[head]):
            # «very little privacy» — количество, а не размер: «sehr wenig Privatsphäre»
            self.mark(a, DICT)
            self.notes.append("«little» при неисчисляемом существительном → «wenig»")
            return tokens + [word("wenig", a)]
        if choice.entry is not None:
            german = clean(choice.entry.de)
            if choice.entry.pos == "VERB":
                verb = german.removeprefix("sich ").split()[-1]
                german = gm.participle(verb) if w.lower.endswith("ed") else gm.infinitive(verb) + "d"
            elif choice.entry.pos == "NOUN" and table is not None and " " not in german:
                # «desktop computers»: существительное, принятое за прилагательное, — часть сложного слова
                german = gm.compound_part(german, choice.entry.gender) + "-"
            self.mark(a, choice.status)
            if german.endswith("-"):
                text = german
            elif table is None:
                text = gm.adjective_form(german, degree, None, gender, number, case)
            else:
                text = gm.adjective_form(german, degree, table, gender, number, case)
            tokens.append(word(text, self.src(a), "rule" if choice.status == RULE else "word"))
        elif choice.status == NUMBER or is_number(w.text):
            self.mark(a, NUMBER)
            tokens.append(word(self.number_text(w.text), a, "number"))
        else:
            tokens.append(self.unknown(a))
        # однородные прилагательные: «fast and efficient»
        for c in self.children(a, "conj"):
            if c.index in self.done:
                continue
            for cc in self.children(c.index, "cc"):
                text = self.coordinator(cc, self._negated_clause(a))
                self.mark(cc.index, DICT)
                if text in {"aber", "sondern", "doch"}:
                    tokens.append(punct(","))
                tokens.append(word(text, cc.index))
            if not self.children(c.index, "cc"):
                tokens.append(punct(","))
            tokens += self.adjective_phrase(c.index, table, gender, number, case, predicative=predicative)
        return tokens

    def post_modifiers(self, i: int, case: str, agr: Agr, exclude: set[int]) -> list[G]:
        """Определения после существительного: of-родительный, предложные, придаточные, приложение."""
        tokens: list[G] = []
        for c in self.children(i):
            if c.index in self.done or c.index in exclude:
                continue
            r = self.rel(c.index)
            if r in {"nmod", "nmod:unmarked", "nmod:tmod", "nmod:npmod", "nmod:desc", "obl"}:
                tokens += self.noun_modifier(c.index)
            elif r == "acl:relcl":
                tokens += [punct(",")] + self.relative_clause(c.index, i, agr) + [punct(",")]
            elif r == "acl":
                tokens += self.reduced_relative(c.index, i, agr)
            elif r == "appos":
                more, _ = self.phrase_node(c.index, case)
                comma_before = any(x.text in {",", "—", "–", "-", ":"} for x in self.children(c.index, "punct")
                                   if x.index < c.index) or (c.index > 0 and self.w[c.index - 1].text == "," and
                                                             self.w[c.index - 1].index not in self.done)
                if more and more[0].text in BRACKETS or not comma_before and self.span(c.index)[0] == i + 1:
                    tokens += more
                else:
                    tokens += [punct(",")] + more + [punct(",")]
            elif r in {"amod"} and c.index > i:
                tokens += self.adjective_phrase(c.index, None, agr.gender, agr.number, case, predicative=True)
            elif r in {"advmod"}:
                tokens += self.adverb_part(c.index, i).tokens
            elif r in {"conj", "cc", "punct", "case", "det", "det:predet", "nmod:poss", "compound", "flat", "amod",
                       "nummod", "fixed"}:
                continue
            elif r in {"advcl", "ccomp", "xcomp", "parataxis", "dep", "list", "orphan", "discourse", "dislocated",
                       "vocative", "reparandum", "goeswith", "mark", "cop", "aux", "aux:pass", "expl"} or r in SUBJ:
                if self.is_predicate(c.index):
                    tokens += [punct(",")] + (self.clause(c.index, "main") if not self.children(c.index, "mark")
                                              else self.complement_clause(c.index))
                else:
                    tokens += self.any_node(c.index)
        return tokens

    def noun_modifier(self, c: int) -> list[G]:
        """Несогласованное определение: of → Genitiv или von; прочие предлоги — как обстоятельство."""
        cases = self.children(c, "case")
        if cases and cases[0].lower == "of" and (c not in self.phrases or self.phrases[c][0].pos in {"NOUN", "PROPN"}):
            self.mark(cases[0].index, DICT)
            w = self.w[c]
            if w.tag == "VBG":
                tokens, _ = self.gerund_noun(c, "G")
                return tokens
            dets = self.children(c, "det", "nmod:poss")
            bare = not dets and w.tag in {"NN", "NNS"} and not self.children(c, "nummod")
            pronoun = w.tag in {"PRP", "DT", "WP", "WDT", "CD"} or w.upos == "PRON"
            if pronoun or bare or (w.tag.startswith("NNP") and self.lex.lookup(w.text, "PROPN", strict=True) is None
                                   and not dets):
                tokens, _ = self.phrase_node(c, "D", skip_case=True)
                return [word("von", cases[0].index)] + tokens
            tokens, _ = self.phrase_node(c, "G", skip_case=True)
            self.notes.append("«of» → Genitiv")
            return tokens
        return self.adverbial(c)

    POSSESSIVE_STEMS = {"my": "mein", "your": "Ihr", "his": "sein", "her": "ihr", "our": "unser", "their": "ihr",
                        "whose": "dessen", "one's": "sein", "thy": "dein"}

    def possessive_stem(self, p: Word) -> str:
        lower = p.lower
        if lower == "its":
            gender = self.ctx.antecedent("sg")
            return "ihr" if gender == "f" else "sein"
        return self.POSSESSIVE_STEMS.get(lower, lower)

    def proper_genitive(self, p: int) -> list[G]:
        """«Hamlet's» → «Hamlets», «Claudius's» → «Claudius'»."""
        tokens: list[G] = []
        for c in self.children(p, "compound", "flat"):
            self.mark(c.index, NAME)
            tokens.append(word(self.w[c.index].text, c.index, "name", keep_case=True))
        self.mark(p, NAME)
        choice = self.choice(p, "PROPN")
        text = clean(choice.entry.de) if choice.entry else self.w[p].text
        if choice.entry is not None and choice.entry.gender in {"m", "n"}:
            genitive = gm.noun_form(text, choice.entry.gender, None, "sg", "G")
        else:
            genitive = self.genitive_name(text)
        tokens.append(word(genitive, self.src(p), "name", keep_case=True))
        self.notes.append(f"притяжательный падеж имени: {self.w[p].text}'s → {self.genitive_name(text)}")
        return tokens

    @staticmethod
    def genitive_name(name: str) -> str:
        if name.endswith(("s", "ß", "x", "z")):
            return name + "'"
        return name + "s"

    @staticmethod
    def number_text(text: str) -> str:
        """«19th» → «19.», «1950s» → «1950er-Jahre», «1,000» → «1.000»."""
        lower = text.lower()
        for suffix in ("st", "nd", "rd", "th"):
            if lower.endswith(suffix) and lower[:-2].isdigit():
                return lower[:-2] + "."
        if lower.endswith("s") and lower[:-1].isdigit() and len(lower) == 5:
            return lower[:-1] + "er-Jahre"
        if "," in text and text.replace(",", "").isdigit():
            return text.replace(",", ".")
        if "." in text and text.replace(".", "").isdigit():
            return text.replace(".", ",")
        return text

    def noun_coordination(self, i: int, case: str, exclude: set[int]) -> tuple[list[G], bool]:
        tokens: list[G] = []
        plural = False
        conjs = [c for c in self.children(i, "conj") if c.index not in exclude and c.index not in self.done]
        for c in conjs:
            ccs = [x for x in self.children(c.index, "cc") if x.index not in self.done]
            commas = [x for x in self.children(c.index, "punct") if x.index < c.index and x.text in {",", ";"}
                      and x.index not in self.done]
            for x in commas:
                self.mark(x.index, "punct")
            if ccs:
                text = self.coordinator(ccs[0], self._negated_clause(i))
                self.mark(ccs[0].index, DICT)
                if ccs[0].lower == "and":
                    plural = True
                if text in {"aber", "sondern", "doch"}:
                    tokens.append(punct(","))              # перед противительным союзом — запятая
                tokens.append(word(text, ccs[0].index))
            elif commas:
                tokens.append(punct(","))
            if self.is_predicate(c.index) and self.children(c.index, *SUBJ):
                tokens += self.clause(c.index, "main")
            else:
                more, _ = self.phrase_node(c.index, case)
                tokens += more
        return tokens, plural

    # ==================================================================================
    # относительные придаточные
    # ==================================================================================

    def relative_clause(self, v: int, antecedent: int, agr: Agr) -> list[G]:
        """«…, which translates code» → «…, der Code übersetzt»."""
        rel = self._relative_word(v)
        gender, number = agr.gender, agr.number
        if rel is None:
            # «the book I read» — относительного слова нет, это прямое дополнение
            pronoun = gm.relative(gender, number, "A" if self.children(v, *SUBJ) else "N")
            self.notes.append("придаточное без относительного слова: добавлено «" + pronoun + "»")
            subj_agr = None if self.children(v, *SUBJ) else Agr(3, number, gender)
            return self.clause(v, "rel", intro=[word(pronoun)], subject_agr=subj_agr,
                               subject_tokens=None if self.children(v, *SUBJ) else [])
        r = self.rel(rel)
        holder = rel
        while self.heads[holder] != v and self.heads[holder] >= 0:
            holder = self.heads[holder]
        word_ = self.w[rel]
        if word_.lower in {"who", "whom", "whose"} and agr.human and gender == "n":
            gender = "m"
        if word_.lower == "which" and self.w[antecedent].upos not in {"NOUN", "PROPN", "PRON", "NUM"} \
                and r in SUBJ | {"obj"}:
            self.notes.append("«which» относится ко всему предложению → «was»")
            return self.clause(v, "rel", intro=[word("was", rel)], skip={rel},
                               subject_tokens=[] if r in SUBJ else None,
                               subject_agr=Agr(3, "sg", "n") if r in SUBJ else None)
        self.mark(rel, DICT)
        if word_.tag == "WP$" or word_.lower == "whose":
            # «whose author» → «dessen Autor»
            stem = "dessen" if gender in {"m", "n"} and number == "sg" else "deren"
            holder_role = self.rel(holder)
            case = "N" if holder_role in SUBJ else "A" if holder_role == "obj" else "D"
            self.done.add(rel)
            inner, _ = self.noun_phrase(holder, case, exclude={rel})
            inner = [t for t in inner if t.text not in {"der", "die", "das", "den", "dem", "des"}]
            intro = [word(stem, rel)] + inner
            if self.children(holder, "case"):
                prep_word = self.children(holder, "case")[0]
                prep, gcase = self.preposition(prep_word, holder, None, False, False)
                self.mark(prep_word.index, DICT)
                intro = [word(prep, prep_word.index)] + intro
            subj = holder_role in SUBJ
            return self.clause(v, "rel", intro=intro, skip={holder}, subject_tokens=[] if subj else None,
                               subject_agr=Agr(3, "sg") if subj else None)
        if word_.lower in {"where"} or word_.tag == "WRB":
            text = {"where": "wo", "when": "als", "why": "warum", "how": "wie"}.get(word_.lower, "wo")
            return self.clause(v, "rel", intro=[word(text, rel)], skip={holder})
        if r in SUBJ:
            pronoun = gm.relative(gender, number, "N")
            return self.clause(v, "rel", intro=[word(pronoun, rel)], skip={rel}, subject_tokens=[],
                               subject_agr=Agr(3, number, gender))
        if r == "obj":
            verb_entry = self.choice(v, "VERB").entry
            case = "D" if verb_entry and verb_entry.props.get("obj") == "D" else "A"
            return self.clause(v, "rel", intro=[word(gm.relative(gender, number, case), rel)], skip={rel})
        if r == "iobj":
            return self.clause(v, "rel", intro=[word(gm.relative(gender, number, "D"), rel)], skip={rel})
        # предложная группа: «in which» → «in dem», «by which» → «durch den»
        cases = self.children(holder, "case") if holder == rel else self.children(rel, "case")
        if cases:
            prep_word = cases[0]
            prep, gcase = self.preposition(prep_word, rel, None, False, self.rel(holder) == "obl:agent")
            for c in cases:
                self.mark(c.index, DICT)
            pronoun = gm.relative(gender, number, gcase if gcase in "NADG" else "D")
            return self.clause(v, "rel", intro=[word(prep, prep_word.index), word(pronoun, rel)], skip={holder})
        return self.clause(v, "rel", intro=[word(gm.relative(gender, number, "A"), rel)], skip={holder})

    def _relative_word(self, v: int) -> int | None:
        for c in self.children(v):
            if c.tag in {"WDT", "WP", "WP$", "WRB"} or (c.lower == "that" and c.index < v and
                                                       self.rel(c.index) in SUBJ | {"obj", "obl"}):
                if c.index < v:
                    return c.index
            for cc in self.children(c.index):
                if cc.tag in {"WDT", "WP", "WP$"} and cc.index < v:
                    return cc.index
        return None

    def reduced_relative(self, v: int, antecedent: int, agr: Agr) -> list[G]:
        """Определительный оборот: «code generated by X» → «Code, der von X erzeugt wird»."""
        w = self.w[v]
        marks = self.children(v, "mark")
        if any(m.lower == "to" for m in marks) or (w.tag == "VB" and not self.children(v, *SUBJ)):
            return [punct(",")] + self.clause(v, "zu") + [punct(",")]
        if self.children(v, *SUBJ) or self.children(v, "aux", "aux:pass") or marks:
            if marks:
                return [punct(",")] + self.complement_clause(v) + [punct(",")]
            return [punct(",")] + self.relative_clause(v, antecedent, agr) + [punct(",")]
        if w.tag == "VBN":
            pronoun = gm.relative(agr.gender, agr.number, "N")
            self.notes.append("причастный оборот → относительное придаточное в страдательном залоге")
            # «a tragedy written by Shakespeare in 1600» — дело прошлое: «geschrieben wurde»
            past = w.lemma.lower() in {"write", "publish", "compose", "found", "invent", "release", "coin",
                                       "build", "discover", "paint", "produce", "establish", "film", "adapt"} or \
                any(self.w[k].text.isdigit() and len(self.w[k].text) == 4 for k in self.span(v))
            return [punct(",")] + self.clause(v, "rel", intro=[word(pronoun)], subject_tokens=[],
                                              subject_agr=Agr(3, agr.number, agr.gender),
                                              forced={"passive": True, "participle": False,
                                                      "tense": "past" if past else "pres"}) + [punct(",")]
        if w.tag == "VBG":
            pronoun = gm.relative(agr.gender, agr.number, "N")
            self.notes.append("-ing-оборот → относительное придаточное")
            return [punct(",")] + self.clause(v, "rel", intro=[word(pronoun)], subject_tokens=[],
                                              subject_agr=Agr(3, agr.number, agr.gender),
                                              forced={"gerund": False}) + [punct(",")]
        if w.upos in {"ADJ"}:
            return self.adjective_phrase(v, None, agr.gender, agr.number, "N", predicative=True)
        return self.any_node(v)


def pre_adv_role(transfer: "SentenceTransfer", i: int) -> bool:
    """У роли перед именем есть притяжательное или числительное — артикль не нужен."""
    return bool(transfer.children(i, "nmod:poss", "nummod"))


class _FakeAdjective:
    """Прилагательное, которое пришло из перевода оборота («maschinell* Übersetzung»)."""

    def __init__(self, text: str, src: int) -> None:
        self.text = text
        self.src = (src,)
        self.index = -1


PAIRED = {"(": ")", "[": "]", "{": "}", "“": "”", "‘": "’", "``": "''"}
SYMMETRIC = {'"', "'"}


def _pairs(words: list[Word]) -> list[tuple[int, int, str, str]]:
    """Пары кавычек и скобок английского предложения: (открывающая, закрывающая, знаки)."""
    pairs = []
    stack: list[Word] = []
    open_symmetric: dict[str, Word] = {}
    for w in words:
        if w.text in PAIRED:
            stack.append(w)
        elif w.text in PAIRED.values():
            for k in range(len(stack) - 1, -1, -1):
                if PAIRED[stack[k].text] == w.text:
                    opener = stack.pop(k)
                    pairs.append((opener.index, w.index, opener.text, w.text))
                    break
        elif w.text in SYMMETRIC and (w.space_after is False or w.text == '"'):
            if w.text in open_symmetric:
                opener = open_symmetric.pop(w.text)
                pairs.append((opener.index, w.index, w.text, w.text))
            elif w.text == '"' or (w.index + 1 < len(words) and not w.space_after):
                open_symmetric[w.text] = w
    return pairs


def restore_pairs(words: list[Word], tokens: list[G]) -> list[G]:
    """Кавычки и скобки ставятся вокруг немецких слов, полученных из английских слов между ними."""
    pairs = _pairs(words)
    marks = {i for a, b, _, _ in pairs for i in (a, b)}
    result = [t for t in tokens if not (t.kind == "punct" and (set(t.src) & marks or t.text in
                                                               {"(", ")", '"', "“", "”", "„"} and not t.src))]
    for a, b, left, right in sorted(pairs, key=lambda p: p[1] - p[0]):
        inside = [k for k, t in enumerate(result) if t.src and all(a < x < b for x in t.src)
                  and t.text not in {",", ";"}]
        if not inside:
            continue
        first, last = inside[0], inside[-1]
        result.insert(last + 1, punct(right, b))
        result.insert(first, punct(left, a))
    return result


def translate_sentence(sentence: AnalyzedSentence, ctx: DocContext) -> tuple[Sentence, dict[int, str]]:
    transfer = SentenceTransfer(sentence, ctx)
    result = transfer.run()
    result.tokens = restore_pairs(sentence.words, result.tokens)
    # слова, которые трансфер не использовал, — в конец (лучше лишнее, чем пропуск)
    missing = [w for w in sentence.words if w.index not in transfer.status and w.index not in transfer.absorbed
               and w.index not in transfer.done and w.is_word]
    for w in missing:
        choice = transfer.choice(w.index)
        if choice.entry is not None:
            transfer.mark(w.index, choice.status)
        else:
            transfer.unknown(w.index)
    for w in sentence.words:
        if w.index in transfer.absorbed:
            transfer.status.setdefault(w.index, transfer.status.get(transfer.absorbed[w.index], DICT))
    return result, transfer.status
