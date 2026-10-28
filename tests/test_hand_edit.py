def test_search_reflects_a_body_edited_directly_in_the_file(store, vault):
    record = store.save_context(
        agent="agent-a", title="Release notes", content="Original wording about pelicans.", namespace="proj"
    )
    assert [found.id for found in store.search_memory(namespace="proj", query="pelicans")] == [record.id]
    assert store.search_memory(namespace="proj", query="albatross") == []

    path = vault.root / record.path
    path.write_text(path.read_text(encoding="utf-8").replace("pelicans", "albatross"), encoding="utf-8")

    assert store.search_memory(namespace="proj", query="pelicans") == []
    found = store.search_memory(namespace="proj", query="albatross")
    assert [item.id for item in found] == [record.id]
    assert found[0].content == "Original wording about albatross."
