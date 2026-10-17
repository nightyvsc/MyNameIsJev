#!/usr/bin/env python3
"""Create a consistent SQLite backup and optionally transfer it to VM5."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIRECTORY = "backups/mynameisjev"


def create_backup(source: Path, output_directory: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source file does not exist: {source}")
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = output_directory / f"audit-{timestamp}.sqlite3"
    source_connection = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        result = destination_connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise sqlite3.DatabaseError(f"Backup integrity check failed: {result!r}")
    except (OSError, sqlite3.Error):
        destination_connection.close()
        source_connection.close()
        destination.unlink(missing_ok=True)
        raise
    destination_connection.close()
    source_connection.close()
    os.chmod(destination, 0o600)
    return destination


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upload_backup(backup: Path, ssh_config: Path) -> str:
    if not ssh_config.is_file():
        raise FileNotFoundError(f"SSH config not found: {ssh_config}")
    filename = backup.name
    remote_path = f"{REMOTE_DIRECTORY}/{filename}"
    subprocess.run(
        ["ssh", "-F", str(ssh_config), "vm5", "mkdir", "-p", "--", REMOTE_DIRECTORY],
        check=True,
    )
    subprocess.run(
        ["scp", "-F", str(ssh_config), str(backup), f"vm5:{remote_path}"],
        check=True,
    )
    result = subprocess.run(
        [
            "ssh",
            "-F",
            str(ssh_config),
            "vm5",
            "sha256sum",
            "--",
            remote_path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    remote_hash = result.stdout.split(maxsplit=1)[0]
    local_hash = sha256_file(backup)
    if not re.fullmatch(r"[0-9a-f]{64}", remote_hash) or remote_hash != local_hash:
        raise RuntimeError("Remote backup SHA-256 does not match the local backup.")
    return remote_hash


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(os.environ.get("AUDIT_DB_PATH", "audit.db")),
        help="Live SQLite database path (default: AUDIT_DB_PATH or audit.db).",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=PROJECT_ROOT / "backups",
        help="Local directory for consistent backups.",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Copy the verified backup to VM5 using the local infra/ssh_config.",
    )
    parser.add_argument(
        "--ssh-config",
        type=Path,
        default=PROJECT_ROOT / "infra" / "ssh_config",
    )
    args = parser.parse_args()
    try:
        backup = create_backup(args.source, args.output_directory)
        digest = sha256_file(backup)
        print(f"Created and integrity-checked backup: {backup}")
        print(f"SHA-256: {digest}")
        if args.upload:
            remote_hash = upload_backup(backup, args.ssh_config)
            print(f"Uploaded and verified on vm5:{REMOTE_DIRECTORY}/{backup.name}")
            print(f"Remote SHA-256: {remote_hash}")
    except (OSError, sqlite3.Error, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
