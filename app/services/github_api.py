from __future__ import annotations

from typing import Any

import httpx

from app.core.settings import get_settings

API_BASE = "https://api.github.com"


class GitHubAPIError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, retry_after: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class GitHubClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns = client is None
        settings = get_settings()
        headers = {
            "Accept": (
                "application/vnd.github+json, "
                "application/vnd.github.mercy-preview+json"
            ),
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        self.client = client or httpx.Client(base_url=API_BASE, headers=headers, timeout=30.0)

    def close(self) -> None:
        if self._owns:
            self.client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self.client.request(method, path, **kwargs)
        if resp.status_code == 429:
            retry_after = None
            raw = resp.headers.get("Retry-After")
            if raw and raw.isdigit():
                retry_after = int(raw)
            raise GitHubAPIError("rate limited", status_code=429, retry_after=retry_after)
        if resp.status_code in (401, 403):
            raise GitHubAPIError(f"auth/permission {resp.status_code}", status_code=resp.status_code)
        if resp.status_code == 404:
            raise GitHubAPIError("not found", status_code=404)
        if resp.status_code >= 500:
            raise GitHubAPIError(f"server {resp.status_code}", status_code=resp.status_code)
        if resp.status_code >= 400:
            raise GitHubAPIError(f"client {resp.status_code}", status_code=resp.status_code)
        if resp.status_code == 204:
            return None
        return resp.json()

    def get_repository(self, repo_id: int) -> dict[str, Any]:
        return self._request("GET", f"/repositories/{repo_id}")

    def get_org(self, login: str) -> dict[str, Any]:
        return self._request("GET", f"/orgs/{login}")

    def get_user(self, login: str) -> dict[str, Any]:
        return self._request("GET", f"/users/{login}")

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        head: str,
        base: str,
        body: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
        )

    def find_open_pull_request(self, owner: str, repo: str, head: str) -> dict[str, Any] | None:
        data = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={"state": "open", "head": f"{owner}:{head}"},
        )
        if isinstance(data, list) and data:
            return data[0]
        return None
