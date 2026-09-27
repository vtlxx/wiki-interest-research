import pytest

from wir_core.errors import WirError
from wir_core.publish.notes import LIMITS, parse_notes

UK = """<!-- інструкція -->
## Висновок
Інтерес падає.

## Рекомендація
Дослідити словацьку аудиторію.

## Що перевірити далі
Опитування.
"""


def test_parse_uk_headings():
    assert parse_notes(UK) == {"conclusion": "Інтерес падає.", "recommendation": "Дослідити словацьку аудиторію.",
                               "next": "Опитування."}


def test_parse_en_headings_optional_next():
    text = "## Conclusion\nFalls.\n\n## Recommendation\nWait.\n"
    assert parse_notes(text) == {"conclusion": "Falls.", "recommendation": "Wait."}


def test_heading_variants_and_multiline_text():
    text = "# conclusion:\nFalls\nsharply.\n\n### **Recommendation**\nWait.\n## Other\nignored\n"
    assert parse_notes(text) == {"conclusion": "Falls sharply.", "recommendation": "Wait."}


def test_missing_section():
    with pytest.raises(WirError) as e:
        parse_notes("## Conclusion\nx\n")
    assert e.value.code == "NOTES_INCOMPLETE" and "Recommendation" in e.value.fix


def test_too_long():
    with pytest.raises(WirError) as e:
        parse_notes("## Conclusion\n" + "x" * (LIMITS["conclusion"] + 1) + "\n## Recommendation\ny\n")
    assert e.value.code == "NOTES_TOO_LONG" and str(LIMITS["conclusion"]) in e.value.fix


def test_template_placeholder_not_filled():
    with pytest.raises(WirError):
        parse_notes("## Висновок\n\n## Рекомендація\n\n<!-- facts:\n- 5%\n-->\n")
