from agent_vault_memory.format import format_record, format_records, format_timestamp


def test_format_timestamp_renders_en_us_style_in_utc():
    assert format_timestamp("2026-10-28T09:13:05Z") == "10/28/2026, 9:13:05 AM"
    assert format_timestamp("2026-01-02T00:05:00Z") == "1/2/2026, 12:05:00 AM"
    assert format_timestamp("2026-01-02T15:05:09Z") == "1/2/2026, 3:05:09 PM"
    assert format_timestamp("not a date") == "not a date"


def test_format_record_matches_the_legacy_list_line_shape(store):
    note = store.save_memory(agent="planner", kind="decision", title="Pick storage", content="c", namespace="alpha")
    handoff = store.create_handoff(to="codex", summary="s", context="c", namespace="alpha")

    assert format_record(note, 0) == "1. [context/decision] (alpha) Pick storage - planner - 10/28/2026, 9:00:01 AM"
    assert (
        format_record(handoff, 1)
        == "2. [handoff/handoff -> codex [PENDING]] (alpha) Handoff to codex - handoff - 10/28/2026, 9:00:02 AM"
    )
    store.ack_handoff(id=handoff.id, namespace="alpha")
    acked = store.list_handoffs(namespace="alpha")[0]
    assert (
        format_record(acked, 0)
        == "1. [handoff/handoff -> codex] (alpha) Handoff to codex - handoff - 10/28/2026, 9:00:02 AM"
    )
    assert format_records([note, handoff]).count("\n") == 1
