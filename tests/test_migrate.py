import subprocess

import pytest

from agent_mem_vault.cli import main
from agent_mem_vault.store import Store
from conftest import TickingClock

FIRST = "2026-10-01-handoff-to-codex-0f0f0f0f.md"
SECOND = "2026-10-02-handoff-to-codex-1e1e1e1e.md"


def legacy_handoff(record_id, namespace, body):
    return (
        f"---\nid: {record_id}\nkind: handoff\nnamespace: {namespace}\nagent: handoff\ntitle: Handoff to codex\n"
        f"created: 2026-10-01T09:00:00Z\nto: codex\nread: false\n---\n{body}\n"
    )


def files(root):
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    )


@pytest.fixture
def legacy_vault(configured_vault):
    root = configured_vault.root
    Store(configured_vault, clock=TickingClock()).save_context(
        agent="a", title="Kept note", content="c", namespace="project/alpha"
    )
    alpha = root / "project-alpha" / "handoff"
    alpha.mkdir()
    (alpha / FIRST).write_text(legacy_handoff("0f0f0f0f-0000", "project/alpha", "First plan."), encoding="utf-8")
    (alpha / SECOND).write_bytes(
        legacy_handoff(
            "1e1e1e1e-0000",
            "project/alpha",
            "Supersedes [[project-alpha/handoff/2026-10-01-handoff-to-codex-0f0f0f0f]].",
        )
        .replace("\n", "\r\n")
        .encode("utf-8")
    )
    beta = root / "beta" / "handoff"
    beta.mkdir(parents=True)
    (beta / FIRST).write_text(legacy_handoff("2d2d2d2d-0000", "beta", "Beta plan."), encoding="utf-8")
    hub = root / "project-alpha" / "project-alpha.md"
    hub.write_text(
        hub.read_text(encoding="utf-8")
        + "\n## handoff\n\n- [[project-alpha/handoff/2026-10-01-handoff-to-codex-0f0f0f0f|Handoff to codex]]\n",
        encoding="utf-8",
    )
    return configured_vault


def test_a_dry_run_lists_every_legacy_handoff_and_changes_nothing(legacy_vault, capsys):
    before = files(legacy_vault.root)

    assert main(["migrate", "--dry-run"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"would move beta/handoff/{FIRST} -> beta/_archive/handoffs/{FIRST}",
        f"would move project-alpha/handoff/{FIRST} -> project-alpha/_archive/handoffs/{FIRST}",
        f"would move project-alpha/handoff/{SECOND} -> project-alpha/_archive/handoffs/{SECOND}",
        "Dry run: 3 legacy handoffs to move. Run `agent-mem-vault migrate --apply` to move them.",
    ]
    assert files(legacy_vault.root) == before


def test_apply_archives_every_legacy_handoff_rewrites_their_links_and_refreshes_the_hub(legacy_vault, capsys):
    root = legacy_vault.root

    assert main(["migrate", "--apply"]) == 0

    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"moved beta/handoff/{FIRST} -> beta/_archive/handoffs/{FIRST}"
    assert out[-1] == "Moved 3 legacy handoffs."
    assert not (root / "project-alpha" / "handoff").exists()
    assert not (root / "beta" / "handoff").exists()
    archived = (root / "project-alpha" / "_archive" / "handoffs" / SECOND).read_bytes()
    assert archived == legacy_handoff(
        "1e1e1e1e-0000",
        "project/alpha",
        "Supersedes [[project-alpha/_archive/handoffs/2026-10-01-handoff-to-codex-0f0f0f0f]].",
    ).replace("\n", "\r\n").encode("utf-8")
    assert "handoff" not in (root / "project-alpha" / "project-alpha.md").read_text(encoding="utf-8")
    assert not (root / "beta" / "beta.md").exists()
    store = Store(legacy_vault)
    assert [record.title for record in store.list_contexts("project/alpha")] == ["Kept note"]
    assert store.search_memory("beta", "plan") == []
    assert legacy_vault.scan().issues == []


def test_apply_again_finds_nothing_and_a_clean_vault_says_so(legacy_vault, capsys):
    main(["migrate", "--apply"])
    capsys.readouterr()

    assert main(["migrate", "--apply"]) == 0
    assert capsys.readouterr().out == "No legacy handoffs found.\n"
    assert main(["migrate", "--dry-run"]) == 0
    assert capsys.readouterr().out == "No legacy handoffs found.\n"


def test_a_taken_archive_path_is_skipped_and_the_handoff_stays(legacy_vault, capsys):
    taken = legacy_vault.root / "beta" / "_archive" / "handoffs" / FIRST
    taken.parent.mkdir(parents=True)
    taken.write_text("mine\n", encoding="utf-8")

    assert main(["migrate", "--apply"]) == 0

    out = capsys.readouterr().out.splitlines()
    assert f"skipped beta/handoff/{FIRST}: beta/_archive/handoffs/{FIRST} already exists" in out
    assert out[-1] == "Moved 2 legacy handoffs."
    assert taken.read_text(encoding="utf-8") == "mine\n"
    assert (legacy_vault.root / "beta" / "handoff" / FIRST).is_file()


@pytest.mark.parametrize("argv", [["migrate"], ["migrate", "--dry-run", "--apply"]])
def test_migrate_needs_exactly_one_of_dry_run_and_apply(legacy_vault, capsys, argv):
    before = files(legacy_vault.root)

    with pytest.raises(SystemExit) as exit_info:
        main(argv)

    assert exit_info.value.code == 2
    assert "--dry-run" in capsys.readouterr().err
    assert files(legacy_vault.root) == before


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_apply_commits_the_moves_and_the_hub_in_the_vault_repository_only(legacy_vault, capsys):
    root = legacy_vault.root
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Dana Tester")
    git(root, "config", "user.email", "dana@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    (root / ".gitignore").write_text(".agent-mem-vault/\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "reset", "-q", "--", f"beta/handoff/{FIRST}")
    git(root, "commit", "-q", "-m", "before")
    (root / "scratch.txt").write_text("mine", encoding="utf-8")

    assert main(["migrate", "--apply"]) == 0

    assert git(root, "log", "-1", "--format=%s") == "avm: migrate 3 legacy handoffs"
    changed = git(root, "show", "--no-renames", "--name-status", "--format=", "HEAD").splitlines()
    assert f"D\tproject-alpha/handoff/{FIRST}" in changed
    assert f"A\tbeta/_archive/handoffs/{FIRST}" in changed
    assert "M\tproject-alpha/project-alpha.md" in changed
    assert git(root, "status", "--porcelain").splitlines() == ["?? scratch.txt"]
    capsys.readouterr()


def test_doctor_points_at_migrate_while_legacy_handoffs_remain(legacy_vault, capsys):
    assert main(["doctor"]) == 0
    assert "legacy handoffs: 3 (archive them with: agent-mem-vault migrate --apply)" in capsys.readouterr().out

    main(["migrate", "--apply"])
    capsys.readouterr()
    assert main(["doctor"]) == 0
    assert "legacy handoffs" not in capsys.readouterr().out
