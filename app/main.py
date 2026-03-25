from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal, init_db
from app.mail_service import (
    cleanup_expired_messages,
    counts,
    delete_inbox_messages,
    delete_message,
    ensure_inbox,
    get_message,
    is_domain_allowed,
    list_inboxes,
    list_messages,
    normalize_address,
    set_inbox_persistent,
)
from app.models import Inbox
from app.schemas import ConfigResponse, DeleteResponse, HealthResponse, InboxCreate, InboxResponse, InboxSummary, InboxUpdate, MessageDetail, MessagePreview
from app.smtp_server import SMTPServer
from app.utils import generate_local_part


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
smtp_server = SMTPServer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    cleanup_expired_messages()
    smtp_server.start()
    try:
        yield
    finally:
        smtp_server.stop()


app = FastAPI(title="Temp Mail", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "accepted_domains": settings.accepted_domains,
            "allow_any_domain": settings.allow_any_domain,
            "poll_seconds": settings.poll_seconds,
        },
    )


@app.get("/api/config", response_model=ConfigResponse)
async def config() -> ConfigResponse:
    return ConfigResponse(
        accepted_domains=settings.accepted_domains,
        allow_any_domain=settings.allow_any_domain,
        poll_seconds=settings.poll_seconds,
        message_ttl_hours=settings.message_ttl_hours,
        max_messages_per_inbox=settings.max_messages_per_inbox,
    )


@app.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    inbox_count, message_count = counts()
    return HealthResponse(
        status="ok",
        smtp_port=settings.smtp_port,
        inbox_count=inbox_count,
        message_count=message_count,
    )


@app.post("/api/inboxes", response_model=InboxResponse)
async def create_inbox(payload: InboxCreate) -> InboxResponse:
    domain = (payload.domain or (settings.accepted_domains[0] if settings.accepted_domains else "temp.local")).lower()
    if not is_domain_allowed(domain):
        raise HTTPException(status_code=400, detail="Domain is not allowed")

    local_part = (payload.local_part or generate_local_part()).strip().lower()
    address = normalize_address(f"{local_part}@{domain}")
    try:
        inbox = ensure_inbox(address)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if payload.is_persistent and not inbox.is_persistent:
        inbox = set_inbox_persistent(address, True) or inbox
    return InboxResponse(address=inbox.address, is_persistent=inbox.is_persistent, created_at=inbox.created_at)


@app.get("/api/inboxes", response_model=list[InboxSummary])
async def inbox_index() -> list[InboxSummary]:
    return [InboxSummary(**item) for item in list_inboxes()]


@app.get("/api/inboxes/{address:path}/messages", response_model=list[MessagePreview])
async def inbox_messages(address: str) -> list[MessagePreview]:
    return [MessagePreview(**item) for item in list_messages(address)]


@app.get("/api/inboxes/{address:path}", response_model=InboxResponse)
async def get_inbox(address: str) -> InboxResponse:
    normalized = normalize_address(address)
    with SessionLocal() as session:
        inbox = session.scalar(select(Inbox).where(Inbox.address == normalized))
        if inbox is None:
            raise HTTPException(status_code=404, detail="Inbox not found")
        return InboxResponse(address=inbox.address, is_persistent=inbox.is_persistent, created_at=inbox.created_at)


@app.patch("/api/inboxes/{address:path}", response_model=InboxResponse)
async def update_inbox(address: str, payload: InboxUpdate) -> InboxResponse:
    inbox = set_inbox_persistent(address, payload.is_persistent)
    if inbox is None:
        raise HTTPException(status_code=404, detail="Inbox not found")
    return InboxResponse(address=inbox.address, is_persistent=inbox.is_persistent, created_at=inbox.created_at)


@app.get("/api/messages/{message_id}", response_model=MessageDetail)
async def message_detail(message_id: int) -> MessageDetail:
    message = get_message(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return MessageDetail(**message)


@app.delete("/api/inboxes/{address:path}/messages", response_model=DeleteResponse)
async def purge_inbox(address: str) -> DeleteResponse:
    return DeleteResponse(deleted=delete_inbox_messages(address))


@app.delete("/api/messages/{message_id}", response_model=DeleteResponse)
async def remove_message(message_id: int) -> DeleteResponse:
    deleted = delete_message(message_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Message not found")
    return DeleteResponse(deleted=deleted)
