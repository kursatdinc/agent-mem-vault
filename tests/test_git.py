import subprocess

import pytest

from agent_vault_memory import git
from agent_vault_memory.store import Store
from agent_vault_memory.vault import Vault
from conftest import TickingClock


def run(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    run(root, "init", "-q", "-b", "main")
    run(root, "config", "user.name", "Dana Tester")
    run(root, "config", "user.email", "dana@example.invalid")
    run(root, "config", "commit.gpgsign", "false")
    return root


def committing_store(root):
    return Store(Vault(root), clock=TickingClock(), git_autocommit=True)


def test_each_write_commits_the_touched_paths_with_the_users_identity(repo):
    store = committing_store(repo)

    record = store.save_memory(agent="a", kind="decision", title="Pick storage", content="c", namespace="proj")
    store.update_memory(record.id, status="accepted")

    subjects = run(repo, "log", "--format=%s").splitlines()
    assert subjects == [f"avm: update decision {record.id[:8]}", f"avm: create decision {record.id[:8]}"]
    assert run(repo, "log", "--format=%an <%ae>", "-1") == "Dana Tester <dana@example.invalid>"
    assert sorted(run(repo, "show", "--name-only", "--format=", "HEAD~1").splitlines()) == [
        "_dashboards/memory.base",
        "proj/_index.md",
        record.path,
    ]
    assert run(repo, "show", "--name-only", "--format=", "HEAD").splitlines() == [record.path]


def test_handoff_state_changes_and_supersedes_are_committed_with_their_own_operation_name(repo):
    store = committing_store(repo)
    old = store.create_handoff(to="b", summary="One", context="c", namespace="proj")
    new = store.create_handoff(to="b", summary="Two", context="c", namespace="proj", supersedes=[old.id])
    store.reopen_handoff(old.id, "proj")
    store.read_handoff("b", "proj")

    assert run(repo, "log", "--format=%s").splitlines() == [
        f"avm: read handoff {new.id[:8]}",
        f"avm: reopen handoff {old.id[:8]}",
        f"avm: create handoff {new.id[:8]}",
        f"avm: create handoff {old.id[:8]}",
    ]
    assert old.path in run(repo, "show", "--name-only", "--format=", "HEAD~2").splitlines()
    assert new.path in run(repo, "show", "--name-only", "--format=", "HEAD~2").splitlines()


def test_nothing_is_committed_unless_the_feature_is_on(repo):
    store = Store(Vault(repo), clock=TickingClock())

    store.save_context(agent="a", title="Quiet", content="c", namespace="proj")

    assert run(repo, "rev-list", "--all", "--count") == "0"


def test_the_state_directory_is_ignored_and_other_files_are_not_committed(repo):
    (repo / ".gitignore").write_text("*.log", encoding="utf-8")
    (repo / "scratch.txt").write_text("mine", encoding="utf-8")
    store = committing_store(repo)

    store.save_context(agent="a", title="Note", content="c", namespace="proj")

    assert (repo / ".gitignore").read_text(encoding="utf-8") == "*.log\n.agent-vault-memory/\n"
    assert run(repo, "status", "--porcelain").splitlines() == ["?? .gitignore", "?? scratch.txt"]


def test_a_failing_commit_is_logged_and_never_fails_the_write(repo, capsys):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho blocked by policy >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    store = committing_store(repo)

    record = store.save_context(agent="a", title="Still saved", content="c", namespace="proj")

    assert store.get_last_context("proj").id == record.id
    assert "git autocommit skipped: git commit failed" in capsys.readouterr().err


def test_a_vault_outside_any_work_tree_is_written_without_git(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()

    record = committing_store(root).save_context(agent="a", title="Plain", content="c", namespace="proj")

    assert (root / record.path).exists()


def test_status_reports_branch_changes_and_distance_from_the_upstream_and_never_pushes(repo, tmp_path):
    remote = tmp_path / "remote.git"
    run(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    run(repo, "remote", "add", "origin", str(remote))
    store = committing_store(repo)
    store.save_context(agent="a", title="Base", content="c", namespace="proj")
    run(repo, "push", "-q", "-u", "origin", "main")

    store.save_context(agent="a", title="Ahead", content="c", namespace="proj")
    (repo / "proj" / "note" / "loose.md").write_text("x", encoding="utf-8")

    status = git.status(repo)
    assert (status.branch, status.upstream, status.ahead, status.behind) == ("main", "origin/main", 1, 0)
    assert status.changed == 2
    assert run(remote, "rev-list", "--count", "main") == "1"


def test_status_is_none_outside_a_work_tree(tmp_path):
    assert git.status(tmp_path) is None
