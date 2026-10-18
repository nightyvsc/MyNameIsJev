#!/usr/bin/env python3
"""Create a consistent SQLite backup and optionally transfer it to VM5."""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIRECTORY = "/backups"
REMOTE_HOST = "10.43.97.73"
REMOTE_USER = "jevbackup"


def create_backup(source: Path, output_directory: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source file does not exist: {source}")
    output_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_directory, 0o700)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")  # noqa: UP017
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


def integrity_check(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if result is None or result[0] != "ok":
        raise sqlite3.DatabaseError(f"SQLite integrity check failed for {path}: {result!r}")


def _sftp_quote(path: Path) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def upload_backup(
    backup: Path,
    identity_file: Path,
    known_hosts: Path,
) -> str:
    if not identity_file.is_file():
        raise FileNotFoundError(f"Backup identity key not found: {identity_file}")
    if not known_hosts.is_file():
        raise FileNotFoundError(f"Pinned known-hosts file not found: {known_hosts}")
    if not backup.is_file():
        raise FileNotFoundError(f"Backup file not found: {backup}")

    filename = backup.name
    remote_path = f"{REMOTE_DIRECTORY}/{filename}"
    local_hash = sha256_file(backup)
    with tempfile.TemporaryDirectory(prefix="jev-backup-") as directory:
        verified_copy = Path(directory) / f"verified-{filename}"
        commands = "\n".join(
            (
                f"put {_sftp_quote(backup.resolve())} {remote_path}",
                f"get {remote_path} {_sftp_quote(verified_copy)}",
            )
        )
        subprocess.run(
        [
                "sftp",
                "-i",
                str(identity_file),
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                f"UserKnownHostsFile={known_hosts}",
                "-b",
                "-",
                f"{REMOTE_USER}@{REMOTE_HOST}",
            ],
            input=commands + "\n",
            text=True,
            check=True,
        )
        remote_copy_hash = sha256_file(verified_copy)
        if remote_copy_hash != local_hash:
            raise RuntimeError("Downloaded VM5 backup differs from the local backup.")
        integrity_check(verified_copy)
        restored_copy = Path(directory) / f"restored-{filename}"
        source_connection = sqlite3.connect(
            f"file:{verified_copy.resolve()}?mode=ro", uri=True
        )
        restored_connection = sqlite3.connect(restored_copy)
        try:
            source_connection.backup(restored_connection)
        finally:
            restored_connection.close()
            source_connection.close()
        integrity_check(restored_copy)
    return remote_copy_hash


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
        help="Upload to VM5 using the dedicated SFTP-only identity and verify by download.",
    )
    parser.add_argument(
        "--identity-file",
        type=Path,
        default=Path.home() / ".ssh" / "jev_vm5_backup",
        help="Dedicated VM1-to-VM5 private key; never use the operator key.",
    )
    parser.add_argument(
        "--known-hosts",
        type=Path,
        default=Path.home() / ".ssh" / "jev_vm5_known_hosts",
        help="Known-hosts file containing VM5's independently verified host key.",
    )
    args = parser.parse_args()
    try:
        backup = create_backup(args.source, args.output_directory)
        digest = sha256_file(backup)
        print(f"Created and integrity-checked backup: {backup}")
        print(f"SHA-256: {digest}")
        if args.upload:
            remote_hash = upload_backup(
                backup,
                args.identity_file,
                args.known_hosts,
            )
            print(
                "Uploaded, downloaded, and restore-checked on "
                f"VM5:{REMOTE_DIRECTORY}/{backup.name}"
            )
            print(f"Verified SHA-256: {remote_hash}")
    except (
        OSError,
        sqlite3.Error,
        subprocess.CalledProcessError,
        RuntimeError,
        ValueError,
    ) as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
