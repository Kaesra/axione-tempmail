from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from email.utils import parseaddr
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import delete, select

from app.config import settings
from app.database import SessionLocal
from app.models import GoogleAccount, GoogleAlias, GoogleOAuthState


GOOGLE_OAUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
GOOGLE_GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GOOGLE_GMAIL_MESSAGE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}?format=full"
GOOGLE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _generate_temp_tag() -> str:
    return f"tm-{secrets.token_hex(4)}"


def _ensure_auto_aliases(session, account_id: int) -> None:
    aliases = session.scalars(select(GoogleAlias).where(GoogleAlias.google_account_id == account_id)).all()
    current_tags = {alias.tag for alias in aliases}
    target_count = max(50, settings.google_temp_alias_pool_size)
    needed = max(0, target_count - len(aliases))
    if needed <= 0:
        return
    for index in range(needed):
        tag = _generate_temp_tag()
        while tag in current_tags:
            tag = _generate_temp_tag()
        current_tags.add(tag)
        session.add(
            GoogleAlias(
                google_account_id=account_id,
                name=f"Temp Alias {len(aliases) + index + 1}",
                tag=tag,
                is_temp=True,
                auto_generated=True,
            )
        )


def _http_json(url: str, method: str = "GET", data: dict | None = None, headers: dict | None = None) -> dict:
    body = None
    merged_headers = {"Accept": "application/json"}
    if data is not None:
        body = urlencode(data).encode("utf-8")
        merged_headers["Content-Type"] = "application/x-www-form-urlencoded"
    if headers:
        merged_headers.update(headers)
    request = Request(url, data=body, headers=merged_headers, method=method)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def google_enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret and settings.google_oauth_redirect_uri)


def create_google_oauth_url(username: str) -> str:
    if not google_enabled():
        raise ValueError("Google OAuth is not configured")
    state = secrets.token_urlsafe(32)
    with SessionLocal() as session:
        session.execute(delete(GoogleOAuthState).where(GoogleOAuthState.username == username))
        session.add(GoogleOAuthState(username=username, state=state))
        session.commit()
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{GOOGLE_OAUTH_URL}?{query}"


def _exchange_code(code: str) -> dict:
    return _http_json(
        GOOGLE_TOKEN_URL,
        method="POST",
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "grant_type": "authorization_code",
        },
    )


def _refresh_access_token(refresh_token: str) -> dict:
    return _http_json(
        GOOGLE_TOKEN_URL,
        method="POST",
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )


def _gmail_profile(access_token: str) -> dict:
    return _http_json(GOOGLE_GMAIL_PROFILE_URL, headers={"Authorization": f"Bearer {access_token}"})


def _public_google_account(account: GoogleAccount, alias_count: int = 0) -> dict:
    return {
        "id": account.id,
        "google_email": account.google_email,
        "created_at": account.created_at,
        "last_sync_at": account.last_sync_at,
        "alias_count": alias_count,
    }


def _public_google_alias(alias: GoogleAlias, email: str) -> dict:
    local_part, _, domain = email.partition("@")
    address = f"{local_part}+{alias.tag}@{domain}" if alias.tag else email
    return {
        "id": alias.id,
        "google_account_id": alias.google_account_id,
        "name": alias.name,
        "tag": alias.tag,
        "address": address,
        "is_temp": alias.is_temp,
        "auto_generated": alias.auto_generated,
        "created_at": alias.created_at,
    }


def _decode_body(payload: dict) -> str:
    import base64

    data = payload.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        text = _decode_body(part)
        if text:
            return text
    return ""


def _message_header(headers: list[dict], name: str) -> str:
    target = name.lower()
    for header in headers:
        if header.get("name", "").lower() == target:
            return header.get("value", "")
    return ""


def complete_google_oauth(state: str, code: str) -> str:
    if not google_enabled():
        raise ValueError("Google OAuth is not configured")
    with SessionLocal() as session:
        row = session.scalar(select(GoogleOAuthState).where(GoogleOAuthState.state == state))
        if row is None:
            raise ValueError("Invalid Google OAuth state")
        username = row.username
        session.delete(row)
        session.commit()

    token_data = _exchange_code(code)
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = int(token_data.get("expires_in", 3600))
    scopes = token_data.get("scope", "")
    if not access_token:
        raise ValueError("Google access token could not be created")

    profile = _gmail_profile(access_token)
    google_email = profile.get("emailAddress", "").strip().lower()
    google_sub = profile.get("emailAddress", "").strip().lower()
    if not google_email:
        raise ValueError("Google account email could not be resolved")

    with SessionLocal() as session:
        account = session.scalar(select(GoogleAccount).where(GoogleAccount.google_email == google_email, GoogleAccount.username == username))
        if account is None:
            account = session.scalar(select(GoogleAccount).where(GoogleAccount.google_sub == google_sub))
        if account is None:
            account = GoogleAccount(username=username, google_email=google_email, google_sub=google_sub)
            session.add(account)
            session.flush()
        account.username = username
        account.google_email = google_email
        account.google_sub = google_sub
        account.access_token = access_token
        if refresh_token:
            account.refresh_token = refresh_token
        account.scopes = scopes
        account.token_expires_at = datetime.utcnow() + timedelta(seconds=max(expires_in - 60, 60))
        account.last_sync_at = account.last_sync_at or datetime.utcnow()
        _ensure_auto_aliases(session, account.id)
        session.commit()
    return username


def list_google_accounts(username: str) -> list[dict]:
    with SessionLocal() as session:
        accounts = session.scalars(select(GoogleAccount).where(GoogleAccount.username == username).order_by(GoogleAccount.created_at.desc())).all()
        results = []
        for account in accounts:
            _ensure_auto_aliases(session, account.id)
            alias_count = session.query(GoogleAlias).filter(GoogleAlias.google_account_id == account.id).count()
            results.append(_public_google_account(account, alias_count))
        session.commit()
        return results


def list_google_aliases(username: str) -> list[dict]:
    with SessionLocal() as session:
        accounts = session.scalars(select(GoogleAccount).where(GoogleAccount.username == username)).all()
        for account in accounts:
            _ensure_auto_aliases(session, account.id)
        session.commit()
        rows = session.execute(
            select(GoogleAlias, GoogleAccount)
            .join(GoogleAccount, GoogleAccount.id == GoogleAlias.google_account_id)
            .where(GoogleAccount.username == username)
            .order_by(GoogleAlias.is_temp.desc(), GoogleAlias.created_at.desc())
        ).all()
        return [_public_google_alias(alias, account.google_email) for alias, account in rows]


def create_google_alias(username: str, google_account_id: int, name: str, tag: str) -> dict:
    normalized_name = name.strip()[:120]
    normalized_tag = "".join(ch for ch in tag.strip().lower() if ch.isalnum() or ch in {"-", "_", "."})[:120]
    if not normalized_name:
        raise ValueError("Alias name is required")
    with SessionLocal() as session:
        account = session.scalar(select(GoogleAccount).where(GoogleAccount.id == google_account_id, GoogleAccount.username == username))
        if account is None:
            raise ValueError("Google account not found")
        existing = session.scalar(select(GoogleAlias).where(GoogleAlias.google_account_id == google_account_id, GoogleAlias.tag == normalized_tag))
        if existing is not None:
            raise ValueError("This alias tag already exists")
        alias = GoogleAlias(google_account_id=google_account_id, name=normalized_name, tag=normalized_tag, is_temp=True, auto_generated=False)
        session.add(alias)
        session.commit()
        session.refresh(alias)
        return _public_google_alias(alias, account.google_email)


def create_temp_google_alias(username: str) -> dict:
    with SessionLocal() as session:
        account = session.scalar(select(GoogleAccount).where(GoogleAccount.username == username).order_by(GoogleAccount.created_at.desc()))
        if account is None:
            raise ValueError("Connect a Google account first")
        tag = _generate_temp_tag()
        while session.scalar(select(GoogleAlias).where(GoogleAlias.google_account_id == account.id, GoogleAlias.tag == tag)) is not None:
            tag = _generate_temp_tag()
        existing_count = session.query(GoogleAlias).filter(GoogleAlias.google_account_id == account.id).count()
        alias = GoogleAlias(
            google_account_id=account.id,
            name=f"Temp Alias {existing_count + 1}",
            tag=tag,
            is_temp=True,
            auto_generated=True,
        )
        session.add(alias)
        session.commit()
        session.refresh(alias)
        _ensure_auto_aliases(session, account.id)
        session.commit()
        return _public_google_alias(alias, account.google_email)


def delete_google_account(username: str, google_account_id: int) -> int:
    with SessionLocal() as session:
        account = session.scalar(select(GoogleAccount).where(GoogleAccount.id == google_account_id, GoogleAccount.username == username))
        if account is None:
            return 0
        session.execute(delete(GoogleAlias).where(GoogleAlias.google_account_id == google_account_id))
        session.delete(account)
        session.commit()
        return 1


def _valid_access_token(account: GoogleAccount) -> str:
    if account.access_token and account.token_expires_at and account.token_expires_at > datetime.utcnow():
        return account.access_token
    if not account.refresh_token:
        raise ValueError("Google refresh token is missing")
    token_data = _refresh_access_token(account.refresh_token)
    access_token = token_data.get("access_token", "")
    expires_in = int(token_data.get("expires_in", 3600))
    if not access_token:
        raise ValueError("Google access token refresh failed")
    account.access_token = access_token
    account.token_expires_at = datetime.utcnow() + timedelta(seconds=max(expires_in - 60, 60))
    return access_token


def list_google_recent_messages(username: str, limit: int = 20) -> list[dict]:
    with SessionLocal() as session:
        accounts = session.scalars(select(GoogleAccount).where(GoogleAccount.username == username).order_by(GoogleAccount.created_at.desc())).all()
        items: list[dict] = []
        for account in accounts:
            access_token = _valid_access_token(account)
            list_payload = _http_json(
                f"{GOOGLE_GMAIL_MESSAGES_URL}?maxResults={max(1, min(limit, 20))}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            for entry in list_payload.get("messages", []) or []:
                detail = _http_json(
                    GOOGLE_GMAIL_MESSAGE_URL.format(message_id=entry.get("id", "")),
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                payload = detail.get("payload", {})
                headers = payload.get("headers", []) or []
                to_value = _message_header(headers, "To")
                subject = _message_header(headers, "Subject")
                sender = _message_header(headers, "From")
                received_at = detail.get("internalDate")
                body = _decode_body(payload)
                _, to_email = parseaddr(to_value)
                matched_alias = ""
                aliases = session.scalars(select(GoogleAlias).where(GoogleAlias.google_account_id == account.id)).all()
                for alias in aliases:
                    if _public_google_alias(alias, account.google_email)["address"].lower() == to_email.lower():
                        matched_alias = alias.name
                        break
                items.append(
                    {
                        "id": f"google-{account.id}-{entry.get('id', '')}",
                        "google_account_id": account.id,
                        "google_email": account.google_email,
                        "subject": subject,
                        "mail_from": sender,
                        "to_address": to_email or to_value,
                        "alias_name": matched_alias,
                        "snippet": detail.get("snippet", "") or body[:200],
                        "body": body,
                        "received_at": datetime.utcfromtimestamp(int(received_at) / 1000).isoformat() if received_at else None,
                    }
                )
            account.last_sync_at = datetime.utcnow()
        session.commit()
    items.sort(key=lambda item: item.get("received_at") or "", reverse=True)
    return items[:limit]
