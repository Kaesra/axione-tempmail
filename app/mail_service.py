from __future__ import annotations

from datetime import datetime, timedelta
from email import policy
from email.parser import BytesParser

from sqlalchemy import delete, desc, func, select

from app.config import settings
from app.database import SessionLocal
from app.models import Inbox, Message
from app.utils import extract_codes


def normalize_address(address: str) -> str:
    return address.strip().lower()


def split_address(address: str) -> tuple[str, str]:
    local_part, _, domain = normalize_address(address).partition("@")
    return local_part, domain


def is_domain_allowed(domain: str) -> bool:
    if settings.allow_any_domain:
        return True
    return domain.lower() in settings.accepted_domains


def ensure_inbox(address: str) -> Inbox:
    normalized = normalize_address(address)
    with SessionLocal() as session:
        inbox_count = session.scalar(select(func.count()).select_from(Inbox)) or 0
        inbox = session.scalar(select(Inbox).where(Inbox.address == normalized))
        if inbox is None:
            if inbox_count >= settings.max_inboxes:
                raise ValueError("Inbox limit reached")
            inbox = Inbox(address=normalized)
            session.add(inbox)
            session.commit()
            session.refresh(inbox)
        return inbox


def _trim_inbox_messages(session, address: str) -> None:
    if settings.max_messages_per_inbox <= 0:
        return

    message_ids = session.scalars(
        select(Message.id)
        .where(Message.inbox_address == address)
        .order_by(desc(Message.received_at), desc(Message.id))
        .offset(settings.max_messages_per_inbox)
    ).all()
    if message_ids:
        session.execute(delete(Message).where(Message.id.in_(message_ids)))


def cleanup_expired_messages() -> int:
    if settings.message_ttl_hours <= 0:
        return 0

    cutoff = datetime.utcnow() - timedelta(hours=settings.message_ttl_hours)
    with SessionLocal() as session:
        result = session.execute(delete(Message).where(Message.received_at < cutoff))
        session.commit()
        return result.rowcount or 0


def save_message(mail_from: str, rcpt_tos: list[str], data: bytes) -> None:
    parsed = BytesParser(policy=policy.default).parsebytes(data)
    subject = str(parsed.get("subject", "")).strip()
    headers = "\n".join(f"{key}: {value}" for key, value in parsed.items())

    text_body = ""
    html_body = ""

    if parsed.is_multipart():
        for part in parsed.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            payload = part.get_content()
            if not isinstance(payload, str):
                continue
            if content_type == "text/plain" and not text_body:
                text_body = payload
            if content_type == "text/html" and not html_body:
                html_body = payload
    else:
        payload = parsed.get_content()
        if isinstance(payload, str):
            if parsed.get_content_type() == "text/html":
                html_body = payload
            else:
                text_body = payload

    with SessionLocal() as session:
        for recipient in rcpt_tos:
            normalized = normalize_address(recipient)
            _, domain = split_address(normalized)
            if not is_domain_allowed(domain):
                continue
            ensure_inbox(normalized)
            session.add(
                Message(
                    inbox_address=normalized,
                    mail_from=normalize_address(mail_from or "unknown@sender"),
                    subject=subject,
                    text_body=text_body,
                    html_body=html_body,
                    raw_headers=headers,
                )
            )
            session.flush()
            _trim_inbox_messages(session, normalized)
        session.commit()


def list_messages(address: str) -> list[dict]:
    normalized = normalize_address(address)
    with SessionLocal() as session:
        messages = session.scalars(
            select(Message).where(Message.inbox_address == normalized).order_by(desc(Message.received_at))
        ).all()
        return [
            {
                "id": message.id,
                "inbox_address": message.inbox_address,
                "mail_from": message.mail_from,
                "subject": message.subject,
                "received_at": message.received_at,
                "codes": extract_codes(message.subject, message.text_body, message.html_body),
            }
            for message in messages
        ]


def get_message(message_id: int) -> dict | None:
    with SessionLocal() as session:
        message = session.get(Message, message_id)
        if message is None:
            return None
        return {
            "id": message.id,
            "inbox_address": message.inbox_address,
            "mail_from": message.mail_from,
            "subject": message.subject,
            "received_at": message.received_at,
            "codes": extract_codes(message.subject, message.text_body, message.html_body),
            "text_body": message.text_body,
            "html_body": message.html_body,
            "raw_headers": message.raw_headers,
        }


def delete_inbox_messages(address: str) -> int:
    normalized = normalize_address(address)
    with SessionLocal() as session:
        result = session.execute(delete(Message).where(Message.inbox_address == normalized))
        session.commit()
        return result.rowcount or 0


def delete_message(message_id: int) -> int:
    with SessionLocal() as session:
        result = session.execute(delete(Message).where(Message.id == message_id))
        session.commit()
        return result.rowcount or 0


def counts() -> tuple[int, int]:
    with SessionLocal() as session:
        inbox_count = session.scalar(select(func.count()).select_from(Inbox)) or 0
        message_count = session.scalar(select(func.count()).select_from(Message)) or 0
        return inbox_count, message_count
