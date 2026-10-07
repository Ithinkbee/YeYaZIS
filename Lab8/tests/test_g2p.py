"""Немецкие правила чтения."""

from __future__ import annotations

import pytest

from glashatai.phonetics.g2p import parse_ipa, to_espeak, transcribe, transcribe_text


@pytest.mark.parametrize("word, ipa", [
    # долгота: открытый слог, двойная согласная, «ie», «h»
    ("Tag", "ˈtaːk"), ("Hand", "ˈhant"), ("Spiel", "ˈʃpiːl"), ("gehen", "ˈɡeː.ən"), ("Zahl", "ˈt͡saːl"),
    # «ch» после разных гласных, «chs», «sch», «-ig»
    ("Buch", "ˈbuːx"), ("Licht", "ˈlɪçt"), ("machen", "ˈma.xən"), ("sechs", "ˈzɛks"), ("wichtig", "ˈvɪç.tɪç"),
    # оглушение на конце слога, «st/sp» в начале основы
    ("Handlung", "ˈhant.lʊŋ"), ("lieblich", "ˈliːp.lɪç"), ("Sprache", "ˈʃpʁaː.xə"), ("Stein", "ˈʃtaɪ̯n"),
    # приставки и суффиксы
    ("Gerät", "ɡəˈʁɛːt"), ("Ergebnis", "ʔɛɐ̯ˈɡɛp.nɪs"), ("Verbindung", "fɛɐ̯ˈbɪn.dʊŋ"),
    ("Ausgabe", "ˈʔaʊ̯sˌɡaː.bə"), ("Zusammenhang", "t͡suˈza.mən.haŋ"), ("Wahrheit", "ˈvaːɐ̯.haɪ̯t"),
    # иноязычные суффиксы забирают ударение
    ("Information", "ʔɪn.fɔɐ̯.maˈt͡sjoːn"), ("Universität", "ʔu.ni.vɛɐ̯.ziˈtɛːt"), ("Theorie", "te.oˈʁiː"),
    ("Struktur", "ʃtʁʊkˈtuːɐ̯"), ("aktuell", "ʔak.tuˈɛl"), ("Faktoren", "fakˈtoː.ʁən"), ("Datei", "daˈtaɪ̯"),
    ("Region", "ʁeˈɡjoːn"), ("Kriterium", "kʁiˈteː.ʁjʊm"), ("Programmierung", "pʁo.ɡʁaˈmiː.ʁʊŋ"),
    # но не там, где окончание только похоже
    ("Stelle", "ˈʃtɛ.lə"), ("Quelle", "ˈkvɛ.lə"), ("Monat", "ˈmoː.nat"),
    # «r» после гласной и безударное «-er»
    ("Speicher", "ˈʃpaɪ̯.çɐ"), ("Wort", "ˈvɔɐ̯t"), ("für", "ˈfyːɐ̯"),
    # «v» в немецких и иноязычных словах
    ("Vektor", "ˈvɛk.tɔɐ̯"), ("verwenden", "fɛɐ̯ˈvɛn.dən"), ("Verifikation", "ve.ʁi.fi.kaˈt͡sjoːn"),
])
def test_words(word, ipa):
    assert transcribe(word).ipa() == ipa


@pytest.mark.parametrize("word, parts", [
    ("Betriebssystem", 4), ("Datenbank", 3), ("Netzwerk", 2), ("Sicherheitsmaßnahmen", 6),
    ("Speichermedien", 4), ("Programmiersprache", 5),
])
def test_compounds_keep_main_stress_on_first_part(word, parts):
    pron = transcribe(word)
    stresses = [s.stress for s in pron.syllables]
    assert len(pron.syllables) == parts
    assert 1 in stresses and 2 in stresses


@pytest.mark.parametrize("word, ipa", [
    ("neunzehnhundertvierundfünfzig", "ˈnɔʏ̯nˌt͡seːnˌhʊn.dɐtˌfiːɐ̯.ʊntˌfʏnf.t͡sɪç"),
    ("dreiundzwanzig", "ˈdʁaɪ̯.ʊntˌt͡svan.t͡sɪç"),
    ("siebzehn", "ˈziːpˌt͡seːn"),
])
def test_number_words(word, ipa):
    assert transcribe(word).ipa() == ipa


@pytest.mark.parametrize("respelling, ipa", [
    ("Kom'peiler", "kɔmˈpaɪ̯.lɐ"), ("Mä'schien", "mɛˈʃiːn"), ("'Lörning", "ˈlœɐ̯.nɪŋ"),
    ("'Fräimwörk", "ˈfʁɛɪ̯m.vœɐ̯k"), ("'Klaud", "ˈklaʊ̯t"), ("Zeh", "ˈt͡seː"), ("Fau", "ˈfaʊ̯"),
])
def test_respellings_with_explicit_stress(respelling, ipa):
    assert transcribe(respelling).ipa() == ipa


def test_exceptions_table():
    assert transcribe("System").source == "exception"
    assert transcribe("System").ipa() == "zʏsˈteːm"
    assert transcribe("Mathematik").ipa() == "ma.te.maˈtiːk"


def test_parse_ipa_marks_first_syllable_if_no_stress():
    syllables = parse_ipa("nɛts")
    assert syllables[0].stress == 1 and syllables[0].phonemes == ["n", "ɛ", "ts"]
    assert [s.phonemes for s in parse_ipa("ˈdeːɐ̯")] == [["d", "eː", "ɐ̯"]]


def test_espeak_notation():
    assert to_espeak(transcribe("'Softwär")) == "zˈɔftvɛɾ"
    assert to_espeak(transcribe("Sprache")) == "ʃprˈɑːxə"
    assert to_espeak(transcribe("Speicher")) == "ʃpˈaɪçɜ"
    assert "ʔ" not in to_espeak(transcribe("Uh"))


def test_glottal_stop_before_initial_vowel():
    assert transcribe("Ende").phonemes[0] == "ʔ"
    assert transcribe("Tag").phonemes[0] == "t"


def test_transcribe_text_skips_punctuation():
    words = [p.word for p in transcribe_text("Ein Satz, mit Kom'peiler!")]
    assert words == ["Ein", "Satz", "mit", "Kom'peiler"]
