import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select
from urllib.parse import urlencode

from core.config import settings
from core.db import async_session_factory
from core.models import UserCredential, UserProfile
from core.vault import encrypt_token


router = APIRouter(prefix="/auth", tags=["Auth"])


def _base_url() -> str:
    """Public base URL of this service (Railway public domain first, then WEBAPP_URL)."""
    public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or ""
    if public_domain:
        return f"https://{public_domain}".rstrip("/")
    return (settings.webapp_url or "").rstrip("/")


@router.get("/gmail")
async def gmail_connect(user_id: int = 0):
    """Redirect the user to Google's OAuth consent screen for read-only Gmail access."""
    if not settings.google_client_id or not settings.google_client_secret:
        return HTMLResponse(
            "<h2>Gmail OAuth is not configured</h2><p>GOOGLE_CLIENT_ID / "
            "GOOGLE_CLIENT_SECRET are missing on this service.</p>",
            status_code=500,
        )

    redirect_uri = f"{_base_url()}/auth/google/callback"
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": (
            "https://www.googleapis.com/auth/gmail.readonly "
            "https://www.googleapis.com/auth/gmail.modify"
        ),
        "access_type": "offline",
        "prompt": "consent",
        "state": str(user_id),
    }
    return RedirectResponse(
        "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    )


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: Optional[str] = None,
    state: str = "",
    error: Optional[str] = None,
):
    """Exchange the OAuth code for a refresh token and store it encrypted."""
    if error:
        return HTMLResponse(f"<h2>Authorization failed</h2><p>{error}</p>", status_code=400)
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    redirect_uri = f"{_base_url()}/auth/google/callback"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_data = resp.json()

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        detail = token_data.get("error_description") or token_data.get("error") or token_data
        raise HTTPException(
            status_code=502,
            detail=f"Google token exchange failed: {detail}",
        )

    try:
        user_id = int(state) if state else 0
    except ValueError:
        user_id = 0

    encrypted = encrypt_token(refresh_token)
    async with async_session_factory() as session:
        result = await session.execute(
            select(UserCredential).where(
                UserCredential.user_id == user_id,
                UserCredential.provider == "gmail",
            )
        )
        cred = result.scalar_one_or_none()
        if cred:
            cred.encrypted_token_payload = encrypted
            session.add(cred)
        else:
            session.add(
                UserCredential(
                    user_id=user_id,
                    provider="gmail",
                    encrypted_token_payload=encrypted,
                )
            )
        await session.commit()

    chat_id = None
    if user_id:
        result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        chat_id = profile.telegram_chat_id if profile else None

    if chat_id:
        # Let the user know on Telegram instead of leaving them to guess.
        from app.ingress import send_telegram_message

        await send_telegram_message(
            chat_id,
            "✅ Gmail connected! Ask me to check your email whenever you're ready.",
        )

    return HTMLResponse(
        "<h2>✅ Gmail connected!</h2>"
        "<p>You can close this tab — I've already pinged you on Telegram.</p>"
    )


_MS_TENANT = settings.microsoft_tenant or "consumers"
_MS_AUTHORIZE_URL = f"https://login.microsoftonline.com/{_MS_TENANT}/oauth2/v2.0/authorize"
_MS_TOKEN_URL = f"https://login.microsoftonline.com/{_MS_TENANT}/oauth2/v2.0/token"
_MS_SCOPES = "offline_access Mail.Read Mail.ReadWrite User.Read"


@router.get("/outlook")
async def outlook_connect(user_id: int = 0):
    """Redirect the user to Microsoft's OAuth consent screen for read/write Outlook mail access."""
    if not settings.microsoft_client_id or not settings.microsoft_client_secret:
        return HTMLResponse(
            "<h2>Outlook OAuth is not configured</h2><p>MICROSOFT_CLIENT_ID / "
            "MICROSOFT_CLIENT_SECRET are missing on this service.</p>",
            status_code=500,
        )

    redirect_uri = f"{_base_url()}/auth/microsoft/callback"
    params = {
        "client_id": settings.microsoft_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": _MS_SCOPES,
        "response_mode": "query",
        "prompt": "consent",
        "state": str(user_id),
    }
    return RedirectResponse(f"{_MS_AUTHORIZE_URL}?{urlencode(params)}")


async def _store_email_credential(user_id: int, provider: str, refresh_token: str) -> None:
    """Upsert an encrypted refresh token for the given email provider."""
    encrypted = encrypt_token(refresh_token)
    async with async_session_factory() as session:
        result = await session.execute(
            select(UserCredential).where(
                UserCredential.user_id == user_id,
                UserCredential.provider == provider,
            )
        )
        cred = result.scalar_one_or_none()
        if cred:
            cred.encrypted_token_payload = encrypted
            session.add(cred)
        else:
            session.add(
                UserCredential(
                    user_id=user_id,
                    provider=provider,
                    encrypted_token_payload=encrypted,
                )
            )
        await session.commit()


async def _notify_connection(user_id: int, provider_label: str) -> None:
    """Ping the user's Telegram when a mailbox gets connected."""
    if not user_id:
        return
    async with async_session_factory() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        chat_id = profile.telegram_chat_id if profile else None
    if chat_id:
        from app.ingress import send_telegram_message

        await send_telegram_message(
            chat_id,
            f"✅ {provider_label} connected! Ask me to check your email whenever you're ready.",
        )


@router.get("/microsoft/callback")
async def microsoft_callback(
    request: Request,
    code: Optional[str] = None,
    state: str = "",
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    """Exchange the Microsoft OAuth code for a refresh token and store it encrypted."""
    if error:
        detail = error_description or error
        return HTMLResponse(f"<h2>Authorization failed</h2><p>{detail}</p>", status_code=400)
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    redirect_uri = f"{_base_url()}/auth/microsoft/callback"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _MS_TOKEN_URL,
            data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret or "",
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": _MS_SCOPES,
            },
        )
        token_data = resp.json()

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        detail = token_data.get("error_description") or token_data.get("error") or token_data
        raise HTTPException(
            status_code=502,
            detail=f"Microsoft token exchange failed: {detail}",
        )

    try:
        user_id = int(state) if state else 0
    except ValueError:
        user_id = 0

    await _store_email_credential(user_id, "outlook", refresh_token)
    await _notify_connection(user_id, "Outlook")

    return HTMLResponse(
        "<h2>✅ Outlook connected!</h2>"
        "<p>You can close this tab — I've already pinged you on Telegram.</p>"
    )


@router.post("/disconnect")
async def disconnect_email(
    user_id: int = 0,
    provider: str = "all",
):
    """Disconnect Gmail, Outlook, or every mailbox for a user."""
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    from capabilities.email.tools import disconnect_email_account

    return await disconnect_email_account(user_id=user_id, provider=provider)
