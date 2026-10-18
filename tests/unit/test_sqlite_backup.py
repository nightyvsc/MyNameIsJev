from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.backup_sqlite import create_backup, sha256_file, upload_backup


class SQLiteBackupTests(unittest.TestCase):
    def test_backup_is_consistent_and_contains_live_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "audit.sqlite3"
            with sqlite3.connect(source) as connection:
                connection.execute("CREATE TABLE audit (id INTEGER PRIMARY KEY, verdict TEXT)")
                connection.execute("INSERT INTO audit (verdict) VALUES ('allow')")

            backup = create_backup(source, root / "backups")
            with sqlite3.connect(backup) as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(
                    connection.execute("SELECT verdict FROM audit").fetchone()[0],
                    "allow",
                )
            self.assertEqual(len(sha256_file(backup)), 64)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_missing_database_is_reported(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(FileNotFoundError),
        ):
            create_backup(Path(directory) / "missing.sqlite3", Path(directory) / "backups")

    def test_sftp_upload_verifies_a_downloaded_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.sqlite3"
            with sqlite3.connect(source) as connection:
                connection.execute("CREATE TABLE audit (id INTEGER PRIMARY KEY)")
                connection.execute("INSERT INTO audit DEFAULT VALUES")
            backup = create_backup(source, root / "backups")
            identity = root / "identity"
            known_hosts = root / "known_hosts"
            identity.touch()
            known_hosts.touch()

            def fake_sftp_run(command, *, input, text, check):
                self.assertEqual(command[0], "sftp")
                self.assertIn("IdentitiesOnly=yes", command)
                self.assertIn("StrictHostKeyChecking=yes", command)
                self.assertTrue(text)
                self.assertTrue(check)
                lines = input.splitlines()
                uploaded_path = Path(lines[0].split('"')[1])
                downloaded_path = Path(lines[1].split('"')[1])
                downloaded_path.write_bytes(uploaded_path.read_bytes())

            with patch("scripts.backup_sqlite.subprocess.run", side_effect=fake_sftp_run):
                remote_hash = upload_backup(backup, identity, known_hosts)

            self.assertEqual(remote_hash, sha256_file(backup))


if __name__ == "__main__":
    unittest.main()
