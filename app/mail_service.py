from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from email import policy
from email.parser import BytesParser

from sqlalchemy import case, delete, desc, func, select

from app.config import settings
from app.database import SessionLocal
from app.domain_service import blocked_domain_names
from app.models import Inbox, Message
from app.utils import detect_message_category, detect_message_kind, extract_codes, extract_links, html_to_text, pick_verification_link, summarize_text


def normalize_address(address: str) -> str:
    return address.strip().lower()


def split_address(address: str) -> tuple[str, str]:
    local_part, _, domain = normalize_address(address).partition("@")
    return local_part, domain


def _message_payload(message: Message) -> dict:
    return {
        "id": message.id,
        "inbox_address": message.inbox_address,
        "mail_from": message.mail_from,
        "sender_domain": message.sender_domain,
        "subject": message.subject,
        "received_at": message.received_at,
        "codes": extract_codes(message.subject, message.text_body, message.html_body),
        "message_category": message.message_category,
        "message_kind": message.message_kind,
        "verification_link": message.verification_link,
        "is_unread": message.is_unread,
        "summary": summarize_text(message.text_body),
    }


def sanitize_local_part(value: str) -> str:
    cleaned = "".join(ch for ch in value.strip().lower() if ch.isalnum() or ch in {"-", ".", "_"})
    return cleaned.strip("-._")[:64]


def sanitize_ip_label(ip_address: str) -> str:
    return sanitize_local_part(ip_address.replace(":", "-").replace(".", "-")) or "unknown-ip"


def _inbox_payload(session, inbox: Inbox) -> dict:
    latest_message = session.scalar(
        select(Message)
        .where(Message.inbox_address == inbox.address)
        .order_by(desc(Message.received_at), desc(Message.id))
        .limit(1)
    )
    message_count = session.scalar(select(func.count()).select_from(Message).where(Message.inbox_address == inbox.address)) or 0
    unread_count = session.scalar(
        select(func.count()).select_from(Message).where(Message.inbox_address == inbox.address, Message.is_unread.is_(True))
    ) or 0
    verification_count = session.scalar(
        select(func.count()).select_from(Message).where(Message.inbox_address == inbox.address, Message.message_kind.in_(["verification", "password_reset", "login_link", "code"]))
    ) or 0
    return {
        "local_part": inbox.local_part,
        "domain": inbox.domain,
        "address": inbox.address,
        "profile_name": inbox.profile_name,
        "profile_type": inbox.profile_type,
        "inbox_mode": inbox.inbox_mode,
        "is_persistent": inbox.is_persistent,
        "requires_approval": inbox.requires_approval,
        "is_approved": inbox.is_approved,
        "approved_at": inbox.approved_at,
        "expires_at": inbox.expires_at,
        "created_at": inbox.created_at,
        "message_count": message_count,
        "unread_count": unread_count,
        "verification_count": verification_count,
        "latest_message_at": latest_message.received_at if latest_message else None,
        "latest_subject": latest_message.subject if latest_message else "",
    }


def _admin_inbox_payload(session, inbox: Inbox) -> dict:
    return {
        **_inbox_payload(session, inbox),
        "owner_username": inbox.owner_username,
        "source_ip": inbox.source_ip,
    }


def _message_stats_by_address(session, addresses: list[str]) -> dict[str, dict]:
    if not addresses:
        return {}
    rows = session.execute(
        select(
            Message.inbox_address,
            func.count(Message.id),
            func.sum(case((Message.is_unread.is_(True), 1), else_=0)),
            func.sum(case((Message.message_kind.in_(["verification", "password_reset", "login_link", "code"]), 1), else_=0)),
        )
        .where(Message.inbox_address.in_(addresses))
        .group_by(Message.inbox_address)
    ).all()
    return {
        inbox_address: {
            "message_count": message_count or 0,
            "unread_count": unread_count or 0,
            "verification_count": verification_count or 0,
        }
        for inbox_address, message_count, unread_count, verification_count in rows
    }


def _latest_message_by_address(session, addresses: list[str]) -> dict[str, dict]:
    if not addresses:
        return {}
    rows = session.execute(
        select(Message.inbox_address, Message.received_at, Message.subject, Message.id)
        .where(Message.inbox_address.in_(addresses))
        .order_by(Message.inbox_address, desc(Message.received_at), desc(Message.id))
    ).all()
    latest_by_address: dict[str, dict] = {}
    for inbox_address, received_at, subject, _ in rows:
        if inbox_address in latest_by_address:
            continue
        latest_by_address[inbox_address] = {
            "latest_message_at": received_at,
            "latest_subject": subject,
        }
    return latest_by_address


def _inbox_payloads(session, inboxes: Sequence[Inbox]) -> list[dict]:
    addresses = [inbox.address for inbox in inboxes]
    stats_by_address = _message_stats_by_address(session, addresses)
    latest_by_address = _latest_message_by_address(session, addresses)
    payloads = []
    for inbox in inboxes:
        stats = stats_by_address.get(inbox.address, {})
        latest = latest_by_address.get(inbox.address, {})
        payloads.append(
            {
                "local_part": inbox.local_part,
                "domain": inbox.domain,
                "address": inbox.address,
                "profile_name": inbox.profile_name,
                "profile_type": inbox.profile_type,
                "inbox_mode": inbox.inbox_mode,
                "is_persistent": inbox.is_persistent,
                "requires_approval": inbox.requires_approval,
                "is_approved": inbox.is_approved,
                "approved_at": inbox.approved_at,
                "expires_at": inbox.expires_at,
                "created_at": inbox.created_at,
                "message_count": stats.get("message_count", 0),
                "unread_count": stats.get("unread_count", 0),
                "verification_count": stats.get("verification_count", 0),
                "latest_message_at": latest.get("latest_message_at"),
                "latest_subject": latest.get("latest_subject", ""),
            }
        )
    return payloads


def _admin_inbox_payloads(session, inboxes: Sequence[Inbox]) -> list[dict]:
    payloads = _inbox_payloads(session, inboxes)
    payload_by_address = {payload["address"]: payload for payload in payloads}
    return [
        {
            **payload_by_address.get(inbox.address, {}),
            "owner_username": inbox.owner_username,
            "source_ip": inbox.source_ip,
        }
        for inbox in inboxes
    ]


def _admin_message_payload(message: Message, inbox: Inbox | None) -> dict:
    return {
        **_message_payload(message),
        "owner_username": inbox.owner_username if inbox else "",
        "inbox_profile_name": inbox.profile_name if inbox else message.inbox_address,
    }


def is_domain_allowed(domain: str) -> bool:
    normalized = domain.lower().strip()
    if normalized in blocked_domain_names():
        return False
    if settings.allow_any_domain:
        return True
    return normalized in settings.accepted_domains


def ensure_inbox(
    address: str,
    owner_username: str = "",
    is_persistent: bool = False,
    profile_name: str = "Inbox",
    profile_type: str = "manual",
    inbox_mode: str = "temp",
    source_ip: str = "",
) -> Inbox:
    normalized = normalize_address(address)
    local_part, domain = split_address(normalized)
    now = datetime.utcnow()
    requires_approval = inbox_mode == "personal"
    approved = not requires_approval
    expires_at = None if inbox_mode == "personal" else now + timedelta(minutes=settings.temp_inbox_minutes)
    with SessionLocal() as session:
        inbox_count = session.scalar(select(func.count()).select_from(Inbox)) or 0
        inbox = session.scalar(select(Inbox).where(Inbox.address == normalized))
        local_conflict = session.scalar(select(Inbox).where(Inbox.local_part == local_part, Inbox.domain == domain))
        if local_conflict is not None and local_conflict.address != normalized:
            raise ValueError("This inbox name is already reserved")
        if inbox is None:
            if inbox_count >= settings.max_inboxes:
                raise ValueError("Inbox limit reached")
            inbox = Inbox(
                local_part=local_part,
                domain=domain,
                address=normalized,
                owner_username=owner_username,
                profile_name=profile_name,
                profile_type=profile_type,
                inbox_mode=inbox_mode,
                source_ip=source_ip,
                is_persistent=is_persistent or inbox_mode == "personal",
                requires_approval=requires_approval,
                is_approved=approved,
                approved_at=now if approved else None,
                expires_at=expires_at,
            )
            session.add(inbox)
            session.commit()
            session.refresh(inbox)
        elif owner_username and inbox.owner_username and inbox.owner_username != owner_username:
            raise ValueError("This inbox belongs to another user")
        elif owner_username and not inbox.owner_username:
            inbox.owner_username = owner_username
            session.commit()
            session.refresh(inbox)
        return inbox


def set_inbox_persistent(address: str, owner_username: str, is_persistent: bool) -> Inbox | None:
    normalized = normalize_address(address)
    with SessionLocal() as session:
        inbox = session.scalar(select(Inbox).where(Inbox.address == normalized, Inbox.owner_username == owner_username))
        if inbox is None:
            return None
        inbox.is_persistent = is_persistent
        session.commit()
        session.refresh(inbox)
        return inbox


def approve_personal_inbox(inbox_id: int) -> dict | None:
    with SessionLocal() as session:
        inbox = session.get(Inbox, inbox_id)
        if inbox is None:
            return None
        inbox.requires_approval = False
        inbox.is_approved = True
        inbox.approved_at = datetime.utcnow()
        inbox.is_persistent = True
        inbox.expires_at = None
        session.commit()
        session.refresh(inbox)
        return _inbox_payload(session, inbox)


def list_pending_personal_inboxes() -> list[dict]:
    with SessionLocal() as session:
        inboxes = session.scalars(
            select(Inbox)
            .where(Inbox.inbox_mode == "personal", Inbox.is_approved.is_(False))
            .order_by(Inbox.created_at)
        ).all()
        return [
            {
                "id": inbox.id,
                "address": inbox.address,
                "owner_username": inbox.owner_username,
                "profile_name": inbox.profile_name,
                "created_at": inbox.created_at,
            }
            for inbox in inboxes
        ]


def temp_inbox_creations_today(owner_username: str) -> int:
    day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as session:
        return session.scalar(
            select(func.count())
            .select_from(Inbox)
            .where(
                Inbox.owner_username == owner_username,
                Inbox.inbox_mode == "temp",
                Inbox.created_at >= day_start,
            )
        ) or 0


def ensure_default_inboxes(owner_username: str, client_ip: str, domain: str) -> None:
    ensure_primary_inbox(owner_username, domain)
    ip_address = f"ip-{sanitize_ip_label(client_ip)}-{sanitize_local_part(owner_username)[:12]}@{domain}"
    ensure_inbox(
        ip_address,
        owner_username=owner_username,
        is_persistent=False,
        profile_name=f"IP Profil {client_ip}",
        profile_type="ip",
        inbox_mode="temp",
        source_ip=client_ip,
    )


def ensure_primary_inbox(owner_username: str, domain: str) -> None:
    local_part = sanitize_local_part(owner_username)
    normalized_domain = domain.strip().lower()
    if not local_part or not normalized_domain:
        return

    address = normalize_address(f"{local_part}@{normalized_domain}")
    now = datetime.utcnow()

    with SessionLocal() as session:
        inbox = session.scalar(select(Inbox).where(Inbox.address == address))
        if inbox is None:
            session.add(
                Inbox(
                    local_part=local_part,
                    domain=normalized_domain,
                    address=address,
                    owner_username=owner_username,
                    profile_name=address,
                    profile_type="primary",
                    inbox_mode="personal",
                    is_persistent=True,
                    requires_approval=False,
                    is_approved=True,
                    approved_at=now,
                    expires_at=None,
                )
            )
            session.commit()
            return

        if inbox.owner_username and inbox.owner_username != owner_username:
            return

        changed = False
        if inbox.owner_username != owner_username:
            inbox.owner_username = owner_username
            changed = True
        if inbox.profile_name != address:
            inbox.profile_name = address
            changed = True
        if inbox.profile_type != "primary":
            inbox.profile_type = "primary"
            changed = True
        if inbox.inbox_mode != "personal":
            inbox.inbox_mode = "personal"
            changed = True
        if not inbox.is_persistent:
            inbox.is_persistent = True
            changed = True
        if inbox.requires_approval:
            inbox.requires_approval = False
            changed = True
        if not inbox.is_approved:
            inbox.is_approved = True
            changed = True
        if inbox.approved_at is None:
            inbox.approved_at = now
            changed = True
        if inbox.expires_at is not None:
            inbox.expires_at = None
            changed = True

        if changed:
            session.commit()


def list_inboxes(owner_username: str) -> list[dict]:
    with SessionLocal() as session:
        inboxes = session.scalars(
            select(Inbox)
            .where(Inbox.owner_username == owner_username)
            .where((Inbox.expires_at.is_(None)) | (Inbox.expires_at > datetime.utcnow()))
            .order_by(desc(Inbox.is_persistent), desc(Inbox.created_at))
        ).all()
        return _inbox_payloads(session, inboxes)


def list_all_inboxes() -> list[dict]:
    with SessionLocal() as session:
        inboxes = session.scalars(
            select(Inbox)
            .where((Inbox.expires_at.is_(None)) | (Inbox.expires_at > datetime.utcnow()))
            .order_by(desc(Inbox.is_persistent), desc(Inbox.created_at))
        ).all()
        return _admin_inbox_payloads(session, inboxes)


def _trim_inbox_messages(session, address: str) -> None:
    if settings.max_messages_per_inbox <= 0:
        return

    inbox = session.scalar(select(Inbox).where(Inbox.address == address))
    if inbox and inbox.is_persistent:
        return
    if inbox and inbox.inbox_mode == "personal":
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
        expired_temp_addresses = select(Inbox.address).where(Inbox.expires_at.is_not(None), Inbox.expires_at < datetime.utcnow())
        session.execute(delete(Message).where(Message.inbox_address.in_(expired_temp_addresses)))
        session.execute(delete(Inbox).where(Inbox.expires_at.is_not(None), Inbox.expires_at < datetime.utcnow()))
        persistent_inboxes = select(Inbox.address).where(Inbox.is_persistent.is_(True))
        result = session.execute(
            delete(Message)
            .where(Message.received_at < cutoff)
            .where(Message.inbox_address.not_in(persistent_inboxes))
        )
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
            if content_type.startswith("multipart/"):
                continue

            try:
                payload = part.get_content()
            except KeyError:
                continue
            if not isinstance(payload, str):
                continue
            if content_type == "text/plain" and not text_body:
                text_body = payload
            if content_type == "text/html" and not html_body:
                html_body = payload
    else:
        try:
            payload = parsed.get_content()
        except KeyError:
            payload = ""
        if isinstance(payload, str):
            if parsed.get_content_type() == "text/html":
                html_body = payload
            else:
                text_body = payload

    if html_body:
        html_as_text = html_to_text(html_body)
        if len(html_as_text) > len(text_body):
            text_body = html_as_text

    sender_domain = split_address(mail_from or "unknown@sender")[1]
    codes = extract_codes(subject, text_body, html_body)
    links = extract_links(text_body, html_body)
    message_category = detect_message_category(sender_domain, subject, text_body)
    message_kind = detect_message_kind(subject, text_body, html_body, codes, links)
    verification_link = pick_verification_link(links)

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
                    sender_domain=sender_domain,
                    subject=subject,
                    message_category=message_category,
                    message_kind=message_kind,
                    verification_link=verification_link,
                    is_unread=True,
                    text_body=text_body,
                    html_body=html_body,
                    raw_headers=headers,
                )
            )
            session.flush()
            _trim_inbox_messages(session, normalized)
        session.commit()


def list_messages(owner_username: str, address: str) -> list[dict]:
    normalized = normalize_address(address)
    with SessionLocal() as session:
        inbox = session.scalar(select(Inbox).where(Inbox.address == normalized, Inbox.owner_username == owner_username))
        if inbox is None or (inbox.expires_at and inbox.expires_at <= datetime.utcnow()):
            return []
        messages = session.scalars(
            select(Message).where(Message.inbox_address == normalized).order_by(desc(Message.received_at))
        ).all()
        return [_message_payload(message) for message in messages]


def get_message(owner_username: str, message_id: int) -> dict | None:
    with SessionLocal() as session:
        message = session.get(Message, message_id)
        if message is None:
            return None
        inbox = session.scalar(select(Inbox).where(Inbox.address == message.inbox_address, Inbox.owner_username == owner_username))
        if inbox is None or (inbox.expires_at and inbox.expires_at <= datetime.utcnow()):
            return None
        message.is_unread = False
        session.commit()
        payload = {
            **_message_payload(message),
            "text_body": message.text_body,
            "html_body": message.html_body,
            "raw_headers": message.raw_headers,
        }
        return payload


def list_all_messages(limit: int = 100) -> list[dict]:
    with SessionLocal() as session:
        rows = session.execute(
            select(Message, Inbox)
            .join(Inbox, Inbox.address == Message.inbox_address, isouter=True)
            .where((Inbox.expires_at.is_(None)) | (Inbox.expires_at > datetime.utcnow()) | (Inbox.id.is_(None)))
            .order_by(desc(Message.received_at), desc(Message.id))
            .limit(limit)
        ).all()
        return [_admin_message_payload(message, inbox) for message, inbox in rows]


def get_admin_message(message_id: int) -> dict | None:
    with SessionLocal() as session:
        row = session.execute(
            select(Message, Inbox)
            .join(Inbox, Inbox.address == Message.inbox_address, isouter=True)
            .where(Message.id == message_id)
        ).first()
        if row is None:
            return None
        message, inbox = row
        payload = {
            **_admin_message_payload(message, inbox),
            "text_body": message.text_body,
            "html_body": message.html_body,
            "raw_headers": message.raw_headers,
        }
        return payload


def delete_admin_message(message_id: int) -> int:
    with SessionLocal() as session:
        result = session.execute(delete(Message).where(Message.id == message_id))
        session.commit()
        return result.rowcount or 0


def delete_inbox_messages(owner_username: str, address: str) -> int:
    normalized = normalize_address(address)
    with SessionLocal() as session:
        inbox = session.scalar(select(Inbox).where(Inbox.address == normalized, Inbox.owner_username == owner_username))
        if inbox is None or (inbox.expires_at and inbox.expires_at <= datetime.utcnow()):
            return 0
        result = session.execute(delete(Message).where(Message.inbox_address == normalized))
        session.commit()
        return result.rowcount or 0


def delete_message(owner_username: str, message_id: int) -> int:
    with SessionLocal() as session:
        message = session.get(Message, message_id)
        if message is None:
            return 0
        inbox = session.scalar(select(Inbox).where(Inbox.address == message.inbox_address, Inbox.owner_username == owner_username))
        if inbox is None or (inbox.expires_at and inbox.expires_at <= datetime.utcnow()):
            return 0
        result = session.execute(delete(Message).where(Message.id == message_id))
        session.commit()
        return result.rowcount or 0


def set_message_unread(owner_username: str, message_id: int, is_unread: bool) -> dict | None:
    with SessionLocal() as session:
        message = session.get(Message, message_id)
        if message is None:
            return None
        inbox = session.scalar(select(Inbox).where(Inbox.address == message.inbox_address, Inbox.owner_username == owner_username))
        if inbox is None or (inbox.expires_at and inbox.expires_at <= datetime.utcnow()):
            return None
        message.is_unread = is_unread
        session.commit()
        session.refresh(message)
        return _message_payload(message)


def counts() -> tuple[int, int]:
    with SessionLocal() as session:
        inbox_count = session.scalar(select(func.count()).select_from(Inbox)) or 0
        message_count = session.scalar(select(func.count()).select_from(Message)) or 0
        return inbox_count, message_count
