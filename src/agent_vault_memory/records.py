import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import yaml

KINDS = ("note", "decision", "assumption", "task", "risk", "handoff", "snapshot")

RELATED_START = "<!-- avm:related:start -->"
RELATED_END = "<!-- avm:related:end -->"

NAMESPACE_SLUG_FALLBACK = "unnamed"
TITLE_SLUG_FALLBACK = "untitled"
TITLE_SLUG_MAX = 48

_KEY_ORDER = (
    "id",
    "kind",
    "namespace",
    "agent",
    "title",
    "created",
    "updated",
    "revision",
    "visibility",
    "validity",
    "tags",
    "status",
    "related_files",
    "supersedes",
    "superseded_by",
    "next_action",
    "branch",
    "commit",
    "to",
    "read",
    "read_at",
    "rejected_reason",
    "agent-written",
)

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_RELATED_BLOCK = re.compile(re.escape(RELATED_START) + r"\n?(.*?)\n?" + re.escape(RELATED_END), re.DOTALL)
_TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"


def _without_timestamp_resolver(resolvers: dict[str, list]) -> dict[str, list]:
    return {key: [item for item in items if item[0] != _TIMESTAMP_TAG] for key, items in resolvers.items()}


class _Loader(yaml.CSafeLoader):
    """Keeps ISO timestamps as plain strings so a record round-trips byte for byte."""


class _Dumper(yaml.SafeDumper):
    """Writes ISO timestamps unquoted, the way Obsidian expects date properties."""


_Loader.yaml_implicit_resolvers = _without_timestamp_resolver(yaml.CSafeLoader.yaml_implicit_resolvers)
_Dumper.yaml_implicit_resolvers = _without_timestamp_resolver(yaml.SafeDumper.yaml_implicit_resolvers)


class RecordError(ValueError):
    """A file that looks like a record candidate but cannot be used as one."""


@dataclass
class Record:
    path: str
    meta: dict[str, Any]
    body: str
    mtime_ns: int = 0
    _split: tuple[str, list[str]] | None = field(default=None, repr=False, compare=False)

    @property
    def id(self) -> str:
        return self.meta["id"]

    @property
    def kind(self) -> str:
        return self.meta["kind"]

    @property
    def namespace(self) -> str:
        return self.meta["namespace"]

    @property
    def agent(self) -> str:
        return str(self.meta.get("agent") or "")

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.path.rsplit("/", 1)[-1].removesuffix(".md"))

    @property
    def created(self) -> str:
        return str(self.meta.get("created") or "")

    @property
    def revision(self) -> int:
        revision = self.meta.get("revision")
        return revision if isinstance(revision, int) and not isinstance(revision, bool) else 1

    @property
    def tags(self) -> list[str]:
        tags = self.meta.get("tags")
        if isinstance(tags, str):
            return [tags]
        if isinstance(tags, list):
            return [str(tag) for tag in tags]
        return []

    @property
    def to(self) -> str | None:
        target = self.meta.get("to")
        return str(target) if target else None

    @property
    def pending(self) -> bool:
        return self.kind == "handoff" and self.meta.get("read") is not True

    @property
    def type(self) -> str:
        return "handoff" if self.kind == "handoff" else "context"

    @property
    def content(self) -> str:
        return self._parts()[0]

    @property
    def related_lines(self) -> list[str]:
        return self._parts()[1]

    @property
    def sort_key(self) -> tuple[str, int]:
        return (self.created, self.mtime_ns)

    def _parts(self) -> tuple[str, list[str]]:
        if self._split is None:
            self._split = split_body(self.body)
        return self._split


def utc_timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str, max_length: int | None = None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if max_length is not None:
        slug = slug[:max_length].strip("-")
    return slug


def namespace_slug(namespace: str) -> str:
    return slugify(namespace) or NAMESPACE_SLUG_FALLBACK


def record_relpath(namespace: str, kind: str, created: str, title: str, record_id: str) -> str:
    title_slug = slugify(title, TITLE_SLUG_MAX) or TITLE_SLUG_FALLBACK
    filename = f"{created[:10]}-{title_slug}-{record_id[:8]}.md"
    return f"{namespace_slug(namespace)}/{kind}/{filename}"


def link_for(path: str) -> str:
    return path.removesuffix(".md")


def wikilink(path: str, title: str | None = None) -> str:
    if title is None:
        return f"[[{link_for(path)}]]"
    display = re.sub(r"\s+", " ", re.sub(r"[\[\]|]", " ", title)).strip()
    return f"[[{link_for(path)}|{display}]]"


def split_body(body: str) -> tuple[str, list[str]]:
    match = _RELATED_BLOCK.search(body)
    if match is None:
        return body.strip(), []
    content = (body[: match.start()] + body[match.end() :]).strip()
    lines = [line for line in match.group(1).splitlines() if line.strip() and line.strip() != "## Related"]
    return content, lines


def _related_block(lines: list[str]) -> str:
    return "\n".join([RELATED_START, "## Related", *lines, RELATED_END])


def build_body(content: str, related_lines: list[str]) -> str:
    body = content.strip() + "\n"
    if related_lines:
        body += "\n" + _related_block(related_lines) + "\n"
    return body


def replace_related(body: str, related_lines: list[str]) -> str:
    """Rewrite only the text between the avm:related markers, appending the block when absent."""
    match = _RELATED_BLOCK.search(body)
    if match is None:
        return body.rstrip("\n") + "\n\n" + _related_block(related_lines) + "\n"
    return body[: match.start()] + _related_block(related_lines) + body[match.end() :]


def _ordered(meta: dict[str, Any]) -> dict[str, Any]:
    known = {key: meta[key] for key in _KEY_ORDER if key in meta}
    extra = {key: value for key, value in meta.items() if key not in known}
    return {**known, **extra}


def render_record(meta: dict[str, Any], body: str) -> str:
    frontmatter = yaml.dump(
        _ordered(meta),
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=None,
        width=1_000_000,
    )
    return f"---\n{frontmatter}---\n{body}"


def parse_record(path: str, text: str, mtime_ns: int = 0) -> Record:
    match = _FRONTMATTER.match(text.removeprefix("﻿"))
    if match is None:
        raise RecordError("missing frontmatter")
    try:
        meta = yaml.load(match.group(1), Loader=_Loader)
    except yaml.YAMLError as error:
        raise RecordError(f"unparseable frontmatter: {error.__class__.__name__}") from error
    if not isinstance(meta, dict):
        raise RecordError("frontmatter is not a mapping")
    for key in ("id", "kind", "namespace"):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            raise RecordError(f"missing or invalid {key}")
    if meta["kind"] not in KINDS:
        raise RecordError(f"unknown kind: {meta['kind']}")
    body = text.removeprefix("﻿")[match.end() :]
    return Record(path=path, meta=meta, body=body, mtime_ns=mtime_ns)
