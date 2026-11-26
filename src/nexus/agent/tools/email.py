"""Tools for the email connection and the emails waiting for an answer."""

from typing import Literal

from pydantic import Field

from nexus.agent.tools.core import Args, NoArgs, ToolContext, ToolResult, ToolSpec
from nexus.agent.tools.helpers import parse_money, show
from nexus.application import email as email_cases
from nexus.application import splits as split_cases
from nexus.domain.email import InboundEmail
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    Direction,
)


async def _connect_email(ctx: ToolContext, _: NoArgs) -> ToolResult:
    if ctx.connect_link is None:
        return ToolResult("Connecting email isn't set up on this server yet.")
    url = await ctx.connect_link(ctx.user)
    return ToolResult(
        "A one-time Connect Gmail link (it works for 10 minutes) is shown as a button. "
        "Tell the user: Google will warn that Nexus isn't verified, because it's a private "
        "app; they tap Advanced, then Go to Nexus, then Allow. Nexus only looks at "
        "receipt-like emails, and nothing is logged until they confirm it.",
        buttons=[[("Connect Gmail", f"url:{url}")]],
    )


class ForwardArgs(Args):
    provider: Literal["gmail", "outlook", "icloud", "yahoo", "other"] = Field(
        description="The user's email provider; other for work email or anything else"
    )


async def _forward_email(ctx: ToolContext, a: ForwardArgs) -> ToolResult:
    if ctx.forward_address is None:
        return ToolResult("Forwarding to Nexus isn't set up on this server yet.")
    address = await ctx.forward_address(ctx.user)
    return ToolResult(
        f"The user's own Nexus address is {address}. Nothing arrives there unless they "
        "forward it, and nothing is logged until they confirm. Steps:\n"
        + email_cases.forwarding_steps(a.provider, address)
        + "\nAfterwards they can ask you to test the setup."
    )


async def _test_email_setup(ctx: ToolContext, _: NoArgs) -> ToolResult:
    found = await email_cases.overview(ctx.uow(), ctx.user.id, now=ctx.now)
    forward = next((c for c in found.connections if c.provider.value == "forward"), None)
    if forward is None:
        if found.connections:
            return ToolResult(
                "Gmail is connected and checked every 15 minutes; email_status shows what "
                "was found. There's no forwarding address to test."
            )
        return ToolResult("No email is connected, so there's nothing to test.")
    await email_cases.test_setup(ctx.uow(), ctx.user.id, now=ctx.now)
    return ToolResult(
        f"Tell the user: send an email to your usual address with the subject "
        f'"Nexus test receipt", so it goes through your forwarding rule (or forward any '
        f"email to {forward.address} by hand). I'll say here when it arrives, usually "
        "within a few minutes. If nothing comes within 15 minutes, the rule isn't "
        "forwarding yet."
    )


class AnswerEmailArgs(Args):
    number: int = Field(
        ge=1, le=email_cases.WAITING_SHOWN, description="The email's number in the waiting list"
    )
    action: Literal["log", "repayment", "income", "skip", "same", "move"] = Field(
        description="log: save it as it was read (money in from someone who owes the user "
        "pays that back). repayment: money in that pays back what the sender owes. income: "
        "money in kept as plain income. skip: log nothing. same: it's the same payment as "
        "the one it looks like (already logged or in another email), so add nothing. move: "
        "it was a transfer to or from the wallet the email names (a line says it may be a "
        "transfer), not spending or income"
    )
    amount: str | None = Field(
        None,
        description="The user's own figure, only when no amount was found or they corrected it",
    )
    currency: str | None = None


async def _waiting_email(ctx: ToolContext, number: int) -> InboundEmail:
    emails = await email_cases.waiting(ctx.uow(), ctx.user.id, now=ctx.now)
    if number > len(emails):
        raise InvalidInput("there's no such email waiting; they may have been answered already")
    return emails[number - 1]


async def _describe_answer(ctx: ToolContext, a: AnswerEmailArgs) -> str:
    email = await _waiting_email(ctx, a.number)
    line = email_cases.describe(email, ctx.tz)
    if a.action == "skip":
        return f"Skip this email and log nothing? {line}"
    if a.action == "same":
        return f"Treat this email as the same payment, adding nothing? {line}"
    if a.action == "move":
        return f"Log it as a transfer between wallets, not spending or income? {line}"
    figure = f" as {parse_money(ctx, a.amount, a.currency)}" if a.amount else ""
    how = {
        "log": "Log it",
        "repayment": "Log it as paying back what they owe",
        "income": "Log it as income (not a repayment)",
    }[a.action]
    return f"{how}{figure}? {line}"


async def _answer_email(ctx: ToolContext, a: AnswerEmailArgs) -> ToolResult:
    email = await _waiting_email(ctx, a.number)
    if a.action == "skip":
        await email_cases.skip_email(ctx.uow(), ctx.user.id, email.id)
        return ToolResult("Skipped; nothing was logged.", wrote=True)
    if a.action == "same":
        kept = await email_cases.same_payment(ctx.uow, ctx.user, email.id, now=ctx.now)
        if kept is None:
            return ToolResult(
                "Marked as the same payment as the other waiting email; answer that one to log it.",
                wrote=True,
            )
        return ToolResult(
            f"Same payment: kept {kept.amount} ({kept.counterparty or 'no name'}); nothing added.",
            wrote=True,
        )
    if a.action == "move":
        moved = await email_cases.move_email(
            ctx.uow,
            ctx.user,
            email.id,
            now=ctx.now,
            amount=parse_money(ctx, a.amount, a.currency) if a.amount else None,
        )
        return ToolResult(
            f"Logged a transfer (not spending or income): {await show(ctx, moved.transaction)}",
            wrote=True,
        )
    tx = await email_cases.log_email(
        ctx.uow,
        ctx.user,
        email.id,
        now=ctx.now,
        amount=parse_money(ctx, a.amount, a.currency) if a.amount else None,
        repayment={"log": None, "repayment": True, "income": False}[a.action],
    )
    if tx.direction is Direction.OUT:
        where = f" at {tx.counterparty}" if tx.counterparty else ""
        return ToolResult(f"Logged {tx.amount}{where}.", wrote=True)
    left = (
        await split_cases.list_open_ious(ctx.uow(), ctx.user.id, participant_name=tx.counterparty)
        if tx.counterparty
        else []
    )
    owed = ", ".join(str(i.outstanding) for i in left)
    status = f" {tx.counterparty} still owes {owed}." if left else ""
    return ToolResult(f"Logged {tx.amount} received from {tx.counterparty}.{status}", wrote=True)


async def _email_status(ctx: ToolContext, _: NoArgs) -> ToolResult:
    found = await email_cases.overview(ctx.uow(), ctx.user.id, now=ctx.now)
    if not found.connections:
        return ToolResult("No email is connected.")
    lines = []
    for c in found.connections:
        state = "working" if c.status.value == "active" else "needs reconnecting"
        if c.provider.value == "forward":
            heard = (
                f", last email received {c.last_received_at.astimezone(ctx.tz):%-d %b %H:%M}"
                if c.last_received_at
                else ", nothing received yet"
            )
            lines.append(f"Forwarding address {c.address}: {state}{heard}")
            continue
        checked = (
            f", last checked {c.synced_until.astimezone(ctx.tz):%-d %b %H:%M}"
            if c.synced_until
            else ", not checked yet"
        )
        lines.append(f"{c.address}: {state}{checked}")
    week = [e for e in found.emails if (ctx.now - e.received_at).days < 7]
    counts: dict[str, int] = {}
    for e in week:
        counts[e.status.value] = counts.get(e.status.value, 0) + 1
    summary = ", ".join(f"{n} {s.replace('_', ' ')}" for s, n in sorted(counts.items()))
    lines.append(f"This week: {summary or 'no receipt-like emails'}.")
    lines += email_cases.sender_checklist(found.emails)
    lines.append(
        "Receipts by email (in Settings, in the web app) lists each one and what happened to it."
    )
    return ToolResult("\n".join(lines))


SPECS: list[ToolSpec] = [
    ToolSpec(
        "answer_email",
        "Answer an email waiting for the user (listed with numbers in their money "
        "snapshot): log it, log money in as a repayment or as income, skip it, or, when "
        "it looks like a payment already recorded, mark it the same payment. "
        "Asks the user to confirm.",
        AnswerEmailArgs,
        _answer_email,
        confirm=_describe_answer,
    ),
    ToolSpec(
        "connect_email",
        "Give the user a link to connect Gmail so receipts are found automatically. "
        "Only when the user asks how to log expenses automatically.",
        NoArgs,
        _connect_email,
    ),
    ToolSpec(
        "forward_email",
        "Give the user their own Nexus address to forward receipts to, with steps for "
        "their mail provider. For Outlook, iCloud, Yahoo, work email, or Gmail users "
        "who'd rather not connect. Only when the user asks to log expenses "
        "automatically.",
        ForwardArgs,
        _forward_email,
    ),
    ToolSpec(
        "test_email_setup",
        "Check the user's email forwarding works: tells them what test email to send, "
        "and Nexus confirms in chat when it arrives.",
        NoArgs,
        _test_email_setup,
    ),
    ToolSpec(
        "email_status",
        "Which mailboxes are connected and what happened to recent receipt emails.",
        NoArgs,
        _email_status,
    ),
]

READ_ONLY: frozenset[str] = frozenset({"email_status"})
