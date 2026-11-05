import re
from dataclasses import dataclass

from agent_mem_vault.records import namespace_slug, read_note, render_record
from agent_mem_vault.vault import Vault

COMPANION_DIR = "_companion"
CARD_FILES = {"last_session": "last-session.md", "threads": "threads.md"}
OWNER_MARKER = ("kind", "companion")
THREAD_FORMAT = "- <branch or topic>: <status>; next: <step>"
_THREAD_LINE = re.compile(r"- \S.*?: \S.*?; next: \S.*")


@dataclass(frozen=True)
class Companion:
    last_session: str | None
    threads: str | None


def card_relpath(namespace: str, card: str) -> str:
    return f"{namespace_slug(namespace)}/{COMPANION_DIR}/{CARD_FILES[card]}"


def existing_cards(vault: Vault, namespace: str) -> list[str]:
    """Paths of the namespace's card files that exist, in CARD_FILES order."""
    return [path for card in CARD_FILES if (vault.root / (path := card_relpath(namespace, card))).is_file()]


def render_card(namespace: str, text: str, updated: str) -> str:
    meta = {"kind": "companion", "namespace": namespace, "updated": updated, "agent-written": True}
    return render_record(meta, text + "\n")


def read_card(vault: Vault, namespace: str, card: str) -> str | None:
    path = vault.root / card_relpath(namespace, card)
    if not path.is_file():
        return None
    return read_note(path.read_text(encoding="utf-8"))[1].strip() or None


def check_threads(text: str) -> None:
    """Every non-blank line of the threads card describes one open thread in THREAD_FORMAT."""
    for line in text.splitlines():
        if line.strip() and not _THREAD_LINE.fullmatch(line.strip()):
            raise ValueError(f'threads: one line per open thread, "{THREAD_FORMAT}"; this line does not fit: {line}')


def card_sections(companion: Companion) -> list[str]:
    cards = (("Last session", companion.last_session), ("Threads", companion.threads))
    return [f"## {heading}\n{text}" for heading, text in cards if text]


def format_companion(companion: Companion) -> str:
    return "\n\n".join(card_sections(companion)) or "No companion cards yet."
