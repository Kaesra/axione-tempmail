from __future__ import annotations

import re
import secrets
import string
from html import unescape
from html.parser import HTMLParser


CODE_PATTERN = re.compile(r"\b(?:\d{4,8}|[A-Z0-9]{6,10})\b")
LINK_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

VERIFICATION_HINTS = (
    "verify",
    "verification",
    "confirm",
    "confirmation",
    "login",
    "sign in",
    "signin",
    "one-time",
    "otp",
    "code",
    "security",
    "magic link",
    "reset",
    "password",
    "activate",
    "2fa",
    "two-factor",
    "auth",
)

LINK_HINTS = ("verify", "confirm", "activate", "auth", "magic", "token", "reset", "password", "login")
SOCIAL_DOMAINS = ("facebook", "instagram", "tiktok", "x.com", "twitter", "discord", "telegram", "linkedin", "snapchat")
SPAM_HINTS = ("casino", "bonus", "win", "prize", "airdrop", "crypto", "gift", "bet", "loan", "investment")
UPDATE_DOMAINS = ("github", "notion", "slack", "jira", "atlassian", "google", "microsoft", "steam")


class HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
        if tag in {"br", "p", "div", "li", "tr", "table", "section"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "div", "li", "tr", "table", "section"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data.strip():
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(part.strip() for part in self._parts if part.strip())


def generate_local_part(length: int = 10) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "tmp-" + "".join(secrets.choice(alphabet) for _ in range(length))


def extract_codes(*parts: str) -> list[str]:
    seen: list[str] = []
    for part in parts:
        for code in CODE_PATTERN.findall(part or ""):
            if code not in seen:
                seen.append(code)
    return seen[:10]


def extract_links(*parts: str) -> list[str]:
    seen: list[str] = []
    for part in parts:
        for link in LINK_PATTERN.findall(part or ""):
            cleaned = link.rstrip(").,]>")
            if cleaned not in seen:
                seen.append(cleaned)
    return seen[:20]


def html_to_text(html: str) -> str:
    if not html:
        return ""
    parser = HTMLTextExtractor()
    parser.feed(unescape(html))
    parser.close()
    return summarize_text(parser.get_text(), limit=4000)


def detect_message_kind(subject: str, text_body: str, html_body: str, codes: list[str], links: list[str]) -> str:
    haystack = " ".join([subject or "", text_body or "", html_body or ""]).lower()
    has_verification_words = any(keyword in haystack for keyword in VERIFICATION_HINTS)
    has_verification_link = any(any(hint in link.lower() for hint in LINK_HINTS) for link in links)
    if has_verification_words or has_verification_link:
        if "reset" in haystack or "password" in haystack:
            return "password_reset"
        if "magic link" in haystack or "sign in" in haystack or "login" in haystack:
            return "login_link"
        return "verification"
    if codes:
        return "code"
    return "general"


def detect_message_category(sender_domain: str, subject: str, text_body: str) -> str:
    sender = (sender_domain or "").lower()
    haystack = f"{subject} {text_body}".lower()
    if any(item in sender for item in SOCIAL_DOMAINS):
        return "social"
    if any(item in sender for item in UPDATE_DOMAINS):
        return "updates"
    if any(item in haystack for item in SPAM_HINTS):
        return "spam"
    return "primary"


def pick_verification_link(links: list[str]) -> str:
    for link in links:
        lower = link.lower()
        if any(hint in lower for hint in LINK_HINTS):
            return link
    return links[0] if links else ""


def summarize_text(*parts: str, limit: int = 160) -> str:
    raw = " ".join(part or "" for part in parts)
    cleaned = re.sub(r"\s+", " ", raw).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "..."
