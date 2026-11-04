from agent_mem_vault.format import format_record, format_records, format_timestamp


def test_format_timestamp_renders_en_us_style_in_utc():
    assert format_timestamp("2026-10-28T09:13:05Z") == "10/28/2026, 9:13:05 AM"
    assert format_timestamp("2026-01-02T00:05:00Z") == "1/2/2026, 12:05:00 AM"
    assert format_timestamp("2026-01-02T15:05:09Z") == "1/2/2026, 3:05:09 PM"
    assert format_timestamp("not a date") == "not a date"


def test_format_record_matches_the_list_line_shape(store):
    decision = store.save_memory(agent="planner", kind="decision", title="Pick storage", content="c", namespace="alpha")
    note = store.save_context(agent="codex", title="Notes", content="c", namespace="alpha")

    assert format_record(decision, 0) == "1. [decision] (alpha) Pick storage - planner - 10/28/2026, 9:00:01 AM"
    assert format_record(note, 1) == "2. [note] (alpha) Notes - codex - 10/28/2026, 9:00:02 AM"
    assert format_records([decision, note]).count("\n") == 1
