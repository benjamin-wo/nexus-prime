from typing import List, Dict, Any, Optional
import asyncio
from langchain_core.tools import tool
from sqlmodel import select
from core.db import async_session_factory
from core.models import UserCredential, UserProfile
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

@tool
async def search_email_messages(
    user_id: int, custom_query: Optional[str] = None, provider: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Search financial email messages across active email providers (Gmail, Outlook, etc.)
    using the zero-friction smart financial query and domain presets.
    """
    async with async_session_factory() as session:
        result = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        tracked_banks = profile.tracked_banks if profile else []

    if provider:
        providers_to_query = [provider.lower()]
    else:
        providers_to_query = await get_active_providers_for_user(user_id)

    tasks = []
    for p_name in providers_to_query:
        if p_name in PROVIDER_REGISTRY:
            tasks.append(
                PROVIDER_REGISTRY[p_name].search_messages(
                    user_id=user_id,
                    tracked_banks=tracked_banks,
                    custom_query=custom_query,
                )
            )

    if not tasks:
        return []

    results = await asyncio.gather(*tasks)
    merged_messages = []
    for res in results:
        merged_messages.extend(res)
    return merged_messages

@tool
async def search_gmail_messages(user_id: int, custom_query: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search Gmail messages using the zero-friction smart financial query.
    Requires gmail.readonly scope.
    """
    return await search_email_messages.ainvoke(
        {"user_id": user_id, "custom_query": custom_query, "provider": "gmail"}
    )

@tool
async def search_outlook_messages(user_id: int, custom_query: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search Microsoft Outlook messages using OData $search and $filter financial queries.
    Requires Mail.Read scope.
    """
    return await search_email_messages.ainvoke(
        {"user_id": user_id, "custom_query": custom_query, "provider": "outlook"}
    )

@tool
async def apply_email_processed_tag(user_id: int, message_id: str, provider: str = "gmail") -> bool:
    """
    Apply the Assistant/Processed tag/label/category to a message in the specified email provider.
    """
    p_name = provider.lower()
    if p_name in PROVIDER_REGISTRY:
        return await PROVIDER_REGISTRY[p_name].apply_processed_label(user_id=user_id, message_id=message_id)
    return False

@tool
async def apply_gmail_processed_label(user_id: int, message_id: str) -> bool:
    """
    Apply the Assistant/Processed label to a message in Gmail (Layer 1 of deduplication).
    Requires gmail.modify scope.
    """
    return await apply_email_processed_tag.ainvoke(
        {"user_id": user_id, "message_id": message_id, "provider": "gmail"}
    )

@tool
async def apply_outlook_processed_category(user_id: int, message_id: str) -> bool:
    """
    Apply the Assistant/Processed category to a message in Outlook (Layer 1 of deduplication).
    Requires Mail.ReadWrite scope.
    """
    return await apply_email_processed_tag.ainvoke(
        {"user_id": user_id, "message_id": message_id, "provider": "outlook"}
    )
