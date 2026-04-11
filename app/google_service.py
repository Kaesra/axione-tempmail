from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import secrets
from datetime import datetime, timedelta
from email.utils import getaddresses, parseaddr
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import delete, select

from app.config import settings
from app.database import SessionLocal
from app.models import GoogleAccount, GoogleAlias, GoogleOAuthState
from app.utils import generate_realistic_local_part, local_part_display_name


GOOGLE_OAUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
GOOGLE_GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GOOGLE_GMAIL_MESSAGE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}?format=full"
LOCAL_ALIAS_PREFIX = "local:"
DEFAULT_GOOGLE_MESSAGE_LIMIT = 10
GOOGLE_MESSAGE_FETCH_WORKERS = 6
GOOGLE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]

def _generate_temp_tag() -> str:
    return generate_realistic_local_part()


def _gmail_base_local_part(email: str) -> str:
    local_part, _, domain = email.partition("@")
    if domain.lower() != "gmail.com":
        return ""
    compact = local_part.replace(".", "").strip().lower()
    if len(compact) < 2 or not compact.isalnum():
        return ""
    return compact


def _iter_gmail_dot_aliases(base_local_part: str):
    length = len(base_local_part)
    if length < 6:
        return

    seen: set[str] = set()

    for split in range(3, length - 2):
        parts = (base_local_part[:split], base_local_part[split:])
        if min(len(part) for part in parts) >= 3:
            candidate = ".".join(parts)
            if candidate not in seen:
                seen.add(candidate)
                yield candidate

    for first_split in range(2, length - 3):
        for second_split in range(first_split + 2, length - 1):
            parts = (
                base_local_part[:first_split],
                base_local_part[first_split:second_split],
                base_local_part[second_split:],
            )
            if min(len(part) for part in parts) >= 2:
                candidate = ".".join(parts)
                if candidate not in seen:
                    seen.add(candidate)
                    yield candidate


def _next_google_alias_tag(email: str, existing_tags: set[str]) -> str:
    base_local_part = _gmail_base_local_part(email)
    if base_local_part:
        for dotted_local_part in _iter_gmail_dot_aliases(base_local_part):
            encoded = f"{LOCAL_ALIAS_PREFIX}{dotted_local_part}"
            if encoded not in existing_tags:
                return encoded
    tag = _generate_temp_tag()
    while tag in existing_tags:
        tag = _generate_temp_tag()
    return tag


def _alias_address(email: str, tag: str) -> str:
    local_part, _, domain = email.partition("@")
    alias_domain = "googlemail.com" if domain.lower() == "gmail.com" else domain
    if tag.startswith(LOCAL_ALIAS_PREFIX):
        return f"{tag[len(LOCAL_ALIAS_PREFIX):]}@{alias_domain}"
    return f"{local_part}+{tag}@{alias_domain}" if tag else email


def _alias_name_from_tag(tag: str) -> str:
    visible = tag[len(LOCAL_ALIAS_PREFIX):] if tag.startswith(LOCAL_ALIAS_PREFIX) else tag
    return f"{local_part_display_name(visible)} Alias"


def _clear_google_message_cache(username: str) -> None:
    return None


def _ensure_auto_aliases(session, account_id: int) -> None:
    account = session.scalar(select(GoogleAccount).where(GoogleAccount.id == account_id))
    if account is None:
        return
    aliases = session.scalars(select(GoogleAlias).where(GoogleAlias.google_account_id == account_id)).all()
    current_tags = {alias.tag for alias in aliases}
    target_count = max(20, min(settings.google_temp_alias_pool_size, 50))
    needed = max(0, target_count - len(aliases))
    if needed <= 0:
        return
    for index in range(needed):
        tag = _next_google_alias_tag(account.google_email, current_tags)
        current_tags.add(tag)
        session.add(
            GoogleAlias(
                google_account_id=account_id,
                name=_alias_name_from_tag(tag),
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
    address = _alias_address(email, alias.tag)
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


def _email_address_variants(value: str) -> set[str]:
    _, parsed = parseaddr(value)
    address = (parsed or value or "").strip().lower()
    if not address or "@" not in address:
        return {address} if address else set()

    local_part, _, domain = address.partition("@")
    variants = {f"{local_part}@{domain}"}
    if domain in {"gmail.com", "googlemail.com"}:
        variants.add(f"{local_part}@gmail.com")
        variants.add(f"{local_part}@googlemail.com")
    return variants


def _alias_name_lookup(account_email: str, aliases: list[GoogleAlias]) -> dict[str, str]:
    alias_name_by_address: dict[str, str] = {}
    for alias in aliases:
        address = _public_google_alias(alias, account_email)["address"]
        for variant in _email_address_variants(address):
            alias_name_by_address.setdefault(variant, alias.name)
    return alias_name_by_address


def _message_recipient_candidates(headers: list[dict]) -> list[str]:
    candidates: list[str] = []
    for header_name in ("Delivered-To", "X-Original-To", "Envelope-To", "To", "Apparently-To", "Cc"):
        header_value = _message_header(headers, header_name)
        if not header_value:
            continue
        parsed_addresses = [address.strip().lower() for _, address in getaddresses([header_value]) if address.strip()]
        if not parsed_addresses and "@" in header_value:
            parsed_addresses = [header_value.strip().lower()]
        for address in parsed_addresses:
            if address and address not in candidates:
                candidates.append(address)
    return candidates


def _match_google_alias_name(headers: list[dict], alias_name_by_address: dict[str, str]) -> tuple[str, str]:
    candidates = _message_recipient_candidates(headers)
    for candidate in candidates:
        for variant in _email_address_variants(candidate):
            alias_name = alias_name_by_address.get(variant)
            if alias_name:
                return candidate, alias_name
    fallback = candidates[0] if candidates else ""
    return fallback, ""


def _fetch_gmail_message_detail(access_token: str, message_id: str) -> dict:
    return _http_json(
        GOOGLE_GMAIL_MESSAGE_URL.format(message_id=message_id),
        headers={"Authorization": f"Bearer {access_token}"},
    )


def _google_message_payload(
    detail: dict,
    account_id: int,
    google_email: str,
    alias_name_by_address: dict[str, str],
) -> dict:
    payload = detail.get("payload", {})
    headers = payload.get("headers", []) or []
    subject = _message_header(headers, "Subject")
    sender = _message_header(headers, "From")
    to_address, matched_alias = _match_google_alias_name(headers, alias_name_by_address)
    received_at = detail.get("internalDate")
    body = _decode_body(payload)
    message_id = detail.get("id", "")
    return {
        "id": f"google-{account_id}-{message_id}",
        "google_account_id": account_id,
        "google_email": google_email,
        "subject": subject,
        "mail_from": sender,
        "to_address": to_address,
        "alias_name": matched_alias,
        "snippet": detail.get("snippet", "") or body[:200],
        "body": body,
        "received_at": datetime.utcfromtimestamp(int(received_at) / 1000).isoformat() if received_at else None,
    }


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
    _clear_google_message_cache(username)
    return username


def list_google_accounts(username: str) -> list[dict]:
    with SessionLocal() as session:
        accounts = session.scalars(select(GoogleAccount).where(GoogleAccount.username == username).order_by(GoogleAccount.created_at.desc())).all()
        results = []
        for account in accounts:
            alias_count = session.query(GoogleAlias).filter(GoogleAlias.google_account_id == account.id).count()
            results.append(_public_google_account(account, alias_count))
        return results


def list_google_aliases(username: str) -> list[dict]:
    with SessionLocal() as session:
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
    if not normalized_tag:
        raise ValueError("Alias tag is required")
    if normalized_tag.startswith(LOCAL_ALIAS_PREFIX):
        raise ValueError("This alias tag is reserved")
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
        _clear_google_message_cache(username)
        return _public_google_alias(alias, account.google_email)


def create_temp_google_alias(username: str) -> dict:
    with SessionLocal() as session:
        account = session.scalar(select(GoogleAccount).where(GoogleAccount.username == username).order_by(GoogleAccount.created_at.desc()))
        if account is None:
            raise ValueError("Connect a Google account first")
        existing_tags = {item.tag for item in session.scalars(select(GoogleAlias).where(GoogleAlias.google_account_id == account.id)).all()}
        tag = _next_google_alias_tag(account.google_email, existing_tags)
        existing_count = session.query(GoogleAlias).filter(GoogleAlias.google_account_id == account.id).count()
        alias = GoogleAlias(
            google_account_id=account.id,
            name=_alias_name_from_tag(tag),
            tag=tag,
            is_temp=True,
            auto_generated=True,
        )
        session.add(alias)
        session.commit()
        session.refresh(alias)
        _ensure_auto_aliases(session, account.id)
        session.commit()
        _clear_google_message_cache(username)
        return _public_google_alias(alias, account.google_email)


def delete_google_account(username: str, google_account_id: int) -> int:
    with SessionLocal() as session:
        account = session.scalar(select(GoogleAccount).where(GoogleAccount.id == google_account_id, GoogleAccount.username == username))
        if account is None:
            return 0
        session.execute(delete(GoogleAlias).where(GoogleAlias.google_account_id == google_account_id))
        session.delete(account)
        session.commit()
        _clear_google_message_cache(username)
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


def list_google_recent_messages(username: str, limit: int = DEFAULT_GOOGLE_MESSAGE_LIMIT) -> list[dict]:
    effective_limit = max(1, min(limit, DEFAULT_GOOGLE_MESSAGE_LIMIT))
    account_payloads: list[dict] = []
    account_errors: list[Exception] = []

    with SessionLocal() as session:
        accounts = session.scalars(select(GoogleAccount).where(GoogleAccount.username == username).order_by(GoogleAccount.created_at.desc())).all()
        for account in accounts:
            try:
                access_token = _valid_access_token(account)
            except Exception as exc:
                account_errors.append(exc)
                continue
            aliases = session.scalars(select(GoogleAlias).where(GoogleAlias.google_account_id == account.id)).all()
            alias_name_by_address = _alias_name_lookup(account.google_email, aliases)
            query = urlencode({"maxResults": effective_limit, "includeSpamTrash": "true"})
            try:
                list_payload = _http_json(
                    f"{GOOGLE_GMAIL_MESSAGES_URL}?{query}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except Exception as exc:
                account_errors.append(exc)
                continue
            account_payloads.append(
                {
                    "account_id": account.id,
                    "google_email": account.google_email,
                    "access_token": access_token,
                    "alias_name_by_address": alias_name_by_address,
                    "message_ids": [
                        entry.get("id", "").strip()
                        for entry in (list_payload.get("messages", []) or [])
                        if entry.get("id", "").strip()
                    ],
                }
            )
            account.last_sync_at = datetime.utcnow()
        session.commit()

    if not account_payloads and account_errors:
        raise ValueError(str(account_errors[0]))

    items: list[dict] = []
    fetch_jobs: list[tuple[dict, str]] = [
        (account_payload, message_id)
        for account_payload in account_payloads
        for message_id in account_payload["message_ids"]
    ]
    if not fetch_jobs:
        return []

    worker_count = max(1, min(GOOGLE_MESSAGE_FETCH_WORKERS, len(fetch_jobs)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_fetch_gmail_message_detail, account_payload["access_token"], message_id): (account_payload, message_id)
            for account_payload, message_id in fetch_jobs
        }
        for future in as_completed(futures):
            account_payload, _ = futures[future]
            try:
                detail = future.result()
            except Exception:
                continue
            items.append(
                _google_message_payload(
                    detail,
                    account_payload["account_id"],
                    account_payload["google_email"],
                    account_payload["alias_name_by_address"],
                )
            )

    items.sort(key=lambda item: item.get("received_at") or "", reverse=True)
    return items[:effective_limit]
