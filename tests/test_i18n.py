import json
from pathlib import Path

from wir_core import i18n

LOCALES = Path(i18n.__file__).parent / "locales"


def test_fallback_to_en_for_other_ui():
    assert i18n.ui_lang("pl") == "en" and i18n.ui_lang("uk") == "uk"
    assert i18n.t("pl", "opt.drop", lang="Polish") == i18n.t("en", "opt.drop", lang="Polish")


def test_uk_translation_used():
    assert i18n.t("uk", "opt.drop", lang="польська") != i18n.t("en", "opt.drop", lang="польська")


def test_lang_names():
    assert i18n.lang_name("pl", "en") == "Polish"
    assert i18n.lang_name("pl", "uk") == "польська"
    assert i18n.lang_name("xx-unknown", "uk") == "xx-unknown"


def test_locales_have_same_keys():
    en = json.loads((LOCALES / "en.json").read_text("utf-8"))
    uk = json.loads((LOCALES / "uk.json").read_text("utf-8"))
    assert set(en) == set(uk)
    assert set(en["langs"]) == set(uk["langs"])
