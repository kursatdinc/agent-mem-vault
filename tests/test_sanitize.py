import pytest

from agent_vault_memory.sanitize import (
    INPUT_LIMITS,
    normalize_limit,
    redact_secrets,
    sanitize_ids,
    sanitize_kind,
    sanitize_namespace,
    sanitize_related_files,
    sanitize_tags,
    sanitize_text,
)


def test_sanitize_text_strips_control_characters_and_trims():
    assert sanitize_text("  hel\x00lo\x07  ", "field", 100) == "hello"
    assert sanitize_text("line one\nline two\ttabbed", "field", 100) == "line one\nline two\ttabbed"


def test_sanitize_text_rejects_non_strings_empty_and_oversized_values():
    with pytest.raises(TypeError, match="field must be a string"):
        sanitize_text(42, "field", 100)
    with pytest.raises(ValueError, match="field is required"):
        sanitize_text(" \x00 ", "field", 100)
    with pytest.raises(ValueError, match="field exceeds 10 characters"):
        sanitize_text("x" * 11, "field", 10)
    assert sanitize_text("x" * 10, "field", 10) == "x" * 10


def test_sanitize_tags_dedupes_trims_and_caps_the_count():
    many = [f"tag{index}" for index in range(INPUT_LIMITS["tags"] + 5)]
    assert sanitize_tags([" a ", "", "a", "b\x00 "]) == ["a", "b"]
    assert sanitize_tags(None) == []
    assert sanitize_tags(many) == many[: INPUT_LIMITS["tags"]]


def test_sanitize_tags_rejects_bad_shapes():
    with pytest.raises(TypeError, match="tags must be an array"):
        sanitize_tags("nope")
    with pytest.raises(TypeError, match="tags must contain only strings"):
        sanitize_tags([1])
    with pytest.raises(ValueError, match="tag exceeds 64 characters"):
        sanitize_tags(["x" * 65])


def test_sanitize_namespace_falls_back_to_the_default():
    assert [sanitize_namespace(value, "fallback") for value in (None, "")] == ["fallback", "fallback"]
    assert sanitize_namespace(" proj ", "fallback") == "proj"
    with pytest.raises(ValueError, match="namespace exceeds 100 characters"):
        sanitize_namespace("n" * 101, "fallback")


def test_sanitize_kind_accepts_known_kinds_only():
    assert sanitize_kind(" decision ") == "decision"
    with pytest.raises(ValueError, match="kind must be one of: note, decision"):
        sanitize_kind("bogus")


def test_sanitize_related_files_and_ids():
    assert sanitize_related_files([" a.py ", "b.py"]) == ["a.py", "b.py"]
    assert sanitize_related_files(None) == []
    with pytest.raises(TypeError, match="relatedFiles must be an array"):
        sanitize_related_files("nope")
    assert sanitize_ids([" id-1 ", "id-2", "id-1"]) == ["id-1", "id-2"]
    with pytest.raises(ValueError, match="supersedes exceeds 20 ids"):
        sanitize_ids([f"id-{index}" for index in range(21)])


@pytest.mark.parametrize(
    ("limit", "expected"),
    [(None, 10), (0, 10), (-3, 10), (float("nan"), 10), (float("inf"), 10), (True, 10), (3, 3), (2.9, 2)],
)
def test_normalize_limit(limit, expected):
    assert normalize_limit(limit) == expected


def test_redact_secrets_masks_known_token_shapes_and_key_value_pairs():
    assert redact_secrets("ghp_" + "a" * 30) == "[REDACTED_TOKEN]"
    assert redact_secrets("use sk-" + "b" * 30 + " now") == "use [REDACTED_TOKEN] now"
    assert redact_secrets("xoxb-1234567890-abc") == "[REDACTED_TOKEN]"
    assert (
        redact_secrets("API_KEY=hunter2 and password=pw") == "API_KEY=[REDACTED_SECRET] and password=[REDACTED_SECRET]"
    )
    assert redact_secrets("nothing to hide") == "nothing to hide"
