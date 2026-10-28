"""Child process used by the concurrency tests: python worker.py <mode> <vault> <start_at> <arg>."""

import json
import sys
import time
from pathlib import Path

from agent_mem_vault.store import Store
from agent_mem_vault.vault import Vault


def main() -> None:
    mode, vault_path, start_at, arg = sys.argv[1], Path(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
    store = Store(Vault(vault_path))
    time.sleep(max(0.0, start_at - time.time()))
    if mode == "save":
        ids = [
            store.save_memory(
                agent=f"worker-{arg}",
                kind="note",
                title=f"Concurrent note {arg} {index}",
                content=f"payload uniq{arg}x{index:03d}",
                namespace="stress",
            ).id
            for index in range(100)
        ]
    else:
        ids = []
        while (record := store.read_handoff(agent="agent-b", namespace="stress")) is not None:
            ids.append(record.id)
    print(json.dumps(ids))


main()
