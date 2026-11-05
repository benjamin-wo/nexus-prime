"""The fixed messages Nexus sends without asking a model, worded for the user's voice.

A "Logged 4.50 at Kopi Corner." or a "📧 From your email: ..." is a template, so the
model's reply style can't reach it. ``phrase`` gives the same message in the wording of the
user's preset (see ``domain.voice``): only the wording changes, never the facts, the amounts
or the buttons, which the caller supplies as ``values``.

- ``default`` is today's exact text, and so is the fallback for any preset a message has no
  wording for.
- ``direct`` is the shortest, ``chill`` is casual, ``hype`` is upbeat but factual.
- ``cheeky`` teases only about everyday spending. Messages about bills, debts, budgets,
  undoing and confirming (``SENSITIVE``) never get it: they use the default wording.

With the emoji dial on "none" the emoji are taken out of the wording too.
"""

from enum import StrEnum

from nexus.domain.emoji import strip_emoji
from nexus.domain.voice import Emoji, Preset, VoiceSettings


class Phrase(StrEnum):
    LOGGED_EXPENSE = "logged_expense"  # amount, where (" at Kopi Corner" or "")
    LOGGED_INCOME = "logged_income"  # amount, source (" from Ann" or "")
    LOGGED_SALARY = "logged_salary"  # amount
    RECORDED_INCOME = "recorded_income"  # amount, what ("salary", "income"), source
    RECEIPT_LOGGED = "receipt_logged"  # entry
    UNDONE = "undone"  # kind ("expense"), what ("2.20 Kopi Corner")
    SKIPPED = "skipped"
    EMAIL_EXPENSE = "email_expense"  # money, where, day
    EMAIL_INCOME = "email_income"  # money, sender (" from Ann" or ""), day
    EMAIL_BOOKING = "email_booking"  # booking, money, where, day, on
    CONFIRM_MANY = "confirm_many"
    CONFIRM_COUNT = "confirm_count"  # action ("Delete"), count
    BUDGET_USED = "budget_used"  # threshold, what, month, used
    BUDGET_REACHED = "budget_reached"  # what, month, used, percent
    BILL_REMINDER = "bill_reminder"  # label, due


# Where a joke would land badly: money owed, budgets blown, changes to the ledger.
SENSITIVE: frozenset[Phrase] = frozenset(
    {
        Phrase.UNDONE,
        Phrase.CONFIRM_MANY,
        Phrase.CONFIRM_COUNT,
        Phrase.BUDGET_USED,
        Phrase.BUDGET_REACHED,
        Phrase.BILL_REMINDER,
    }
)

_DEFAULT: dict[Phrase, str] = {
    Phrase.LOGGED_EXPENSE: "Logged {amount}{where}.",
    Phrase.LOGGED_INCOME: "Logged {amount} received{source}.",
    Phrase.LOGGED_SALARY: "Logged {amount} salary. Enjoy payday! 🎉",
    Phrase.RECORDED_INCOME: "Recorded {amount} {what}{source}.",
    Phrase.RECEIPT_LOGGED: "Logged from receipt: {entry}",
    Phrase.UNDONE: "Undone: the {kind} of {what}.",
    Phrase.SKIPPED: "Skipped. Nothing was logged.",
    Phrase.EMAIL_EXPENSE: "📧 From your email: {money}{where} on {day}. Log it?",
    Phrase.EMAIL_INCOME: (
        "📧 From your email: {money} came in{sender} on {day}. Log it as money in?"
    ),
    Phrase.EMAIL_BOOKING: (
        "📧 From your email: a {booking}, {money}{where} on {day}.{on} Log the cost?"
    ),
    Phrase.CONFIRM_MANY: "Confirm these changes?",
    Phrase.CONFIRM_COUNT: "{action} {count} entries?",
    Phrase.BUDGET_USED: "You've used {threshold}% of your {what} for {month}: {used}.",
    Phrase.BUDGET_REACHED: "You've reached your {what} for {month}: {used} ({percent}%).",
    Phrase.BILL_REMINDER: "Reminder: {label} is {due}.",
}

_DIRECT: dict[Phrase, str] = {
    Phrase.LOGGED_EXPENSE: "Logged: {amount}{where}.",
    Phrase.LOGGED_INCOME: "Logged: {amount} in{source}.",
    Phrase.LOGGED_SALARY: "Logged: {amount} salary.",
    Phrase.RECORDED_INCOME: "Recorded: {amount} {what}{source}.",
    Phrase.RECEIPT_LOGGED: "Logged: {entry}",
    Phrase.UNDONE: "Undone: {kind} of {what}.",
    Phrase.SKIPPED: "Skipped. Nothing logged.",
    Phrase.EMAIL_EXPENSE: "Email: {money}{where}, {day}. Log it?",
    Phrase.EMAIL_INCOME: "Email: {money} in{sender}, {day}. Log as money in?",
    Phrase.EMAIL_BOOKING: "Email: a {booking}, {money}{where}, {day}.{on} Log the cost?",
    Phrase.CONFIRM_MANY: "Confirm?",
    Phrase.CONFIRM_COUNT: "{action} {count} entries?",
    Phrase.BUDGET_USED: "{threshold}% of your {what} used for {month}: {used}.",
    Phrase.BUDGET_REACHED: "Reached your {what} for {month}: {used} ({percent}%).",
    Phrase.BILL_REMINDER: "{label}: {due}.",
}

_CHILL: dict[Phrase, str] = {
    Phrase.LOGGED_EXPENSE: "{amount}{where}, done.",
    Phrase.LOGGED_INCOME: "{amount} in{source}, got it.",
    Phrase.LOGGED_SALARY: "Salary's in, {amount} logged. Enjoy payday!",
    Phrase.RECORDED_INCOME: "Got it, {amount} {what}{source}.",
    Phrase.RECEIPT_LOGGED: "Got the receipt: {entry}",
    Phrase.UNDONE: "Undone, the {kind} of {what} is gone.",
    Phrase.SKIPPED: "Skipped, nothing logged.",
    Phrase.EMAIL_EXPENSE: "📧 Spotted {money}{where} in your email ({day}). Log it?",
    Phrase.EMAIL_INCOME: "📧 Looks like {money} came in{sender} on {day}. Log it as money in?",
    Phrase.EMAIL_BOOKING: (
        "📧 Found a {booking} in your email: {money}{where} on {day}.{on} Log the cost?"
    ),
    Phrase.CONFIRM_MANY: "Okay to go ahead with these?",
    Phrase.CONFIRM_COUNT: "{action} these {count} entries?",
    Phrase.BUDGET_USED: "Heads up, you're at {threshold}% of your {what} for {month}: {used}.",
    Phrase.BUDGET_REACHED: "You've hit your {what} for {month}: {used} ({percent}%).",
    Phrase.BILL_REMINDER: "Heads up, {label} is {due}.",
}

# Upbeat, and only about things that are good news or neutral: nothing is cheered about a
# bill, a budget or a change to the ledger.
_HYPE: dict[Phrase, str] = {
    Phrase.LOGGED_EXPENSE: "Logged {amount}{where}. Nice and tidy! ✅",
    Phrase.LOGGED_INCOME: "Logged {amount} received{source}. Money in! 🎉",
    Phrase.LOGGED_SALARY: "Logged {amount} salary. Payday! 🎉🎉",
    Phrase.RECORDED_INCOME: "Recorded {amount} {what}{source}. Nice one! 🎉",
    Phrase.RECEIPT_LOGGED: "Receipt logged! {entry}",
    Phrase.SKIPPED: "Skipped. Nothing was logged, all good!",
    Phrase.EMAIL_EXPENSE: "📧 New one from your email: {money}{where} on {day}. Log it?",
    Phrase.EMAIL_INCOME: (
        "📧 Good news from your email: {money} came in{sender} on {day}. Log it as money in?"
    ),
    Phrase.EMAIL_BOOKING: (
        "📧 A {booking} turned up in your email: {money}{where} on {day}.{on} Log the cost?"
    ),
}

# Light teasing about everyday spending only.
_CHEEKY: dict[Phrase, str] = {
    Phrase.LOGGED_EXPENSE: "Logged {amount}{where}. Your wallet felt that one.",
    Phrase.LOGGED_SALARY: "Logged {amount} salary. Try not to spend it all on bubble tea.",
    Phrase.SKIPPED: "Skipped. Pretend it never happened. Nothing was logged.",
    Phrase.EMAIL_EXPENSE: "📧 Your inbox snitched: {money}{where} on {day}. Log it?",
}

_BY_PRESET: dict[Preset, dict[Phrase, str]] = {
    Preset.DEFAULT: _DEFAULT,
    Preset.DIRECT: _DIRECT,
    Preset.CHILL: _CHILL,
    Preset.HYPE: _HYPE,
    Preset.CHEEKY: _CHEEKY,
}


def phrase(key: Phrase, voice: VoiceSettings, **values: object) -> str:
    """The message ``key`` in the user's voice, with ``values`` filled in. A preset with no
    wording for it (always so for ``SENSITIVE`` messages and ``cheeky``) uses the default
    wording; with emoji "none" the result has none. Raises KeyError for a value the
    wording needs and ``values`` lacks."""
    template = _DEFAULT[key]
    if key not in SENSITIVE or voice.preset is not Preset.CHEEKY:
        template = _BY_PRESET[voice.preset].get(key, template)
    text = template.format(**{name: str(value) for name, value in values.items()})
    return strip_emoji(text) if voice.emoji is Emoji.NONE else text
