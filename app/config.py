from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    db_url: str = os.getenv("TEMPMAIL_DB_URL", "sqlite:///./tempmail.db")
    web_host: str = os.getenv("TEMPMAIL_WEB_HOST", "0.0.0.0")
    web_port: int = int(os.getenv("TEMPMAIL_WEB_PORT", "8080"))
    smtp_host: str = os.getenv("TEMPMAIL_SMTP_HOST", "0.0.0.0")
    smtp_port: int = int(os.getenv("TEMPMAIL_SMTP_PORT", "25"))
    accepted_domains_raw: str = os.getenv("TEMPMAIL_ACCEPTED_DOMAINS", "axione.xyz")
    allow_any_domain: bool = _bool("TEMPMAIL_ALLOW_ANY_DOMAIN", False)
    poll_seconds: int = int(os.getenv("TEMPMAIL_POLL_SECONDS", "8"))
    message_ttl_hours: int = int(os.getenv("TEMPMAIL_MESSAGE_TTL_HOURS", "24"))
    temp_inbox_minutes: int = int(os.getenv("TEMPMAIL_TEMP_INBOX_MINUTES", "5"))
    temp_daily_limit: int = int(os.getenv("TEMPMAIL_TEMP_DAILY_LIMIT", "3"))
    max_messages_per_inbox: int = int(os.getenv("TEMPMAIL_MAX_MESSAGES_PER_INBOX", "100"))
    max_inboxes: int = int(os.getenv("TEMPMAIL_MAX_INBOXES", "10000"))
    session_hours: int = int(os.getenv("TEMPMAIL_SESSION_HOURS", "72"))
    secure_cookies: bool = _bool("TEMPMAIL_SECURE_COOKIES", False)
    admin_username: str = os.getenv("TEMPMAIL_ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("TEMPMAIL_ADMIN_PASSWORD", "change-me-now")
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_oauth_redirect_uri: str = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8080/api/integrations/google/callback")

    @property
    def accepted_domains(self) -> list[str]:
        return [item.strip().lower() for item in self.accepted_domains_raw.split(",") if item.strip()]


settings = Settings()
