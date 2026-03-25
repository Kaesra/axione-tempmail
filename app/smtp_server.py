from __future__ import annotations

from aiosmtpd.controller import Controller

from app.config import settings
from app.mail_service import is_domain_allowed, save_message, split_address


class TempMailHandler:
    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        _, domain = split_address(address)
        if not is_domain_allowed(domain):
            return "550 mailbox unavailable"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        save_message(envelope.mail_from, envelope.rcpt_tos, envelope.content)
        return "250 Message accepted"


class SMTPServer:
    def __init__(self) -> None:
        self.controller = Controller(
            TempMailHandler(),
            hostname=settings.smtp_host,
            port=settings.smtp_port,
        )

    def start(self) -> None:
        self.controller.start()

    def stop(self) -> None:
        self.controller.stop()
