import fcntl
import hashlib
import os
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from agent_vault_memory.records import KINDS, Record, RecordError, parse_record, read_note

STATE_DIR = ".agent-vault-memory"
LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_POLL_SECONDS = 0.005


class VaultError(Exception):
    """Base class for vault level failures reported to the caller."""


class LockTimeoutError(VaultError):
    pass


class ConflictError(VaultError):
    pass


class RevisionConflict(VaultError):
    def __init__(self, expected: int, current: int) -> None:
        super().__init__(f"expected revision {expected} but the current revision is {current}")
        self.expected = expected
        self.current = current


@dataclass(frozen=True)
class Issue:
    path: str
    reason: str


@dataclass
class ScanResult:
    records: list[Record] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def log(message: str) -> None:
    print(f"agent-vault-memory: {message}", file=sys.stderr)


class Vault:
    def __init__(self, root: Path, lock_timeout: float = LOCK_TIMEOUT_SECONDS) -> None:
        if not root.is_dir():
            raise VaultError(f"vault path is not a directory: {root}")
        self.root = root.resolve()
        self.lock_timeout = lock_timeout
        self.state_dir = self.root / STATE_DIR
        self.tmp_dir = self.state_dir / "tmp"
        self.lock_path = self.state_dir / "lock"

    def ensure_state(self) -> None:
        created = not self.state_dir.exists()
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        if created and self._inside_git_repository():
            self._ignore_state_dir()

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Exclusive cross-process lock held on a dedicated descriptor for the whole operation."""
        self.ensure_state()
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            deadline = time.monotonic() + self.lock_timeout
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise LockTimeoutError(
                            f"could not lock the vault within {self.lock_timeout:g}s; another process is writing"
                        ) from None
                    time.sleep(_LOCK_POLL_SECONDS)
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def tmp_leftovers(self) -> list[Path]:
        if not self.tmp_dir.is_dir():
            return []
        return sorted(path for path in self.tmp_dir.iterdir() if path.is_file())

    def clean_tmp_leftovers(self) -> list[Path]:
        """Remove incomplete writes. Runs under the lock so it never races a live writer."""
        if not self.tmp_leftovers():
            return []
        with self.lock():
            leftovers = self.tmp_leftovers()
            for path in leftovers:
                path.unlink(missing_ok=True)
                log(f"removed incomplete write {path.name}")
            return leftovers

    def write_new(self, relpath: str, text: str) -> None:
        """Atomically create a file. The caller holds the lock."""
        target = self.root / relpath
        if target.exists():
            raise VaultError(f"refusing to overwrite existing file: {relpath}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self._write_tmp(text), target)

    def write_generated(self, relpath: str, text: str) -> bool:
        """Atomically (re)write a generated file; unchanged text is skipped and a note a human wrote is never replaced.

        The caller holds the lock. Returns whether the file changed.
        """
        target = self.root / relpath
        if target.exists():
            self._check_inside_vault(target)
            existing = target.read_text(encoding="utf-8")
            if existing == text:
                return False
            if read_note(existing)[0].get("generated") is not True:
                raise VaultError(f"refusing to overwrite a file that is not generated: {relpath}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self._write_tmp(text), target)
        return True

    def update_file(self, relpath: str, build_text: Callable[[Record], str]) -> Record:
        """Re-read, rebuild and atomically replace a record. The caller holds the lock.

        A human editing the file between our read and our replace is detected by hash;
        the update retries once and then reports a conflict instead of overwriting.
        """
        target = self.root / relpath
        for _ in range(2):
            raw = target.read_bytes()
            record = parse_record(relpath, raw.decode("utf-8"), target.stat().st_mtime_ns)
            tmp = self._write_tmp(build_text(record))
            if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(raw).digest():
                tmp.unlink(missing_ok=True)
                continue
            os.replace(tmp, target)
            return parse_record(relpath, target.read_text(encoding="utf-8"), target.stat().st_mtime_ns)
        raise ConflictError(f"{relpath} was changed while updating it; try again")

    def scan(self) -> ScanResult:
        result = ScanResult()
        first_path_by_id: dict[str, str] = {}
        for relpath, path in self._candidates():
            try:
                self._check_inside_vault(path)
                text = path.read_text(encoding="utf-8")
                record = parse_record(relpath, text, path.stat().st_mtime_ns)
            except (OSError, UnicodeDecodeError, RecordError, VaultError) as error:
                result.issues.append(Issue(relpath, _reason(error)))
                continue
            folder_kind = relpath.split("/")[1]
            if record.kind != folder_kind:
                result.issues.append(Issue(relpath, f"kind {record.kind} does not match folder {folder_kind}"))
                continue
            if record.id in first_path_by_id:
                result.issues.append(Issue(relpath, f"duplicate id (also at {first_path_by_id[record.id]})"))
                continue
            first_path_by_id[record.id] = relpath
            result.records.append(record)
        return result

    def _candidates(self) -> Iterator[tuple[str, Path]]:
        for namespace_dir in _subdirectories(self.root):
            for kind in KINDS:
                kind_dir = namespace_dir / kind
                if not kind_dir.is_dir() or kind_dir.is_symlink():
                    continue
                for path in sorted(kind_dir.glob("*.md")):
                    if path.name.startswith(".") or not path.is_file():
                        continue
                    yield f"{namespace_dir.name}/{kind}/{path.name}", path

    def _check_inside_vault(self, path: Path) -> None:
        if path.is_symlink() and not path.resolve().is_relative_to(self.root):
            raise VaultError("resolves outside the vault")

    def _write_tmp(self, text: str) -> Path:
        tmp = self.tmp_dir / f"{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        return tmp

    def _inside_git_repository(self) -> bool:
        return any((directory / ".git").exists() for directory in (self.root, *self.root.parents))

    def _ignore_state_dir(self) -> None:
        gitignore = self.root / ".gitignore"
        entry = f"{STATE_DIR}/"
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        if entry in existing.splitlines():
            return
        separator = "" if not existing or existing.endswith("\n") else "\n"
        gitignore.write_text(f"{existing}{separator}{entry}\n", encoding="utf-8")


def _subdirectories(root: Path) -> list[Path]:
    return sorted(
        path for path in root.iterdir() if path.is_dir() and not path.is_symlink() and not path.name.startswith(".")
    )


def _reason(error: Exception) -> str:
    if isinstance(error, UnicodeDecodeError):
        return "not valid UTF-8"
    if isinstance(error, OSError):
        return f"unreadable: {error.strerror or error.__class__.__name__}"
    return str(error)
