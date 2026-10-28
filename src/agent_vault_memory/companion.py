from dataclasses import dataclass

from agent_vault_memory.records import namespace_slug, read_note, render_record
from agent_vault_memory.vault import Vault

COMPANION_DIR = "_companion"
CARD_FILES = {"last_session": "last-session.md", "threads": "threads.md"}
OWNER_MARKER = ("kind", "companion")


@dataclass(frozen=True)
class Companion:
    last_session: str | None
    threads: str | None


def card_relpath(namespace: str, card: str) -> str:
    return f"{namespace_slug(namespace)}/{COMPANION_DIR}/{CARD_FILES[card]}"


def render_card(namespace: str, text: str, updated: str) -> str:
    meta = {"kind": "companion", "namespace": namespace, "updated": updated, "agent-written": True}
    return render_record(meta, text + "\n")


def read_card(vault: Vault, namespace: str, card: str) -> str | None:
    path = vault.root / card_relpath(namespace, card)
    if not path.is_file():
        return None
    return read_note(path.read_text(encoding="utf-8"))[1].strip() or None


def format_companion(companion: Companion) -> str:
    sections = [
        f"## {heading}\n{text}"
        for heading, text in (("Last session", companion.last_session), ("Threads", companion.threads))
        if text
    ]
    return "\n\n".join(sections) if sections else "No companion cards yet."
