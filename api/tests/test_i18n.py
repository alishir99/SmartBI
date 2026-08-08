"""Language resolution, and the half of it that can silently corrupt a figure."""

from __future__ import annotations

import pytest

from api import i18n
from api.agent import validate
from api.agent.prompts import system_prompt


@pytest.fixture(autouse=True)
def _restore_language():
    """Every test here sets the language; none may leak it into the next one."""
    yield
    i18n.use("sv")


# ------------------------------------------------------------------ resolution

@pytest.mark.parametrize("requested, expected", [
    ("en", "en"),
    ("EN", "en"),
    ("en-GB", "en"),
    # A whole Accept-Language header, unparsed: the first tag the app actually ships in wins.
    ("de-DE,de;q=0.9,en-US;q=0.8", "en"),
    # Unknown languages fall back rather than 400. A wrong language is a bad answer; a
    # rejected request is no answer.
    ("fr", "sv"),
    ("", "sv"),
    (None, "sv"),
])
def test_a_language_is_resolved_or_falls_back(requested, expected):
    assert i18n.resolve(requested) == expected


def test_every_language_answers_every_key():
    """A missing key falls back to Swedish, which on an English screen reads as a bug rather
    than as a translation gap. So the tables have to stay the same shape."""
    reference = set(i18n.STRINGS["sv"])
    for lang in i18n.LANGUAGES:
        assert set(i18n.STRINGS[lang]) == reference, f"{lang} is out of step with sv"


def test_the_prompt_states_the_answer_language():
    assert "Svara på svenska" in system_prompt("sv")
    assert "Answer in ENGLISH" in system_prompt("en")


# ------------------------------------------------- the number grammar (money path)
# A misread separator fails silently: a figure that IS in the result gets rejected as
# wrong, hiding the whole narrative behind the amber banner.

@pytest.mark.parametrize("lang, text, expected", [
    ("sv", "Försäljningen var 1 234 567 kr.", 1_234_567),
    ("en", "Sales were 1,234,567 SEK.", 1_234_567),
    ("sv", "Snittpriset var 1 234,50 kr.", 1_234.50),
    ("en", "The average price was 1,234.50 SEK.", 1_234.50),
    ("sv", "Omsättningen nådde 12,4 Mkr.", 12_400_000),
    ("en", "Revenue reached 12.4M.", 12_400_000),
    # A period between three digits is a thousands group in Swedish and a decimal in English.
    ("sv", "Vi sålde för 12.400 kr.", 12_400),
    ("en", "We sold 12.400 units.", 12.4),
])
def test_a_figure_is_read_the_way_its_language_writes_it(lang, text, expected):
    i18n.use(lang)
    literals = validate.extract_numbers(text)
    assert [lit.value for lit in literals] == [pytest.approx(expected)]


def test_a_one_letter_magnitude_does_not_eat_the_word_it_starts():
    """"12 months" is not twelve million. English needs single-letter suffixes (M, k) and a
    suffix that matches the front of a longer word is how one becomes the other."""
    i18n.use("en")
    values = [lit.value for lit in validate.extract_numbers("Over 12 months we grew.")]
    assert values == [12.0]


@pytest.mark.parametrize("lang, text, unit_class", [
    ("sv", "Andelen föll 12,2 procentenheter.", "pe"),
    ("en", "The share fell 12.2 pp.", "pe"),
    ("sv", "Andelen är 22,8 %.", "percent"),
    ("en", "The share is 22.8%.", "percent"),
    ("en", "We sold 4,500 units.", "count"),
])
def test_a_unit_is_classified_in_either_language(lang, text, unit_class):
    """Percentage points are their own class in both languages: letting them share "%" is what
    let a 12,2 p.e. fall be written as "12,2 percent" and pass validation."""
    i18n.use(lang)
    literals = validate.extract_numbers(text)
    assert [lit.unit_class for lit in literals][0] == unit_class


def test_non_measurements_are_masked_in_either_language():
    """"Top 10" is a limit and "Q2" is a quarter. Neither is a figure to check against data."""
    i18n.use("en")
    assert validate.extract_numbers("Top 10 products in Q2 and week 14.") == []
    i18n.use("sv")
    assert validate.extract_numbers("Topp 10 produkter i K2 och v. 14.") == []


def test_a_currency_column_is_money_whatever_the_currency_is():
    """The unit is the deployment's ISO code, so the validator cannot compare against a literal
    - anything that is not one of the three fixed units is money."""
    assert validate._class_of_unit("SEK") == "money"
    assert validate._class_of_unit("EUR") == "money"
    assert validate._class_of_unit("JPY") == "money"
    assert validate._class_of_unit("%") == "percent"
    assert validate._class_of_unit("st") == "count"
    assert validate._class_of_unit("p.e.") == "pe"
