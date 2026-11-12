from datetime import timedelta

from agent_mem_vault.search import query_stems, stems
from mcp_session import call, run_session


def titles(records):
    return [record.title for record in records]


def test_stems_lowercase_split_on_word_characters_and_stem_english():
    assert stems("Running, RUNS & ran-fast! agents") == ["run", "run", "ran", "fast", "agent"]
    assert query_stems("agents agent") == frozenset({"agent"})


def test_a_query_matches_inflected_forms_in_title_content_or_tags(store):
    store.save_context(agent="a", title="Deploying services", content="Nothing else.", namespace="p")
    store.save_context(agent="a", title="Other", content="The deployment is scheduled.", namespace="p")
    store.save_context(agent="a", title="Third", content="Nothing.", tags=["deployments"], namespace="p")
    store.save_context(agent="a", title="Unrelated", content="Nothing at all.", namespace="p")

    assert sorted(titles(store.search_memory(namespace="p", query="deploy"))) == [
        "Deploying services",
        "Other",
        "Third",
    ]


def test_every_query_stem_must_occur_somewhere_in_title_content_or_tags(store):
    store.save_context(agent="a", title="Alpha", content="beta gamma", tags=["delta"], namespace="p")
    store.save_context(agent="a", title="Alpha only", content="beta", namespace="p")

    assert titles(store.search_memory(namespace="p", query="alpha gamma delta")) == ["Alpha"]
    assert titles(store.search_memory(namespace="p", query="alpha gamma delta epsilon")) == []


def test_title_hits_weigh_three_times_a_content_hit_and_ties_fall_back_to_newest(store):
    store.save_context(agent="a", title="Plain", content="cache cache", namespace="p")
    store.save_context(agent="a", title="Three hits", content="cache cache cache", namespace="p")
    store.save_context(agent="a", title="Cache design", content="unrelated words", namespace="p")
    store.save_context(agent="a", title="Plain two", content="cache cache", namespace="p")

    assert titles(store.search_memory(namespace="p", query="cache")) == [
        "Cache design",
        "Three hits",
        "Plain two",
        "Plain",
    ]


def test_a_match_weighs_less_as_it_ages_losing_half_its_boost_every_thirty_days(store):
    store.save_context(agent="a", title="Three hits", content="cache cache cache", namespace="p")
    store.clock.moment += timedelta(days=30)
    store.save_context(agent="a", title="Two hits", content="cache cache", namespace="p")

    assert titles(store.search_memory(namespace="p", query="cache")) == ["Three hits", "Two hits"]

    store.clock.moment += timedelta(days=30)
    store.save_context(agent="a", title="Two hits today", content="cache cache", namespace="p")

    # 2 x 1.0 today > 3 x 0.625 at sixty days > 2 x 0.75 at thirty days
    assert titles(store.search_memory(namespace="p", query="cache")) == ["Two hits today", "Three hits", "Two hits"]


def test_the_age_weight_never_drops_below_half_so_an_old_title_hit_beats_a_new_content_hit(store):
    store.save_context(agent="a", title="Cache design", content="unrelated words", namespace="p")
    store.clock.moment += timedelta(days=3650)
    store.save_context(agent="a", title="Plain", content="one cache mention", namespace="p")

    assert titles(store.search_memory(namespace="p", query="cache")) == ["Cache design", "Plain"]


def write_note(vault, name, frontmatter, content):
    path = vault.root / "p" / "note" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {name}\nkind: note\nnamespace: p\ntitle: {name.title()}\n{frontmatter}---\n{content}\n",
        encoding="utf-8",
    )


def test_a_hand_written_date_is_aged_and_a_record_without_one_counts_as_old(store, vault):
    write_note(vault, "dated", "created: 2026-10-27\n", "cache cache")
    write_note(vault, "undated", "", "cache cache cache")
    store.save_context(agent="a", title="Fresh", content="cache cache", namespace="p")

    # 2 x 1.0 fresh > 2 x 0.98 at 33 hours > 3 x 0.5 undated
    assert titles(store.search_memory(namespace="p", query="cache")) == ["Fresh", "Dated", "Undated"]


def test_a_created_date_in_the_future_weighs_no_more_than_a_new_record(store, vault):
    write_note(vault, "ahead", "created: 2027-10-28T09:00:00Z\n", "cache")
    store.save_context(agent="a", title="Fresh", content="cache cache", namespace="p")

    assert titles(store.search_memory(namespace="p", query="cache")) == ["Fresh", "Ahead"]


def test_agent_and_destination_names_are_not_searched_but_the_related_block_is_not_content(store):
    old = store.save_memory(agent="zebra-agent", kind="decision", title="Old", content="old body", namespace="p")
    store.save_memory(agent="a", kind="decision", title="New", content="new body", namespace="p", supersedes=[old.id])

    assert store.search_memory(namespace="p", query="zebra", include_closed=True) == []
    assert store.search_memory(namespace="p", query="supersedes", include_closed=True) == []
    assert titles(store.search_memory(namespace="p", query="old", include_closed=True)) == ["Old"]


def test_a_query_without_word_characters_matches_nothing_and_no_query_lists_newest_first(store):
    store.save_context(agent="a", title="One", content="c", namespace="p")
    store.save_context(agent="a", title="Two", content="c", namespace="p")

    assert store.search_memory(namespace="p", query="?!") == []
    assert titles(store.search_memory(namespace="p")) == ["Two", "One"]
    assert titles(store.search_memory(namespace="p", limit=1)) == ["Two"]


def test_an_alias_hit_matches_and_weighs_between_a_title_hit_and_a_content_hit(store):
    store.save_memory(agent="a", kind="decision", title="Plain", content="adk adk", namespace="p")
    store.save_memory(agent="a", kind="decision", title="ADK pin", content="x", namespace="p")
    store.save_memory(agent="a", kind="decision", title="Runtime upgrade", content="x", aliases=["ADK"], namespace="p")
    store.save_memory(agent="a", kind="decision", title="Unrelated", content="x", namespace="p")

    assert titles(store.search_memory(namespace="p", query="adk")) == ["ADK pin", "Runtime upgrade", "Plain"]


def test_a_hand_written_alias_string_is_searched_like_a_one_item_list(store, vault):
    record = store.save_memory(agent="a", kind="decision", title="Runtime upgrade", content="x", namespace="p")
    path = vault.root / record.path
    path.write_text(path.read_text(encoding="utf-8").replace("title:", "aliases: google adk\ntitle:", 1), "utf-8")

    assert titles(store.search_memory(namespace="p", query="google adk")) == ["Runtime upgrade"]


def test_a_partial_search_ranks_records_by_how_many_query_words_they_hold_and_drops_less_than_half(store):
    store.save_context(agent="a", title="Alpha beta gamma", content="x", namespace="p")
    store.save_context(agent="a", title="Alpha beta", content="x", namespace="p")
    store.save_context(agent="a", title="Alpha", content="x", namespace="p")
    store.save_context(agent="a", title="Unrelated", content="x", namespace="p")

    found = store.search_partial(namespace="p", query="alpha beta gamma delta")

    assert titles(found) == ["Alpha beta gamma", "Alpha beta"]


def test_a_partial_search_ignores_filler_words_and_finds_nothing_in_a_query_made_of_them(store):
    store.save_context(agent="a", title="Cache layout", content="x", namespace="p")

    assert titles(store.search_partial(namespace="p", query="why did we drop the cache")) == ["Cache layout"]
    assert store.search_partial(namespace="p", query="why did we") == []
    assert store.search_partial(namespace="p", query="?!") == []


def test_a_partial_search_keeps_the_filters_of_the_exact_one(store):
    store.save_memory(agent="a", kind="decision", title="Alpha beta", content="x", namespace="p")
    store.save_memory(agent="a", kind="risk", title="Alpha beta", content="x", namespace="p")
    store.save_memory(agent="a", kind="decision", title="Alpha beta", content="x", namespace="other")

    found = store.search_partial(namespace="p", query="alpha gamma", kind="risk")

    assert [(record.kind, record.namespace) for record in found] == [("risk", "p")]
    assert len(store.search_partial(namespace="p", query="alpha beta gamma delta", limit=1)) == 1


def test_the_search_tool_offers_labelled_partial_matches_only_when_no_record_holds_every_word(tmp_path):
    async def scenario(session):
        for title in ("Alpha beta", "Gamma"):
            await call(session, "save_context", agent="a", title=title, content="x", namespace="p")
        return {
            "exact": await call(session, "search_memory", namespace="p", query="alpha beta"),
            "partial": await call(session, "search_memory", namespace="p", query="alpha beta delta"),
            "none": await call(session, "search_memory", namespace="p", query="zebra"),
        }

    replies = run_session(tmp_path, scenario)

    assert replies["exact"].startswith("1. [note] (p) Alpha beta - a - ")
    assert replies["partial"].startswith(
        "No record holds every word; closest partial matches:\n1. [note] (p) Alpha beta - a - "
    )
    assert replies["none"] == "No matching memory found."
