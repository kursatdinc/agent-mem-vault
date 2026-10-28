import fcntl
import os

import pytest

from agent_mem_vault.records import render_record
from agent_mem_vault.vault import ConflictError, LockTimeoutError, Vault, VaultError


def write_record(vault, relpath, meta, body="Body text.\n"):
    target = vault.root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_record(meta, body), encoding="utf-8")


def valid_meta(record_id="11111111-aaaa", kind="note", namespace="proj"):
    return {"id": record_id, "kind": kind, "namespace": namespace, "title": "T", "created": "2026-10-28T09:00:00Z"}


def test_vault_rejects_a_missing_directory(tmp_path):
    with pytest.raises(VaultError, match="not a directory"):
        Vault(tmp_path / "nope")


def test_lock_times_out_with_a_clear_error_while_another_descriptor_holds_it(vault):
    vault.ensure_state()
    holder = os.open(vault.lock_path, os.O_CREAT | os.O_RDWR)
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        with (
            pytest.raises(LockTimeoutError, match="could not lock the vault within 0.2s"),
            Vault(vault.root, lock_timeout=0.2).lock(),
        ):
            pass
    finally:
        os.close(holder)

    with vault.lock():
        pass


def test_leftover_tmp_files_are_reported_then_removed(vault, capsys):
    vault.ensure_state()
    (vault.tmp_dir / "half-written.tmp").write_text("---\nid: x", encoding="utf-8")

    assert [path.name for path in vault.tmp_leftovers()] == ["half-written.tmp"]
    removed = vault.clean_tmp_leftovers()

    assert [path.name for path in removed] == ["half-written.tmp"]
    assert vault.tmp_leftovers() == []
    assert "removed incomplete write half-written.tmp" in capsys.readouterr().err


def test_state_dir_is_gitignored_only_inside_a_git_repository(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    Vault(plain).ensure_state()
    assert not (plain / ".gitignore").exists()

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".gitignore").write_text("*.log", encoding="utf-8")
    Vault(repo).ensure_state()
    Vault(repo).ensure_state()
    assert (repo / ".gitignore").read_text(encoding="utf-8") == "*.log\n.agent-mem-vault/\n"


def test_scan_reports_invalid_candidates_and_ignores_everything_else(vault):
    write_record(vault, "proj/note/2026-10-28-ok-11111111.md", valid_meta())
    write_record(vault, "proj/note/2026-10-28-zdup-11111111b.md", valid_meta())
    write_record(vault, "proj/note/no-id.md", {"kind": "note", "namespace": "proj"})
    write_record(vault, "proj/note/bad-kind.md", valid_meta("22222222", kind="bogus"))
    write_record(vault, "proj/decision/wrong-folder.md", valid_meta("33333333", kind="note"))
    (vault.root / "proj/note/broken.md").write_text("---\nid: [unclosed\n---\nbody", encoding="utf-8")
    (vault.root / "proj/note/plain.md").write_text("no frontmatter at all", encoding="utf-8")
    write_record(vault, "proj/proj.md", valid_meta("44444444"))
    write_record(vault, "proj/unknown-kind/x.md", valid_meta("55555555"))
    write_record(vault, "loose.md", valid_meta("66666666"))
    write_record(vault, ".hidden/note/x.md", valid_meta("77777777"))
    write_record(vault, "_dashboards/memory.md", valid_meta("88888888"))

    result = vault.scan()

    assert [record.id for record in result.records] == ["11111111-aaaa"]
    assert {issue.path: issue.reason for issue in result.issues} == {
        "proj/note/2026-10-28-zdup-11111111b.md": "duplicate id (also at proj/note/2026-10-28-ok-11111111.md)",
        "proj/note/no-id.md": "missing or invalid id",
        "proj/note/bad-kind.md": "unknown kind: bogus",
        "proj/decision/wrong-folder.md": "kind note does not match folder decision",
        "proj/note/broken.md": "unparseable frontmatter: ParserError",
        "proj/note/plain.md": "missing frontmatter",
    }


def test_scan_refuses_a_symlinked_record_that_resolves_outside_the_vault(vault, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text(render_record(valid_meta("99999999"), "secret"), encoding="utf-8")
    link = vault.root / "proj/note/linked.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)

    result = vault.scan()

    assert result.records == []
    assert [(issue.path, issue.reason) for issue in result.issues] == [
        ("proj/note/linked.md", "resolves outside the vault")
    ]


def test_update_retries_once_when_a_human_edits_the_file_midway(vault):
    relpath = "proj/note/2026-10-28-ok-11111111.md"
    write_record(vault, relpath, valid_meta())
    attempts = []

    def rebuild(record):
        attempts.append(record.body)
        if len(attempts) == 1:
            (vault.root / relpath).write_text(render_record(valid_meta(), "Human edit.\n"), encoding="utf-8")
        return render_record({**record.meta, "revision": 2}, record.body)

    with vault.lock():
        updated = vault.update_file(relpath, rebuild)

    assert attempts == ["Body text.\n", "Human edit.\n"]
    assert updated.content == "Human edit."
    assert updated.revision == 2


def test_update_reports_a_conflict_instead_of_overwriting_a_changing_file(vault):
    relpath = "proj/note/2026-10-28-ok-11111111.md"
    write_record(vault, relpath, valid_meta())
    edits = iter(["First human edit.\n", "Second human edit.\n"])

    def rebuild(record):
        (vault.root / relpath).write_text(render_record(valid_meta(), next(edits)), encoding="utf-8")
        return render_record({**record.meta, "revision": 2}, record.body)

    with vault.lock(), pytest.raises(ConflictError, match="was changed while updating it"):
        vault.update_file(relpath, rebuild)

    assert vault.scan().records[0].content == "Second human edit."
    assert vault.tmp_leftovers() == []
