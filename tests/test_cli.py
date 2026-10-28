import pytest

from agent_vault_memory.cli import main
from agent_vault_memory.store import Store
from agent_vault_memory.vault import Vault


@pytest.fixture
def configured_vault(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    root.mkdir()
    config_file = tmp_path / "config.yaml"
    config_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("AGENT_VAULT_MEMORY_VAULT", str(root))
    monkeypatch.setenv("AGENT_VAULT_MEMORY_CONFIG", str(config_file))
    monkeypatch.delenv("AGENT_VAULT_MEMORY_DEFAULT_NAMESPACE", raising=False)
    monkeypatch.delenv("AGENT_VAULT_MEMORY_REDACT_SECRETS", raising=False)
    return Vault(root)


def test_help_exits_zero_and_names_the_program(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    output = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert "agent-vault-memory" in output
    for command in ("doctor", "list", "search", "handoffs"):
        assert command in output


def test_a_missing_vault_setting_is_reported_on_stderr_with_exit_code_two(tmp_path, monkeypatch, capsys):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("AGENT_VAULT_MEMORY_CONFIG", str(config_file))
    monkeypatch.delenv("AGENT_VAULT_MEMORY_VAULT", raising=False)

    assert main(["list"]) == 2
    assert "vault is not configured" in capsys.readouterr().err


def test_list_search_and_handoffs_print_the_legacy_line_format(configured_vault, capsys):
    store = Store(configured_vault)
    store.save_memory(
        agent="planner", kind="decision", title="Pick storage", content="Markdown files.", namespace="alpha"
    )
    store.save_context(agent="planner", title="Other note", content="Unrelated.", namespace="alpha")
    store.create_handoff(to="codex", summary="Continue", context="Details", namespace="alpha")

    assert main(["list", "--namespace", "alpha", "--kind", "decision"]) == 0
    listed = capsys.readouterr().out.splitlines()
    assert len(listed) == 1
    assert listed[0].startswith("1. [context/decision] (alpha) Pick storage - planner - ")

    assert main(["search", "markdown", "--namespace", "alpha"]) == 0
    assert capsys.readouterr().out.startswith("1. [context/decision] (alpha) Pick storage - planner - ")

    assert main(["handoffs", "--namespace", "alpha", "--status", "pending", "--agent", "codex"]) == 0
    assert capsys.readouterr().out.startswith("1. [handoff/handoff -> codex [PENDING]] (alpha) Handoff to codex - ")

    assert main(["search", "nonexistent"]) == 0
    assert capsys.readouterr().out == "No matching memory found.\n"
    assert main(["handoffs", "--namespace", "empty"]) == 0
    assert capsys.readouterr().out == "No handoffs found.\n"
    assert main(["list", "--namespace", "empty"]) == 0
    assert capsys.readouterr().out == "No saved context yet.\n"


def test_doctor_reports_config_vault_counts_issues_and_leftovers_without_touching_the_vault(configured_vault, capsys):
    store = Store(configured_vault)
    store.save_memory(agent="a", kind="decision", title="D", content="c")
    store.save_context(agent="a", title="N1", content="c")
    store.save_context(agent="a", title="N2", content="c")
    (configured_vault.root / "default" / "note" / "broken.md").write_text("no frontmatter", encoding="utf-8")
    (configured_vault.root / ".agent-vault-memory" / "tmp" / "partial.tmp").write_text("x", encoding="utf-8")

    assert main(["doctor"]) == 0
    first = capsys.readouterr().out
    (configured_vault.root / ".obsidian").mkdir()
    assert main(["doctor"]) == 0
    second = capsys.readouterr().out

    assert f"vault: {configured_vault.root}" in first
    assert ".obsidian: missing" in first
    assert ".obsidian: present" in second
    assert "default namespace: default" in first
    assert "redact secrets: true" in first
    assert "records: 3 (decision 1, note 2)" in first
    assert "issues: 1\n  default/note/broken.md: missing frontmatter" in first
    assert "tmp leftovers: 1\n  partial.tmp" in first
    assert (configured_vault.root / ".agent-vault-memory" / "tmp" / "partial.tmp").exists()


def test_doctor_does_not_create_the_state_directory_in_a_fresh_vault(configured_vault, capsys):
    assert main(["doctor"]) == 0

    assert "records: 0" in capsys.readouterr().out
    assert not configured_vault.state_dir.exists()
