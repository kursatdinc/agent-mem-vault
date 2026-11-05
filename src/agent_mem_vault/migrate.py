import os
from dataclasses import dataclass
from pathlib import Path

from agent_mem_vault import git
from agent_mem_vault.generated import hub_relpath
from agent_mem_vault.records import namespace_slug, read_note
from agent_mem_vault.store import Store

LEGACY_DIR = "handoff"
ARCHIVE_DIR = "_archive/handoffs"


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


def archive_legacy_handoffs(store: Store) -> list[Move]:
    """Move legacy handoffs into the archive, refresh the affected hubs and commit when the vault is a git work tree."""
    root = store.vault.root
    with store.vault.lock():
        moves = legacy_handoffs(root)
        done = [move for move in moves if not move.blocked]
        tracked = _tracked(root, [move.source for move in done])
        namespaces = {}
        for move in done:
            namespace = _archive(store, move)
            if namespace is not None:
                namespaces.setdefault(namespace_slug(namespace), namespace)
        for folder in {move.source.rsplit("/", 1)[0] for move in done}:
            if not any((root / folder).iterdir()):
                (root / folder).rmdir()
        touched = [move.target for move in done] + [move.source for move in done if move.source in tracked]
        for namespace in namespaces.values():
            if (root / hub_relpath(namespace)).is_file():
                touched += store.refresh_generated(namespace)
        if done:
            noun = "handoff" if len(done) == 1 else "handoffs"
            git.autocommit(root, touched, f"avm: migrate {len(done)} legacy {noun}")
        return moves


def _archive(store: Store, move: Move) -> str | None:
    """Move one file, pointing its links at the archive; returns the namespace named in its frontmatter."""
    root = store.vault.root
    source = root / move.source
    namespace_dir = move.source.split("/", 1)[0]
    raw = source.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        (root / move.target).parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, root / move.target)
        return None
    old_prefix, new_prefix = f"[[{namespace_dir}/{LEGACY_DIR}/", f"[[{namespace_dir}/{ARCHIVE_DIR}/"
    store.vault.write_new(move.target, text.replace(old_prefix, new_prefix))
    source.unlink()
    namespace = read_note(text)[0].get("namespace")
    return namespace if isinstance(namespace, str) and namespace_slug(namespace) == namespace_dir else None


def _tracked(root: Path, relpaths: list[str]) -> set[str]:
    if not relpaths or not git.inside_work_tree(root):
        return set()
    try:
        return set(git.run_git(root, "ls-files", "-z", "--", *relpaths).split("\0")) - {""}
    except git.GitError:
        return set()
