from __future__ import annotations

import os
import platform
import shutil
import socket
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def save_env_file(path: Path, values: dict[str, str]) -> None:
    lines = [f"{key}={value}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def is_port_free(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def is_privileged_context() -> bool:
    if os.name != "nt":
        geteuid = getattr(os, "geteuid", None)
        return bool(geteuid and geteuid() == 0)
    return is_port_free(25)


def pick_port(preferred: list[int], fallback_start: int) -> int:
    for port in preferred:
        if is_port_free(port):
            return port
    port = fallback_start
    while port < fallback_start + 200:
        if is_port_free(port):
            return port
        port += 1
    raise RuntimeError("No free port found")


def main() -> None:
    created_env = False
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
        created_env = True

    values = load_env_file(ENV_FILE)

    if created_env or not values.get("TEMPMAIL_WEB_PORT"):
        values["TEMPMAIL_WEB_PORT"] = str(pick_port([8080, 8081, 3000], 8082))

    if created_env or not values.get("TEMPMAIL_SMTP_PORT"):
        smtp_candidates = [25, 2525] if is_privileged_context() else [2525, 2526, 2527]
        values["TEMPMAIL_SMTP_PORT"] = str(pick_port(smtp_candidates, 2600))

    values.setdefault("TEMPMAIL_DB_URL", "sqlite:///./tempmail.db")
    values.setdefault("TEMPMAIL_WEB_HOST", "0.0.0.0")
    values.setdefault("TEMPMAIL_SMTP_HOST", "0.0.0.0")
    values.setdefault("TEMPMAIL_ACCEPTED_DOMAINS", "axione.xyz")
    values.setdefault("TEMPMAIL_ALLOW_ANY_DOMAIN", "false")
    values.setdefault("TEMPMAIL_POLL_SECONDS", "8")
    values.setdefault("TEMPMAIL_MESSAGE_TTL_HOURS", "24")
    values.setdefault("TEMPMAIL_MAX_MESSAGES_PER_INBOX", "100")
    values.setdefault("TEMPMAIL_MAX_INBOXES", "10000")

    save_env_file(ENV_FILE, values)

    print(f"Platform: {platform.system()}")
    print(f"Web port: {values['TEMPMAIL_WEB_PORT']}")
    print(f"SMTP port: {values['TEMPMAIL_SMTP_PORT']}")
    print(f"Env file: {ENV_FILE}")


if __name__ == "__main__":
    main()
