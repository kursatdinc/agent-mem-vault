import subprocess

import pytest

from agent_mem_vault.cli import main
from agent_mem_vault.store import Store
from conftest import TickingClock


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def stem(record):
    return record.path.removesuffix(".md")


def archived(record):
    namespace_dir, kind, name = record.path.split("/", 2)
    return f"{namespace_dir}/_archive/{kind}/{name}"


@pytest.fixture
def closed_vault(configured_vault):
    store = Store(configured_vault, clock=TickingClock())
    old = store.save_memory(agent="a", kind="decision", title="Use SQLite", content="first", namespace="project/alpha")
    new = store.save_memory(
        agent="a",
        kind="decision",
        title="Use PostgreSQL",
        content="second",
        namespace="project/alpha",
        supersedes=[old.id],
    )
    risk = store.save_memory(agent="a", kind="risk", title="Locks the table", content="r", namespace="project/alpha")
    store.update_memory(risk.id, status="resolved")
    note = store.save_context(
        agent="a", title="Kept note", content=f"See [[{stem(old)}|the old choice]].", namespace="project/alpha"
    )
    return configured_vault, old, new, store.get_memories([risk.id])[0] or risk, note


def test_a_dry_run_lists_every_closed_record_and_changes_nothing(closed_vault, capsys):
    vault, old, _, risk, _ = closed_vault
    before = sorted(p.as_posix() for p in vault.root.rglob("*.md"))

    assert main(["archive", "--dry-run"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"would move {old.path} -> {archived(old)}",
        f"would move {risk.path} -> {archived(risk)}",
        "Dry run: 2 closed records to archive. Run `agent-mem-vault archive --apply` to archive them.",
    ]
    assert sorted(p.as_posix() for p in vault.root.rglob("*.md")) == before


def test_apply_moves_closed_records_out_of_the_server_view_and_relinks_every_note(closed_vault, capsys):
    vault, old, new, risk, note = closed_vault
    root = vault.root

    assert main(["archive", "--apply"]) == 0

    out = capsys.readouterr().out.splitlines()
    assert out[:2] == [f"moved {old.path} -> {archived(old)}", f"moved {risk.path} -> {archived(risk)}"]
    assert "Archived 2 closed records." in out
    assert not (root / old.path).exists() and (root / archived(old)).is_file()
    assert not (root / risk.path).exists() and (root / archived(risk)).is_file()
    for path in (new.path, note.path, archived(old)):
        text = (root / path).read_text(encoding="utf-8")
        assert f"[[{stem(old)}" not in text
    assert f"[[{archived(old).removesuffix('.md')}|the old choice]]" in (root / note.path).read_text(encoding="utf-8")
    store = Store(vault)
    titles = [r.title for r in store.search_memory("project/alpha", include_closed=True)]
    assert sorted(titles) == ["Kept note", "Use PostgreSQL"]
    assert store.get_links(new.id)[1].unresolved == []
    assert "Use SQLite" not in (root / "project-alpha" / "project-alpha.md").read_text(encoding="utf-8")
    assert vault.scan().issues == []


def test_apply_again_finds_nothing(closed_vault, capsys):
    main(["archive", "--apply"])
    capsys.readouterr()

    assert main(["archive", "--apply"]) == 0
    assert capsys.readouterr().out == "No closed records found.\nHubs are up to date.\n"


def test_apply_commits_the_moves_and_the_relinked_notes(closed_vault, capsys):
    vault, old, new, _, note = closed_vault
    root = vault.root
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Dana Tester")
    git(root, "config", "user.email", "dana@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    (root / ".gitignore").write_text(".agent-mem-vault/\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "before")

    assert main(["archive", "--apply"]) == 0

    assert git(root, "log", "-1", "--format=%s") == "avm: archive 2 closed records"
    changed = git(root, "show", "--no-renames", "--name-status", "--format=", "HEAD").splitlines()
    assert f"D\t{old.path}" in changed
    assert f"A\t{archived(old)}" in changed
    assert f"M\t{new.path}" in changed
    assert f"M\t{note.path}" in changed
    assert git(root, "status", "--porcelain") == ""
    capsys.readouterr()
