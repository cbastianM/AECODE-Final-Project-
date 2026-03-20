"""
GitHub integration for structural model version control.
Uses PyGithub to manage model files in a GitHub repository.
"""

import json
import base64
from datetime import datetime
from github import Github, GithubException


class GitHubVCS:
    """Version Control System backed by GitHub."""

    MODEL_DIR = "models"  # directory in repo where models are stored

    def __init__(self, token: str, repo_name: str):
        """
        Initialize connection to GitHub.
        token: GitHub Personal Access Token
        repo_name: Full repo name e.g. 'user/structural-models'
        """
        self.gh = Github(token)
        self.repo = self.gh.get_repo(repo_name)

    # ── Branch operations ───────────────────────────────────────────────

    def list_branches(self) -> list[dict]:
        """List all branches with metadata."""
        branches = []
        for b in self.repo.get_branches():
            commit = b.commit
            branches.append({
                "name": b.name,
                "sha": commit.sha[:8],
                "last_modified": commit.commit.author.date.isoformat(),
                "author": commit.commit.author.name,
                "message": commit.commit.message,
                "protected": b.protected,
            })
        return sorted(branches, key=lambda x: x["last_modified"], reverse=True)

    def create_branch(self, branch_name: str, source_branch: str = "main") -> dict:
        """Create a new branch from source."""
        source = self.repo.get_branch(source_branch)
        ref = self.repo.create_git_ref(
            ref=f"refs/heads/{branch_name}",
            sha=source.commit.sha,
        )
        return {"name": branch_name, "sha": ref.object.sha[:8]}

    def delete_branch(self, branch_name: str) -> bool:
        """Delete a branch (cannot delete default branch)."""
        try:
            ref = self.repo.get_git_ref(f"heads/{branch_name}")
            ref.delete()
            return True
        except GithubException:
            return False

    # ── Model file operations ───────────────────────────────────────────

    def _model_path(self, filename: str) -> str:
        return f"{self.MODEL_DIR}/{filename}"

    def list_models(self, branch: str = "main") -> list[dict]:
        """List all model files in a branch."""
        try:
            contents = self.repo.get_contents(self.MODEL_DIR, ref=branch)
        except GithubException:
            return []

        models = []
        for f in contents:
            if f.name.endswith(".json"):
                models.append({
                    "name": f.name,
                    "path": f.path,
                    "size_kb": round(f.size / 1024, 1),
                    "sha": f.sha[:8],
                    "download_url": f.download_url,
                })
        return sorted(models, key=lambda x: x["name"])

    def get_model(self, filename: str, branch: str = "main") -> dict | None:
        """Download and parse a model JSON from the repo."""
        try:
            path = self._model_path(filename)
            content = self.repo.get_contents(path, ref=branch)
            decoded = base64.b64decode(content.content).decode("utf-8")
            return json.loads(decoded)
        except GithubException:
            return None

    def upload_model(
        self,
        filename: str,
        model_data: dict,
        branch: str = "main",
        message: str | None = None,
    ) -> dict:
        """
        Upload (create or update) a model JSON to the repo.
        Returns commit info.
        """
        path = self._model_path(filename)
        content = json.dumps(model_data, indent=2, ensure_ascii=False)
        if message is None:
            message = f"Update {filename} — {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        try:
            # Try to get existing file to update
            existing = self.repo.get_contents(path, ref=branch)
            result = self.repo.update_file(
                path=path,
                message=message,
                content=content,
                sha=existing.sha,
                branch=branch,
            )
        except GithubException:
            # File doesn't exist, create it
            result = self.repo.create_file(
                path=path,
                message=message,
                content=content,
                branch=branch,
            )

        return {
            "sha": result["commit"].sha[:8],
            "message": message,
            "url": result["content"].html_url,
        }

    def delete_model(self, filename: str, branch: str = "main") -> bool:
        """Delete a model file from the repo."""
        try:
            path = self._model_path(filename)
            existing = self.repo.get_contents(path, ref=branch)
            self.repo.delete_file(
                path=path,
                message=f"Delete {filename}",
                sha=existing.sha,
                branch=branch,
            )
            return True
        except GithubException:
            return False

    # ── Version history ─────────────────────────────────────────────────

    def get_commit_history(self, branch: str = "main", max_commits: int = 50) -> list[dict]:
        """Get commit history for a branch."""
        commits = []
        for c in self.repo.get_commits(sha=branch)[:max_commits]:
            commits.append({
                "sha": c.sha[:8],
                "message": c.commit.message,
                "author": c.commit.author.name,
                "date": c.commit.author.date.isoformat(),
                "files_changed": [f.filename for f in c.files] if c.files else [],
            })
        return commits

    def get_model_versions(self, filename: str, branch: str = "main") -> list[dict]:
        """Get all commits that modified a specific model file."""
        path = self._model_path(filename)
        versions = []
        for c in self.repo.get_commits(sha=branch, path=path):
            versions.append({
                "sha": c.sha[:8],
                "full_sha": c.sha,
                "message": c.commit.message,
                "author": c.commit.author.name,
                "date": c.commit.author.date.isoformat(),
            })
        return versions

    def get_model_at_commit(self, filename: str, commit_sha: str) -> dict | None:
        """Get a model file at a specific commit."""
        try:
            path = self._model_path(filename)
            content = self.repo.get_contents(path, ref=commit_sha)
            decoded = base64.b64decode(content.content).decode("utf-8")
            return json.loads(decoded)
        except GithubException:
            return None

    # ── Repo info ───────────────────────────────────────────────────────

    def get_repo_info(self) -> dict:
        return {
            "name": self.repo.full_name,
            "description": self.repo.description,
            "default_branch": self.repo.default_branch,
            "private": self.repo.private,
            "size_kb": self.repo.size,
            "url": self.repo.html_url,
        }
