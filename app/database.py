from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
engine = create_engine(settings.db_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _sqlite_has_unique_local_part(connection) -> bool:
    rows = connection.execute(text("PRAGMA index_list('inboxes')")).fetchall()
    for row in rows:
        is_unique = bool(row[2])
        if not is_unique:
            continue
        index_name = row[1]
        columns = [item[2] for item in connection.execute(text(f"PRAGMA index_info('{index_name}')")).fetchall()]
        if columns == ["local_part"]:
            return True
    return False


def _rebuild_inboxes_table_without_local_part_unique(connection) -> None:
    connection.execute(text("ALTER TABLE inboxes RENAME TO inboxes_legacy"))
    connection.execute(
        text(
            "CREATE TABLE inboxes ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "local_part VARCHAR(120) NOT NULL, "
            "domain VARCHAR(255) NOT NULL, "
            "address VARCHAR(255) NOT NULL, "
            "owner_username VARCHAR(120) NOT NULL DEFAULT '', "
            "profile_name VARCHAR(120) NOT NULL DEFAULT 'Inbox', "
            "profile_type VARCHAR(50) NOT NULL DEFAULT 'manual', "
            "inbox_mode VARCHAR(30) NOT NULL DEFAULT 'temp', "
            "source_ip VARCHAR(120) NOT NULL DEFAULT '', "
            "is_persistent BOOLEAN NOT NULL DEFAULT 0, "
            "requires_approval BOOLEAN NOT NULL DEFAULT 0, "
            "is_approved BOOLEAN NOT NULL DEFAULT 1, "
            "approved_at DATETIME, "
            "expires_at DATETIME, "
            "created_at DATETIME NOT NULL, "
            "UNIQUE(address)"
            ")"
        )
    )
    connection.execute(
        text(
            "INSERT INTO inboxes ("
            "id, local_part, domain, address, owner_username, profile_name, profile_type, inbox_mode, source_ip, "
            "is_persistent, requires_approval, is_approved, approved_at, expires_at, created_at"
            ") "
            "SELECT "
            "id, local_part, domain, address, owner_username, profile_name, profile_type, inbox_mode, source_ip, "
            "is_persistent, requires_approval, is_approved, approved_at, expires_at, created_at "
            "FROM inboxes_legacy"
        )
    )
    connection.execute(text("DROP TABLE inboxes_legacy"))


def init_db() -> None:
    from app import models

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    inbox_columns = {column["name"] for column in inspector.get_columns("inboxes")}
    message_columns = {column["name"] for column in inspector.get_columns("messages")}
    google_account_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        if settings.db_url.startswith("sqlite") and _sqlite_has_unique_local_part(connection):
            _rebuild_inboxes_table_without_local_part_unique(connection)
            inspector = inspect(engine)
            inbox_columns = {column["name"] for column in inspector.get_columns("inboxes")}
            message_columns = {column["name"] for column in inspector.get_columns("messages")}
            google_account_tables = set(inspector.get_table_names())
        if "local_part" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN local_part VARCHAR(120) DEFAULT ''"))
        if "domain" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN domain VARCHAR(255) DEFAULT ''"))
        if "owner_username" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN owner_username VARCHAR(120) DEFAULT ''"))
        if "profile_name" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN profile_name VARCHAR(120) DEFAULT 'Inbox'"))
        if "profile_type" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN profile_type VARCHAR(50) DEFAULT 'manual'"))
        if "inbox_mode" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN inbox_mode VARCHAR(30) DEFAULT 'temp'"))
        if "source_ip" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN source_ip VARCHAR(120) DEFAULT ''"))
        if "is_persistent" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN is_persistent BOOLEAN DEFAULT 0"))
        if "requires_approval" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN requires_approval BOOLEAN DEFAULT 0"))
        if "is_approved" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN is_approved BOOLEAN DEFAULT 1"))
        if "approved_at" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN approved_at DATETIME"))
        if "expires_at" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN expires_at DATETIME"))
        if "sender_domain" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN sender_domain VARCHAR(255) DEFAULT ''"))
        if "message_category" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN message_category VARCHAR(50) DEFAULT 'primary'"))
        if "message_kind" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN message_kind VARCHAR(50) DEFAULT 'general'"))
        if "verification_link" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN verification_link VARCHAR(1000) DEFAULT ''"))
        if "is_unread" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN is_unread BOOLEAN DEFAULT 1"))
        connection.execute(
            text(
                "UPDATE inboxes SET local_part = lower(substr(address, 1, instr(address, '@') - 1)) "
                "WHERE local_part = '' OR local_part IS NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE inboxes SET domain = lower(substr(address, instr(address, '@') + 1)) "
                "WHERE domain = '' OR domain IS NULL"
            )
        )
        connection.execute(text("UPDATE inboxes SET inbox_mode = 'personal' WHERE profile_type = 'personal' AND (inbox_mode = '' OR inbox_mode IS NULL OR inbox_mode = 'temp')"))
        connection.execute(text("UPDATE inboxes SET inbox_mode = 'temp' WHERE inbox_mode = '' OR inbox_mode IS NULL"))
        connection.execute(text("UPDATE inboxes SET is_approved = 1 WHERE is_approved IS NULL"))
        if "google_accounts" in google_account_tables:
            google_account_columns = {column["name"] for column in inspector.get_columns("google_accounts")}
            if "scopes" not in google_account_columns:
                connection.execute(text("ALTER TABLE google_accounts ADD COLUMN scopes TEXT DEFAULT ''"))
            if "token_expires_at" not in google_account_columns:
                connection.execute(text("ALTER TABLE google_accounts ADD COLUMN token_expires_at DATETIME"))
            if "last_sync_at" not in google_account_columns:
                connection.execute(text("ALTER TABLE google_accounts ADD COLUMN last_sync_at DATETIME"))
        if "google_aliases" in google_account_tables:
            google_alias_columns = {column["name"] for column in inspector.get_columns("google_aliases")}
            if "is_temp" not in google_alias_columns:
                connection.execute(text("ALTER TABLE google_aliases ADD COLUMN is_temp BOOLEAN DEFAULT 1"))
            if "auto_generated" not in google_alias_columns:
                connection.execute(text("ALTER TABLE google_aliases ADD COLUMN auto_generated BOOLEAN DEFAULT 1"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_inboxes_local_part ON inboxes (local_part)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_inboxes_domain ON inboxes (domain)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_inboxes_owner_expires_created ON inboxes (owner_username, expires_at, created_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_inboxes_expires_persistent_created ON inboxes (expires_at, is_persistent, created_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_inbox_received ON messages (inbox_address, received_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_inbox_unread ON messages (inbox_address, is_unread)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_inbox_kind ON messages (inbox_address, message_kind)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_google_accounts_username_created ON google_accounts (username, created_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_google_aliases_account_created ON google_aliases (google_account_id, created_at)"))
