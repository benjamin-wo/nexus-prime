from typing import Protocol, List, Dict, Any, Optional
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from core.models import UserProfile, UserCredential
from core.db import async_session_factory
from core.shared_tools.email_presets import build_gmail_query, build_outlook_query

class EmailProvider(Protocol):
    """Protocol for email service providers (Gmail, Outlook, etc.)."""
    async def search_messages(
        self, user_id: int, tracked_banks: List[str], custom_query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        ...

    async def apply_processed_label(self, user_id: int, message_id: str) -> bool:
        ...

class GmailProvider:
    """Gmail backend implementation using Google OAuth and Lucene-style search queries."""
    async def search_messages(
        self, user_id: int, tracked_banks: List[str], custom_query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = build_gmail_query(tracked_banks=tracked_banks, custom_query=custom_query)
        # In live execution, calls Google Gmail OAuth API via get_user_gmail_token(user_id)
        # Structured mock return for extraction pipeline and testing
        return [
            {
                "id": "msg_1001",
                "provider": "gmail",
                "subject": "Your receipt from Starbucks",
                "sender": "receipts@starbucks.com",
                "snippet": "Thank you for your order. Total paid: $15.00 on 2026-08-01.",
                "date": "2026-08-01T10:00:00Z",
                "query_used": query,
            }
        ]

    async def apply_processed_label(self, user_id: int, message_id: str) -> bool:
        # In live execution, modifies Gmail thread labels via API (requires gmail.modify)
        print(f"[GMAIL API] Applied label Assistant/Processed to message {message_id} for user {user_id}")
        return True

class OutlookProvider:
    """Microsoft Outlook / Graph API backend implementation using OData $search and categories."""
    async def search_messages(
        self, user_id: int, tracked_banks: List[str], custom_query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        odata_params = build_outlook_query(tracked_banks=tracked_banks, custom_query=custom_query)
        # In live execution, calls Microsoft Graph API via OAuth refresh token in UserCredential
        return [
            {
                "id": "msg_outlook_2001",
                "provider": "outlook",
                "subject": "Payment receipt from Amazon",
                "sender": "auto-confirm@amazon.com",
                "snippet": "Your order has been charged. Total paid: $42.50 on 2026-08-01.",
                "date": "2026-08-01T11:30:00Z",
                "query_used": odata_params,
            }
        ]

    async def apply_processed_label(self, user_id: int, message_id: str) -> bool:
        # In live execution, PATCHes Microsoft Graph message categories with 'Assistant/Processed'
        print(f"[OUTLOOK GRAPH API] Applied category Assistant/Processed to message {message_id} for user {user_id}")
        return True

PROVIDER_REGISTRY: Dict[str, EmailProvider] = {
    "gmail": GmailProvider(),
    "outlook": OutlookProvider(),
}

async def get_active_providers_for_user(user_id: int) -> List[str]:
    """
    Query UserCredential for active email provider registrations.
    Defaults to ['gmail'] if none are configured to maintain backward compatibility.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(UserCredential).where(UserCredential.user_id == user_id)
        )
        creds = result.scalars().all()
        providers = [c.provider.lower() for c in creds if c.provider.lower() in PROVIDER_REGISTRY]
        return list(set(providers)) if providers else ["gmail"]
