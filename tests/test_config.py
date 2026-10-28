from pathlib import Path

import pytest

from agent_vault_memory.config import ConfigError, load_config


def test_defaults_come_from_the_vault_setting_alone(tmp_path):
    empty = _empty_file(tmp_path)

    config = load_config({"AGENT_VAULT_MEMORY_VAULT": str(tmp_path), "AGENT_VAULT_MEMORY_CONFIG": empty})

    assert config.vault == tmp_path
    assert config.default_namespace == "default"
    assert config.redact_secrets is True
    assert config.config_file == Path(empty)


def test_environment_overrides_the_config_file_which_overrides_defaults(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("vault: /from/file\ndefault_namespace: from-file\nredact_secrets: false\n", encoding="utf-8")

    from_file = load_config({"AGENT_VAULT_MEMORY_CONFIG": str(config_file)})
    from_env = load_config(
        {
            "AGENT_VAULT_MEMORY_CONFIG": str(config_file),
            "AGENT_VAULT_MEMORY_VAULT": "/from/env",
            "AGENT_VAULT_MEMORY_DEFAULT_NAMESPACE": "from-env",
            "AGENT_VAULT_MEMORY_REDACT_SECRETS": "TRUE",
        }
    )

    assert (from_file.vault, from_file.default_namespace, from_file.redact_secrets) == (
        Path("/from/file"),
        "from-file",
        False,
    )
    assert (from_env.vault, from_env.default_namespace, from_env.redact_secrets) == (
        Path("/from/env"),
        "from-env",
        True,
    )


def test_a_leading_tilde_in_the_vault_path_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    config = load_config({"AGENT_VAULT_MEMORY_VAULT": "~/notes", "AGENT_VAULT_MEMORY_CONFIG": _empty_file(tmp_path)})

    assert config.vault == tmp_path / "notes"


def test_missing_vault_and_invalid_values_raise_actionable_errors(tmp_path):
    empty = _empty_file(tmp_path)

    with pytest.raises(ConfigError, match="vault is not configured: set AGENT_VAULT_MEMORY_VAULT"):
        load_config({"AGENT_VAULT_MEMORY_CONFIG": empty})
    with pytest.raises(ConfigError, match="AGENT_VAULT_MEMORY_REDACT_SECRETS must be true or false"):
        load_config(
            {
                "AGENT_VAULT_MEMORY_CONFIG": empty,
                "AGENT_VAULT_MEMORY_VAULT": "/v",
                "AGENT_VAULT_MEMORY_REDACT_SECRETS": "maybe",
            }
        )
    not_a_mapping = tmp_path / "list.yaml"
    not_a_mapping.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must contain a mapping"):
        load_config({"AGENT_VAULT_MEMORY_CONFIG": str(not_a_mapping)})
    with pytest.raises(ConfigError, match="config file not found"):
        load_config({"AGENT_VAULT_MEMORY_CONFIG": str(tmp_path / "missing.yaml")})


def _empty_file(directory: Path) -> str:
    path = directory / "empty.yaml"
    path.write_text("", encoding="utf-8")
    return str(path)


def test_git_autocommit_is_off_by_default_and_read_from_the_features_section(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("vault: /v\nfeatures:\n  git_autocommit: true\n", encoding="utf-8")
    plain = _empty_file(tmp_path)

    assert load_config({"AGENT_VAULT_MEMORY_CONFIG": str(config_file)}).git_autocommit is True
    assert load_config({"AGENT_VAULT_MEMORY_VAULT": "/v", "AGENT_VAULT_MEMORY_CONFIG": plain}).git_autocommit is False


@pytest.mark.parametrize("features", ["features: yes", "features:\n  git_autocommit: sometimes"])
def test_an_invalid_features_section_is_a_config_error(tmp_path, features):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"vault: /v\n{features}\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config({"AGENT_VAULT_MEMORY_CONFIG": str(config_file)})


def test_feature_flags_default_to_off_except_visibility_and_are_read_from_the_features_section(tmp_path):
    plain = load_config({"AGENT_VAULT_MEMORY_VAULT": "/v", "AGENT_VAULT_MEMORY_CONFIG": _empty_file(tmp_path)})
    config_file = tmp_path / "features.yaml"
    config_file.write_text(
        "vault: /v\nfeatures:\n  receipts: true\n  companion: true\n  visibility: false\n  hooks: true\n"
        "companion:\n  max_chars: 500\n",
        encoding="utf-8",
    )
    configured = load_config({"AGENT_VAULT_MEMORY_CONFIG": str(config_file)})

    assert (plain.receipts, plain.companion, plain.visibility, plain.hooks, plain.companion_max_chars) == (
        False,
        False,
        True,
        False,
        3000,
    )
    assert (
        configured.receipts,
        configured.companion,
        configured.visibility,
        configured.hooks,
        configured.companion_max_chars,
    ) == (True, True, False, True, 500)


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ("features:\n  receipts: maybe", "features.receipts must be true or false"),
        ("companion:\n  max_chars: 0", "companion.max_chars must be a positive integer"),
        ("companion:\n  max_chars: lots", "companion.max_chars must be a positive integer"),
        ("companion: 5", "companion must be a mapping"),
    ],
)
def test_invalid_feature_values_are_config_errors_naming_the_key(tmp_path, section, message):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"vault: /v\n{section}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_config({"AGENT_VAULT_MEMORY_CONFIG": str(config_file)})
