from datetime import UTC, datetime

from agent_vault_memory.records import Record


def format_timestamp(timestamp: str) -> str:
    """Render an ISO timestamp the way the legacy en-US formatter did, in UTC."""
    try:
        moment = datetime.fromisoformat(timestamp).astimezone(UTC)
    except ValueError:
        return timestamp
    hour = moment.hour % 12 or 12
    meridiem = "AM" if moment.hour < 12 else "PM"
    return f"{moment.month}/{moment.day}/{moment.year}, {hour}:{moment.minute:02d}:{moment.second:02d} {meridiem}"


def format_record(record: Record, index: int) -> str:
    destination = f" -> {record.to}" if record.to else ""
    pending = " [PENDING]" if record.pending else ""
    return (
        f"{index + 1}. [{record.type}/{record.kind}{destination}{pending}] ({record.namespace}) "
        f"{record.title} - {record.agent} - {format_timestamp(record.created)}"
    )


def format_records(records: list[Record]) -> str:
    return "\n".join(format_record(record, index) for index, record in enumerate(records))
