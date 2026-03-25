from __future__ import annotations

import re
import secrets
import string


CODE_PATTERN = re.compile(r"\b(?:\d{4,8}|[A-Z0-9]{6,10})\b")


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
