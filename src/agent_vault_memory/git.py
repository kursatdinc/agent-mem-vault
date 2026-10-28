import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_vault_memory.vault import log

GIT_TIMEOUT_SECONDS = 30


class GitError(Exception):
    pass


@dataclass(frozen=True)
class GitStatus:
    branch: str
    changed: int
    upstream: str | None
    ahead: int
    behind: int


def run_git(cwd: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitError(f"git {args[0]} failed: {error}") from error
    if result.returncode != 0:
        raise GitError(f"git {args[0]} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout.rstrip("\n")


def inside_work_tree(root: Path) -> bool:
    try:
        return run_git(root, "rev-parse", "--is-inside-work-tree") == "true"
    except GitError:
        return False


def autocommit(root: Path, relpaths: list[str], message: str) -> None:
    """Commit exactly these paths with the user's own git identity. Never pushes; failures are only logged."""
    try:
        if not inside_work_tree(root):
            return
        run_git(root, "add", "--", *relpaths)
        run_git(root, "commit", "-m", message, "--", *relpaths)
    except GitError as error:
        log(f"git autocommit skipped: {error}")


def status(root: Path) -> GitStatus | None:
    """Branch, uncommitted changes under the vault and distance from the upstream; None outside a work tree."""
    if not inside_work_tree(root):
        return None
    try:
        branch = run_git(root, "branch", "--show-current") or "detached HEAD"
        changed = len(run_git(root, "status", "--porcelain", "--", ".").splitlines())
    except GitError:
        return None
    try:
        upstream = run_git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        distance = run_git(root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
        ahead, behind = (int(count) for count in distance.split())
    except GitError:
        return GitStatus(branch, changed, None, 0, 0)
    return GitStatus(branch, changed, upstream, ahead, behind)
