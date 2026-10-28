import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

ENV_VAULT = "AGENT_MEM_VAULT_VAULT"
ENV_CONFIG = "AGENT_MEM_VAULT_CONFIG"
ENV_NAMESPACE = "AGENT_MEM_VAULT_DEFAULT_NAMESPACE"
ENV_REDACT = "AGENT_MEM_VAULT_REDACT_SECRETS"
DEFAULT_CONFIG_FILE = Path("~/.config/agent-mem-vault/config.yaml")
DEFAULT_COMPANION_MAX_CHARS = 3000


class ConfigError(Exception):
    """The configuration is missing or invalid; the message tells the user what to fix."""


@dataclass(frozen=True)
class Config:
    vault: Path
    default_namespace: str = "default"
    redact_secrets: bool = True
    receipts: bool = False
    companion: bool = False
    visibility: bool = True
    hooks: bool = False
    git_autocommit: bool = False
    companion_max_chars: int = DEFAULT_COMPANION_MAX_CHARS
    config_file: Path | None = None


def _read_config_file(env: Mapping[str, str]) -> tuple[dict, Path | None]:
    explicit = env.get(ENV_CONFIG)
    path = Path(explicit).expanduser() if explicit else DEFAULT_CONFIG_FILE.expanduser()
    if not path.is_file():
        if explicit:
            raise ConfigError(f"config file not found: {path}")
        return {}, None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise ConfigError(f"cannot read config file {path}: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"config file {path} must contain a mapping")
    return data, path


def _parse_bool(value: object, source: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ConfigError(f"{source} must be true or false")


def _mapping(data: dict, key: str) -> dict:
    section = data.get(key) or {}
    if not isinstance(section, dict):
        raise ConfigError(f"{key} must be a mapping")
    return section


def _parse_max_chars(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError("companion.max_chars must be a positive integer")
    return value


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Built-in defaults, then the config file, then environment variables."""
    env = os.environ if env is None else env
    data, config_file = _read_config_file(env)

    vault = env.get(ENV_VAULT) or data.get("vault")
    if not vault:
        raise ConfigError(f"vault is not configured: set {ENV_VAULT} or `vault` in the config file")
    namespace = env.get(ENV_NAMESPACE) or data.get("default_namespace", "default")
    redact = env[ENV_REDACT] if ENV_REDACT in env else data.get("redact_secrets", True)

    if not isinstance(vault, str) or not isinstance(namespace, str):
        raise ConfigError("vault and default_namespace must be strings")
    features = _mapping(data, "features")
    companion = _mapping(data, "companion")
    return Config(
        vault=Path(vault).expanduser(),
        default_namespace=namespace,
        redact_secrets=_parse_bool(redact, ENV_REDACT if ENV_REDACT in env else "redact_secrets"),
        receipts=_parse_bool(features.get("receipts", False), "features.receipts"),
        companion=_parse_bool(features.get("companion", False), "features.companion"),
        visibility=_parse_bool(features.get("visibility", True), "features.visibility"),
        hooks=_parse_bool(features.get("hooks", False), "features.hooks"),
        git_autocommit=_parse_bool(features.get("git_autocommit", False), "features.git_autocommit"),
        companion_max_chars=_parse_max_chars(companion.get("max_chars", DEFAULT_COMPANION_MAX_CHARS)),
        config_file=config_file,
    )
