from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Annotated

from aiosmtpd.controller import Controller
from fastapi import FastAPI, HTTPException, Query

DEFAULT_DB = Path(os.environ.get("MAIL_DB_PATH", "world/data/mail.sqlite3"))
SMTP_HOST = os.environ.get("SMTP_HOST", "0.0.0.0")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "2525"))


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS emails (
            id TEXT PRIMARY KEY,
            sender TEXT NOT NULL,
            recipients_json TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            received_at TEXT NOT NULL
        )"""
    )
    return connection


def _message_body(message: object) -> str:
    if not hasattr(message, "walk"):
        return str(message)
    parts: list[str] = []
    for part in message.walk():  # type: ignore[attr-defined]
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_type() == "text/plain":
            try:
                parts.append(part.get_content())
            except (LookupError, UnicodeError):
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    parts.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(parts)


class SinkHandler:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def handle_DATA(self, server: object, session: object, envelope: object) -> str:
        del server, session
        message_data = envelope.content
        if not isinstance(message_data, bytes):
            message_data = bytes(message_data)
        message = BytesParser(policy=policy.default).parsebytes(message_data)
        sender = str(getattr(envelope, "mail_from", ""))
        recipients = [str(recipient) for recipient in getattr(envelope, "rcpt_tos", [])]
        with closing(_connect(self.db_path)) as connection:
            connection.execute(
                """INSERT INTO emails
                   (id, sender, recipients_json, subject, body, received_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    sender,
                    json.dumps(recipients),
                    str(message.get("subject", "")),
                    _message_body(message),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()
        return "250 Message accepted by local sink; not delivered."


def create_app(
    db_path: Path | None = None,
    smtp_host: str = SMTP_HOST,
    smtp_port: int = SMTP_PORT,
) -> FastAPI:
    database = db_path or DEFAULT_DB
    smtp_controller: Controller | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal smtp_controller
        smtp_controller = Controller(SinkHandler(database), hostname=smtp_host, port=smtp_port)
        smtp_controller.start()
        try:
            yield
        finally:
            if smtp_controller is not None:
                smtp_controller.stop()
                smtp_controller = None

    app = FastAPI(title="Local SMTP Sink API", version="1.0.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        with closing(_connect(database)) as connection:
            connection.execute("SELECT 1")
        return {"status": "ok"}

    @app.get("/emails")
    def list_emails(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, object]:
        with closing(_connect(database)) as connection:
            total = connection.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
            rows = connection.execute(
                """SELECT id, sender, recipients_json, subject, body, received_at
                   FROM emails ORDER BY rowid DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        items = [
            {
                "id": row["id"],
                "from": row["sender"],
                "to": json.loads(row["recipients_json"]),
                "subject": row["subject"],
                "body": row["body"],
                "received_at": row["received_at"],
            }
            for row in rows
        ]
        return {"total": total, "items": items}

    @app.get("/emails/{email_id}")
    def get_email(email_id: str) -> dict[str, object]:
        with closing(_connect(database)) as connection:
            row = connection.execute(
                """SELECT id, sender, recipients_json, subject, body, received_at
                   FROM emails WHERE id = ?""",
                (email_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Email not found.")
        return {
            "id": row["id"],
            "from": row["sender"],
            "to": json.loads(row["recipients_json"]),
            "subject": row["subject"],
            "body": row["body"],
            "received_at": row["received_at"],
        }

    @app.delete("/emails")
    def clear_emails() -> dict[str, int]:
        with closing(_connect(database)) as connection:
            deleted = connection.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
            connection.execute("DELETE FROM emails")
            connection.commit()
        return {"deleted": deleted}

    return app


app = create_app()
