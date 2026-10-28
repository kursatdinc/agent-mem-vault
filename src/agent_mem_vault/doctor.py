import json
import subprocess
from collections import Counter

from agent_mem_vault import git
from agent_mem_vault.config import Config
from agent_mem_vault.links import normalized_target, unresolved_targets
from agent_mem_vault.runtime import open_vault
from agent_mem_vault.vault import Vault

OBSIDIAN_TIMEOUT_SECONDS = 30
NOT_RUNNING = "Obsidian not running: parity check skipped"


def run_doctor(config: Config) -> int:
    vault = open_vault(config)
    scan = vault.scan()
    counts = Counter(record.kind for record in scan.records)
    leftovers = vault.tmp_leftovers()
    unresolved = unresolved_targets(vault, scan.records)
    print(f"config file: {config.config_file or 'none (defaults and environment)'}")
    print(f"vault: {vault.root}")
    print(f".obsidian: {'present' if (vault.root / '.obsidian').is_dir() else 'missing'}")
    print(f"default namespace: {config.default_namespace}")
    print(f"redact secrets: {str(config.redact_secrets).lower()}")
    print(f"git autocommit: {str(config.git_autocommit).lower()}")
    flags = (("receipts", config.receipts), ("companion", config.companion))
    flags += (("visibility", config.visibility), ("hooks", config.hooks))
    print("features: " + ", ".join(f"{name} {'on' if enabled else 'off'}" for name, enabled in flags))
    breakdown = ", ".join(f"{kind} {count}" for kind, count in sorted(counts.items()))
    print(f"records: {len(scan.records)}" + (f" ({breakdown})" if breakdown else ""))
    print(f"issues: {len(scan.issues)}")
    for issue in scan.issues:
        print(f"  {issue.path}: {issue.reason}")
    print(f"tmp leftovers: {len(leftovers)}")
    for path in leftovers:
        print(f"  {path.name}")
    print(f"unresolved links in records: {sum(len(targets) for targets in unresolved.values())}")
    print(_git_line(vault))
    for line in _obsidian_parity(vault, unresolved):
        print(line)
    return 0


def _git_line(vault: Vault) -> str:
    status = git.status(vault.root)
    if status is None:
        return "git: not a git work tree"
    changes = f"dirty ({status.changed} changed)" if status.changed else "clean"
    distance = (
        f"ahead {status.ahead}, behind {status.behind} of {status.upstream}" if status.upstream else "no upstream"
    )
    return f"git: branch {status.branch}, {changes}, {distance}"


def _obsidian_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "Obsidian"], capture_output=True, check=False).returncode == 0
    except OSError:
        return False


def _reported_unresolved(output: str) -> set[tuple[str, str]]:
    """Pairs of (source file, link) from `obsidian unresolved verbose format=json`."""
    pairs: set[tuple[str, str]] = set()
    for entry in json.loads(output):
        link = entry.get("link") or entry.get("name") or entry.get("target")
        sources = entry.get("files") or entry.get("sources") or entry.get("source") or entry.get("file")
        if not link or not sources:
            raise ValueError("entry without a link and its source files")
        for source in [sources] if isinstance(sources, str) else sources:
            pairs.add((source, normalized_target(link)))
    return pairs


def _obsidian_parity(vault: Vault, ours: dict[str, set[str]]) -> list[str]:
    if not _obsidian_running():
        return [NOT_RUNNING]
    try:
        result = subprocess.run(
            ["obsidian", "unresolved", "verbose", "format=json"],
            cwd=vault.root,
            capture_output=True,
            text=True,
            timeout=OBSIDIAN_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return ["obsidian CLI not found: parity check skipped"]
    except (OSError, subprocess.TimeoutExpired) as error:
        return [f"obsidian CLI failed: parity check skipped ({error})"]
    if result.returncode != 0:
        return [f"obsidian CLI failed: parity check skipped ({result.stderr.strip() or result.returncode})"]
    try:
        reported = {pair for pair in _reported_unresolved(result.stdout) if pair[0] in ours}
    except (ValueError, AttributeError, TypeError):
        return ["obsidian CLI output not understood: parity check skipped"]
    mine = {(path, target) for path, targets in ours.items() for target in targets}
    if mine == reported:
        return [f"obsidian parity: ok ({len(mine)} unresolved links match)"]
    return [
        "obsidian parity: differences",
        *(f"  only avm: {path} -> {target}" for path, target in sorted(mine - reported)),
        *(f"  only obsidian: {path} -> {target}" for path, target in sorted(reported - mine)),
    ]
