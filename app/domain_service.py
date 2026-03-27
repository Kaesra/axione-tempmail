from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import BlockedDomain


BLOCKED_DOMAIN_CACHE_TTL_SECONDS = 10
_blocked_domain_cache: tuple[datetime, set[str]] | None = None


def normalize_domain(value: str) -> str:
    domain = value.strip().lower().lstrip("@").rstrip(".")
    return domain


def _clear_blocked_domain_cache() -> None:
    global _blocked_domain_cache
    _blocked_domain_cache = None


def blocked_domain_names(force_refresh: bool = False) -> set[str]:
    global _blocked_domain_cache
    now = datetime.utcnow()
    if not force_refresh and _blocked_domain_cache is not None:
        cached_at, cached_domains = _blocked_domain_cache
        if now - cached_at < timedelta(seconds=BLOCKED_DOMAIN_CACHE_TTL_SECONDS):
            return set(cached_domains)

    with SessionLocal() as session:
        domains = {
            item.domain
            for item in session.scalars(select(BlockedDomain).order_by(BlockedDomain.domain)).all()
        }
    _blocked_domain_cache = (now, domains)
    return set(domains)


def available_domains() -> list[str]:
    blocked = blocked_domain_names()
    return [domain for domain in settings.accepted_domains if domain not in blocked]


def default_domain() -> str:
    domains = available_domains()
    return domains[0] if domains else ""


def list_blocked_domains() -> list[dict]:
    with SessionLocal() as session:
        rows = session.scalars(select(BlockedDomain).order_by(BlockedDomain.domain)).all()
        return [
            {
                "id": row.id,
                "domain": row.domain,
                "reason": row.reason,
                "created_at": row.created_at,
            }
            for row in rows
        ]


def upsert_blocked_domain(domain: str, reason: str = "") -> dict:
    normalized = normalize_domain(domain)
    if not normalized:
        raise ValueError("Domain is required")
    with SessionLocal() as session:
        row = session.scalar(select(BlockedDomain).where(BlockedDomain.domain == normalized))
        if row is None:
            row = BlockedDomain(domain=normalized, reason=reason.strip()[:255])
            session.add(row)
        else:
            row.reason = reason.strip()[:255]
        session.commit()
        session.refresh(row)
        payload = {
            "id": row.id,
            "domain": row.domain,
            "reason": row.reason,
            "created_at": row.created_at,
        }
    _clear_blocked_domain_cache()
    return payload


def delete_blocked_domain(domain: str) -> int:
    normalized = normalize_domain(domain)
    if not normalized:
        return 0
    with SessionLocal() as session:
        row = session.scalar(select(BlockedDomain).where(BlockedDomain.domain == normalized))
        if row is None:
            return 0
        session.delete(row)
        session.commit()
    _clear_blocked_domain_cache()
    return 1
