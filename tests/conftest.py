from datetime import UTC, datetime, timedelta

import pytest

from agent_mem_vault.records import KINDS, RECEIPT_KIND
from agent_mem_vault.store import Store
from agent_mem_vault.vault import Vault


class TickingClock:
    """Deterministic clock: every call is one second after the previous one."""

    def __init__(self) -> None:
        self.moment = datetime(2026, 10, 28, 9, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.moment += timedelta(seconds=1)
        return self.moment


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    return Vault(root)


@pytest.fixture
def store(vault):
    return Store(vault, clock=TickingClock())


@pytest.fixture
def receipt_store(tmp_path):
    root = tmp_path / "receipt-vault"
    root.mkdir()
    return Store(Vault(root, kinds=(*KINDS, RECEIPT_KIND)), clock=TickingClock())


@pytest.fixture
def companion_store(tmp_path):
    root = tmp_path / "companion-vault"
    root.mkdir()
    return Store(Vault(root), clock=TickingClock(), companion_max_chars=40)


@pytest.fixture
def configured_vault(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    root.mkdir()
    config_file = tmp_path / "config.yaml"
    config_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("AGENT_MEM_VAULT_VAULT", str(root))
    monkeypatch.setenv("AGENT_MEM_VAULT_CONFIG", str(config_file))
    monkeypatch.delenv("AGENT_MEM_VAULT_DEFAULT_NAMESPACE", raising=False)
    monkeypatch.delenv("AGENT_MEM_VAULT_REDACT_SECRETS", raising=False)
    return Vault(root)
