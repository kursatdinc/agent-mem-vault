import pytest

from agent_vault_memory.records import (
    RELATED_END,
    RELATED_START,
    RecordError,
    build_body,
    namespace_slug,
    parse_record,
    record_relpath,
    render_record,
    replace_related,
    slugify,
    split_body,
    wikilink,
)


def test_namespace_slug_replaces_runs_of_other_characters():
    assert namespace_slug("project/ai-agents") == "project-ai-agents"
    assert namespace_slug("  Weird__Name!! 2 ") == "weird-name-2"
    assert namespace_slug("///") == "unnamed"


def test_title_slug_is_cut_to_48_characters_without_a_trailing_dash():
    title = "Use ADK 2.11 for the agent runtime across every single service we ship"
    relpath = record_relpath("proj", "decision", "2026-10-28T09:13:05Z", title, "3f9a2c1e-0000")
    assert relpath == "proj/decision/2026-10-28-use-adk-2-11-for-the-agent-runtime-across-every-3f9a2c1e.md"
    assert slugify("a" * 47 + " b", 48) == "a" * 47
    assert (
        record_relpath("proj", "note", "2026-10-28T09:13:05Z", "???", "abcdef12-0")
        == "proj/note/2026-10-28-untitled-abcdef12.md"
    )


def test_wikilink_uses_vault_relative_path_without_extension_and_cleans_the_display_title():
    assert wikilink("proj/note/a.md") == "[[proj/note/a]]"
    assert wikilink("proj/note/a.md", "Fix [[x]] | y\nnow") == "[[proj/note/a|Fix x y now]]"


def test_render_then_parse_round_trips_timestamps_as_strings_and_keeps_unknown_keys():
    meta = {
        "id": "abc",
        "kind": "note",
        "namespace": "proj",
        "title": "yes",
        "created": "2026-10-28T09:13:05Z",
        "revision": 1,
        "read": False,
        "aliases": ["Alt name"],
        "tags": ["a", "b"],
    }

    text = render_record(meta, "Body.\n")
    record = parse_record("proj/note/x.md", text)

    assert record.meta == meta
    assert record.created == "2026-10-28T09:13:05Z"
    assert text.startswith("---\nid: abc\nkind: note\nnamespace: proj\ntitle: 'yes'\ncreated: 2026-10-28T09:13:05Z\n")
    assert list(record.meta) == ["id", "kind", "namespace", "title", "created", "revision", "tags", "read", "aliases"]


def test_split_and_replace_related_touch_only_the_text_between_markers():
    body = build_body("Content.", ["- Supersedes [[a]]"])
    assert body == f"Content.\n\n{RELATED_START}\n## Related\n- Supersedes [[a]]\n{RELATED_END}\n"
    assert split_body(body) == ("Content.", ["- Supersedes [[a]]"])

    edited = "Human intro.\n" + body + "Human outro.\n"
    replaced = replace_related(edited, ["- Superseded by [[b]]"])
    block = f"{RELATED_START}\n## Related\n- Superseded by [[b]]\n{RELATED_END}"
    assert replaced == f"Human intro.\nContent.\n\n{block}\nHuman outro.\n"

    assert (
        replace_related("Plain body.\n", ["- x"]) == f"Plain body.\n\n{RELATED_START}\n## Related\n- x\n{RELATED_END}\n"
    )
    assert split_body("No block here.\n") == ("No block here.", [])


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("no frontmatter", "missing frontmatter"),
        ("---\n- a\n- b\n---\n", "frontmatter is not a mapping"),
        ("---\nkind: note\nnamespace: p\n---\n", "missing or invalid id"),
        ("---\nid: 1\nkind: note\nnamespace: p\n---\n", "missing or invalid id"),
        ("---\nid: a\nkind: bogus\nnamespace: p\n---\n", "unknown kind: bogus"),
        ("---\nid: a\nkind: note\n---\n", "missing or invalid namespace"),
    ],
)
def test_parse_record_rejects_unusable_candidates(text, reason):
    with pytest.raises(RecordError, match=reason):
        parse_record("p/note/x.md", text)


def test_record_accessors_tolerate_hand_edited_frontmatter():
    record = parse_record(
        "p/handoff/x.md",
        "---\nid: a\nkind: handoff\nnamespace: p\ntags: solo\nrevision: nope\nto: codex\n---\nBody\n",
    )
    assert record.tags == ["solo"]
    assert record.revision == 1
    assert record.pending is True
    assert record.type == "handoff"
    assert record.title == "x"
