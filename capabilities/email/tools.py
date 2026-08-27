from typing import List, Dict, Any, Optional
import asyncio
import httpx
from datetime import datetime, timezone as dt_timezone
from email.utils import parsedate_to_datetime
from langchain_core.tools import tool
from sqlmodel import select
from core.db import async_session_factory
from core.models import UserCredential, UserProfile
from core.tool_guard import identity_bound
from core.vault import decrypt_token
from core.shared_tools.email_presets import build_gmail_query, build_outlook_query
from capabilities.email.providers import (
    EmailProvider,
    PROVIDER_REGISTRY,
    get_active_providers_for_user,
)

async def get_user_email_token(user_id: int, provider: str = "gmail") -> Optional[str]:
    """Retrieve and decrypt the user's OAuth refresh token from PostgreSQL for the given provider."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(UserCredential).where(
                UserCredential.user_id == user_id,
                UserCredential.provider == provider.lower(),
            )
        )
        cred = result.scalar_one_or_none()
        if not cred:
            return None
        try:
            return decrypt_token(cred.encrypted_token_payload)
        except Exception as exc:  # noqa: BLE001 - a bad key must not crash the webhook
            print(
                f"[EMAIL] failed to decrypt {provider} token for user {user_id}: "
                f"{type(exc).__name__} — treat as not connected"
            )
            return None

async def get_user_gmail_token(user_id: int) -> Optional[str]:
    """Retrieve and decrypt the user's Gmail OAuth refresh token from PostgreSQL (backward compatibility)."""
    return await get_user_email_token(user_id, provider="gmail")

async def get_user_outlook_token(user_id: int) -> Optional[str]:
    """Retrieve and decrypt the user's Microsoft OAuth refresh token from PostgreSQL."""
    return await get_user_email_token(user_id, provider="outlook")


async def _revoke_gmail_token(refresh_token: str) -> bool:
    """Best-effort Google token revocation; local deletion remains authoritative."""
    if not refresh_token:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://oauth2.googleapis.com/revoke",
                data={"token": refresh_token},
            )
        return response.status_code == 200
    except Exception as exc:  # noqa: BLE001 - disconnect must succeed locally even if revoke is unavailable
        print(f"[GMAIL] token revocation failed: {type(exc).__name__}")
        return False


async def disconnect_email_account(
    user_id: int,
    provider: str = "all",
) -> Dict[str, Any]:
    """Remove one or all mailbox credentials for a user.

    Tokens are deleted from the local vault first. Gmail revocation is attempted
    afterward; Microsoft refresh tokens have no equivalent consumer revocation
    endpoint, so deleting the local token stops all future Graph access.
    """
    requested = (provider or "all").strip().lower()
    if requested in {"all", "email", "both"}:
        providers = set(PROVIDER_REGISTRY)
    elif requested in PROVIDER_REGISTRY:
        providers = {requested}
    else:
        return {
            "status": "invalid_provider",
            "provider": requested,
            "message": "Choose gmail, outlook, or all.",
        }

    gmail_tokens: List[str] = []
    connected: List[str] = []
    async with async_session_factory() as session:
        result = await session.execute(
            select(UserCredential).where(
                UserCredential.user_id == user_id,
                UserCredential.provider.in_(providers),
            )
        )
        credentials = list(result.scalars().all())
        for credential in credentials:
            provider_name = credential.provider.lower()
            connected.append(provider_name)
            if provider_name == "gmail":
                try:
                    gmail_tokens.append(decrypt_token(credential.encrypted_token_payload))
                except Exception:
                    pass
            await session.delete(credential)
        if credentials:
            await session.commit()

    revoked = 0
    for token in gmail_tokens:
        if await _revoke_gmail_token(token):
            revoked += 1

    return {
        "status": "ok",
        "requested_provider": requested,
        "disconnected": sorted(set(connected)),
        "count": len(connected),
        "gmail_tokens_revoked": revoked,
    }

async def discover_and_track_bank_domain(user_id: int, sender_email: str) -> bool:
    """
    Auto-discovery: extract domain from sender (e.g. alerts@mybank.com)
    and automatically append to UserProfile.tracked_banks if new.
    """
    if "@" not in sender_email:
        return False
    domain = sender_email.split("@")[-1].strip().lower()

    async with async_session_factory() as session:
        result = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if not profile:
            return False

        current_banks = list(profile.tracked_banks or [])
        if domain not in current_banks:
            current_banks.append(domain)
            profile.tracked_banks = current_banks
            session.add(profile)
            await session.commit()
            return True
        return False

def _parse_message_datetime(raw: Any) -> Optional[datetime]:
    """Parse an email date string into an aware UTC datetime, or None."""
    if not raw:
        return None
    value = str(raw)
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def _sort_messages_newest_first(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort merged provider results by message date, newest first. Messages with an
    unparseable date sort last so they never masquerade as the newest."""
    def key(msg: Dict[str, Any]):
        parsed = _parse_message_datetime(msg.get("date") or "")
        return (parsed is not None, parsed if parsed else datetime.min.replace(tzinfo=dt_timezone.utc))
    return sorted(messages, key=key, reverse=True)


@tool
@identity_bound
async def search_email_messages(
    user_id: int,
    custom_query: Optional[str] = None,
    provider: Optional[str] = None,
    latest: bool = False,
) -> List[Dict[str, Any]]:
    """
    Search financial email messages across active email providers (Gmail, Outlook, etc.)
    using the zero-friction smart financial query and domain presets.

    When latest=True, fetch the newest messages from each provider with no financial
    keyword filter and return them merged, newest first.
    """
    async with async_session_factory() as session:
        result = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        tracked_banks = profile.tracked_banks if profile else []

    if provider:
        providers_to_query = [provider.lower()]
    else:
        providers_to_query = await get_active_providers_for_user(user_id)

    queried_providers = [p_name for p_name in providers_to_query if p_name in PROVIDER_REGISTRY]
    tasks = [
        PROVIDER_REGISTRY[p_name].search_messages(
            user_id=user_id,
            tracked_banks=tracked_banks,
            custom_query=custom_query,
            latest=latest,
        )
        for p_name in queried_providers
    ]

    if not tasks:
        return []

    # return_exceptions=True: every provider here (IMAP, mock) already swallows
    # its own errors and returns [] on failure, except the real Gmail/Outlook
    # OAuth paths, which can raise on a network blip or a rejected token
    # exchange. Without this, asyncio.gather propagates that single provider's
    # exception and discards results from every OTHER provider that already
    # succeeded — one flaky mailbox taking down the whole search and crashing
    # the webhook turn instead of degrading gracefully.
    results = await asyncio.gather(*tasks, return_exceptions=True)
    merged_messages = []
    for p_name, res in zip(queried_providers, results):
        if isinstance(res, BaseException):
            print(f"[EMAIL] {p_name} search failed, skipping: {type(res).__name__}: {res}")
            continue
        merged_messages.extend(res)
    return _sort_messages_newest_first(merged_messages)

@tool
@identity_bound
async def search_gmail_messages(user_id: int, custom_query: Optional[str] = None, latest: bool = False) -> List[Dict[str, Any]]:
    """
    Search Gmail messages using the zero-friction smart financial query.
    Requires gmail.readonly scope.
    """
    return await search_email_messages.ainvoke(
        {"user_id": user_id, "custom_query": custom_query, "provider": "gmail", "latest": latest}
    )

@tool
@identity_bound
async def search_outlook_messages(user_id: int, custom_query: Optional[str] = None, latest: bool = False) -> List[Dict[str, Any]]:
    """
    Search Microsoft Outlook messages using OData $search and $filter financial queries.
    Requires Mail.Read scope.
    """
    return await search_email_messages.ainvoke(
        {"user_id": user_id, "custom_query": custom_query, "provider": "outlook", "latest": latest}
    )

@tool
@identity_bound
async def apply_email_processed_tag(user_id: int, message_id: str, provider: str = "gmail") -> bool:
    """
    Apply the Assistant/Processed tag/label/category to a message in the specified email provider.
    """
    p_name = provider.lower()
    if p_name in PROVIDER_REGISTRY:
        return await PROVIDER_REGISTRY[p_name].apply_processed_label(user_id=user_id, message_id=message_id)
    return False

@tool
@identity_bound
async def apply_gmail_processed_label(user_id: int, message_id: str) -> bool:
    """
    Apply the Assistant/Processed label to a message in Gmail (Layer 1 of deduplication).
    Requires gmail.modify scope.
    """
    return await apply_email_processed_tag.ainvoke(
        {"user_id": user_id, "message_id": message_id, "provider": "gmail"}
    )

@tool
@identity_bound
async def apply_outlook_processed_category(user_id: int, message_id: str) -> bool:
    """
    Apply the Assistant/Processed category to a message in Outlook (Layer 1 of deduplication).
    Requires Mail.ReadWrite scope.
    """
    return await apply_email_processed_tag.ainvoke(
        {"user_id": user_id, "message_id": message_id, "provider": "outlook"}
    )


# --- Agent-callable connection/sweep tools ----------------------------------


@tool
@identity_bound
async def get_email_connection_status(user_id: int = 0) -> str:
    """
    Check which mailboxes (Gmail/Outlook) are connected for the user, and
    return sign-in link(s) for any that are configured on this deployment
    but not yet connected. Call this before search_my_email or
    sweep_email_for_expenses if you don't already know the connection state
    this turn -- the bot cannot read email until the user grants access.

    Args:
        user_id: ignored; the assistant injects the authenticated user's ID.
    """
    import os

    from core.config import settings

    uid = int(user_id or 0)
    gmail_token = await get_user_gmail_token(uid)
    outlook_token = await get_user_outlook_token(uid)
    needs_gmail = bool(settings.google_client_id and settings.google_client_secret) and not gmail_token
    needs_outlook = bool(settings.microsoft_client_id and settings.microsoft_client_secret) and not outlook_token

    if not needs_gmail and not needs_outlook:
        connected = ", ".join(p for p, tok in (("Gmail", gmail_token), ("Outlook", outlook_token)) if tok)
        return f"[email] Already connected: {connected or 'no provider configured on this deployment'}."

    public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or ""
    base = f"https://{public_domain}".rstrip("/") if public_domain else (settings.webapp_url or "").rstrip("/")
    lines = ["[email] One-time access needed -- open a link and allow read-only access:"]
    if needs_gmail:
        lines.append(f"Gmail: {base}/auth/gmail?user_id={uid}")
    if needs_outlook:
        lines.append(f"Outlook: {base}/auth/outlook?user_id={uid}")
    return "\n".join(lines)


@tool
@identity_bound
async def disconnect_email(provider: str = "all", user_id: int = 0) -> str:
    """
    Disconnect a connected mailbox so the assistant stops reading it and
    stops using it for automatic expense tracking.

    Args:
        provider: "gmail", "outlook", or "all".
        user_id: ignored; the assistant injects the authenticated user's ID.
    """
    result = await disconnect_email_account(user_id=int(user_id or 0), provider=provider)
    if result.get("count"):
        names = ", ".join(result["disconnected"]).title()
        return f"Disconnected {names}. I will no longer read that mailbox."
    target = "your mailbox" if provider == "all" else f"your {provider} account"
    return f"[email] No connected credential found for {target}."


@tool
@identity_bound
async def sweep_email_for_expenses(provider: Optional[str] = None, user_id: int = 0) -> str:
    """
    Search the user's inbox for financial emails (receipts, bills, bank
    alerts) and auto-log any expenses found (deduped by email ID; ambiguous
    ones are skipped, never auto-logged). Use for "check my email for
    expenses" / "did I get billed for anything". For "what's new in my
    inbox" (no expense intent), use search_my_email instead -- it's
    read-only and won't write anything.

    Args:
        provider: restrict to "gmail" or "outlook"; omit to search all connected.
        user_id: ignored; the assistant injects the authenticated user's ID.
    """
    from capabilities.expenses.tools import log_expenses_from_emails

    uid = int(user_id or 0)
    results = await search_email_messages.ainvoke({"user_id": uid, "provider": provider})
    if results:
        for msg in results:
            sender = msg.get("sender", "")
            if sender:
                await discover_and_track_bank_domain(uid, sender)

    expense_result = await log_expenses_from_emails.ainvoke(
        {"user_id": uid, "emails": results, "notify": False}
    )
    logged = expense_result.get("logged") or []
    skipped = expense_result.get("skipped") or []
    if not logged:
        return "[email] Checked the inbox -- nothing expense-related found." + (
            f" ({len(skipped)} ambiguous, skipped)" if skipped else ""
        )
    lines = [f"Checked the inbox -- auto-logged {len(logged)} expense(s):"]
    for item in logged[:8]:
        lines.append(f"• {item['currency']} {item['amount']:.2f} — {item['merchant']} ({item['category']})")
    if skipped:
        lines.append(f"…{len(skipped)} ambiguous skipped.")
    return "\n".join(lines)
