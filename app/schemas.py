from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InboxCreate(BaseModel):
    local_part: str | None = Field(default=None, min_length=1, max_length=64)
    domain: str | None = Field(default=None, min_length=1, max_length=255)
    is_persistent: bool = False
    profile_name: str | None = Field(default=None, min_length=1, max_length=120)
    inbox_mode: str = Field(default="temp", pattern="^(temp|personal)$")


class InboxResponse(BaseModel):
    local_part: str
    domain: str
    address: str
    profile_name: str
    profile_type: str
    inbox_mode: str
    is_persistent: bool
    requires_approval: bool
    is_approved: bool
    approved_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime


class InboxUpdate(BaseModel):
    is_persistent: bool


class InboxSummary(BaseModel):
    local_part: str
    domain: str
    address: str
    profile_name: str
    profile_type: str
    inbox_mode: str
    is_persistent: bool
    requires_approval: bool
    is_approved: bool
    approved_at: datetime | None = None
    expires_at: datetime | None = None
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
    message_category: str
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


class AuthRequest(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=6, max_length=200)


class UserResponse(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_approved: bool
    created_at: datetime
    approved_at: datetime | None = None


class AuthStatusResponse(BaseModel):
    user: UserResponse | None


class AuthMessageResponse(BaseModel):
    message: str
    user: UserResponse | None = None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    prefix: str
    last_four: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    token: str


class ApiKeyCreateResponse(BaseModel):
    api_key: ApiKeyResponse
    message: str


class AdminInboxSummary(InboxSummary):
    owner_username: str
    source_ip: str


class AdminMessagePreview(MessagePreview):
    owner_username: str
    inbox_profile_name: str


class AdminMessageDetail(AdminMessagePreview):
    text_body: str
    html_body: str
    raw_headers: str


class PersonalInboxApproval(BaseModel):
    id: int
    address: str
    owner_username: str
    profile_name: str
    created_at: datetime


class ConfigResponse(BaseModel):
    accepted_domains: list[str]
    allow_any_domain: bool
    poll_seconds: int
    message_ttl_hours: int
    temp_inbox_minutes: int
    temp_daily_limit: int
    max_messages_per_inbox: int


class HealthResponse(BaseModel):
    status: str
    smtp_port: int
    inbox_count: int
    message_count: int


class DeleteResponse(BaseModel):
    deleted: int
