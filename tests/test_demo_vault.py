import filecmp
import subprocess
import sys
from pathlib import Path

from agent_mem_vault.companion import check_threads
from agent_mem_vault.links import link_report
from agent_mem_vault.store import Store
from agent_mem_vault.vault import Vault

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo-vault"


def _scan():
    return Vault(DEMO).scan()


def test_committed_demo_vault_parses_without_issues():
    scan = _scan()

    assert scan.issues == []
    counts = {kind: sum(record.kind == kind for record in scan.records) for kind in {r.kind for r in scan.records}}
    assert counts == {"decision": 5, "note": 1, "risk": 2, "snapshot": 2}
    assert not list(DEMO.glob("*/handoff"))


def test_demo_vault_shows_supersedes_chain_lifecycle_statuses_and_a_rejected_idea():
    records = {record.title: record for record in _scan().records}

    assert records["Use SQLite for the first release"].meta["superseded_by"].endswith("-234bc139]]")
    assert records["Move order storage to PostgreSQL"].meta["superseded_by"].endswith("-eb0b3836]]")
    assert "superseded_by" not in records["Pin PostgreSQL 16 in CI and production"].meta
    assert {title: record.meta["status"] for title, record in records.items() if record.kind == "decision"} == {
        "Use SQLite for the first release": "superseded",
        "Cache order lookups in process memory": "accepted",
        "Move order storage to PostgreSQL": "superseded",
        "Pin PostgreSQL 16 in CI and production": "accepted",
        "Sync offline first, reconcile on reconnect": "accepted",
    }
    assert records["Migration script locks the orders table"].meta["review_by"] == "2026-03-20"
    assert records["Cache order lookups in process memory"].meta["validity"] == "rejected"


def test_demo_vault_keeps_open_work_in_the_companion_cards():
    store = Store(Vault(DEMO), companion_max_chars=3000)
    harbor = store.get_companion("project/harbor-api")
    lantern = store.get_companion("project/lantern-mobile")

    assert harbor.last_session.startswith("Pinned PostgreSQL 16")
    assert [line.split(":")[0] for line in harbor.threads.splitlines()] == ["- feat/batch-backfill", "- retry-policy"]
    assert lantern.threads.startswith("- fix/push-token-refresh: ")
    check_threads(harbor.threads)
    check_threads(lantern.threads)


def test_demo_vault_has_no_unresolved_links():
    vault = Vault(DEMO)

    for record in vault.scan().records:
        assert link_report(vault, record).unresolved == []


def test_demo_vault_opens_as_obsidian_vault_and_keeps_no_server_state():
    assert sorted(path.name for path in (DEMO / ".obsidian").iterdir()) == ["app.json"]
    assert not (DEMO / ".agent-mem-vault").exists()


def test_build_script_reproduces_the_committed_demo_vault(tmp_path):
    rebuilt = tmp_path / "demo-vault"

    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_demo_vault.py"), str(rebuilt)], check=True)

    comparison = filecmp.dircmp(DEMO, rebuilt)
    assert _differences(comparison) == []


def _differences(comparison: filecmp.dircmp) -> list[str]:
    found = [*comparison.left_only, *comparison.right_only, *comparison.diff_files]
    for child in comparison.subdirs.values():
        found += _differences(child)
    return found
