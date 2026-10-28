from agent_vault_memory.links import Resolver, link_target, targets_in


def write_note(vault, relpath, text):
    path = vault.root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def stem(record):
    return record.path.removesuffix(".md")


def test_link_target_drops_display_text_and_heading():
    assert link_target("folder/Note#Heading|shown") == "folder/Note"
    assert link_target("Note#^block") == "Note"
    assert link_target("#Heading") == ""
    assert link_target("  Note  ") == "Note"


def test_targets_come_from_frontmatter_and_body_but_not_from_code():
    meta = {"supersedes": ["[[a/b|B]]"], "related_files": ["src/x.py"], "nested": {"link": "[[c]]"}}
    body = "See [[d#h]] and ![[e.png]].\n```\n[[fenced]]\n```\nInline `[[inline]]` stays out. [[d]] again.\n"

    assert targets_in(meta, body) == ["a/b", "c", "d", "e.png"]


def test_resolution_prefers_the_exact_path_then_the_shortest_path_then_aliases():
    files = [
        "Roadmap.md",
        "archive/Roadmap.md",
        "archive/2024/Roadmap.md",
        "areas/work/Deep.md",
        "assets/diagram.png",
        "People/Dana Ruiz.md",
    ]
    resolver = Resolver(files, {"dana": ["People/Dana Ruiz.md"]})

    assert resolver.resolve("archive/Roadmap") == "archive/Roadmap.md"
    assert resolver.resolve("Roadmap") == "Roadmap.md"
    assert resolver.resolve("Roadmap.md") == "Roadmap.md"
    assert resolver.resolve("roadmap") == "Roadmap.md"
    assert resolver.resolve("2024/Roadmap") == "archive/2024/Roadmap.md"
    assert resolver.resolve("work/Deep") == "areas/work/Deep.md"
    assert resolver.resolve("diagram.png") == "assets/diagram.png"
    assert resolver.resolve("Dana") == "People/Dana Ruiz.md"
    assert resolver.resolve("Nobody") is None


def test_get_links_reports_outgoing_unresolved_and_backlinks(store, vault):
    write_note(vault, "Roadmap.md", "# Roadmap\n")
    write_note(vault, "archive/Roadmap.md", "# Old roadmap\n")
    write_note(vault, "areas/work/Deep.md", "# Deep\n")
    write_note(vault, "assets/diagram.png", "png")
    write_note(vault, "People/Dana Ruiz.md", "---\naliases: [Dana]\n---\n# Dana\n")
    target = store.save_context(
        agent="agent-a",
        title="Target",
        content=(
            "See [[Roadmap]], [[Roadmap#Q1|the plan]], [[archive/Roadmap]], ![[diagram.png]], "
            "[[work/Deep]], [[Dana]] and [[Missing note]]. `[[Ignored]]`"
        ),
        namespace="proj",
    )
    write_note(vault, "Journal.md", f"Wrote about [[{stem(target)}|my note]].\n")
    write_note(
        vault, "Ideas.md", f"---\nrelated: '[[{target.path.rsplit('/', 1)[1].removesuffix('.md')}#Heading]]'\n---\n"
    )
    write_note(vault, "Unrelated.md", "[[Roadmap]]\n")

    record, links = store.get_links(target.id)

    assert record.id == target.id
    assert links.outgoing == [
        "Roadmap.md",
        "archive/Roadmap.md",
        "assets/diagram.png",
        "areas/work/Deep.md",
        "People/Dana Ruiz.md",
    ]
    assert links.unresolved == ["Missing note"]
    assert links.backlinks == ["Ideas.md", "Journal.md", "proj/_index.md"]


def test_supersede_links_show_up_in_both_directions(store):
    old = store.save_memory(agent="a", kind="decision", title="Old", content="c", namespace="proj")
    new = store.save_memory(agent="a", kind="decision", title="New", content="c", namespace="proj", supersedes=[old.id])

    _, new_links = store.get_links(new.id)
    _, old_links = store.get_links(old.id)

    assert new_links.outgoing == [old.path]
    assert new_links.backlinks == ["proj/_index.md", old.path]
    assert old_links.outgoing == [new.path]
    assert old_links.backlinks == ["proj/_index.md", new.path]


def test_get_links_of_an_unknown_id_is_none(store):
    assert store.get_links("00000000-0000-0000-0000-000000000000") is None
