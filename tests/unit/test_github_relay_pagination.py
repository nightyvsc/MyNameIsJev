from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

import httpx
from fastapi import HTTPException
from world.github_relay.app import _list_pull_request_files


class GithubRelayPaginationTests(unittest.TestCase):
    def test_fetches_multiple_pages_and_checks_expected_count(self) -> None:
        first_page = [{"filename": f"file-{index}.txt"} for index in range(100)]
        second_page = [{"filename": "file-100.txt"}]
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            httpx.Response(
                200,
                json=first_page,
                request=httpx.Request("GET", "https://api.github.test/files?page=1"),
            ),
            httpx.Response(
                200,
                json=second_page,
                request=httpx.Request("GET", "https://api.github.test/files?page=2"),
            ),
        ]

        files = asyncio.run(
            _list_pull_request_files(client, "https://api.github.test", "demo/repo", 1, {}, 101)
        )

        self.assertEqual(len(files), 101)
        self.assertEqual(client.get.await_count, 2)

    def test_fails_closed_when_github_returns_incomplete_file_list(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            httpx.Response(
                200,
                json=[{"filename": f"file-{index}.txt"} for index in range(100)],
                request=httpx.Request("GET", "https://api.github.test/files?page=1"),
            ),
            httpx.Response(
                200,
                json=[],
                request=httpx.Request("GET", "https://api.github.test/files?page=2"),
            ),
        ]

        with self.assertRaises(HTTPException) as caught:
            asyncio.run(
                _list_pull_request_files(client, "https://api.github.test", "demo/repo", 1, {}, 101)
            )

        self.assertEqual(caught.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
