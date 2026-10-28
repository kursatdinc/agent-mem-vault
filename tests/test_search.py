from agent_mem_vault.search import query_stems, stems


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


def test_agent_and_destination_names_are_not_searched_but_the_related_block_is_not_content(store):
    old = store.save_memory(agent="zebra-agent", kind="decision", title="Old", content="old body", namespace="p")
    store.save_memory(agent="a", kind="decision", title="New", content="new body", namespace="p", supersedes=[old.id])

    assert store.search_memory(namespace="p", query="zebra") == []
    assert store.search_memory(namespace="p", query="supersedes") == []
    assert titles(store.search_memory(namespace="p", query="old")) == ["Old"]


def test_a_query_without_word_characters_matches_nothing_and_no_query_lists_newest_first(store):
    store.save_context(agent="a", title="One", content="c", namespace="p")
    store.save_context(agent="a", title="Two", content="c", namespace="p")

    assert store.search_memory(namespace="p", query="?!") == []
    assert titles(store.search_memory(namespace="p")) == ["Two", "One"]
    assert titles(store.search_memory(namespace="p", limit=1)) == ["Two"]
