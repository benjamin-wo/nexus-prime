"""Whether something a model read from a web page is really on that page. Pure rules,
no I/O.

A model that sorts search results can still name a place or quote a figure the
page never gave. When the page's own text came back with the search, code checks
the claim against it: a name must appear in the page, and so must each figure.
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

_NOT_WORD = re.compile(r"[^0-9a-z]+")
_NUMBER = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s*([kK])?\b")
# "8 000", written with spaces between thousands, read as one number as well.
_SPACED = re.compile(r"(?<![\d.,])\d{1,3}(?: \d{3})+(?![\d,])")
_ARTICLE = re.compile(r"^(the|a|an) ")


def normalise(text: str) -> str:
    """Lower case, accents and punctuation removed, spaces collapsed: "Ōmoide-Yokochō"
    reads as "omoide yokocho"."""
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return " ".join(_NOT_WORD.sub(" ", plain.casefold()).split())


def mentions(page: str, name: str) -> bool:
    """Whether ``page`` names ``name``, ignoring case, accents, punctuation and a
    leading "the"."""
    wanted = _ARTICLE.sub("", normalise(name))
    if len(wanted) < 2:
        return False
    return f" {wanted} " in f" {normalise(page)} "


def figures(page: str) -> set[Decimal]:
    """Every number written in ``page``: "1,200", "8 000", "15.5", "15k"."""
    found: set[Decimal] = set()
    for whole, fraction, thousands in _NUMBER.findall(page):
        digits = whole.replace(",", "")
        try:
            value = Decimal(f"{digits}.{fraction}" if fraction else digits)
        except InvalidOperation:
            continue
        found.add(value * 1000 if thousands else value)
    found.update(Decimal(m.replace(" ", "")) for m in _SPACED.findall(page))
    return found


def has_figure(page: str, value: Decimal) -> bool:
    return value in figures(page)
