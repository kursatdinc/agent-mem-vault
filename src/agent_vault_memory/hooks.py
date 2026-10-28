import hashlib
import json
import sys
from pathlib import Path

from agent_vault_memory import git
from agent_vault_memory.config import load_config
from agent_vault_memory.format import format_brief
from agent_vault_memory.records import namespace_slug
from agent_vault_memory.runtime import open_store
from agent_vault_memory.vault import Vault, log

CLIENTS = ("claude", "codex")
SESSION_START_LIMIT = 9000
TRUNCATION_NOTE = "\n[brief truncated]"
HOOK_TIMEOUT_SECONDS = 5
STOP_NUDGE = (
    "[agent-vault-memory] Work state changed since the last check. Before finishing, record durable decisions, "
    "risks and next steps with the agent-vault-memory tools (save_memory with kind decision or risk, "
    "create_handoff for a hand-over). If there is nothing durable to record, say so in one line and stop."
)
CLIENT_SETTINGS_FILE = {"claude": "~/.claude/settings.json", "codex": "the hooks.json of your Codex setup"}


def run_hook(action: str, client: str) -> int:
    """Run one hook entry point. It always exits 0: a failing hook must never break the client session."""
    try:
        output = print_config(client) if action == "print-config" else _run_event(action, client)
    except Exception as error:
        log(f"hook {action} skipped: {error}")
        return 0
    if output:
        print(output)
    return 0


def namespace_for(cwd: Path) -> str:
    try:
        root = Path(git.run_git(cwd, "rev-parse", "--show-toplevel"))
    except git.GitError:
        root = cwd
    return f"project/{root.name}"


def print_config(client: str) -> str:
    """The settings snippet for a client. The CLI never edits client settings itself."""
    command = f"agent-vault-memory hook %s --client {client}"
    snippet = {
        "hooks": {
            event: [{"hooks": [{"type": "command", "command": command % action, "timeout": HOOK_TIMEOUT_SECONDS}]}]
            for event, action in (("SessionStart", "session-start"), ("Stop", "stop"))
        }
    }
    print(
        f"Merge this into {CLIENT_SETTINGS_FILE[client]} and set features.hooks: true in the config.", file=sys.stderr
    )
    return json.dumps(snippet, indent=2)


def _run_event(action: str, client: str) -> str:
    config = load_config()
    if not config.hooks:
        return ""
    payload = _read_payload()
    cwd = Path(payload["cwd"]) if isinstance(payload.get("cwd"), str) and payload["cwd"] else Path.cwd()
    namespace = namespace_for(cwd)
    store = open_store(config)
    if action == "session-start":
        return _session_start(client, _capped(format_brief(store.get_project_brief(namespace))))
    if payload.get("stop_hook_active") is True or not _git_state_changed(store.vault, cwd, namespace):
        return ""
    return json.dumps({"decision": "block", "reason": STOP_NUDGE}) if client == "claude" else STOP_NUDGE


def _read_payload() -> dict:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _capped(text: str) -> str:
    if len(text) <= SESSION_START_LIMIT:
        return text
    return text[: SESSION_START_LIMIT - len(TRUNCATION_NOTE)] + TRUNCATION_NOTE


def _session_start(client: str, context: str) -> str:
    if client == "claude":
        return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}})
    return context


def _git_state_changed(vault: Vault, cwd: Path, namespace: str) -> bool:
    """True once per change of (HEAD, working tree status); outside a git work tree there is no state to compare."""
    if not git.inside_work_tree(cwd):
        return False
    try:
        head = git.run_git(cwd, "rev-parse", "HEAD")
    except git.GitError:
        head = "no-commits"
    status = "\n".join(sorted(git.run_git(cwd, "status", "--porcelain").splitlines()))
    signature = f"{head}:{hashlib.sha1(status.encode()).hexdigest()}"
    marker = vault.state_dir / "state" / f"stop-{namespace_slug(namespace)}"
    if marker.is_file() and marker.read_text(encoding="utf-8") == signature:
        return False
    vault.ensure_state()
    marker.parent.mkdir(exist_ok=True)
    marker.write_text(signature, encoding="utf-8")
    return True
