"""Check whether a newer version of StreamStudy is published upstream.

Git checkouts are compared by commit SHA (latest commit on ``main``). ZIP /
archive copies are compared by the ``VERSION`` file, because they have no git
metadata. The check is read-only and fails silently when offline.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import __version__

REPO = "llascari/RFD_LL_StreamStudy"
REPO_URL = f"https://github.com/{REPO}"
ARCHIVE_URL = f"https://github.com/{REPO}/archive/refs/heads/main.zip"
API_COMMIT_URL = f"https://api.github.com/repos/{REPO}/commits/main"
RAW_VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/main/VERSION"


@dataclass(frozen=True)
class UpdateStatus:
    available: bool | None
    method: str  # "git" | "archive"
    local: str
    remote: str
    remote_date: str = ""
    url: str = REPO_URL
    error: str = ""

    @property
    def local_label(self) -> str:
        return f"commit {self.local[:7]}" if self.method == "git" else f"version {self.local}"

    @property
    def remote_label(self) -> str:
        return f"commit {self.remote[:7]}" if self.method == "git" else f"version {self.remote}"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def local_version(root: Path | None = None) -> str:
    root = root or project_root()
    try:
        return (root / "VERSION").read_text().strip() or __version__
    except OSError:
        return __version__


def is_git_checkout(root: Path | None = None) -> bool:
    root = root or project_root()
    return (root / ".git").exists()


def git_sha(root: Path | None = None, *, runner=subprocess.run) -> str | None:
    root = root or project_root()
    try:
        result = runner(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _version_tuple(text: str) -> tuple[int, ...] | None:
    parts = text.strip().lstrip("v").split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def versions_differ(local: str, remote: str) -> bool:
    local_tuple = _version_tuple(local)
    remote_tuple = _version_tuple(remote)
    if local_tuple is not None and remote_tuple is not None:
        return remote_tuple > local_tuple
    return local.strip() != remote.strip()


def check_for_update(
    root: Path | None = None,
    client=None,
    *,
    sha_reader=git_sha,
) -> UpdateStatus:
    """Compare the local checkout with the latest upstream commit."""
    root = root or project_root()
    if client is None:
        raise ValueError("check_for_update needs an HTTP client")
    try:
        commit = client.get_json(API_COMMIT_URL)
        remote_sha = str(commit.get("sha", ""))
        remote_date = str((commit.get("commit") or {}).get("committer", {}).get("date", ""))
        url = str(commit.get("html_url", REPO_URL))
    except Exception as exc:  # noqa: BLE001 - offline is normal
        return UpdateStatus(
            available=None,
            method="git" if is_git_checkout(root) else "archive",
            local="",
            remote="",
            error=str(exc),
        )

    if is_git_checkout(root):
        local_sha = sha_reader(root) or ""
        return UpdateStatus(
            available=bool(local_sha and remote_sha and local_sha != remote_sha),
            method="git",
            local=local_sha,
            remote=remote_sha,
            remote_date=remote_date,
            url=url,
        )

    local = local_version(root)
    try:
        remote_version = client.get_text(RAW_VERSION_URL).strip()
    except Exception as exc:  # noqa: BLE001
        return UpdateStatus(
            available=None,
            method="archive",
            local=local,
            remote="",
            remote_date=remote_date,
            url=url,
            error=str(exc),
        )
    return UpdateStatus(
        available=versions_differ(local, remote_version),
        method="archive",
        local=local,
        remote=remote_version,
        remote_date=remote_date,
        url=ARCHIVE_URL,
    )


def update_instructions(status: UpdateStatus, root: Path | None = None) -> str:
    root = root or project_root()
    if status.method == "git":
        return (
            f"A newer commit is available.\n\n"
            f"Local:  {status.local[:7]}\nRemote: {status.remote[:7]}"
            + (f"  ({status.remote_date})" if status.remote_date else "")
            + "\n\nUpdate from a terminal:\n\n"
            f"  cd {root}\n"
            "  git pull\n\n"
            "Then close and restart StreamStudy. Settings live outside the project "
            "and are kept. If git reports local changes, commit or stash them first."
        )
    return (
        f"A newer version is available.\n\n"
        f"Local:  {status.local}\nRemote: {status.remote}"
        + (f"  ({status.remote_date})" if status.remote_date else "")
        + "\n\nDownload the latest ZIP:\n\n"
        f"  {ARCHIVE_URL}\n\n"
        "Extract it and replace this folder (or point your shortcut at the new one). "
        "Your settings live outside the project and are kept. Then restart StreamStudy."
    )
