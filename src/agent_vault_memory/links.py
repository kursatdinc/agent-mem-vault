import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_vault_memory.records import Record, read_note
from agent_vault_memory.vault import Vault

_WIKILINK = re.compile(r"!?\[\[([^\[\]\n]+?)\]\]")
_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)
_MARKDOWN = ".md"


@dataclass(frozen=True)
class Links:
    outgoing: list[str]
    unresolved: list[str]
    backlinks: list[str]


def link_target(raw: str) -> str:
    """The note a wikilink points at: display text and heading are dropped."""
    return raw.split("|", 1)[0].split("#", 1)[0].strip()


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    return []


def targets_in(meta: dict[str, Any], body: str) -> list[str]:
    """Wikilink targets from frontmatter values and from the body outside code, first occurrence first."""
    texts = [*_strings(meta), _CODE.sub("", body)]
    found = (link_target(match) for text in texts for match in _WIKILINK.findall(text))
    return list(dict.fromkeys(target for target in found if target))


def _key(path: str) -> str:
    return path.removesuffix(_MARKDOWN)


def normalized_target(raw: str) -> str:
    """Comparable form of a link as Obsidian reports it: no heading, display text, extension or case."""
    return _key(link_target(raw)).casefold()


class Resolver:
    """Obsidian link resolution: exact path, then name or path suffix with the shortest path winning, then alias."""

    def __init__(self, files: list[str], aliases: dict[str, list[str]]) -> None:
        self._exact = {_key(path): path for path in files}
        self._by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for path in files:
            key = _key(path).casefold()
            self._by_name[key.rsplit("/", 1)[-1]].append((key, path))
        self._aliases = aliases

    def resolve(self, target: str) -> str | None:
        wanted = _key(target)
        if wanted in self._exact:
            return self._exact[wanted]
        folded = wanted.casefold()
        name = folded.rsplit("/", 1)[-1]
        matches = [path for key, path in self._by_name.get(name, []) if key == folded or key.endswith(f"/{folded}")]
        matches = matches or self._aliases.get(folded, [])
        return min(matches, key=lambda path: (len(path), path)) if matches else None


@dataclass
class _Graph:
    notes: dict[str, tuple[dict[str, Any], str]]
    resolver: Resolver

    def outgoing(self, path: str) -> list[str]:
        meta, body = self.notes[path]
        return targets_in(meta, body)


def _files(root: Path) -> list[str]:
    found: list[str] = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for name in sorted(filenames):
            path = Path(directory) / name
            if not name.startswith(".") and not path.is_symlink():
                found.append(path.relative_to(root).as_posix())
    return found


def _alias_names(meta: dict[str, Any]) -> list[str]:
    names = (alias.strip().casefold() for key in ("aliases", "alias") for alias in _strings(meta.get(key)))
    return [name for name in names if name]


def _load_graph(vault: Vault) -> _Graph:
    files = _files(vault.root)
    notes: dict[str, tuple[dict[str, Any], str]] = {}
    aliases: dict[str, list[str]] = defaultdict(list)
    for path in files:
        if not path.endswith(_MARKDOWN):
            continue
        try:
            text = (vault.root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta, body = read_note(text)
        notes[path] = (meta, body)
        for alias in _alias_names(meta):
            aliases[alias].append(path)
    return _Graph(notes, Resolver(files, dict(aliases)))


def link_report(vault: Vault, record: Record) -> Links:
    graph = _load_graph(vault)
    graph.notes.setdefault(record.path, (record.meta, record.body))
    outgoing: list[str] = []
    unresolved: list[str] = []
    for target in graph.outgoing(record.path):
        destination = graph.resolver.resolve(target)
        if destination is None:
            unresolved.append(target)
        elif destination != record.path and destination not in outgoing:
            outgoing.append(destination)
    backlinks = sorted(
        path
        for path in graph.notes
        if path != record.path and any(graph.resolver.resolve(target) == record.path for target in graph.outgoing(path))
    )
    return Links(outgoing, unresolved, backlinks)


def unresolved_targets(vault: Vault, records: list[Record]) -> dict[str, set[str]]:
    """Unresolved link targets of each record file, keyed by vault-relative path."""
    graph = _load_graph(vault)
    return {
        record.path: {
            _key(target).casefold() for target in graph.outgoing(record.path) if graph.resolver.resolve(target) is None
        }
        for record in records
        if record.path in graph.notes
    }
