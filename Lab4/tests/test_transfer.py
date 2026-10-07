"""Перевод с трансфером: немецкий порядок слов, падежи, глагольные формы.

Каждый пример проверяет одно правило трансфера (подписано в комментарии).
Ожидаемые переводы — правильные немецкие предложения: если пример перестал
проходить, сломалось правило, а не «немного изменился перевод».
"""

from __future__ import annotations

import pytest

CASES = [
    # порядок слов главного предложения: подлежащее — глагол — дополнение; Akkusativ мужского рода
    ("cs", "The compiler translates the source code.", "Der Compiler übersetzt den Quellcode."),
    # обстоятельство на первом месте — глагол вторым (V2), подлежащее после глагола
    ("cs", "Yesterday the compiler translated the program.", "Gestern übersetzte der Compiler das Programm."),
    # придаточное с «dass»: глагол в конце; know + придаточное → wissen
    ("cs", "We know that the compiler translates the program.",
     "Wir wissen, dass der Compiler das Programm übersetzt."),
    # пассив: werden + Partizip II в конце, by → von (+ vom)
    ("cs", "The program was compiled by the compiler.", "Das Programm wurde vom Compiler kompiliert."),
    # перфект: рамочная конструкция hat … gelernt
    ("cs", "The network has learned the patterns.", "Das Netzwerk hat die Muster gelernt."),
    # do not + существительное с неопределённым артиклем → kein
    ("cs", "The algorithm does not use a stack.", "Der Algorithmus verwendet keinen Stapel."),
    # there is → es gibt + Akkusativ
    ("cs", "There is no simple solution.", "Es gibt keine einfache Lösung."),
    # of → Genitiv; сложное слово из оборота словаря
    ("cs", "The operating system manages the memory of the computer.",
     "Das Betriebssystem verwaltet den Speicher des Computers."),
    # отделяемая приставка уходит в конец: einführen → führt … ein
    ("cs", "The user introduces the new method.", "Der Benutzer führt die neue Methode ein."),
    # относительное придаточное: род и число по антецеденту, глагол в конце
    ("cs", "A compiler is a program that translates code.", "Ein Compiler ist ein Programm, das Code übersetzt."),
    # to + инфинитив цели → um … zu
    ("cs", "We use a cache to reduce the latency.", "Wir verwenden einen Cache, um die Latenz zu reduzieren."),
    # have to / need to / want to / be able to / be going to → модальный глагол (или werden) + инфинитив
    ("cs", "We need to reduce the latency.", "Wir müssen die Latenz reduzieren."),
    ("cs", "We had to reduce the latency.", "Wir mussten die Latenz reduzieren."),
    ("lit", "She wants to marry him.", "Sie will ihn heiraten."),
    ("cs", "The system is able to learn.", "Das System kann lernen."),
    ("cs", "The user is going to install the program.", "Der Benutzer wird das Programm installieren."),
    # need смысловым глаголом
    ("cs", "The model needs much memory.", "Das Modell benötigt viel Speicher."),
    # it is … that → es ist …, dass
    ("cs", "It is important that the system is secure.", "Es ist wichtig, dass das System sicher ist."),
    # модальный глагол: инфинитив в конце; склонение прилагательного без артикля
    ("cs", "The model can learn complex functions.", "Das Modell kann komplexe Funktionen lernen."),
    # пассив во мн. ч., оборот из словаря (data sets → Datensätze), Dativ после auf
    ("cs", "Neural networks are trained on large data sets.",
     "Neuronale Netze werden auf großen Datensätzen trainiert."),
    # придаточное условия впереди: главное начинается с глагола
    ("cs", "If the input is invalid, the parser reports an error.",
     "Wenn die Eingabe ungültig ist, meldet der Parser einen Fehler."),
    # перфект пассива: ist … worden
    ("cs", "The program has been tested.", "Das Programm ist getestet worden."),
    # будущее время: werden + инфинитив
    ("cs", "The students will read the article.", "Die Studenten werden den Artikel lesen."),
    # вопрос с вопросительным словом в подлежащем
    ("cs", "Which algorithm is faster?", "Welcher Algorithmus ist schneller?"),
    # вопрос с do: вопросительное слово — дополнение
    ("cs", "Which method does the compiler use?", "Welche Methode verwendet der Compiler?"),
    # общий вопрос: глагол первым, приставка в конце
    ("cs", "Does the user introduce the method?", "Führt der Benutzer die Methode ein?"),
    # вопрос с why и связкой
    ("cs", "Why is the cache fast?", "Warum ist der Cache schnell?"),
    # сравнительная степень, которую теггер принял за существительное
    ("cs", "The faster algorithm uses less memory.", "Der schnellere Algorithmus verwendet weniger Speicher."),
    # инфинитив при прилагательном: easy to train → einfach zu trainieren
    ("cs", "The bigger model is easier to train.", "Das größere Modell ist einfacher zu trainieren."),
    # is to + инфинитив: сказуемое — инфинитивный оборот
    ("cs", "The goal is to reduce the latency.", "Das Ziel ist, die Latenz zu reduzieren."),
    # противительный союз: запятая; после отрицания — sondern
    ("cs", "The method is simple but slow.", "Die Methode ist einfach, aber langsam."),
    ("cs", "He uses not a stack but a queue.", "Er verwendet nicht einen Stapel, sondern eine Warteschlange."),
    # полное причастие в рамке и придаточное с перфектом
    ("cs", "Yesterday the compiler has translated the program into machine code.",
     "Gestern hat der Compiler das Programm in Maschinencode übersetzt."),
    ("cs", "We know that the compiler has translated the program.",
     "Wir wissen, dass der Compiler das Programm übersetzt hat."),
    # сочинённые существительные во мн. ч.
    ("cs", "Data structures and algorithms are important.", "Datenstrukturen und Algorithmen sind wichtig."),
    # имя собственное, by при существительном → von
    ("lit", "Hamlet is a tragedy by William Shakespeare.", "Hamlet ist eine Tragödie von William Shakespeare."),
    ("lit", "The novel was written by Jane Austen.", "Der Roman wurde von Jane Austen geschrieben."),
    # отрицание при глаголе без дополнения с артиклем: nicht в конце
    ("lit", "Elizabeth does not like Mr Darcy.", "Elizabeth mag Mr Darcy nicht."),
    # which после существительного → die (женский род антецедента)
    ("lit", "Victor creates a creature, which is a monster.", "Victor erschafft eine Kreatur, die ein Monster ist."),
    # роль перед именем получает артикль: critic Lionel Trilling → der Kritiker
    ("lit", "The book was praised by critic Lionel Trilling.", "Das Buch wurde vom Kritiker Lionel Trilling gelobt."),
    # little при неисчисляемом существительном без артикля — wenig, при исчисляемом с артиклем — klein
    ("lit", "In Oceania the upper and middle classes have very little true privacy.",
     "In Ozeanien haben die oberen und mittleren Klassen sehr wenig wahre Privatsphäre."),
    ("lit", "The little dog sleeps.", "Der kleine Hund schläft."),
    # «most» + существительное — с артиклем; like — глагол, а не предлог
    ("lit", "Most users like it.", "Die meisten Benutzer mögen es."),
    # придаточное времени в начале, которое анализатор разобрал как однородное сказуемое: when → als
    ("lit", "When Fitzgerald died in 1940, he was famous.", "Als Fitzgerald 1940 starb, war er berühmt."),
    # глагол, которого нет в словаре, не переводится статьёй существительного; род. падеж имени — -s
    ("lit", "She then journeyed to the region of Geneva.", "Sie reiste dann zur Region Genfs."),
    # «'s»: притяжательное определение, даже если анализатор сделал его подлежащим
    ("lit", "His father's ghost appears.", "Der Geist seines Vaters erscheint."),
    # именная часть со связкой, подвешенная к подлежащему, — сказуемое
    ("lit", "Shakespeare's longest play is Hamlet.", "Shakespeares längstes Theaterstück ist Hamlet."),
    ("lit", "The novel's heroine, Elizabeth Bennet, is clever.", "Die Heldin des Romans, Elizabeth Bennet, ist klug."),
    # предложение без глагола по разметке теггера: «returns» — глагол (отделяемая приставка)
    ("lit", "The prince of Denmark returns.", "Der Prinz Dänemarks kehrt zurück."),
    # глагол, принятый теггером за существительное, в предложении с герундием; герундий-дополнение → zu-инфинитив
    ("cs", "The method avoids copying the data.", "Die Methode vermeidet, die Daten zu kopieren."),
    # аббревиатура во мн. ч. — без перевода, но с согласованием во мн. ч.
    ("cs", "The CPUs are fast.", "Die CPUs sind schnell."),
    # междометие перед предложением не вызывает инверсии; please в просьбе — bitte
    ("cs", "Yes, the program works.", "Ja, das Programm arbeitet."),
    ("cs", "Please check the results.", "Prüfen Sie bitte die Ergebnisse."),
    # глагольный оборот с дополнением, у которого своя предложная группа: exact revenge against → sich rächen an
    ("lit", "He wants to exact revenge against his uncle.", "Er will sich an seinem Onkel rächen."),
    # место из словаря имён
    ("lit", "He lives in New York.", "Er lebt in New York."),
]


@pytest.mark.parametrize("domain, english, german", CASES, ids=[c[1][:40] for c in CASES])
def test_transfer(de, domain, english, german):
    assert de(english, domain) == german


def test_headings_are_translated_as_common_words(translator):
    t = translator.translate("# Philosophical\n\nHamlet is a tragedy.\n\n# Main Themes\n\nText.", domain="lit",
                             log_unknown=False)
    headings = [" ".join(s.text for s in sentences) for heading, sentences in t.paragraphs if heading]
    assert headings == ["Philosophisch", "Wichtigste Themen"]


def test_word_order_notes_explain_the_transfer(translator):
    t = translator.translate("Yesterday the compiler translated the program.", domain="cs", log_unknown=False)
    notes = " ".join(t.sentences[0].notes)
    assert "V2" in notes


def test_every_word_finds_a_place(translator):
    """Ни одно слово исходного текста не теряется: каждому слову соответствует немецкое слово
    (кроме артиклей и служебных слов, которые в немецком выражаются формой)."""
    text = ("The story is told by Nick Carraway, who lives in West Egg. "
            "The compiler, which was written in C, translates programs quickly.")
    t = translator.translate(text, domain="lit", log_unknown=False)
    for s_index, sentence in enumerate(t.analysis.sentences):
        covered = {i for token in t.sentences[s_index].tokens for i in token.src}
        content = [w for w in sentence.words if w.upos in {"NOUN", "PROPN", "VERB", "ADJ"}]
        assert all(w.index in covered for w in content), [w.text for w in content if w.index not in covered]


def test_direct_mode_keeps_english_word_order(translator):
    t = translator.translate("The network has learned the patterns.", domain="cs", mode="direct", log_unknown=False)
    assert t.sentences[0].text == "Das Netzwerk hat gelernt die Muster."


def test_direct_mode_differs_from_transfer(translator):
    text = "The user introduces the new method."
    direct = translator.translate(text, domain="cs", mode="direct", log_unknown=False).sentences[0].text
    transfer = translator.translate(text, domain="cs", log_unknown=False).sentences[0].text
    assert direct != transfer
    assert "führt ein" in direct and transfer.endswith("ein.")


def test_names_learned_from_the_document(translator):
    """«Windows» в начале документа — имя (Microsoft Windows), значит, и дальше не «Fenster»."""
    t = translator.translate("Microsoft Windows is an operating system. Many users prefer Windows. "
                             "Windows runs on most computers.", domain="cs", log_unknown=False)
    assert [s.text for s in t.sentences][1:] == ["Viele Benutzer bevorzugen Windows.",
                                                 "Windows läuft auf den meisten Computern."]

