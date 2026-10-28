import io
import json
import re
import subprocess
import sys
import time

import pytest

from agent_vault_memory.cli import main
from agent_vault_memory.store import Store
from conftest import TickingClock

HOOKS_ON = "features:\n  hooks: true\n"
STOP_NUDGE_TEXT = (
    "[agent-vault-memory] Work state changed since the last check. Before finishing, record durable decisions, "
    "risks and next steps with the agent-vault-memory tools (save_memory with kind decision or risk, "
    "create_handoff for a hand-over). If there is nothing durable to record, say so in one line and stop."
)


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=Tester", "-c", "user.email=tester@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def hooks_vault(configured_vault, tmp_path):
    (tmp_path / "config.yaml").write_text(HOOKS_ON, encoding="utf-8")
    return configured_vault


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "demo-repo"
    (root / "src").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "commit", "-q", "--allow-empty", "-m", "initial")
    return root


def run_cli(monkeypatch, capsys, argv, payload=None, raw=None):
    text = raw if raw is not None else json.dumps(payload or {})
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def save_snapshot(vault, namespace, content="Snapshot body."):
    Store(vault, clock=TickingClock()).create_snapshot(
        agent="a", title="Demo state", content=content, namespace=namespace
    )


def test_session_start_for_claude_prints_the_brief_as_hook_json_for_the_git_root_namespace(
    hooks_vault, repo, monkeypatch, capsys
):
    save_snapshot(hooks_vault, "project/demo-repo")

    code, out, _ = run_cli(
        monkeypatch, capsys, ["hook", "session-start", "--client", "claude"], {"cwd": str(repo / "src")}
    )

    assert code == 0
    assert json.loads(out) == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "**Demo state** - project/demo-repo - 10/28/2026, 9:00:01 AM\n\nSnapshot body.",
        }
    }


def test_session_start_for_codex_prints_plain_text(hooks_vault, repo, monkeypatch, capsys):
    save_snapshot(hooks_vault, "project/demo-repo")

    code, out, _ = run_cli(monkeypatch, capsys, ["hook", "session-start", "--client", "codex"], {"cwd": str(repo)})

    assert code == 0
    assert out == "**Demo state** - project/demo-repo - 10/28/2026, 9:00:01 AM\n\nSnapshot body.\n"


def test_outside_a_git_repository_the_namespace_falls_back_to_the_cwd_basename(
    hooks_vault, tmp_path, monkeypatch, capsys
):
    plain = tmp_path / "plain-dir"
    plain.mkdir()

    _, out, _ = run_cli(monkeypatch, capsys, ["hook", "session-start", "--client", "codex"], {"cwd": str(plain)})

    assert re.fullmatch(
        r"\*\*Project brief for project/plain-dir\*\* - project/plain-dir - \d+/\d+/\d{4}, \d+:\d{2}:\d{2} [AP]M\n\n"
        r"No saved memory found for namespace: project/plain-dir\n",
        out,
    )


def test_the_session_context_is_capped_at_9000_characters(hooks_vault, repo, monkeypatch, capsys):
    save_snapshot(hooks_vault, "project/demo-repo", content="z" * 20_000)

    _, out, _ = run_cli(monkeypatch, capsys, ["hook", "session-start", "--client", "claude"], {"cwd": str(repo)})

    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert len(context) == 9000
    assert context.endswith("zzz\n[brief truncated]")


def test_hooks_print_nothing_and_exit_zero_while_the_feature_is_off(configured_vault, repo, monkeypatch, capsys):
    save_snapshot(configured_vault, "project/demo-repo")

    for action in ("session-start", "stop"):
        code, out, err = run_cli(monkeypatch, capsys, ["hook", action, "--client", "claude"], {"cwd": str(repo)})
        assert (code, out, err) == (0, "", "")


def test_every_failure_still_exits_zero_with_the_reason_on_stderr(hooks_vault, repo, tmp_path, monkeypatch, capsys):
    argv = ["hook", "session-start", "--client", "codex"]
    monkeypatch.setenv("AGENT_VAULT_MEMORY_VAULT", str(tmp_path / "missing-vault"))
    missing_vault = run_cli(monkeypatch, capsys, argv, {"cwd": str(repo)})
    monkeypatch.delenv("AGENT_VAULT_MEMORY_VAULT")
    no_vault_setting = run_cli(monkeypatch, capsys, argv, {"cwd": str(repo)})
    monkeypatch.setenv("AGENT_VAULT_MEMORY_VAULT", str(hooks_vault.root))
    monkeypatch.chdir(tmp_path)
    garbage_payload = run_cli(monkeypatch, capsys, argv, raw="not json")

    assert missing_vault == (
        0,
        "",
        "agent-vault-memory: hook session-start skipped: "
        f"vault path is not a directory: {tmp_path / 'missing-vault'}\n",
    )
    assert no_vault_setting[0:2] == (0, "")
    assert "vault is not configured" in no_vault_setting[2]
    assert garbage_payload[0] == 0
    assert garbage_payload[1].endswith(f"No saved memory found for namespace: project/{tmp_path.name}\n")


def test_stop_nudges_once_per_git_state_change(hooks_vault, repo, monkeypatch, capsys):
    argv = ["hook", "stop", "--client", "claude"]
    payload = {"cwd": str(repo)}

    first = run_cli(monkeypatch, capsys, argv, payload)
    repeated = run_cli(monkeypatch, capsys, argv, payload)
    (repo / "notes.txt").write_text("edit", encoding="utf-8")
    dirtied = run_cli(monkeypatch, capsys, argv, payload)
    dirtied_again = run_cli(monkeypatch, capsys, argv, payload)
    git(repo, "add", "notes.txt")
    git(repo, "commit", "-q", "-m", "add notes")
    committed = run_cli(monkeypatch, capsys, argv, payload)

    block = json.dumps({"decision": "block", "reason": STOP_NUDGE_TEXT}) + "\n"
    assert first == (0, block, "")
    assert repeated == (0, "", "")
    assert dirtied == (0, block, "")
    assert dirtied_again == (0, "", "")
    assert committed == (0, block, "")
    assert (hooks_vault.root / ".agent-vault-memory" / "state" / "stop-project-demo-repo").is_file()


def test_stop_for_codex_prints_the_nudge_as_plain_text_and_respects_an_active_stop_hook(
    hooks_vault, repo, monkeypatch, capsys
):
    argv = ["hook", "stop", "--client", "codex"]

    reentrant = run_cli(monkeypatch, capsys, argv, {"cwd": str(repo), "stop_hook_active": True})
    plain = run_cli(monkeypatch, capsys, argv, {"cwd": str(repo)})

    assert reentrant == (0, "", "")
    assert plain == (0, STOP_NUDGE_TEXT + "\n", "")


def test_stop_stays_silent_outside_a_git_work_tree(hooks_vault, tmp_path, monkeypatch, capsys):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    result = run_cli(monkeypatch, capsys, ["hook", "stop", "--client", "claude"], {"cwd": str(plain)})

    assert result == (0, "", "")


@pytest.mark.parametrize("client", ["claude", "codex"])
def test_print_config_prints_the_settings_snippet_and_never_touches_client_settings(
    configured_vault, tmp_path, monkeypatch, capsys, client
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    code, out, err = run_cli(monkeypatch, capsys, ["hook", "print-config", "--client", client])

    command = f"agent-vault-memory hook %s --client {client}"
    assert code == 0
    assert json.loads(out) == {
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": command % "session-start", "timeout": 5}]}],
            "Stop": [{"hooks": [{"type": "command", "command": command % "stop", "timeout": 5}]}],
        }
    }
    assert err.startswith("Merge this into ")
    assert not (tmp_path / "home").exists()


def write_generated_vault(root, count):
    for index in range(count):
        namespace = f"project-p{index % 5}"
        created = f"2026-01-{index % 28 + 1:02d}T10:{index // 60 % 60:02d}:{index % 60:02d}Z"
        kind = ("note", "decision", "risk", "task")[index % 4]
        folder = root / namespace / kind
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{created[:10]}-record-{index}-{index:08x}.md").write_text(
            f"---\nid: {index:08x}-0000-4000-8000-000000000000\nkind: {kind}\nnamespace: project/p{index % 5}\n"
            f"agent: gen\ntitle: Generated record {index}\ncreated: {created}\nupdated: {created}\nrevision: 1\n"
            f"visibility: internal\nvalidity: valid\ntags: [bulk]\n---\n{'Body text of a generated record. ' * 8}\n",
            encoding="utf-8",
        )


def test_session_start_finishes_under_two_seconds_on_a_5000_record_vault(tmp_path):
    vault_root = tmp_path / "big-vault"
    vault_root.mkdir()
    write_generated_vault(vault_root, 5000)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(HOOKS_ON, encoding="utf-8")
    payload = json.dumps({"cwd": str(tmp_path / "p1")})
    (tmp_path / "p1").mkdir()
    environment = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "AGENT_VAULT_MEMORY_VAULT": str(vault_root),
        "AGENT_VAULT_MEMORY_CONFIG": str(config_file),
    }

    started = time.perf_counter()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from agent_vault_memory.cli import run; run()",
            "hook",
            "session-start",
            "--client",
            "claude",
        ],
        input=payload,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - started

    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert result.returncode == 0
    assert context.startswith("**Project brief for project/p1** - project/p1 - ")
    assert context.count("\n- [") == 10
    assert elapsed < 2.0
