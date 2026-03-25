from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Inbox(Base):
    __tablename__ = "inboxes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    local_part: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    address: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    owner_username: Mapped[str] = mapped_column(String(120), default="", index=True)
    profile_name: Mapped[str] = mapped_column(String(120), default="Inbox")
    profile_type: Mapped[str] = mapped_column(String(50), default="manual", index=True)
    inbox_mode: Mapped[str] = mapped_column(String(30), default="temp", index=True)
    source_ip: Mapped[str] = mapped_column(String(120), default="", index=True)
    is_persistent: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    inbox_address: Mapped[str] = mapped_column(String(255), index=True)
    mail_from: Mapped[str] = mapped_column(String(255), default="")
    sender_domain: Mapped[str] = mapped_column(String(255), default="", index=True)
    subject: Mapped[str] = mapped_column(String(500), default="")
    message_category: Mapped[str] = mapped_column(String(50), default="primary", index=True)
    message_kind: Mapped[str] = mapped_column(String(50), default="general", index=True)
    verification_link: Mapped[str] = mapped_column(String(1000), default="")
    is_unread: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    text_body: Mapped[str] = mapped_column(Text, default="")
    html_body: Mapped[str] = mapped_column(Text, default="")
    raw_headers: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
