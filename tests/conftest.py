from datetime import UTC, datetime, timedelta

import pytest

from agent_vault_memory.records import KINDS, RECEIPT_KIND
from agent_vault_memory.store import Store
from agent_vault_memory.vault import Vault


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
