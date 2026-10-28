import json
import subprocess
import sys
import time
from pathlib import Path

from agent_mem_vault.records import parse_record
from agent_mem_vault.store import Store
from agent_mem_vault.vault import STATE_DIR, Vault

WORKER = Path(__file__).with_name("worker.py")


def run_workers(mode: str, vault_root: Path, args: list[str]) -> list[list[str]]:
    start_at = time.time() + 1.5
    children = [
        subprocess.Popen(
            [sys.executable, str(WORKER), mode, str(vault_root), str(start_at), arg],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for arg in args
    ]
    results = []
    for child in children:
        stdout, stderr = child.communicate(timeout=120)
        assert child.returncode == 0, stderr
        results.append(json.loads(stdout))
    return results


def record_files(vault_root: Path) -> list[Path]:
    hubs = {f"{path.name}.md" for path in vault_root.iterdir()}
    return [path for path in vault_root.rglob("*.md") if STATE_DIR not in path.parts and path.name not in hubs]


def test_two_processes_saving_100_records_each_leave_200_parseable_findable_files(tmp_path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    saved = run_workers("save", vault_root, ["a", "b"])

    files = record_files(vault_root)
    assert len(files) == 200
    for path in files:
        relpath = path.relative_to(vault_root).as_posix()
        record = parse_record(relpath, path.read_text(encoding="utf-8"))
        assert record.kind == "note"
    store = Store(Vault(vault_root))
    assert Vault(vault_root).scan().issues == []
    for worker, ids in zip(["a", "b"], saved, strict=True):
        assert len(ids) == 100
        for index, record_id in enumerate(ids):
            found = store.search_memory(namespace="stress", query=f"uniq{worker}x{index:03d}")
            assert [record.id for record in found] == [record_id]
    assert Vault(vault_root).tmp_leftovers() == []


def test_two_processes_reading_50_pending_handoffs_mark_each_exactly_once(tmp_path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    store = Store(Vault(vault_root))
    created = {
        store.create_handoff(
            to="agent-b", summary=f"Step {index}", context=f"Continue step {index}.", namespace="stress"
        ).id
        for index in range(50)
    }

    first, second = run_workers("read", vault_root, ["a", "b"])

    assert len(first) + len(second) == 50
    assert set(first) | set(second) == created
    assert set(first) & set(second) == set()
    handoffs = store.list_handoffs(namespace="stress", limit=100)
    assert len(handoffs) == 50
    for record in handoffs:
        assert record.meta["read"] is True
        assert record.revision == 2
        assert record.meta["read_at"].endswith("Z")
