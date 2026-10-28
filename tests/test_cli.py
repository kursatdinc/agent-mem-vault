import json
import subprocess

import pytest

from agent_vault_memory.cli import main
from agent_vault_memory.store import Store


class FakeProcesses:
    """Stands in for pgrep and the obsidian CLI; git runs for real."""

    def __init__(self, real):
        self.real = real
        self.obsidian_running = False
        self.obsidian_stdout = "[]"
        self.obsidian_returncode = 0
        self.obsidian_installed = True
        self.obsidian_calls = []

    def __call__(self, argv, **kwargs):
        if argv[0] == "pgrep":
            assert argv == ["pgrep", "-x", "Obsidian"]
            return subprocess.CompletedProcess(argv, 0 if self.obsidian_running else 1, "", "")
        if argv[0] == "obsidian":
            if not self.obsidian_installed:
                raise FileNotFoundError("obsidian")
            self.obsidian_calls.append((argv, kwargs["cwd"]))
            return subprocess.CompletedProcess(argv, self.obsidian_returncode, self.obsidian_stdout, "")
        return self.real(argv, **kwargs)


@pytest.fixture(autouse=True)
def processes(monkeypatch):
    fake = FakeProcesses(subprocess.run)
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


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
    assert "features: receipts off, companion off, visibility on, hooks off" in first
    assert "records: 3 (decision 1, note 2)" in first
    assert "issues: 1\n  default/note/broken.md: missing frontmatter" in first
    assert "tmp leftovers: 1\n  partial.tmp" in first
    assert (configured_vault.root / ".agent-vault-memory" / "tmp" / "partial.tmp").exists()


def test_doctor_does_not_create_the_state_directory_in_a_fresh_vault(configured_vault, capsys):
    assert main(["doctor"]) == 0

    assert "records: 0" in capsys.readouterr().out
    assert not configured_vault.state_dir.exists()


def test_doctor_without_obsidian_running_skips_the_parity_check_and_reports_git_and_links(
    configured_vault, processes, capsys
):
    Store(configured_vault).save_context(agent="a", title="N", content="See [[Missing note]].")

    assert main(["doctor"]) == 0

    output = capsys.readouterr().out.splitlines()
    assert "git autocommit: false" in output
    assert "unresolved links in records: 1" in output
    assert "git: not a git work tree" in output
    assert output[-1] == "Obsidian not running: parity check skipped"
    assert processes.obsidian_calls == []


def test_doctor_reports_branch_dirty_state_and_missing_upstream_inside_a_git_work_tree(configured_vault, capsys):
    root = configured_vault.root
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    Store(configured_vault).save_context(agent="a", title="N", content="c")

    assert main(["doctor"]) == 0

    assert "git: branch main, dirty (3 changed), no upstream" in capsys.readouterr().out.splitlines()


def record_path(vault):
    return vault.scan().records[0].path


def test_doctor_compares_unresolved_links_with_the_obsidian_cli_restricted_to_record_files(
    configured_vault, processes, capsys
):
    Store(configured_vault).save_context(
        agent="a", title="N", content="See [[Missing note#Part|shown]] and [[_index]]."
    )
    path = record_path(configured_vault)
    processes.obsidian_running = True
    processes.obsidian_stdout = json.dumps(
        [{"link": "Missing note", "files": [path, "Journal.md"]}, {"link": "Elsewhere", "files": ["Journal.md"]}]
    )

    assert main(["doctor"]) == 0

    assert capsys.readouterr().out.splitlines()[-1] == "obsidian parity: ok (1 unresolved links match)"
    assert processes.obsidian_calls == [(["obsidian", "unresolved", "verbose", "format=json"], configured_vault.root)]


def test_doctor_prints_each_difference_between_our_scan_and_obsidian(configured_vault, processes, capsys):
    Store(configured_vault).save_context(agent="a", title="N", content="See [[Only Ours]] and [[Both]].")
    path = record_path(configured_vault)
    processes.obsidian_running = True
    processes.obsidian_stdout = json.dumps(
        [{"link": "Both", "files": [path]}, {"link": "Only Theirs", "files": [path]}]
    )

    assert main(["doctor"]) == 0

    assert capsys.readouterr().out.splitlines()[-3:] == [
        "obsidian parity: differences",
        f"  only avm: {path} -> only ours",
        f"  only obsidian: {path} -> only theirs",
    ]


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ({"obsidian_installed": False}, "obsidian CLI not found: parity check skipped"),
        ({"obsidian_returncode": 1}, "obsidian CLI failed: parity check skipped (1)"),
        ({"obsidian_stdout": "not json"}, "obsidian CLI output not understood: parity check skipped"),
        ({"obsidian_stdout": '[{"link": "X"}]'}, "obsidian CLI output not understood: parity check skipped"),
    ],
)
def test_doctor_reports_an_unusable_obsidian_cli_without_failing(configured_vault, processes, capsys, setup, expected):
    processes.obsidian_running = True
    for name, value in setup.items():
        setattr(processes, name, value)

    assert main(["doctor"]) == 0

    assert capsys.readouterr().out.splitlines()[-1] == expected
