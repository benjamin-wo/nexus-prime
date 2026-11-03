"""Card numbers for tests, built when a test runs so that no card-like number is ever
written in the repository."""

import random


def luhn_digit(partial: str) -> str:
    """The check digit that makes ``partial`` + digit pass the Luhn checksum."""
    total = 0
    for n, ch in enumerate(reversed(partial)):
        d = int(ch)
        if n % 2 == 0:  # these double once the check digit is appended
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return str((10 - total % 10) % 10)


def card_number(prefix: str = "4", length: int = 16, seed: int = 1) -> str:
    """A number of ``length`` digits starting ``prefix`` that passes the Luhn check; the
    digits between are the same for the same ``seed``."""
    rng = random.Random(seed)  # noqa: S311 - made-up test data
    body = prefix + "".join(str(rng.randrange(10)) for _ in range(length - 1 - len(prefix)))
    return body + luhn_digit(body)


def spaced(number: str, sep: str = " ", groups: tuple[int, ...] = (4, 4, 4, 4, 3)) -> str:
    """``number`` in groups (the last takes what is left): the way a card is typed."""
    parts: list[str] = []
    at = 0
    for size in groups:
        if at >= len(number):
            break
        parts.append(number[at : at + size])
        at += size
    if at < len(number):
        parts[-1] += number[at:]
    return sep.join(parts)


def last4(number: str) -> str:
    return number[-4:]
