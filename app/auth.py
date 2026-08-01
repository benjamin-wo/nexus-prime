import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select
from urllib.parse import urlencode

from core.config import settings
from core.db import async_session_factory
from core.models import UserCredential
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
        "scope": "https://www.googleapis.com/auth/gmail.readonly",
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

    return HTMLResponse(
        "<h2>✅ Gmail connected!</h2>"
        "<p>You can close this tab and message the bot again — it can now read your inbox.</p>"
    )
