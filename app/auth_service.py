from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import Cookie, HTTPException
from sqlalchemy import delete, select

from app.config import settings
from app.database import SessionLocal
from app.models import AuthSession, User


SESSION_COOKIE = "tempmail_session"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    salt, _, digest = password_hash.partition("$")
    if not salt or not digest:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return secrets.compare_digest(check.hex(), digest)


def ensure_bootstrap_admin() -> None:
    with SessionLocal() as session:
        admin = session.scalar(select(User).where(User.username == settings.admin_username))
        if admin is None:
            admin = User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                is_admin=True,
                is_approved=True,
                approved_at=datetime.utcnow(),
            )
            session.add(admin)
            session.commit()
            return

        changed = False
        if not admin.is_admin:
            admin.is_admin = True
            changed = True
        if not admin.is_approved:
            admin.is_approved = True
            admin.approved_at = admin.approved_at or datetime.utcnow()
            changed = True
        if not verify_password(settings.admin_password, admin.password_hash):
            admin.password_hash = hash_password(settings.admin_password)
            changed = True
        if changed:
            session.commit()


def register_user(username: str, password: str) -> User:
    normalized = username.strip().lower()
    with SessionLocal() as session:
        existing = session.scalar(select(User).where(User.username == normalized))
        if existing is not None:
            raise ValueError("Username already exists")
        user = User(username=normalized, password_hash=hash_password(password), is_admin=False, is_approved=False)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def login_user(username: str, password: str) -> tuple[User, str]:
    normalized = username.strip().lower()
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == normalized))
        if user is None or not verify_password(password, user.password_hash):
            raise ValueError("Invalid username or password")
        if not user.is_approved:
            raise PermissionError("Your account is waiting for admin approval")
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=settings.session_hours)
        session.execute(delete(AuthSession).where(AuthSession.username == normalized))
        session.add(AuthSession(token=token, username=normalized, expires_at=expires_at))
        session.commit()
        return user, token


def logout_session(token: str | None) -> None:
    if not token:
        return
    with SessionLocal() as session:
        session.execute(delete(AuthSession).where(AuthSession.token == token))
        session.commit()


def _public_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "is_approved": user.is_approved,
        "created_at": user.created_at,
        "approved_at": user.approved_at,
    }


def get_user_by_session(token: str | None) -> dict | None:
    if not token:
        return None
    with SessionLocal() as session:
        auth_session = session.scalar(select(AuthSession).where(AuthSession.token == token))
        if auth_session is None:
            return None
        if auth_session.expires_at < datetime.utcnow():
            session.delete(auth_session)
            session.commit()
            return None
        user = session.scalar(select(User).where(User.username == auth_session.username))
        if user is None:
            return None
        return _public_user(user)


def require_user(tempmail_session: str | None = Cookie(default=None)) -> dict:
    user = get_user_by_session(tempmail_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not user["is_approved"]:
        raise HTTPException(status_code=403, detail="Account approval pending")
    return user


def require_admin(tempmail_session: str | None = Cookie(default=None)) -> dict:
    user = require_user(tempmail_session)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def list_pending_users() -> list[dict]:
    with SessionLocal() as session:
        users = session.scalars(select(User).where(User.is_approved.is_(False)).order_by(User.created_at)).all()
        return [_public_user(user) for user in users]


def approve_user(user_id: int) -> dict | None:
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if user is None:
            return None
        user.is_approved = True
        user.approved_at = datetime.utcnow()
        session.commit()
        session.refresh(user)
        return _public_user(user)
