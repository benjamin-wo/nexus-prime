"""The fixed texts a health reply may state numbers from."""

from nexus.domain import health_texts
from nexus.domain.health_texts import Signpost


def fixed_health_texts() -> list[str]:
    """The fixed referral texts and signposts (``domain.health_texts``): code's own words, so
    their numbers (995, 1767) are as good as a tool's."""
    found: list[str] = []

    def add(value: object) -> None:
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, Signpost):
            found.extend((value.name, value.contact, value.note))
        elif isinstance(value, tuple):
            for item in value:
                add(item)

    for name, value in vars(health_texts).items():
        if name.isupper():
            add(value)
    return found
