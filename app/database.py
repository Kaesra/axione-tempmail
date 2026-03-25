from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
engine = create_engine(settings.db_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from app import models

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    inbox_columns = {column["name"] for column in inspector.get_columns("inboxes")}
    message_columns = {column["name"] for column in inspector.get_columns("messages")}
    with engine.begin() as connection:
        if "is_persistent" not in inbox_columns:
            connection.execute(text("ALTER TABLE inboxes ADD COLUMN is_persistent BOOLEAN DEFAULT 0"))
        if "sender_domain" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN sender_domain VARCHAR(255) DEFAULT ''"))
        if "message_kind" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN message_kind VARCHAR(50) DEFAULT 'general'"))
        if "verification_link" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN verification_link VARCHAR(1000) DEFAULT ''"))
        if "is_unread" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN is_unread BOOLEAN DEFAULT 1"))
