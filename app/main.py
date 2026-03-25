from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.auth_service import (
    SESSION_COOKIE,
    approve_user,
    ensure_bootstrap_admin,
    get_user_by_session,
    list_pending_users,
    login_user,
    logout_session,
    register_user,
    require_admin,
    require_user,
)
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
    set_message_unread,
    set_inbox_persistent,
)
from app.models import Inbox
from app.schemas import AuthMessageResponse, AuthRequest, AuthStatusResponse, ConfigResponse, DeleteResponse, HealthResponse, InboxCreate, InboxResponse, InboxSummary, InboxUpdate, MessageDetail, MessagePreview, MessageUpdate, UserResponse
from app.smtp_server import SMTPServer
from app.utils import generate_local_part


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
smtp_server = SMTPServer()


def user_response_payload(user) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        is_approved=user.is_approved,
        created_at=user.created_at,
        approved_at=user.approved_at,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_bootstrap_admin()
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
    current_user = get_user_by_session(request.cookies.get(SESSION_COOKIE))
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "accepted_domains": settings.accepted_domains,
            "allow_any_domain": settings.allow_any_domain,
            "poll_seconds": settings.poll_seconds,
            "current_user": current_user,
        },
    )


@app.post("/api/auth/register", response_model=AuthMessageResponse)
async def auth_register(payload: AuthRequest) -> AuthMessageResponse:
    try:
        user = register_user(payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AuthMessageResponse(message="Registration created. Waiting for admin approval.", user=user_response_payload(user))


@app.post("/api/auth/login", response_model=AuthMessageResponse)
async def auth_login(payload: AuthRequest, response: Response) -> AuthMessageResponse:
    try:
        user, token = login_user(payload.username, payload.password)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=settings.secure_cookies, max_age=settings.session_hours * 3600)
    return AuthMessageResponse(message="Login successful", user=user_response_payload(user))


@app.post("/api/auth/logout", response_model=AuthMessageResponse)
async def auth_logout(request: Request, response: Response) -> AuthMessageResponse:
    logout_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE)
    return AuthMessageResponse(message="Logged out", user=None)


@app.get("/api/auth/me", response_model=AuthStatusResponse)
async def auth_me(request: Request) -> AuthStatusResponse:
    user = get_user_by_session(request.cookies.get(SESSION_COOKIE))
    return AuthStatusResponse(user=UserResponse(**user) if user else None)


@app.get("/api/admin/users", response_model=list[UserResponse])
async def admin_users(_: dict = Depends(require_admin)) -> list[UserResponse]:
    return [UserResponse(**item) for item in list_pending_users()]


@app.post("/api/admin/users/{user_id}/approve", response_model=UserResponse)
async def admin_approve_user(user_id: int, _: dict = Depends(require_admin)) -> UserResponse:
    user = approve_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**user)


@app.get("/api/config", response_model=ConfigResponse)
async def config(_: dict = Depends(require_user)) -> ConfigResponse:
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
async def create_inbox(payload: InboxCreate, _: dict = Depends(require_user)) -> InboxResponse:
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
async def inbox_index(_: dict = Depends(require_user)) -> list[InboxSummary]:
    return [InboxSummary(**item) for item in list_inboxes()]


@app.get("/api/inboxes/{address:path}/messages", response_model=list[MessagePreview])
async def inbox_messages(address: str, _: dict = Depends(require_user)) -> list[MessagePreview]:
    return [MessagePreview(**item) for item in list_messages(address)]


@app.get("/api/inboxes/{address:path}", response_model=InboxResponse)
async def get_inbox(address: str, _: dict = Depends(require_user)) -> InboxResponse:
    normalized = normalize_address(address)
    with SessionLocal() as session:
        inbox = session.scalar(select(Inbox).where(Inbox.address == normalized))
        if inbox is None:
            raise HTTPException(status_code=404, detail="Inbox not found")
        return InboxResponse(address=inbox.address, is_persistent=inbox.is_persistent, created_at=inbox.created_at)


@app.patch("/api/inboxes/{address:path}", response_model=InboxResponse)
async def update_inbox(address: str, payload: InboxUpdate, _: dict = Depends(require_user)) -> InboxResponse:
    inbox = set_inbox_persistent(address, payload.is_persistent)
    if inbox is None:
        raise HTTPException(status_code=404, detail="Inbox not found")
    return InboxResponse(address=inbox.address, is_persistent=inbox.is_persistent, created_at=inbox.created_at)


@app.get("/api/messages/{message_id}", response_model=MessageDetail)
async def message_detail(message_id: int, _: dict = Depends(require_user)) -> MessageDetail:
    message = get_message(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return MessageDetail(**message)


@app.delete("/api/inboxes/{address:path}/messages", response_model=DeleteResponse)
async def purge_inbox(address: str, _: dict = Depends(require_user)) -> DeleteResponse:
    return DeleteResponse(deleted=delete_inbox_messages(address))


@app.delete("/api/messages/{message_id}", response_model=DeleteResponse)
async def remove_message(message_id: int, _: dict = Depends(require_user)) -> DeleteResponse:
    deleted = delete_message(message_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Message not found")
    return DeleteResponse(deleted=deleted)


@app.patch("/api/messages/{message_id}", response_model=MessagePreview)
async def update_message(message_id: int, payload: MessageUpdate, _: dict = Depends(require_user)) -> MessagePreview:
    message = set_message_unread(message_id, payload.is_unread)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return MessagePreview(**message)
