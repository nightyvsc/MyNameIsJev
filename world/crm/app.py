from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Annotated

from faker import Faker
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_DB = Path(os.environ.get("CRM_DB_PATH", "world/data/crm.sqlite3"))
INITIAL_CONTACTS = 1_000


class ContactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str = Field(default="", max_length=40)
    company: str = Field(default="", max_length=200)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS contacts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL,
            company TEXT NOT NULL
        )"""
    )
    return connection


def _initialize(db_path: Path) -> None:
    with closing(_connect(db_path)) as connection:
        current_count = connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        if current_count == 0:
            fake = Faker()
            fake.seed_instance(731_042)
            rows = [
                (
                    str(uuid.uuid4()),
                    fake.name(),
                    f"contact-{index}@example.invalid",
                    fake.phone_number()[:40],
                    fake.company(),
                )
                for index in range(INITIAL_CONTACTS)
            ]
            connection.executemany(
                "INSERT INTO contacts (id, name, email, phone, company) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            connection.commit()


def create_app(db_path: Path | None = None) -> FastAPI:
    database = db_path or DEFAULT_DB
    app = FastAPI(title="Mock CRM", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        _initialize(database)
        with closing(_connect(database)) as connection:
            connection.execute("SELECT 1")
        return {"status": "ok"}

    @app.get("/contacts")
    def list_contacts(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, object]:
        _initialize(database)
        with closing(_connect(database)) as connection:
            total = connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
            rows = connection.execute(
                """SELECT id, name, email, phone, company
                   FROM contacts ORDER BY rowid LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return {"total": total, "items": [dict(row) for row in rows]}

    @app.get("/contacts/{contact_id}")
    def get_contact(contact_id: str) -> dict[str, str]:
        _initialize(database)
        with closing(_connect(database)) as connection:
            row = connection.execute(
                "SELECT id, name, email, phone, company FROM contacts WHERE id = ?",
                (contact_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Contact not found.")
        return dict(row)

    @app.post("/contacts/bulk-upsert")
    def bulk_upsert(contacts: list[ContactInput]) -> dict[str, int]:
        if len(contacts) > 1_000:
            raise HTTPException(status_code=413, detail="At most 1000 records per request.")
        _initialize(database)
        with closing(_connect(database)) as connection:
            connection.executemany(
                """INSERT INTO contacts (id, name, email, phone, company)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(email) DO UPDATE SET
                     name = excluded.name,
                     phone = excluded.phone,
                     company = excluded.company""",
                [
                    (str(uuid.uuid4()), item.name, str(item.email), item.phone, item.company)
                    for item in contacts
                ],
            )
            connection.commit()
        return {"upserted": len(contacts)}

    return app


app = create_app()
