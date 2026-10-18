from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

from jev_gate.models.contracts import Action, Decision


def _allowed_repositories() -> set[str]:
    return {
        repo.strip()
        for repo in os.environ.get("GITHUB_ALLOWED_REPOSITORIES", "").split(",")
        if repo.strip()
    }


def _make_action(
    repository: str, pull: dict[str, Any], files: list[dict[str, Any]]
) -> dict[str, Any]:
    changed_paths = [
        str(item["filename"])
        for item in files
        if isinstance(item.get("filename"), str) and item["filename"]
    ]
    full_patch_text = "\n".join(
        str(item.get("patch", "")) for item in files if isinstance(item.get("patch"), str)
    )
    patch_text = full_patch_text[:30_000]
    pr_number = pull["number"]
    title = str(pull.get("title", ""))
    user = pull.get("user") or {}
    actor_name = user.get("login") or user.get("id") or "github-webhook-relay"
    action = Action(
        schema_version="2.0",
        action_id=uuid.uuid4(),
        action_class="pr_action",
        subtype="merge",
        tool="github.evaluate_pull_request",
        actor=f"github:{actor_name}",
        args={
            "changed_files": int(pull.get("changed_files") or len(changed_paths)),
            "lines_added": int(pull.get("additions") or 0),
            "lines_deleted": int(pull.get("deletions") or 0),
            "files": changed_paths,
        },
        recipients=[],
        payload={
            "repository": repository,
            "pull_request_number": pr_number,
            "title": title,
            "body": str(pull.get("body") or ""),
            "diff": patch_text,
            "changed_paths": changed_paths,
            "base_branch": str((pull.get("base") or {}).get("ref", "")),
            "head_branch": str((pull.get("head") or {}).get("ref", "")),
            "pull_request_url": str(pull.get("html_url", "")),
            "diff_truncated": len(full_patch_text) > len(patch_text),
        },
        risk_level="medium",
        dry_run=False,
        created_at=datetime.now(timezone.utc),  # noqa: UP017
    )
    return action.model_dump(mode="json", exclude_none=True)


async def _list_pull_request_files(
    client: httpx.AsyncClient,
    api_base: str,
    repository: str,
    pull_number: int,
    headers: dict[str, str],
    expected_count: int | None,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for page in range(1, 31):
        response = await client.get(
            f"{api_base}/repos/{repository}/pulls/{pull_number}/files",
            headers=headers,
            params={"per_page": 100, "page": page},
        )
        if response.is_error:
            raise HTTPException(
                status_code=502,
                detail=f"GitHub files API returned HTTP {response.status_code}.",
            )
        try:
            page_files = response.json()
        except ValueError as error:
            raise HTTPException(
                status_code=502, detail="GitHub files API returned invalid JSON."
            ) from error
        if not isinstance(page_files, list) or any(
            not isinstance(item, dict) for item in page_files
        ):
            raise HTTPException(
                status_code=502, detail="GitHub files API returned an invalid response."
            )
        files.extend(page_files)
        if len(page_files) < 100:
            break
    else:
        raise HTTPException(
            status_code=502,
            detail="Pull request exceeds the 3,000-file analysis limit.",
        )

    if expected_count is not None and len(files) < expected_count:
        raise HTTPException(
            status_code=502,
            detail="GitHub returned an incomplete pull request file list.",
        )
    return files


def create_app() -> FastAPI:
    app = FastAPI(title="GitHub Webhook Relay", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, object]:
        configured = bool(
            os.environ.get("GITHUB_WEBHOOK_SECRET")
            and os.environ.get("GATE_TOKEN")
            and os.environ.get("GATEWAY_BASE_URL")
        )
        return {"status": "ok", "configured": configured}

    @app.post("/webhook", status_code=202)
    async def receive_webhook(
        request: Request,
        event: str | None = Header(default=None, alias="X-GitHub-Event"),
        signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    ) -> dict[str, Any]:
        secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
        if not secret:
            raise HTTPException(status_code=503, detail="Webhook secret is not configured.")
        if not signature or not signature.startswith("sha256="):
            raise HTTPException(status_code=401, detail="Missing webhook signature.")

        raw_body = await request.body()
        expected = (
            "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=401, detail="Invalid webhook signature.")

        if event != "pull_request":
            return {"status": "ignored", "reason": "Unsupported event."}
        try:
            payload = await request.json()
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid JSON payload.") from error

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid webhook JSON object.")
        action_name = payload.get("action")
        if action_name not in {"opened", "synchronize", "reopened"}:
            return {"status": "ignored", "reason": "Pull request action is not evaluated."}

        repository_data = payload.get("repository")
        if not isinstance(repository_data, dict):
            raise HTTPException(status_code=400, detail="Missing repository details.")
        repository = str(repository_data.get("full_name", ""))
        allowed = _allowed_repositories()
        if not repository or repository not in allowed:
            raise HTTPException(
                status_code=403, detail="Repository is not in the configured allowlist."
            )

        pull = payload.get("pull_request")
        if (
            not isinstance(pull, dict)
            or not isinstance(pull.get("number"), int)
            or isinstance(pull.get("number"), bool)
            or pull["number"] < 1
        ):
            raise HTTPException(status_code=400, detail="Missing pull request details.")
        gate_base_url = os.environ.get("GATEWAY_BASE_URL")
        gate_token = os.environ.get("GATE_TOKEN")
        github_token = os.environ.get("GITHUB_TOKEN")
        if not gate_base_url or not gate_token or not github_token:
            raise HTTPException(
                status_code=503,
                detail="Gateway URL/token and GitHub read token must be configured.",
            )

        api_base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            files_data = await _list_pull_request_files(
                client,
                api_base,
                repository,
                pull["number"],
                headers,
                pull.get("changed_files"),
            )
            action = _make_action(repository, pull, files_data)
            gate_response = await client.post(
                f"{gate_base_url.rstrip('/')}/gate",
                json=action,
                headers={"X-Gate-Token": gate_token},
            )
            if gate_response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Gateway returned HTTP {gate_response.status_code}.",
                )
            try:
                decision = Decision.model_validate(gate_response.json())
            except (ValueError, TypeError) as error:
                raise HTTPException(
                    status_code=502, detail="Gateway returned an invalid Decision."
                ) from error

            decision_id = str(decision.action_id)
            verdict = decision.verdict.value if decision.verdict is not None else None
            writes_enabled = os.environ.get("GITHUB_ENABLE_WRITES", "").lower() == "true"
            github_write_result = "disabled"
            if (
                writes_enabled
                and decision.status.value == "decided"
                and verdict in {"allow", "ask", "deny"}
            ):
                if verdict == "allow":
                    review_payload = {
                        "event": "APPROVE",
                        "body": "Approved by the JEV safety gate.",
                    }
                    write_url = f"{api_base}/repos/{repository}/pulls/{pull['number']}/reviews"
                elif verdict == "deny":
                    review_payload = {
                        "event": "REQUEST_CHANGES",
                        "body": "Changes requested by the JEV safety gate.",
                    }
                    write_url = f"{api_base}/repos/{repository}/pulls/{pull['number']}/reviews"
                else:
                    review_payload = {
                        "body": (
                            "The JEV safety gate requires human approval before this pull "
                            "request can proceed."
                        )
                    }
                    write_url = f"{api_base}/repos/{repository}/issues/{pull['number']}/comments"
                write_response = await client.post(
                    write_url,
                    json=review_payload,
                    headers=headers,
                )
                if write_response.is_error:
                    raise HTTPException(
                        status_code=502,
                        detail=f"GitHub write API returned HTTP {write_response.status_code}.",
                    )
                github_write_result = "submitted"

        return {
            "status": "evaluated",
            "verdict": verdict,
            "decision_id": decision_id,
            "github_write": github_write_result,
        }

    return app


app = create_app()
