from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Inbox(Base):
    __tablename__ = "inboxes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    address: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    is_persistent: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    inbox_address: Mapped[str] = mapped_column(String(255), index=True)
    mail_from: Mapped[str] = mapped_column(String(255), default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    text_body: Mapped[str] = mapped_column(Text, default="")
    html_body: Mapped[str] = mapped_column(Text, default="")
    raw_headers: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
