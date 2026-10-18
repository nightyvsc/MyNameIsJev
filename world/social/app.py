from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_DB = Path(os.environ.get("SOCIAL_DB_PATH", "world/data/social.sqlite3"))
PLATFORMS = ("twitter", "linkedin", "instagram")


class CreatePost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=10_000)
    platform: str


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            platform TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    return connection


def create_app(db_path: Path | None = None) -> FastAPI:
    database = db_path or DEFAULT_DB
    app = FastAPI(title="Mock Social API", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        with closing(_connect(database)) as connection:
            connection.execute("SELECT 1")
        return {"status": "ok"}

    @app.post("/posts", status_code=201)
    def create_post(request: CreatePost) -> dict[str, str]:
        if request.platform not in PLATFORMS:
            raise HTTPException(status_code=422, detail="Unsupported platform.")
        post_id = str(uuid.uuid4())
        with closing(_connect(database)) as connection:
            connection.execute(
                "INSERT INTO posts (id, content, platform, created_at) VALUES (?, ?, ?, ?)",
                (
                    post_id,
                    request.content,
                    request.platform,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()
        return {"id": post_id, "url": f"https://fakesocial.local/post/{post_id}"}

    @app.get("/posts")
    def list_posts(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, object]:
        with closing(_connect(database)) as connection:
            total = connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            rows = connection.execute(
                """SELECT id, content, platform, created_at
                   FROM posts ORDER BY rowid DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return {"total": total, "items": [dict(row) for row in rows]}

    @app.delete("/posts/{post_id}")
    def delete_post(post_id: str) -> dict[str, bool]:
        with closing(_connect(database)) as connection:
            cursor = connection.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            connection.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Post not found.")
        return {"deleted": True}

    return app


app = create_app()
