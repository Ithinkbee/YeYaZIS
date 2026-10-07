"""Фразы-пасхалки и вход администратора."""

from __future__ import annotations

import json

import pytest

from sluhach import config
from sluhach.admin import Admin, AdminError
from sluhach.eggs import DEFAULT_EGGS, EggError, EggStore


# --- хранилище -------------------------------------------------------------------

def test_defaults_until_the_admin_changes_something(eggs):
    assert [(egg.key, egg.answer) for egg in eggs.all()] == list(DEFAULT_EGGS)
    assert not eggs.path.exists()


def test_add_saves_and_survives_restart(eggs):
    egg = eggs.add("  Кто  там?  ", "Это я, почтальон Печкин.")
    assert egg.key == "Кто там?" and egg.language == "ru" and egg.id and egg.created
    again = EggStore(eggs.path)
    assert [item.key for item in again.all()] == [DEFAULT_EGGS[0][0], DEFAULT_EGGS[1][0], "Кто там?"]
    saved = json.loads(eggs.path.read_text(encoding="utf-8"))
    assert saved["eggs"][-1]["answer"] == "Это я, почтальон Печкин."


def test_update_and_remove(eggs):
    egg = eggs.add("Кто там?", "Никого.")
    changed = eggs.update(egg.id, "Кто здесь?", "Все свои.")
    assert changed.id == egg.id and changed.created == egg.created
    assert eggs.get(egg.id).key == "Кто здесь?" and eggs.match("кто там") is None
    assert eggs.remove(egg.id) and eggs.get(egg.id) is None
    assert not eggs.remove(egg.id)
    with pytest.raises(EggError, match="нет"):
        eggs.update("нет-такой", "Кто там?", "Никого.")


def test_removing_everything_does_not_bring_defaults_back(eggs):
    for egg in eggs.all():
        eggs.remove(egg.id)
    assert eggs.all() == [] and EggStore(eggs.path).all() == []
    assert eggs.match("сколько стоит слон") is None


@pytest.mark.parametrize("key, answer, problem", [
    ("", "ответ", "слишком короткая"),
    ("да", "ответ", "слишком короткая"),
    ("?!", "ответ", "слишком короткая"),
    ("Кто там?", "", "нет фразы-ответа"),
    ("Кто там?", "   ", "нет фразы-ответа"),
    ("я" * (config.MAX_EGG_KEY_CHARS + 1), "ответ", "длиннее"),
    ("Кто там?", "я" * (config.MAX_EGG_ANSWER_CHARS + 1), "длиннее"),
    ("сколько СТОИТ слон", "ответ", "уже есть"),            # тот же ключ в другом написании
])
def test_bad_eggs_are_refused(eggs, key, answer, problem):
    with pytest.raises(EggError, match=problem):
        eggs.add(key, answer)
    assert len(eggs.all()) == len(DEFAULT_EGGS)


def test_update_may_keep_its_own_key(eggs):
    egg = eggs.all()[0]
    assert eggs.update(egg.id, egg.key, "Новый ответ.").answer == "Новый ответ."
    with pytest.raises(EggError, match="уже есть"):
        eggs.update(egg.id, DEFAULT_EGGS[1][0], "ответ")


def test_limit(eggs, monkeypatch):
    monkeypatch.setattr(config, "MAX_EGGS", len(DEFAULT_EGGS) + 1)
    eggs.add("Кто там?", "Никого.")
    with pytest.raises(EggError, match="больше нельзя"):
        eggs.add("Кто здесь?", "Никого.")


def test_spoiled_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "eggs.json"
    path.write_text("не JSON", encoding="utf-8")
    assert len(EggStore(path).all()) == len(DEFAULT_EGGS)
    path.write_text(json.dumps({"eggs": [{"id": "1", "key": "Кто там?", "answer": "Я."}, {"key": "без ответа"}, 7]}),
                    encoding="utf-8")
    assert [egg.key for egg in EggStore(path).all()] == ["Кто там?"]


# --- сравнение с услышанным ---------------------------------------------------------

@pytest.mark.parametrize("heard", [
    "сколько стоит слон", "Сколько стоит слон?", "СКОЛЬКО СТОИТ СЛОН!!!", "пафнутий сколько стоит слон",
    "сколько стоит слом", "скока стоит слон", "сколько стоят слон",
])
def test_key_phrase_is_recognised(eggs, heard):
    found = eggs.match(heard)
    assert found is not None and found[0].answer == "Вам тут не рынок и не цирк."
    assert config.EGG_THRESHOLD <= found[1] <= 1.0


@pytest.mark.parametrize("heard", [
    "сколько стоит билет", "слон", "сколько", "сколько стоит слон в зоопарке за углом", "", "wie spät ist es",
])
def test_other_phrases_are_not(eggs, heard):
    assert eggs.match(heard) is None


def test_best_egg_wins(eggs):
    eggs.add("Сколько стоит слоник?", "Слоники не продаются.")
    assert eggs.match("сколько стоит слоник")[0].answer == "Слоники не продаются."
    assert eggs.match("сколько стоит слон")[0].answer == "Вам тут не рынок и не цирк."


def test_languages(eggs):
    german = eggs.match("wie viel kostet ein elefant")[0]
    assert german.language == "de" and german.answer_language == "de"
    mixed = eggs.add("Скажи спасибо по-немецки", "Vielen Dank!")
    assert mixed.language == "ru" and mixed.answer_language == "de"
    assert mixed.to_dict()["answer_language"] == "de"
    assert eggs.match("wieviel kostet ein elefant", "de") is not None       # склейка слов не мешает


# --- администратор --------------------------------------------------------------------

class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_login_and_logout():
    admin = Admin("секрет")
    with pytest.raises(AdminError, match="неверное имя или пароль"):
        admin.login("admin", "не секрет")
    token = admin.login("admin", "секрет")
    assert len(token) > 30 and admin.check(token)
    assert not admin.check("чужой-ключ") and not admin.check("") and not admin.check(None)
    assert admin.login("admin", "секрет") != token              # у каждого входа свой ключ
    admin.logout(token)
    assert not admin.check(token)


def test_both_name_and_password_are_needed():
    for name, password in (("admin", "секрет"), ("хозяин", "мимо"), ("", "секрет"), ("хозяин", ""), ("", "")):
        with pytest.raises(AdminError, match="неверное имя или пароль"):   # ответ не говорит, что именно не так
            Admin("секрет", name="Хозяин").login(name, password)
    admin = Admin("секрет", name="Хозяин")
    assert admin.check(admin.login("хозяин", "секрет"))
    assert admin.check(admin.login("  ХОЗЯИН ", "секрет"))       # имя — без учёта регистра и пробелов по краям
    with pytest.raises(AdminError):
        admin.login("хозяин", "Секрет")                          # а пароль — буква в букву


def test_name_and_password_come_from_config(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "из-настроек")
    monkeypatch.setattr(config, "ADMIN_LOGIN", "root")
    assert Admin().check(Admin().login("root", "из-настроек")) is False   # ключ одного входа другому не подходит
    admin = Admin()
    assert admin.check(admin.login("root", "из-настроек"))
    with pytest.raises(AdminError):
        admin.login("admin", "из-настроек")


def test_empty_password_never_opens():
    admin = Admin("")
    with pytest.raises(AdminError):
        admin.login("admin", "")


def test_session_expires():
    clock = Clock()
    admin = Admin("секрет", clock=clock)
    token = admin.login("admin", "секрет")
    clock.now += config.ADMIN_SESSION_HOURS * 3600 - 1
    assert admin.check(token)
    clock.now += 2
    assert not admin.check(token)


def test_lock_after_wrong_passwords():
    clock = Clock()
    admin = Admin("секрет", clock=clock)
    for _ in range(config.ADMIN_ATTEMPTS):
        with pytest.raises(AdminError, match="неверное имя или пароль"):
            admin.login("admin", "мимо")
    with pytest.raises(AdminError, match="слишком много попыток"):
        admin.login("admin", "секрет")                           # даже верный пароль пока не принимается
    clock.now += config.ADMIN_LOCK_SECONDS + 1
    assert admin.check(admin.login("admin", "секрет"))


def test_right_password_resets_the_counter():
    admin = Admin("секрет")
    for _ in range(config.ADMIN_ATTEMPTS - 1):
        with pytest.raises(AdminError):
            admin.login("admin", "мимо")
    admin.login("admin", "секрет")
    for _ in range(config.ADMIN_ATTEMPTS - 1):
        with pytest.raises(AdminError, match="неверное имя или пароль"):
            admin.login("admin", "мимо")
