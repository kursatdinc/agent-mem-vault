from pathlib import Path

from agent_mem_vault import git
from agent_mem_vault.config import Config
from agent_mem_vault.records import KINDS, RECEIPT_KIND
from agent_mem_vault.store import Store
from agent_mem_vault.vault import Vault


def repo_namespace(cwd: Path) -> str | None:
    """`project/<basename of the git root>` for a directory inside a git work tree, else None."""
    try:
        root = Path(git.run_git(cwd, "rev-parse", "--show-toplevel"))
    except git.GitError:
        return None
    return f"project/{root.name}"


def open_vault(config: Config) -> Vault:
    return Vault(config.vault, kinds=(*KINDS, RECEIPT_KIND) if config.receipts else KINDS)


def open_store(config: Config) -> Store:
    """A store whose default namespace is the repository of the working directory, else the configured one."""
    return Store(
        open_vault(config),
        repo_namespace(Path.cwd()) or config.default_namespace,
        config.redact_secrets,
        git_autocommit=config.git_autocommit,
        companion_max_chars=config.companion_max_chars if config.companion else None,
        visibility_filter=config.visibility,
    )
