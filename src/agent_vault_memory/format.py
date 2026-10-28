from datetime import UTC, datetime

from agent_vault_memory.links import Links
from agent_vault_memory.records import Record
from agent_vault_memory.store import Brief
from agent_vault_memory.vault import Issue


def format_timestamp(timestamp: str) -> str:
    """Render an ISO timestamp the way the legacy en-US formatter did, in UTC."""
    try:
        moment = datetime.fromisoformat(timestamp).astimezone(UTC)
    except ValueError:
        return timestamp
    hour = moment.hour % 12 or 12
    meridiem = "AM" if moment.hour < 12 else "PM"
    return f"{moment.month}/{moment.day}/{moment.year}, {hour}:{moment.minute:02d}:{moment.second:02d} {meridiem}"


def format_record(record: Record, index: int, mark_rejected: bool = False) -> str:
    destination = f" -> {record.to}" if record.to else ""
    pending = " [PENDING]" if record.pending else ""
    rejected = " [rejected]" if mark_rejected and record.meta.get("validity") == "rejected" else ""
    return (
        f"{index + 1}. [{record.type}/{record.kind}{destination}{pending}{rejected}] ({record.namespace}) "
        f"{record.title} - {record.agent} - {format_timestamp(record.created)}"
    )


def format_records(records: list[Record], mark_rejected: bool = False) -> str:
    return "\n".join(format_record(record, index, mark_rejected) for index, record in enumerate(records))


def format_brief(brief: Brief) -> str:
    return f"**{brief.title}** - {brief.namespace} - {format_timestamp(brief.created)}\n\n{brief.content}"


def format_links(record: Record, links: Links) -> str:
    sections = [f"**{record.title}** - {record.namespace}"]
    for heading, items in (
        ("Outgoing links", links.outgoing),
        ("Unresolved links", links.unresolved),
        ("Backlinks", links.backlinks),
    ):
        sections.append(f"{heading} ({len(items)}):" + "".join(f"\n- {item}" for item in items))
    return "\n\n".join(sections)


def format_issues(issues: list[Issue]) -> str:
    noun = "issue" if len(issues) == 1 else "issues"
    return f"{len(issues)} {noun}:" + "".join(f"\n- {issue.path}: {issue.reason}" for issue in issues)
