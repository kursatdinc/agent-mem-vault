import os
import re
from dataclasses import dataclass
from pathlib import Path

from agent_mem_vault import git
from agent_mem_vault.store import Store, is_active

LEGACY_DIR = "handoff"
ARCHIVE_DIR = "_archive/handoffs"
CLOSED_ARCHIVE_DIR = "_archive"


@dataclass(frozen=True)
class Move:
    source: str
    target: str
    blocked: bool


def legacy_handoffs(root: Path) -> list[Move]:
    """Every file left in a 1.x `<ns-dir>/handoff/` folder, with its archive path; `blocked` when that path is taken."""
    moves = []
    for namespace_dir in sorted(root.iterdir()):
        folder = namespace_dir / LEGACY_DIR
        if (
            namespace_dir.name.startswith(".")
            or namespace_dir.is_symlink()
            or not folder.is_dir()
            or folder.is_symlink()
        ):
            continue
        for path in sorted(folder.glob("*.md")):
            if path.name.startswith(".") or path.is_symlink() or not path.is_file():
                continue
            source = f"{namespace_dir.name}/{LEGACY_DIR}/{path.name}"
            target = f"{namespace_dir.name}/{ARCHIVE_DIR}/{path.name}"
            moves.append(Move(source, target, (root / target).exists()))
    return moves


def archive_legacy_handoffs(store: Store) -> tuple[list[Move], list[str]]:
    """Move legacy handoffs into the archive, then rebuild every hub, and commit when the vault is a git work tree.

    Returns the moves and the hub files the rebuild touched.
    """
    root = store.vault.root
    with store.vault.lock():
        moves = legacy_handoffs(root)
        done = [move for move in moves if not move.blocked]
        for move in done:
            _archive(store, move)
        for folder in {move.source.rsplit("/", 1)[0] for move in done}:
            if not any((root / folder).iterdir()):
                (root / folder).rmdir()
        hubs = store.refresh_hubs()[0]
        if done:
            noun = "handoff" if len(done) == 1 else "handoffs"
            touched = [move.target for move in done] + [move.source for move in done] + hubs
            git.autocommit(root, touched, f"avm: migrate {len(done)} legacy {noun}")
        elif hubs:
            git.autocommit(root, hubs, "avm: rebuild hubs")
        return moves, hubs


def closed_records(store: Store) -> list[Move]:
    """Every closed record (superseded, resolved or replaced by another one), with its path under
    `<ns-dir>/_archive/<kind>/`; `blocked` when that path is taken."""
    root = store.vault.root
    moves = []
    for record in sorted(store.vault.scan().records, key=lambda record: record.path):
        if is_active(record):
            continue
        namespace_dir, kind, name = record.path.split("/", 2)
        target = f"{namespace_dir}/{CLOSED_ARCHIVE_DIR}/{kind}/{name}"
        moves.append(Move(record.path, target, (root / target).exists()))
    return moves


def archive_closed_records(store: Store) -> tuple[list[Move], list[str], list[str]]:
    """Move closed records into their namespace archive, point every link in the vault at the new paths, rebuild every
    hub, and commit when the vault is a git work tree. The server reads records only from kind folders, so an archived
    record leaves the brief, search and get_memory; git history and the archive folder keep it.

    Returns the moves, the notes whose links were rewritten and the hub files the rebuild touched.
    """
    root = store.vault.root
    with store.vault.lock():
        moves = closed_records(store)
        done = [move for move in moves if not move.blocked]
        sources = {move.source for move in done}
        relinked = [path for path in _relink(store, done) if path not in sources]
        for move in done:
            (root / move.target).parent.mkdir(parents=True, exist_ok=True)
            os.replace(root / move.source, root / move.target)
        hubs = store.refresh_hubs()[0]
        if done:
            noun = "record" if len(done) == 1 else "records"
            touched = [move.target for move in done] + sorted(sources) + relinked + hubs
            git.autocommit(root, touched, f"avm: archive {len(done)} closed {noun}")
        elif hubs:
            git.autocommit(root, hubs, "avm: rebuild hubs")
        return moves, relinked, hubs


def _relink(store: Store, moves: list[Move]) -> list[str]:
    """Rewrite the wikilinks that point at a moved record in every note of the vault; returns the paths it changed."""
    if not moves:
        return []
    renames = {move.source.removesuffix(".md"): move.target.removesuffix(".md") for move in moves}
    pattern = re.compile(r"\[\[(" + "|".join(map(re.escape, renames)) + r")(?=[\]|#])")
    root = store.vault.root
    changed = []
    for path in sorted(root.rglob("*.md")):
        relpath = path.relative_to(root)
        if path.is_symlink() or any(part.startswith(".") for part in relpath.parts):
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        relinked = pattern.sub(lambda match: f"[[{renames[match.group(1)]}", text)
        if relinked != text:
            store.vault.rewrite(relpath.as_posix(), relinked)
            changed.append(relpath.as_posix())
    return changed


def _archive(store: Store, move: Move) -> None:
    """Move one file, pointing its links at the archive."""
    root = store.vault.root
    source = root / move.source
    namespace_dir = move.source.split("/", 1)[0]
    raw = source.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        (root / move.target).parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, root / move.target)
        return
    old_prefix, new_prefix = f"[[{namespace_dir}/{LEGACY_DIR}/", f"[[{namespace_dir}/{ARCHIVE_DIR}/"
    store.vault.write_new(move.target, text.replace(old_prefix, new_prefix))
    source.unlink()
