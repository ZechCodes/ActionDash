"""GitHub API client for repo and webhook management."""

import httpx


class GitHubClient:
    """Async client for GitHub REST API v3."""

    BASE_URL = "https://api.github.com"

    def __init__(self, access_token: str):
        self._token = access_token
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def list_repos(self) -> list[dict]:
        """Fetch all repos the user has admin access to, sorted by recently updated."""
        repos: list[dict] = []
        page = 1
        async with httpx.AsyncClient(
            base_url=self.BASE_URL, headers=self._headers, timeout=15.0
        ) as client:
            while True:
                resp = await client.get(
                    "/user/repos",
                    params={
                        "sort": "updated",
                        "direction": "desc",
                        "per_page": 100,
                        "page": page,
                        "affiliation": "owner,collaborator,organization_member",
                    },
                )
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                # Only include repos where the user has admin permission
                repos.extend(
                    r for r in batch if r.get("permissions", {}).get("admin")
                )
                if len(batch) < 100:
                    break
                page += 1
        return repos

    async def create_webhook(
        self, repo_full_name: str, webhook_url: str, secret: str
    ) -> dict:
        """Create a webhook on a repo for workflow_run and workflow_job events."""
        owner, repo = repo_full_name.split("/", 1)
        async with httpx.AsyncClient(
            base_url=self.BASE_URL, headers=self._headers, timeout=15.0
        ) as client:
            resp = await client.post(
                f"/repos/{owner}/{repo}/hooks",
                json={
                    "name": "web",
                    "active": True,
                    "events": ["workflow_run", "workflow_job"],
                    "config": {
                        "url": webhook_url,
                        "content_type": "json",
                        "secret": secret,
                        "insecure_ssl": "0",
                    },
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def get_run_jobs(self, repo_full_name: str, run_id: int) -> list[dict]:
        """Fetch all jobs for a workflow run, including steps."""
        owner, repo = repo_full_name.split("/", 1)
        async with httpx.AsyncClient(
            base_url=self.BASE_URL, headers=self._headers, timeout=15.0
        ) as client:
            resp = await client.get(
                f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs"
            )
            resp.raise_for_status()
            return resp.json().get("jobs", [])

    async def delete_webhook(self, repo_full_name: str, webhook_id: int) -> None:
        """Delete a webhook from a repo."""
        owner, repo = repo_full_name.split("/", 1)
        async with httpx.AsyncClient(
            base_url=self.BASE_URL, headers=self._headers, timeout=15.0
        ) as client:
            resp = await client.delete(
                f"/repos/{owner}/{repo}/hooks/{webhook_id}"
            )
            resp.raise_for_status()
