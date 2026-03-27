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
    create_api_key,
    ensure_bootstrap_admin,
    get_user_by_session,
    list_pending_users,
    list_api_keys,
    login_user,
    logout_session,
    register_user,
    revoke_api_key,
    require_admin,
    require_user,
)
from app.config import settings
from app.database import SessionLocal, init_db
from app.google_service import complete_google_oauth, create_google_alias, create_google_oauth_url, delete_google_account, google_enabled, list_google_accounts, list_google_aliases, list_google_recent_messages
from app.mail_service import (
    approve_personal_inbox,
    cleanup_expired_messages,
    counts,
    delete_admin_message,
    delete_inbox_messages,
    delete_message,
    ensure_default_inboxes,
    ensure_inbox,
    get_admin_message,
    get_message,
    is_domain_allowed,
    list_all_inboxes,
    list_all_messages,
    list_inboxes,
    list_pending_personal_inboxes,
    list_messages,
    normalize_address,
    set_message_unread,
    set_inbox_persistent,
    temp_inbox_creations_today,
)
from app.models import Inbox
from app.schemas import AdminInboxSummary, AdminMessageDetail, AdminMessagePreview, ApiKeyCreate, ApiKeyCreateResponse, ApiKeyResponse, AuthMessageResponse, AuthRequest, AuthStatusResponse, ConfigResponse, DeleteResponse, GoogleAccountResponse, GoogleAliasCreate, GoogleAliasResponse, GoogleConnectResponse, GoogleMessageResponse, HealthResponse, InboxCreate, InboxResponse, InboxSummary, InboxUpdate, MessageDetail, MessagePreview, MessageUpdate, PersonalInboxApproval, UserResponse
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


def template_user_payload(user: dict | None) -> dict | None:
    if user is None:
        return None
    payload = dict(user)
    for key in ("created_at", "approved_at"):
        value = payload.get(key)
        if value is not None:
            payload[key] = value.isoformat()
    return payload


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
            "temp_inbox_minutes": settings.temp_inbox_minutes,
            "temp_daily_limit": settings.temp_daily_limit,
            "current_user": template_user_payload(current_user),
            "admin_username": settings.admin_username,
            "google_enabled": google_enabled(),
        },
    )


@app.get("/guide", response_class=HTMLResponse)
async def guide(request: Request):
    current_user = get_user_by_session(request.cookies.get(SESSION_COOKIE))
    return templates.TemplateResponse(
        request,
        "docs.html",
        {
            "current_user": template_user_payload(current_user),
            "accepted_domains": settings.accepted_domains,
            "smtp_port": settings.smtp_port,
            "web_port": settings.web_port,
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


@app.get("/api/auth/api-keys", response_model=list[ApiKeyResponse])
async def auth_api_keys(user: dict = Depends(require_user)) -> list[ApiKeyResponse]:
    return [ApiKeyResponse(**item) for item in list_api_keys(user["username"])]


@app.post("/api/auth/api-keys", response_model=ApiKeyCreateResponse)
async def auth_create_api_key(payload: ApiKeyCreate, user: dict = Depends(require_user)) -> ApiKeyCreateResponse:
    try:
        api_key = create_api_key(user["username"], payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiKeyCreateResponse(api_key=ApiKeyResponse(**api_key), message="API key created")


@app.delete("/api/auth/api-keys/{api_key_id}", response_model=ApiKeyResponse)
async def auth_revoke_api_key(api_key_id: int, user: dict = Depends(require_user)) -> ApiKeyResponse:
    api_key = revoke_api_key(user["username"], api_key_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    return ApiKeyResponse(**api_key)


@app.get("/api/integrations/google/connect", response_model=GoogleConnectResponse)
async def google_connect(user: dict = Depends(require_user)) -> GoogleConnectResponse:
    try:
        url = create_google_oauth_url(user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GoogleConnectResponse(url=url)


@app.get("/api/integrations/google/callback", response_class=HTMLResponse)
async def google_callback(state: str, code: str):
    try:
        complete_google_oauth(state, code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HTMLResponse("<script>window.location='/?google=connected'</script>")


@app.get("/api/integrations/google/accounts", response_model=list[GoogleAccountResponse])
async def google_accounts(user: dict = Depends(require_user)) -> list[GoogleAccountResponse]:
    return [GoogleAccountResponse(**item) for item in list_google_accounts(user["username"])]


@app.post("/api/integrations/google/aliases", response_model=GoogleAliasResponse)
async def google_alias_create(payload: GoogleAliasCreate, user: dict = Depends(require_user)) -> GoogleAliasResponse:
    try:
        alias = create_google_alias(user["username"], payload.google_account_id, payload.name, payload.tag)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GoogleAliasResponse(**alias)


@app.get("/api/integrations/google/aliases", response_model=list[GoogleAliasResponse])
async def google_aliases(user: dict = Depends(require_user)) -> list[GoogleAliasResponse]:
    return [GoogleAliasResponse(**item) for item in list_google_aliases(user["username"])]


@app.get("/api/integrations/google/messages", response_model=list[GoogleMessageResponse])
async def google_messages(user: dict = Depends(require_user)) -> list[GoogleMessageResponse]:
    return [GoogleMessageResponse(**item) for item in list_google_recent_messages(user["username"])]


@app.delete("/api/integrations/google/accounts/{google_account_id}", response_model=DeleteResponse)
async def google_account_delete(google_account_id: int, user: dict = Depends(require_user)) -> DeleteResponse:
    return DeleteResponse(deleted=delete_google_account(user["username"], google_account_id))


@app.get("/api/admin/users", response_model=list[UserResponse])
async def admin_users(_: dict = Depends(require_admin)) -> list[UserResponse]:
    return [UserResponse(**item) for item in list_pending_users()]


@app.post("/api/admin/users/{user_id}/approve", response_model=UserResponse)
async def admin_approve_user(user_id: int, _: dict = Depends(require_admin)) -> UserResponse:
    user = approve_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**user)


@app.get("/api/admin/inboxes/pending-personal", response_model=list[PersonalInboxApproval])
async def admin_pending_personal_inboxes(_: dict = Depends(require_admin)) -> list[PersonalInboxApproval]:
    return [PersonalInboxApproval(**item) for item in list_pending_personal_inboxes()]


@app.post("/api/admin/inboxes/{inbox_id}/approve-personal", response_model=InboxSummary)
async def admin_approve_personal_inbox(inbox_id: int, _: dict = Depends(require_admin)) -> InboxSummary:
    inbox = approve_personal_inbox(inbox_id)
    if inbox is None:
        raise HTTPException(status_code=404, detail="Inbox not found")
    return InboxSummary(**inbox)


@app.get("/api/admin/inboxes/all", response_model=list[AdminInboxSummary])
async def admin_all_inboxes(_: dict = Depends(require_admin)) -> list[AdminInboxSummary]:
    return [AdminInboxSummary(**item) for item in list_all_inboxes()]


@app.get("/api/admin/messages/recent", response_model=list[AdminMessagePreview])
async def admin_recent_messages(_: dict = Depends(require_admin)) -> list[AdminMessagePreview]:
    return [AdminMessagePreview(**item) for item in list_all_messages()]


@app.get("/api/admin/messages/{message_id}", response_model=AdminMessageDetail)
async def admin_message_detail(message_id: int, _: dict = Depends(require_admin)) -> AdminMessageDetail:
    message = get_admin_message(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return AdminMessageDetail(**message)


@app.delete("/api/admin/messages/{message_id}", response_model=DeleteResponse)
async def admin_remove_message(message_id: int, _: dict = Depends(require_admin)) -> DeleteResponse:
    deleted = delete_admin_message(message_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Message not found")
    return DeleteResponse(deleted=deleted)


@app.get("/api/config", response_model=ConfigResponse)
async def config(_: dict = Depends(require_user)) -> ConfigResponse:
    return ConfigResponse(
        accepted_domains=settings.accepted_domains,
        allow_any_domain=settings.allow_any_domain,
        poll_seconds=settings.poll_seconds,
        message_ttl_hours=settings.message_ttl_hours,
        temp_inbox_minutes=settings.temp_inbox_minutes,
        temp_daily_limit=settings.temp_daily_limit,
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
async def create_inbox(payload: InboxCreate, user: dict = Depends(require_user)) -> InboxResponse:
    domain = (payload.domain or (settings.accepted_domains[0] if settings.accepted_domains else "temp.local")).lower()
    if not is_domain_allowed(domain):
        raise HTTPException(status_code=400, detail="Domain is not allowed")

    if payload.inbox_mode == "temp" and not user["is_admin"]:
        temp_count = temp_inbox_creations_today(user["username"])
        if temp_count >= settings.temp_daily_limit:
            raise HTTPException(status_code=429, detail=f"Gunluk temp mail limiti doldu ({settings.temp_daily_limit})")

    local_part = generate_local_part() if payload.inbox_mode == "temp" else (payload.local_part or generate_local_part()).strip().lower()
    address = normalize_address(f"{local_part}@{domain}")
    try:
        inbox = ensure_inbox(
            address,
            owner_username=user["username"],
            is_persistent=payload.is_persistent,
            profile_name=payload.profile_name or ("Temp Profil" if payload.inbox_mode == "temp" else f"{local_part}@{domain}"),
            profile_type="manual",
            inbox_mode=payload.inbox_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if payload.is_persistent and not inbox.is_persistent:
        inbox = set_inbox_persistent(address, user["username"], True) or inbox
    return InboxResponse(
        local_part=inbox.local_part,
        domain=inbox.domain,
        address=inbox.address,
        profile_name=inbox.profile_name,
        profile_type=inbox.profile_type,
        inbox_mode=inbox.inbox_mode,
        is_persistent=inbox.is_persistent,
        requires_approval=inbox.requires_approval,
        is_approved=inbox.is_approved,
        approved_at=inbox.approved_at,
        expires_at=inbox.expires_at,
        created_at=inbox.created_at,
    )


@app.get("/api/inboxes", response_model=list[InboxSummary])
async def inbox_index(request: Request, user: dict = Depends(require_user)) -> list[InboxSummary]:
    ensure_default_inboxes(user["username"], request.client.host if request.client else "unknown", settings.accepted_domains[0])
    return [InboxSummary(**item) for item in list_inboxes(user["username"])]


@app.get("/api/inboxes/{address:path}/messages", response_model=list[MessagePreview])
async def inbox_messages(address: str, user: dict = Depends(require_user)) -> list[MessagePreview]:
    return [MessagePreview(**item) for item in list_messages(user["username"], address)]


@app.get("/api/inboxes/{address:path}", response_model=InboxResponse)
async def get_inbox(address: str, user: dict = Depends(require_user)) -> InboxResponse:
    normalized = normalize_address(address)
    with SessionLocal() as session:
        inbox = session.scalar(select(Inbox).where(Inbox.address == normalized, Inbox.owner_username == user["username"]))
        if inbox is None:
            raise HTTPException(status_code=404, detail="Inbox not found")
        return InboxResponse(local_part=inbox.local_part, domain=inbox.domain, address=inbox.address, profile_name=inbox.profile_name, profile_type=inbox.profile_type, inbox_mode=inbox.inbox_mode, is_persistent=inbox.is_persistent, requires_approval=inbox.requires_approval, is_approved=inbox.is_approved, approved_at=inbox.approved_at, expires_at=inbox.expires_at, created_at=inbox.created_at)


@app.patch("/api/inboxes/{address:path}", response_model=InboxResponse)
async def update_inbox(address: str, payload: InboxUpdate, user: dict = Depends(require_user)) -> InboxResponse:
    inbox = set_inbox_persistent(address, user["username"], payload.is_persistent)
    if inbox is None:
        raise HTTPException(status_code=404, detail="Inbox not found")
    return InboxResponse(local_part=inbox.local_part, domain=inbox.domain, address=inbox.address, profile_name=inbox.profile_name, profile_type=inbox.profile_type, inbox_mode=inbox.inbox_mode, is_persistent=inbox.is_persistent, requires_approval=inbox.requires_approval, is_approved=inbox.is_approved, approved_at=inbox.approved_at, expires_at=inbox.expires_at, created_at=inbox.created_at)


@app.get("/api/messages/{message_id}", response_model=MessageDetail)
async def message_detail(message_id: int, user: dict = Depends(require_user)) -> MessageDetail:
    message = get_message(user["username"], message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return MessageDetail(**message)


@app.delete("/api/inboxes/{address:path}/messages", response_model=DeleteResponse)
async def purge_inbox(address: str, user: dict = Depends(require_user)) -> DeleteResponse:
    return DeleteResponse(deleted=delete_inbox_messages(user["username"], address))


@app.delete("/api/messages/{message_id}", response_model=DeleteResponse)
async def remove_message(message_id: int, user: dict = Depends(require_user)) -> DeleteResponse:
    deleted = delete_message(user["username"], message_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Message not found")
    return DeleteResponse(deleted=deleted)


@app.patch("/api/messages/{message_id}", response_model=MessagePreview)
async def update_message(message_id: int, payload: MessageUpdate, user: dict = Depends(require_user)) -> MessagePreview:
    message = set_message_unread(user["username"], message_id, payload.is_unread)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return MessagePreview(**message)
