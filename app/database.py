from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
engine = create_engine(settings.db_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    from app import models

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    inbox_columns = {column["name"] for column in inspector.get_columns("inboxes")}
    message_columns = {column["name"] for column in inspector.get_columns("messages")}
    with engine.begin() as connection:
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
