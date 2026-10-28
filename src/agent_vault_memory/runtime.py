from agent_vault_memory.config import Config
from agent_vault_memory.records import KINDS, RECEIPT_KIND
from agent_vault_memory.store import Store
from agent_vault_memory.vault import Vault


def open_vault(config: Config) -> Vault:
    return Vault(config.vault, kinds=(*KINDS, RECEIPT_KIND) if config.receipts else KINDS)


def open_store(config: Config) -> Store:
    return Store(
        open_vault(config),
        config.default_namespace,
        config.redact_secrets,
        git_autocommit=config.git_autocommit,
        companion_max_chars=config.companion_max_chars if config.companion else None,
    )
