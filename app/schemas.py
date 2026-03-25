from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InboxCreate(BaseModel):
    local_part: str | None = Field(default=None, min_length=1, max_length=64)
    domain: str | None = Field(default=None, min_length=1, max_length=255)
    is_persistent: bool = False


class InboxResponse(BaseModel):
    address: str
    is_persistent: bool
    created_at: datetime


class InboxUpdate(BaseModel):
    is_persistent: bool


class InboxSummary(BaseModel):
    address: str
    is_persistent: bool
    created_at: datetime
    message_count: int
    unread_count: int
    verification_count: int
    latest_message_at: datetime | None = None
    latest_subject: str = ""


class MessagePreview(BaseModel):
    id: int
    inbox_address: str
    mail_from: str
    sender_domain: str
    subject: str
    received_at: datetime
    codes: list[str]
    message_kind: str
    verification_link: str
    is_unread: bool
    summary: str


class MessageDetail(MessagePreview):
    text_body: str
    html_body: str
    raw_headers: str


class MessageUpdate(BaseModel):
    is_unread: bool


class ConfigResponse(BaseModel):
    accepted_domains: list[str]
    allow_any_domain: bool
    poll_seconds: int
    message_ttl_hours: int
    max_messages_per_inbox: int


class HealthResponse(BaseModel):
    status: str
    smtp_port: int
    inbox_count: int
    message_count: int


class DeleteResponse(BaseModel):
    deleted: int
