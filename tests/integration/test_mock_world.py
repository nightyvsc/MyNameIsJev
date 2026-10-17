from __future__ import annotations

import smtplib
import socket
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from world.crm.app import create_app as create_crm_app
from world.github_relay.app import _make_action
from world.github_relay.app import create_app as create_relay_app
from world.mail.app import create_app as create_mail_app
from world.social.app import create_app as create_social_app


def free_tcp_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class MockWorldIntegrationTests(unittest.TestCase):
    def test_crm_lists_seed_data_upserts_and_reads_contact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = create_crm_app(Path(directory) / "crm.sqlite3")
            with TestClient(app) as client:
                initial = client.get("/contacts")
                self.assertEqual(initial.status_code, 200)
                self.assertEqual(initial.json()["total"], 1_000)

                upsert = client.post(
                    "/contacts/bulk-upsert",
                    json=[
                        {
                            "name": "Demo Person",
                            "email": "demo@example.invalid",
                            "phone": "555-0100",
                            "company": "Example Co",
                        }
                    ],
                )
                self.assertEqual(upsert.json(), {"upserted": 1})
                contact = client.get("/contacts", params={"limit": 10, "offset": 1000}).json()
                self.assertEqual(contact["total"], 1_001)
                row = next(
                    item for item in contact["items"] if item["email"] == "demo@example.invalid"
                )
                self.assertEqual(client.get(f"/contacts/{row['id']}").json()["name"], "Demo Person")
                self.assertEqual(client.get("/health").json(), {"status": "ok"})

    def test_smtp_sink_accepts_and_lists_mail_without_external_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            port = free_tcp_port()
            app = create_mail_app(Path(directory) / "mail.sqlite3", "127.0.0.1", port)
            with TestClient(app) as client:
                message = EmailMessage()
                message["From"] = "agent@example.invalid"
                message["To"] = "recipient@example.invalid"
                message["Subject"] = "Synthetic sink test"
                message.set_content("This stays in the local SMTP sink.")
                with smtplib.SMTP("127.0.0.1", port, timeout=3) as smtp:
                    refused = smtp.send_message(message)
                self.assertEqual(refused, {})

                result = client.get("/emails").json()
                self.assertEqual(result["total"], 1)
                self.assertEqual(result["items"][0]["subject"], "Synthetic sink test")
                self.assertEqual(result["items"][0]["to"], ["recipient@example.invalid"])
                self.assertIn("local SMTP sink", result["items"][0]["body"] or "")
                self.assertEqual(client.delete("/emails").json(), {"deleted": 1})

    def test_social_api_creates_lists_and_deletes_posts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = create_social_app(Path(directory) / "social.sqlite3")
            with TestClient(app) as client:
                created = client.post(
                    "/posts",
                    json={"content": "Synthetic test post.", "platform": "linkedin"},
                )
                self.assertEqual(created.status_code, 201)
                post_id = created.json()["id"]
                self.assertIn(post_id, created.json()["url"])
                self.assertEqual(client.get("/posts").json()["total"], 1)
                self.assertEqual(client.delete(f"/posts/{post_id}").json(), {"deleted": True})
                self.assertEqual(client.get("/posts").json()["total"], 0)

    def test_github_relay_rejects_invalid_webhook_signature(self) -> None:
        with (
            patch.dict("os.environ", {"GITHUB_WEBHOOK_SECRET": "local-test-secret"}),
            TestClient(create_relay_app()) as client,
        ):
            response = client.post(
                "/webhook",
                content=b'{"action":"opened"}',
                headers={
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": "sha256=invalid",
                },
            )
            self.assertEqual(response.status_code, 401)

    def test_github_payload_maps_to_action_contract(self) -> None:
        pull = {
            "number": 12,
            "title": "Test change",
            "body": "synthetic PR",
            "changed_files": 2,
            "additions": 5,
            "deletions": 1,
            "user": {"id": 123},
            "base": {"ref": "main"},
            "head": {"ref": "feature"},
        }
        action = _make_action(
            "demo/repository",
            pull,
            [
                {"filename": ".github/workflows/test.yml", "patch": "+name: test"},
                {"filename": "pyproject.toml", "patch": "+added-dependency"},
            ],
        )
        self.assertEqual(action["action_class"], "repo_merge")
        self.assertTrue(action["diff_stats"]["touches_ci"])
        self.assertTrue(action["diff_stats"]["adds_dependency"])
        self.assertEqual(action["diff_stats"]["files_changed"], 2)
        self.assertFalse(action["context"]["diff_truncated"])

    def test_github_action_marks_truncated_diffs(self) -> None:
        action = _make_action(
            "demo/repository",
            {"number": 13, "changed_files": 1},
            [{"filename": "large.diff", "patch": "x" * 30_001}],
        )
        self.assertTrue(action["context"]["diff_truncated"])
        self.assertLessEqual(len(action["payload"]["diff"]), 30_000)


if __name__ == "__main__":
    unittest.main()
